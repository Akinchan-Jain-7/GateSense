"""A thin client for the GateSense API, acting as many people at once.

- People sign in with the shared demo password. Tokens are cached per person and renewed
  with the refresh token (logins are rate-limited; refreshes aren't).
- Cameras send reads with their device keys.
- After a demo reset every account and camera key is recreated, so old tokens and keys
  stop working. That surfaces as `NeedsBootstrapError`: the simulator starts over.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class NeedsBootstrapError(Exception):
    """Credentials no longer work (the demo was reset): sign in and fetch keys again."""


class ApiError(Exception):
    def __init__(self, status: int, detail: object) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status


@dataclass
class Tokens:
    access: str
    refresh: str


class Api:
    def __init__(
        self, base_url: str, password: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=15, transport=transport)
        self.password = password
        self.tokens: dict[str, Tokens] = {}

    def close(self) -> None:
        self.http.close()

    # --- people -------------------------------------------------------------------

    def _login(self, email: str) -> Tokens:
        response = self.http.post(
            "/api/v1/auth/login", data={"username": email, "password": self.password}
        )
        if response.status_code == 401:
            raise NeedsBootstrapError(f"{email} can't sign in")
        _raise_for(response)
        body = response.json()
        tokens = Tokens(body["access_token"], body["refresh_token"])
        self.tokens[email] = tokens
        return tokens

    def _refresh(self, email: str) -> Tokens | None:
        old = self.tokens.get(email)
        if old is None:
            return None
        response = self.http.post("/api/v1/auth/refresh", json={"refresh_token": old.refresh})
        if response.is_error:
            return None
        body = response.json()
        tokens = Tokens(body["access_token"], body["refresh_token"])
        self.tokens[email] = tokens
        return tokens

    def call(self, email: str, method: str, path: str, **kwargs: Any) -> Any:
        """Call the API as `email`, renewing the session once if it has expired."""
        tokens = self.tokens.get(email) or self._login(email)
        for attempt in range(2):
            response = self.http.request(
                method, path, headers={"Authorization": f"Bearer {tokens.access}"}, **kwargs
            )
            if response.status_code != 401 or attempt == 1:
                break
            tokens = self._refresh(email) or self._login(email)
        if response.status_code == 401:
            raise NeedsBootstrapError(f"{email} was signed out")
        _raise_for(response)
        return response.json() if response.content else None

    def all_pages(self, email: str, path: str, **params: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.call(email, "GET", path, params={**params, "limit": 100, "offset": offset})
            items.extend(page["items"])
            offset += 100
            if offset >= page["total"] or not page["items"]:
                return items

    # --- cameras ------------------------------------------------------------------

    def read(
        self,
        key: str,
        plate_text: str,
        confidence: float,
        snapshot: bytes | None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        data = {
            "plate_text": plate_text,
            "confidence": f"{confidence:.3f}",
            "captured_at": (at or datetime.now(UTC)).isoformat(),
        }
        files = {"snapshot": ("snapshot.jpg", snapshot, "image/jpeg")} if snapshot else None
        response = self.http.post(
            "/api/v1/gate-events", data=data, files=files, headers={"X-Device-Key": key}
        )
        if response.status_code == 401:
            raise NeedsBootstrapError("camera key no longer valid")
        _raise_for(response)
        result: dict[str, Any] = response.json()
        return result


def _raise_for(response: httpx.Response) -> None:
    if response.is_error:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        raise ApiError(response.status_code, detail)
