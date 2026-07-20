"""
Error handling for LinkedIn Corp MCP Server.

Normalizes LinkedIn API errors into MCP-compatible format:
- error_code
- error_message
- retryable
- original_provider_error
"""

from typing import Any, Optional


class LinkedInError(Exception):
    """Base error for LinkedIn operations."""

    def __init__(
        self,
        message: str,
        error_code: str = "LINKEDIN_ERROR",
        retryable: bool = False,
        original_error: Optional[Any] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.retryable = retryable
        self.original_error = original_error
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "error_message": self.message,
            "retryable": self.retryable,
            "original_provider_error": str(self.original_error)
            if self.original_error
            else None,
        }


class LinkedInAuthError(LinkedInError):
    def __init__(
        self,
        message: str = "Token expired or invalid",
        original_error: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            error_code="AUTH_ERROR",
            retryable=True,
            original_error=original_error,
        )


class LinkedInNotFoundError(LinkedInError):
    def __init__(
        self,
        message: str = "Resource not found",
        original_error: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            error_code="NOT_FOUND",
            retryable=False,
            original_error=original_error,
        )


class LinkedInPermissionError(LinkedInError):
    def __init__(
        self,
        message: str = "Permission denied",
        original_error: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            error_code="PERMISSION_DENIED",
            retryable=False,
            original_error=original_error,
        )


class LinkedInRateLimitError(LinkedInError):
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        original_error: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            error_code="RATE_LIMIT",
            retryable=True,
            original_error=original_error,
        )


class LinkedInValidationError(LinkedInError):
    def __init__(
        self,
        message: str,
        original_error: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            retryable=False,
            original_error=original_error,
        )


def normalize_linkedin_error(
    exc: Exception, status_code: Optional[int] = None
) -> LinkedInError:
    """Map LinkedIn HTTP / transport errors to standardized LinkedInError subclasses."""
    error_str = str(exc).lower()
    code = status_code
    if code is None:
        if "401" in error_str:
            code = 401
        elif "403" in error_str:
            code = 403
        elif "404" in error_str:
            code = 404
        elif "429" in error_str:
            code = 429
        elif "500" in error_str or "502" in error_str or "503" in error_str:
            code = 500

    if code == 401 or ("invalid" in error_str and "token" in error_str):
        return LinkedInAuthError(message="Token expired or invalid", original_error=exc)
    if code == 403 or "permission" in error_str or "forbidden" in error_str:
        return LinkedInPermissionError(message="Permission denied", original_error=exc)
    if code == 404 or "not found" in error_str:
        return LinkedInNotFoundError(message="Resource not found", original_error=exc)
    if code == 429 or "rate" in error_str or "throttle" in error_str:
        return LinkedInRateLimitError(message="Rate limit exceeded", original_error=exc)
    if code in (500, 502, 503):
        return LinkedInError(
            message="LinkedIn API server error",
            error_code="PROVIDER_ERROR",
            retryable=True,
            original_error=exc,
        )
    return LinkedInError(
        message=str(exc),
        error_code="UNKNOWN_ERROR",
        retryable=False,
        original_error=exc,
    )
