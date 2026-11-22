"""`/api/v1/ws`: live updates for the web app.

Browsers can't set an Authorization header on a WebSocket, so the access token goes in
the query string: `wss://…/api/v1/ws?token=<access token>`. (Access tokens are short-lived;
our request logs record paths only, never query strings.)

Guards and admins receive the society's console feed; everyone receives their own
events. Send `ping` to get `{"type": "pong"}` back (for keep-alive checks).
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.deps import AppSettings, DbSession, RedisClient
from app.core import metrics
from app.core.security import InvalidTokenError, decode_token
from app.models import User
from app.models.enums import UserRole
from app.services import realtime

router = APIRouter(tags=["real time"])

CLOSE_UNAUTHORIZED = 4401  # app-specific close code (4000-4999); the client should re-login


async def _forward(websocket: WebSocket, redis: RedisClient, channels: list[str]) -> None:
    pubsub = redis.pubsub()
    await pubsub.subscribe(*channels)
    try:
        async for item in pubsub.listen():
            if item["type"] == "message":
                data = item["data"]
                await websocket.send_text(data.decode() if isinstance(data, bytes) else str(data))
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py lacks a hint here


async def _receive(websocket: WebSocket) -> None:
    while True:
        if (await websocket.receive_text()).strip() == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}))


@router.websocket("/ws")
async def live_updates(
    websocket: WebSocket,
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
    token: str | None = None,
) -> None:
    user = None
    if token:
        try:
            claims = decode_token(settings, token, expected_type="access")
            user = await db.get(User, claims.subject)
        except InvalidTokenError:
            user = None
    if user is None or not user.is_active:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    channels = [realtime.user_channel(user.id)]
    if user.role in (UserRole.ADMIN, UserRole.GUARD):
        channels.insert(0, realtime.console_channel(user.society_id))
    role = user.role.value
    await db.commit()  # give the DB connection back: this socket may stay open for hours

    await websocket.accept()
    metrics.websocket_connections.inc()
    await websocket.send_text(json.dumps({"type": "hello", "data": {"role": role}}))
    tasks = [
        asyncio.create_task(_forward(websocket, redis, channels)),
        asyncio.create_task(_receive(websocket)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        metrics.websocket_connections.dec()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await task
    with contextlib.suppress(RuntimeError):
        await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
