"""Sender/user filters — allow-list and block-list by user ID."""

from __future__ import annotations

from typing import Any

from tlgr.filters import register_filter
from tlgr.gateway.event import Event


def _sender_id(event: Event) -> int | None:
    if event.source == "telegram":
        return event.raw.message.sender_id
    if isinstance(event.raw, dict):
        return event.raw.get("sender_id")
    return None


@register_filter("from_users")
def filter_from_users(event: Event, value: Any) -> tuple[bool, str]:
    """Sender must be in the given list of user IDs.  Value: list[int]."""
    sid = _sender_id(event)
    allowed = value if isinstance(value, list) else [value]
    if sid in allowed:
        return True, "sender allowed"
    return False, "sender not allowed"


@register_filter("exclude_users")
def filter_exclude_users(event: Event, value: Any) -> tuple[bool, str]:
    """Sender must NOT be in the given list of user IDs.  Value: list[int]."""
    sid = _sender_id(event)
    excluded = value if isinstance(value, list) else [value]
    if sid in excluded:
        return False, "sender excluded"
    return True, "sender allowed"
