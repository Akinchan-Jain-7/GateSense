"""Telegram bot (linking, buttons, notifications) and the WebSocket live feed."""

import asyncio
import json
import uuid
from collections.abc import Iterator, MutableMapping
from typing import Any

import httpx
import httpx2
import pytest
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_telegram_bot
from app.core.config import get_settings
from app.main import app
from app.models import Flat, Notification, Society, User
from app.models.enums import NotificationStatus
from app.services import realtime
from app.services.telegram import TelegramBot
from app.workers.tasks import send_approval
from tests import factories
from tests.factories import auth_headers

SECRET = "webhook-secret-for-tests"


class FakeBot:
    """Records what the bot would send to Telegram."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str, Any]] = []
        self.answers: list[str] = []
        self.edits: list[str] = []

    async def send_message(self, chat_id: int, text: str, buttons: Any = None) -> None:
        self.messages.append((chat_id, text, buttons))

    async def answer_callback(self, callback_id: str, text: str) -> None:
        self.answers.append(text)

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        self.edits.append(text)


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeBot]:
    fake = FakeBot()
    monkeypatch.setattr(get_settings(), "telegram_webhook_secret", SecretStr(SECRET))
    app.dependency_overrides[get_telegram_bot] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_telegram_bot, None)


async def webhook(
    client: httpx2.AsyncClient, update: dict[str, Any], secret: str | None = SECRET
) -> httpx2.Response:
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
    return await client.post("/api/v1/telegram/webhook", json=update, headers=headers)


async def link(client: httpx2.AsyncClient, resident: User, chat_id: int) -> None:
    code = (await client.post("/api/v1/telegram/link-code", headers=auth_headers(resident))).json()[
        "code"
    ]
    response = await webhook(
        client, {"message": {"chat": {"id": chat_id}, "text": f"/start {code}"}}
    )
    assert response.json() == {"result": "linked"}


async def pending_approval(client: httpx2.AsyncClient, guard: User, flat: Flat) -> str:
    response = await client.post(
        "/api/v1/visits",
        json={
            "full_name": "Rohit Verma",
            "phone": "9876543210",
            "flat_id": str(flat.id),
            "plate": "MH12DE1433",
        },
        headers=auth_headers(guard),
    )
    return str(response.json()["approval"]["id"])


def press(chat_id: int, approval_id: str, choice: str) -> dict[str, Any]:
    return {
        "callback_query": {
            "id": "cb1",
            "data": f"ap:{approval_id}:{choice}",
            "message": {"message_id": 7, "chat": {"id": chat_id}},
        }
    }


# --- Telegram -----------------------------------------------------------------------------


async def test_linking_a_chat_with_a_one_time_code(
    client: httpx2.AsyncClient, bot: FakeBot, resident: User, db: AsyncSession
) -> None:
    response = await client.post("/api/v1/telegram/link-code", headers=auth_headers(resident))
    code = response.json()["code"]
    assert response.json()["expires_in_seconds"] == 600

    assert (
        await webhook(client, {"message": {"chat": {"id": 555}, "text": f"/start {code}"}})
    ).json()["result"] == "linked"
    await db.refresh(resident)
    assert resident.telegram_chat_id == 555
    assert "Linked to GateSense as" in bot.messages[-1][1]
    # The code works once.
    again = await webhook(client, {"message": {"chat": {"id": 556}, "text": f"/start {code}"}})
    assert again.json()["result"] == "bad_code"


async def test_webhook_rejects_calls_without_the_secret(
    client: httpx2.AsyncClient, bot: FakeBot
) -> None:
    assert (await webhook(client, {}, secret=None)).status_code == 401
    assert (await webhook(client, {}, secret="wrong")).status_code == 401


async def test_webhook_is_off_without_a_bot(client: httpx2.AsyncClient) -> None:
    assert (await webhook(client, {})).status_code == 404


async def test_approving_from_telegram_buttons(
    client: httpx2.AsyncClient, bot: FakeBot, guard: User, resident: User, flat: Flat
) -> None:
    await link(client, resident, 555)
    approval_id = await pending_approval(client, guard, flat)

    assert (await webhook(client, press(555, approval_id, "a"))).json()["result"] == "decided"
    assert bot.answers[-1] == "You approved this visitor"
    assert "approved ✅" in bot.edits[-1]
    approval = (await client.get("/api/v1/approvals", headers=auth_headers(resident))).json()[
        "items"
    ][0]
    assert (approval["status"], approval["channel"]) == ("approved", "telegram")

    # Pressing again (or the other button) is harmless.
    assert (await webhook(client, press(555, approval_id, "a"))).json()[
        "result"
    ] == "already_decided"
    assert (await webhook(client, press(555, approval_id, "d"))).json()["result"] == "conflict"


async def test_buttons_check_who_is_pressing(
    client: httpx2.AsyncClient,
    bot: FakeBot,
    guard: User,
    resident: User,
    flat: Flat,
    society: Society,
    db: AsyncSession,
) -> None:
    approval_id = await pending_approval(client, guard, flat)
    assert (await webhook(client, press(999, approval_id, "a"))).json()["result"] == "not_linked"
    neighbour = await factories.make_resident(
        db, society, await factories.make_flat(db, society, "C", "104"), email="n@test.in"
    )
    await link(client, neighbour, 777)
    assert (await webhook(client, press(777, approval_id, "a"))).json()["result"] == "not_allowed"
    garbage = {"callback_query": {"id": "x", "data": "rm -rf", "message": {"chat": {"id": 777}}}}
    assert (await webhook(client, garbage)).json()["result"] == "bad_data"
    chat = await webhook(client, {"message": {"chat": {"id": 777}, "text": "hello"}})
    assert chat.json()["result"] == "help"


async def test_approval_request_is_sent_once_per_linked_resident(
    client: httpx2.AsyncClient,
    bot: FakeBot,
    guard: User,
    resident: User,
    flat: Flat,
    db: AsyncSession,
) -> None:
    await link(client, resident, 555)
    approval_id = uuid.UUID(await pending_approval(client, guard, flat))
    settings = get_settings()

    assert await send_approval(db, settings, bot, approval_id) == 1  # type: ignore[arg-type]
    chat_id, text, buttons = bot.messages[-1]
    assert chat_id == 555
    assert "Visitor for B-402" in text and "MH12DE1433" in text
    assert [b["callback_data"] for b in buttons[0]] == [
        f"ap:{approval_id}:a",
        f"ap:{approval_id}:d",
    ]
    # The job ran twice (a retry): no second message.
    assert await send_approval(db, settings, bot, approval_id) == 0  # type: ignore[arg-type]
    notes = (await db.scalars(select(Notification))).all()
    assert [(n.kind, n.status, n.attempts) for n in notes] == [
        ("approval_request", NotificationStatus.SENT, 1)
    ]


async def test_failed_sends_are_logged(
    client: httpx2.AsyncClient,
    bot: FakeBot,
    guard: User,
    resident: User,
    flat: Flat,
    db: AsyncSession,
) -> None:
    await link(client, resident, 555)
    approval_id = uuid.UUID(await pending_approval(client, guard, flat))

    async def broken(*args: object) -> None:
        raise RuntimeError("Telegram is down")

    bot.send_message = broken  # type: ignore[method-assign, assignment]
    assert await send_approval(db, get_settings(), bot, approval_id) == 0  # type: ignore[arg-type]
    note = await db.scalar(select(Notification))
    assert note is not None
    assert (note.status, note.last_error) == (NotificationStatus.FAILED, "Telegram is down")


async def test_bot_client_talks_to_the_bot_api() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("/editMessageText"):
            return httpx.Response(200, json={"ok": False, "description": "message is not modified"})
        return httpx.Response(200, json={"ok": True, "result": {}})

    bot = TelegramBot("123:abc", transport=httpx.MockTransport(handler))
    await bot.send_message(5, "hi", [[{"text": "ok", "callback_data": "x"}]])
    await bot.answer_callback("cb", "done")
    with pytest.raises(RuntimeError, match="not modified"):
        await bot.edit_message(5, 1, "new")
    await bot.aclose()
    assert calls[0] == (
        "/bot123:abc/sendMessage",
        {
            "chat_id": 5,
            "text": "hi",
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[{"text": "ok", "callback_data": "x"}]]},
        },
    )
    assert calls[1][0] == "/bot123:abc/answerCallbackQuery"


# --- WebSocket ------------------------------------------------------------------------------


class Socket:
    """Drives the app's WebSocket route directly over ASGI, in the test's event loop."""

    def __init__(self, path: str) -> None:
        raw_path, _, query = path.partition("?")
        self.scope = {
            "type": "websocket",
            "path": raw_path,
            "raw_path": raw_path.encode(),
            "query_string": query.encode(),
            "headers": [],
            "scheme": "ws",
            "server": ("test", 80),
            "client": ("test", 1),
            "subprotocols": [],
            "root_path": "",
            "app": app,
        }
        self.incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.outgoing: asyncio.Queue[MutableMapping[str, Any]] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "Socket":
        await self.incoming.put({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(self.scope, self.incoming.get, self.outgoing.put))
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        assert self.task is not None
        await asyncio.wait_for(self.task, timeout=5)

    async def receive(self) -> MutableMapping[str, Any]:
        return await asyncio.wait_for(self.outgoing.get(), timeout=5)

    async def receive_json(self) -> dict[str, Any]:
        message = await self.receive()
        assert message["type"] == "websocket.send", message
        data: dict[str, Any] = json.loads(message["text"])
        return data

    async def send(self, text: str) -> None:
        await self.incoming.put({"type": "websocket.receive", "text": text})


def token_for(user: User) -> str:
    return auth_headers(user)["Authorization"].removeprefix("Bearer ")


async def test_websocket_needs_a_valid_token(client: httpx2.AsyncClient) -> None:
    for path in ("/api/v1/ws", "/api/v1/ws?token=not-a-jwt"):
        async with Socket(path) as socket:
            closed = await socket.receive()
            assert (closed["type"], closed["code"]) == ("websocket.close", 4401)


async def test_guard_gets_the_console_feed(
    client: httpx2.AsyncClient, guard: User, society: Society, redis_client: Redis
) -> None:
    async with Socket(f"/api/v1/ws?token={token_for(guard)}") as socket:
        assert (await socket.receive())["type"] == "websocket.accept"
        assert await socket.receive_json() == {"type": "hello", "data": {"role": "guard"}}
        await socket.send("ping")
        assert await socket.receive_json() == {"type": "pong"}

        await asyncio.sleep(0.05)  # let the subscription settle
        await realtime.publish(
            redis_client, [realtime.console_channel(society.id)], "alert.created", {"x": 1}
        )
        message = await socket.receive_json()
        assert (message["type"], message["data"]) == ("alert.created", {"x": 1})


async def test_resident_gets_their_approval_requests_live(
    client: httpx2.AsyncClient,
    guard: User,
    resident: User,
    flat: Flat,
    society: Society,
    db: AsyncSession,
) -> None:
    async with Socket(f"/api/v1/ws?token={token_for(resident)}") as socket:
        await socket.receive()  # accept
        assert (await socket.receive_json())["data"] == {"role": "resident"}
        await asyncio.sleep(0.05)
        approval_id = await pending_approval(client, guard, flat)
        message = await socket.receive_json()
        assert message["type"] == "approval.requested"
        assert message["data"]["id"] == approval_id
        assert message["data"]["visit"]["visitor_name"] == "Rohit Verma"
