"""HTTP middleware, written as plain ASGI classes (no BaseHTTPMiddleware: it adds a task
and a copy of the response stream to every request, which showed up under load).

Order, outermost first (see main.py):
1. RequestContext: request id, one log line per request, Prometheus metrics.
2. SecurityHeaders: browser hardening headers on every response.
3. BodySizeLimit: refuse oversized uploads before anyone reads them.
"""

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.core import metrics
from app.core.request_context import request_id

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

logger = logging.getLogger("gatesense.api")
VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return str(value.decode("latin-1"))
    return None


def _route_templates(app: Any) -> dict[int, str]:
    """Full path template for each route object, e.g. `/api/v1/visits/{visit_id}`.

    FastAPI 0.165 routes through included routers, so a matched route's own `.path` is
    relative to its router (`/visits/{visit_id}`). Each included router lists its routes
    with their full paths in `effective_route_contexts()`.
    """
    templates: dict[int, str] = {}
    for route in getattr(getattr(app, "router", None), "routes", []):
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            if path := getattr(route, "path", None):
                templates[id(route)] = path
            continue
        for context in contexts():
            templates.setdefault(id(context.original_route), context.path)
    return templates


class RequestContextMiddleware:
    """Gives each request an id (or keeps a sane one sent by a proxy in X-Request-ID),
    returns it in the response, puts it on every log line, and records metrics."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._templates: dict[int, str] | None = None

    def template(self, scope: Scope) -> str:
        route = scope.get("route")
        if route is None:
            return "unmatched"  # 404s: never label by raw path (unbounded values)
        if self._templates is None:
            self._templates = _route_templates(scope.get("app"))
        template = self._templates.get(id(route)) or getattr(route, "path", None)
        return str(template) if template else "unmatched"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _header(scope, b"x-request-id")
        rid = incoming if incoming and VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id.set(rid)
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            elapsed = time.perf_counter() - started
            template = self.template(scope)
            method = scope.get("method", "")
            metrics.http_requests.labels(method, template, str(status_code)).inc()
            metrics.http_duration.labels(method, template).observe(elapsed)
            logger.info(
                "request",
                extra={
                    "method": method,
                    "path": scope.get("path"),
                    "route": template,
                    "status": status_code,
                    "duration_ms": round(elapsed * 1000, 1),
                },
            )
            request_id.reset(token)


# Swagger UI and ReDoc load scripts from a CDN; the API's own JSON needs nothing at all.
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


class SecurityHeadersMiddleware:
    """Headers that tell browsers to be strict with our responses. Pages that need a
    different Content-Security-Policy (the visitor page) set their own; it's kept."""

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {key.lower() for key, _ in headers}
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if not path.startswith(DOCS_PATHS):
                    extra.append((b"content-security-policy", API_CSP.encode()))
                if self.hsts:
                    extra.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                headers.extend((k, v) for k, v in extra if k not in present)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Refuse request bodies over the limit with 413, without reading them into memory.

    Checks Content-Length up front, and also counts bytes as they stream in (a client can
    leave Content-Length out). Camera uploads get room for a snapshot; everything else is
    small JSON or form data.
    """

    def __init__(self, app: ASGIApp, *, default_limit: int, upload_limit: int) -> None:
        self.app = app
        self.default_limit = default_limit
        self.upload_limit = upload_limit

    def limit_for(self, scope: Scope) -> int:
        if scope.get("method") == "POST" and scope.get("path", "").endswith("/gate-events"):
            return self.upload_limit
        return self.default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope)
        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _too_large(send, limit)
            return

        received = 0
        too_large = False

        async def counting_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Raising here would be swallowed by FastAPI's body parsing (it turns
                    # any error into a 400), so pretend the client went away and replace
                    # whatever response the app then produces with a 413.
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        replaced = False

        async def guarded_send(message: Message) -> None:
            nonlocal replaced
            if not too_large:
                await send(message)
            elif not replaced:
                replaced = True
                await _too_large(send, limit)

        await self.app(scope, counting_receive, guarded_send)


async def _too_large(send: Send, limit: int) -> None:
    body = json.dumps({"detail": f"Request body too large (max {limit} bytes)"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
