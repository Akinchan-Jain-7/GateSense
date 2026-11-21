import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Body, Header, HTTPException, status
from pydantic import BaseModel

from app.api.deps import AppSettings, Bot, DbSession, RedisClient, ResidentUser
from app.services import telegram as service

router = APIRouter(prefix="/telegram", tags=["telegram"])


class LinkCode(BaseModel):
    code: str
    link: str | None
    expires_in_seconds: int


@router.post("/link-code", response_model=LinkCode)
async def create_link_code(
    resident: ResidentUser, redis: RedisClient, settings: AppSettings
) -> LinkCode:
    """Open `link` on your phone (or send `/start <code>` to the bot) within 10 minutes."""
    code, link = await service.create_link_code(redis, settings, resident)
    return LinkCode(code=code, link=link, expires_in_seconds=service.LINK_CODE_TTL_SECONDS)


@router.delete("/link", status_code=status.HTTP_204_NO_CONTENT)
async def unlink(resident: ResidentUser, db: DbSession) -> None:
    resident.telegram_chat_id = None
    await db.commit()


@router.post("/webhook", include_in_schema=False)
async def webhook(
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
    bot: Bot,
    update: Annotated[dict[str, Any], Body()],
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, str]:
    """Telegram calls this. The secret header proves the call is from Telegram."""
    expected = settings.telegram_webhook_secret
    if bot is None or expected is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Telegram bot is not configured")
    if secret is None or not hmac.compare_digest(secret, expected.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Bad webhook secret")
    return {"result": await service.handle_update(db, redis, settings, bot, update)}
