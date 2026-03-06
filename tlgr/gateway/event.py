"""Thin event envelope for the Gateway pipeline.

The envelope carries a source discriminator and the raw event payload.
Filters extract what they need from ``raw`` directly, keeping the envelope
protocol-agnostic so it can wrap Telethon events, inbound webhook payloads,
or any future event source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Event:
    source: str
    raw: Any
    account: str = ""
    event_type: str = "new_message"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
