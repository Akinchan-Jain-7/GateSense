"""Telegram bot: residents approve or deny visitors from a chat.

Linking (once per resident):
1. The resident asks the API for a link code (`POST /telegram/link-code`) and opens
   `https://t.me/<bot>?start=<code>`; Telegram sends the bot `/start <code>`.
2. Our webhook finds the code (kept in Redis for 10 minutes, only as a hash) and saves the
   chat id on the user. Codes work once.

Approving:
- A new approval is sent to every linked resident of the flat with two inline buttons whose
  `callback_data` is `ap:<approval id>:a` or `ap:<approval id>:d`.
- On a button press, Telegram calls our webhook. We check the call really comes from
  Telegram (the secret token header set when the webhook was registered), that the chat
  belongs to a resident of *that* flat, then decide through the same code as the web app,
  so pressing twice, or deciding on web and Telegram, is harmless.
"""

import hashlib
import logging
import secrets
import uuid
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Approval, User
from app.models.enums import ApprovalChannel, ApprovalStatus, UserRole
from app.services import visitors
from app.services.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

LINK_CODE_TTL_SECONDS = 600
_LINK_KEY = "gatesense:telegram:link:{}"


class TelegramBot:
    """The few Bot API calls we use. `transport` lets tests fake Telegram."""

    def __init__(
        self,
        token: str,
        api_url: str = "https://api.telegram.org",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.http = httpx.AsyncClient(
            base_url=f"{api_url}/bot{token}", timeout=10, transport=transport
        )

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        response = await self.http.post(f"/{method}", json=params)
        body: dict[str, Any] = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
        return body

    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None
    ) -> None:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        await self.call("sendMessage", **params)

    async def answer_callback(self, callback_id: str, text: str) -> None:
        await self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        await self.call(
            "editMessageText", chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML"
        )

    async def aclose(self) -> None:
        await self.http.aclose()


def build_bot(settings: Settings) -> TelegramBot | None:
    if settings.telegram_bot_token is None:
        return None
    return TelegramBot(settings.telegram_bot_token.get_secret_value(), settings.telegram_api_url)


# --- Linking ------------------------------------------------------------------------------


def _code_key(code: str) -> str:
    return _LINK_KEY.format(hashlib.sha256(code.encode()).hexdigest())


async def create_link_code(
    redis: Redis, settings: Settings, resident: User
) -> tuple[str, str | None]:
    code = secrets.token_urlsafe(12)  # Telegram start parameters allow A-Z a-z 0-9 _ -
    await redis.set(_code_key(code), str(resident.id), ex=LINK_CODE_TTL_SECONDS)
    link = (
        f"https://t.me/{settings.telegram_bot_username}?start={code}"
        if settings.telegram_bot_username
        else None
    )
    return code, link


async def _link_chat(db: AsyncSession, redis: Redis, code: str, chat_id: int) -> User | None:
    user_id = await redis.getdel(_code_key(code))  # works once
    if user_id is None:
        return None
    user = await db.get(
        User, uuid.UUID(user_id.decode() if isinstance(user_id, bytes) else str(user_id))
    )
    if user is None or not user.is_active:
        return None
    # A chat can belong to one account: unlink it from anyone else first.
    previous = await db.scalar(
        select(User).where(User.telegram_chat_id == chat_id, User.id != user.id)
    )
    if previous is not None:
        previous.telegram_chat_id = None
        await db.flush()
    user.telegram_chat_id = chat_id
    await db.commit()
    return user


# --- Approval messages --------------------------------------------------------------------


def approval_text(approval: Approval) -> str:
    visit = visitors.visit_read(approval.visit)
    lines = [
        f"🚗 <b>Visitor for {visit.flat_label}</b>",
        f"{visit.visitor_name or 'Visitor'} · {visit.category.value}",
    ]
    if visit.plate_normalized:
        lines.append(f"Vehicle: {visit.plate_normalized}")
    if visit.purpose:
        lines.append(f"Purpose: {visit.purpose}")
    lines.append("Approve within 3 minutes, or the guard decides.")
    return "\n".join(lines)


def approval_buttons(approval: Approval) -> list[list[dict[str, str]]]:
    return [
        [
            {"text": "✅ Approve", "callback_data": f"ap:{approval.id}:a"},
            {"text": "❌ Deny", "callback_data": f"ap:{approval.id}:d"},
        ]
    ]


async def linked_residents(db: AsyncSession, flat_id: uuid.UUID) -> list[User]:
    ids = await visitors.flat_resident_ids(db, flat_id)
    rows = await db.scalars(
        select(User).where(User.id.in_(ids), User.telegram_chat_id.is_not(None))
    )
    return list(rows)


# --- Webhook ------------------------------------------------------------------------------


async def handle_update(
    db: AsyncSession, redis: Redis, settings: Settings, bot: TelegramBot, update: dict[str, Any]
) -> str:
    """Process one webhook update. Returns what happened (for logs and tests)."""
    if callback := update.get("callback_query"):
        return await _handle_button(db, redis, settings, bot, callback)
    message = update.get("message") or {}
    text = str(message.get("text") or "")
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None:
        return "ignored"
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and (
            user := await _link_chat(db, redis, parts[1].strip(), int(chat_id))
        ):
            await bot.send_message(
                int(chat_id),
                f"Linked to GateSense as {user.full_name}. Visitor requests will arrive here.",
            )
            return "linked"
        await bot.send_message(
            int(chat_id), "That link has expired. Open a fresh one from the GateSense app."
        )
        return "bad_code"
    await bot.send_message(
        int(chat_id), "I only send visitor requests. Use the buttons on them to answer."
    )
    return "help"


async def _handle_button(
    db: AsyncSession, redis: Redis, settings: Settings, bot: TelegramBot, callback: dict[str, Any]
) -> str:
    callback_id = str(callback.get("id"))
    chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
    message_id = (callback.get("message") or {}).get("message_id")
    try:
        kind, raw_id, choice = str(callback.get("data", "")).split(":")
        approval_id = uuid.UUID(raw_id)
        if kind != "ap" or choice not in {"a", "d"}:
            raise ValueError
    except ValueError:
        await bot.answer_callback(callback_id, "Unknown button")
        return "bad_data"

    user = (
        await db.scalar(select(User).where(User.telegram_chat_id == chat_id)) if chat_id else None
    )
    if user is None or not user.is_active or user.role is not UserRole.RESIDENT:
        await bot.answer_callback(callback_id, "This chat isn't linked to a resident account")
        return "not_linked"
    try:
        result = await visitors.decide_approval(
            db, redis, settings, user, approval_id, choice == "a", ApprovalChannel.TELEGRAM
        )
    except NotFoundError:
        await bot.answer_callback(callback_id, "This request isn't for your flat")
        return "not_allowed"
    except ConflictError as exc:
        await bot.answer_callback(callback_id, str(exc))
        return "conflict"

    verdict = "approved ✅" if result.approval.status is ApprovalStatus.APPROVED else "denied ❌"
    await bot.answer_callback(
        callback_id,
        f"You {verdict.split()[0]} this visitor" if result.changed else f"Already {verdict}",
    )
    if chat_id and message_id:
        await bot.edit_message(
            int(chat_id),
            int(message_id),
            approval_text(result.approval) + f"\n\n<b>{verdict}</b> by {user.full_name}",
        )
    return "decided" if result.changed else "already_decided"
