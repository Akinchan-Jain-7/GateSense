"""Turn service errors into HTTP responses (see app/services/errors.py)."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.services.errors import (
    AuthenticationError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    ServiceError,
)

_STATUS_CODES: dict[type[ServiceError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidInputError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    RateLimitedError: status.HTTP_429_TOO_MANY_REQUESTS,
}


async def _handle_service_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ServiceError):  # registered only for ServiceError
        raise exc
    code = next(
        (code for cls, code in _STATUS_CODES.items() if isinstance(exc, cls)),
        status.HTTP_400_BAD_REQUEST,
    )
    headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None
    if isinstance(exc, RateLimitedError):
        headers = {"Retry-After": str(exc.retry_after)}
    return JSONResponse(status_code=code, content={"detail": exc.message}, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, _handle_service_error)
