"""Domain errors of the control plane, mapped to HTTP problems by the API layer."""

from __future__ import annotations

from typing import Any


class ControlError(Exception):
    status = 400
    title = "Bad Request"

    def __init__(self, detail: str, extra: dict[str, Any] | None = None) -> None:
        self.detail = detail
        self.extra = extra or {}
        super().__init__(detail)


class NotFound(ControlError):
    status = 404
    title = "Not Found"


class Conflict(ControlError):
    status = 409
    title = "Conflict"


class PreconditionFailed(ControlError):
    status = 412
    title = "Precondition Failed"


class Invalid(ControlError):
    status = 422
    title = "Unprocessable Content"


class Forbidden(ControlError):
    status = 403
    title = "Forbidden"


class Unauthorized(ControlError):
    status = 401
    title = "Unauthorized"


class TooManyRequests(ControlError):
    status = 429
    title = "Too Many Requests"
