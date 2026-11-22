"""Errors raised by services.

Services know nothing about HTTP. They raise these, and `app/api/errors.py` turns each one
into a response with the right status code. That keeps business rules testable without
a web server, and lets Celery jobs (Phase 5) reuse the same services.
"""


class ServiceError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    """The record doesn't exist (or belongs to another society). → 404"""


class ConflictError(ServiceError):
    """The request clashes with existing data, e.g. a duplicate plate. → 409"""


class InvalidInputError(ServiceError):
    """Well-formed but not acceptable, e.g. a plate that isn't a valid Indian format. → 422"""


class AuthenticationError(ServiceError):
    """Wrong credentials or a bad/expired/revoked token. → 401"""


class RateLimitedError(ServiceError):
    """Too many requests from one client in a short time. → 429 with Retry-After"""

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after
