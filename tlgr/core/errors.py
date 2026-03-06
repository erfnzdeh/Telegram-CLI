"""Error types and JSON error formatting for tlgr."""

from __future__ import annotations

import json
import sys
from typing import Any


class TlgrError(Exception):
    """Base error for all tlgr errors."""

    code: str = "TLGR_ERROR"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class AuthenticationError(TlgrError):
    code = "AUTH_ERROR"


class SessionError(TlgrError):
    code = "SESSION_ERROR"


class ConfigurationError(TlgrError):
    code = "CONFIG_ERROR"


class ChatNotFoundError(TlgrError):
    code = "CHAT_NOT_FOUND"


class PermissionError_(TlgrError):
    code = "PERMISSION_DENIED"


class RateLimitError(TlgrError):
    code = "RATE_LIMITED"

    def __init__(self, message: str, wait_seconds: int = 0):
        super().__init__(message, code="RATE_LIMITED")
        self.wait_seconds = wait_seconds


class DaemonError(TlgrError):
    code = "DAEMON_ERROR"


class DaemonNotRunningError(DaemonError):
    code = "DAEMON_NOT_RUNNING"


class IPCError(TlgrError):
    code = "IPC_ERROR"


def format_error_json(error: Exception) -> dict[str, Any]:
    """Format an error as a JSON-serializable dict."""
    code = getattr(error, "code", "UNKNOWN_ERROR")
    result: dict[str, Any] = {"error": str(error), "code": code}
    if isinstance(error, RateLimitError) and error.wait_seconds:
        result["wait_seconds"] = error.wait_seconds
    return result


def emit_error(error: Exception, use_json: bool = False) -> None:
    """Emit an error to stderr (human) and optionally stdout (JSON)."""
    if use_json:
        json.dump(format_error_json(error), sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()
    print(f"Error: {error}", file=sys.stderr)
