"""Message filtering for selective forwarding."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any

from telethon.tl.types import Message


class MessageType(Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    AUDIO = "audio"
    POLL = "poll"
    LOCATION = "location"
    LIVE_LOCATION = "live_location"
    CONTACT = "contact"
    GAME = "game"
    INVOICE = "invoice"
    DICE = "dice"
    GIF = "gif"
    WEBPAGE = "webpage"
    UNSUPPORTED = "unsupported"


def detect_message_type(message: Message) -> MessageType:
    from telethon.tl.types import (
        MessageMediaPhoto,
        MessageMediaDocument,
        MessageMediaPoll,
        MessageMediaGeo,
        MessageMediaGeoLive,
        MessageMediaContact,
        MessageMediaWebPage,
        MessageMediaGame,
        MessageMediaInvoice,
        MessageMediaDice,
        DocumentAttributeSticker,
        DocumentAttributeVideo,
        DocumentAttributeAudio,
        DocumentAttributeAnimated,
    )

    if not message.media:
        return MessageType.TEXT
    media = message.media
    if isinstance(media, MessageMediaPhoto):
        return MessageType.PHOTO
    if isinstance(media, MessageMediaPoll):
        return MessageType.POLL
    if isinstance(media, MessageMediaGeoLive):
        return MessageType.LIVE_LOCATION
    if isinstance(media, MessageMediaGeo):
        return MessageType.LOCATION
    if isinstance(media, MessageMediaContact):
        return MessageType.CONTACT
    if isinstance(media, MessageMediaGame):
        return MessageType.GAME
    if isinstance(media, MessageMediaInvoice):
        return MessageType.INVOICE
    if isinstance(media, MessageMediaDice):
        return MessageType.DICE
    if isinstance(media, MessageMediaWebPage):
        return MessageType.WEBPAGE
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if doc is None:
            return MessageType.UNSUPPORTED
        is_animated = False
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeAnimated):
                is_animated = True
            if isinstance(attr, DocumentAttributeSticker):
                return MessageType.STICKER
            if isinstance(attr, DocumentAttributeVideo):
                if attr.round_message:
                    return MessageType.VIDEO_NOTE
                if is_animated:
                    return MessageType.GIF
                return MessageType.VIDEO
            if isinstance(attr, DocumentAttributeAudio):
                if attr.voice:
                    return MessageType.VOICE
                return MessageType.AUDIO
        if is_animated or (hasattr(doc, "mime_type") and doc.mime_type == "image/gif"):
            return MessageType.GIF
        return MessageType.DOCUMENT
    return MessageType.UNSUPPORTED


def is_forwardable(message: Message) -> tuple[bool, str]:
    if message.action is not None:
        return False, f"Service message: {type(message.action).__name__}"
    if not message.text and not message.media:
        return False, "Empty message"
    if message.media:
        if hasattr(message.media, "ttl_seconds") and message.media.ttl_seconds:
            return False, "Self-destructing message"
    return True, ""


@dataclass
class MessageFilter:
    types: list[MessageType] | None = None
    exclude_types: list[MessageType] | None = None
    after: datetime | None = None
    before: datetime | None = None
    contains: list[str] | None = None
    contains_any: list[str] | None = None
    excludes: list[str] | None = None
    regex: str | None = None
    has_media: bool | None = None
    min_size: int | None = None
    max_size: int | None = None
    from_users: list[int] | None = None
    exclude_users: list[int] | None = None
    is_reply: bool | None = None
    is_forward: bool | None = None
    has_links: bool | None = None
    _compiled_regex: re.Pattern | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.regex:
            self._compiled_regex = re.compile(self.regex, re.IGNORECASE)

    def matches(self, message: Message) -> tuple[bool, str]:
        if self.types:
            mt = detect_message_type(message)
            if mt not in self.types:
                return False, f"type {mt.value} not in {[t.value for t in self.types]}"
        if self.exclude_types:
            mt = detect_message_type(message)
            if mt in self.exclude_types:
                return False, f"type {mt.value} excluded"
        msg_date = message.date
        if msg_date and self.after:
            a = self.after.replace(tzinfo=timezone.utc) if self.after.tzinfo is None else self.after
            d = msg_date.replace(tzinfo=timezone.utc) if msg_date.tzinfo is None else msg_date
            if d < a:
                return False, f"before cutoff"
        if msg_date and self.before:
            b = self.before.replace(tzinfo=timezone.utc) if self.before.tzinfo is None else self.before
            d = msg_date.replace(tzinfo=timezone.utc) if msg_date.tzinfo is None else msg_date
            if d > b:
                return False, f"after cutoff"
        text = (message.text or message.message or "").lower()
        if self.contains:
            for kw in self.contains:
                if kw.lower() not in text:
                    return False, f"missing keyword: {kw}"
        if self.contains_any:
            if not any(kw.lower() in text for kw in self.contains_any):
                return False, "none of keywords found"
        if self.excludes:
            for kw in self.excludes:
                if kw.lower() in text:
                    return False, f"excluded keyword: {kw}"
        if self._compiled_regex and not self._compiled_regex.search(message.text or ""):
            return False, "regex not matched"
        if self.has_media is not None:
            if (message.media is not None) != self.has_media:
                return False, "media filter"
        sender_id = message.sender_id
        if self.from_users and sender_id not in self.from_users:
            return False, "sender not allowed"
        if self.exclude_users and sender_id in self.exclude_users:
            return False, "sender excluded"
        if self.is_reply is not None:
            if (message.reply_to is not None) != self.is_reply:
                return False, "reply filter"
        if self.is_forward is not None:
            if (message.forward is not None) != self.is_forward:
                return False, "forward filter"
        if self.has_links is not None:
            has = bool(message.entities and any(
                hasattr(e, "url") or e.__class__.__name__ in ("MessageEntityUrl", "MessageEntityTextUrl")
                for e in message.entities
            ))
            if has != self.has_links:
                return False, "links filter"
        return True, "passed"

    def is_empty(self) -> bool:
        return all(
            getattr(self, f.name) is None
            for f in self.__dataclass_fields__.values()
            if f.name != "_compiled_regex"
        )


def parse_date(date_str: str) -> datetime:
    date_str = date_str.strip()
    rel = re.match(r"^(\d+)([dwmh])$", date_str.lower())
    if rel:
        val, unit = int(rel.group(1)), rel.group(2)
        now = datetime.now(timezone.utc)
        deltas = {"h": timedelta(hours=val), "d": timedelta(days=val), "w": timedelta(weeks=val), "m": timedelta(days=val * 30)}
        return now - deltas[unit]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {date_str}")


def parse_message_types(types_str: str) -> list[MessageType]:
    valid = {t.value: t for t in MessageType}
    result: list[MessageType] = []
    for t in types_str.split(","):
        t = t.strip().lower()
        if t and t in valid:
            result.append(valid[t])
        elif t:
            raise ValueError(f"Invalid message type: {t}")
    return result


def create_filter_from_job_config(fc) -> MessageFilter | None:
    """Create a MessageFilter from a JobFilterConfig dataclass."""
    if fc is None:
        return None
    kwargs: dict[str, Any] = {}
    if fc.types:
        kwargs["types"] = [MessageType(t) for t in fc.types]
    if fc.exclude_types:
        kwargs["exclude_types"] = [MessageType(t) for t in fc.exclude_types]
    if fc.after:
        kwargs["after"] = parse_date(fc.after)
    if fc.before:
        kwargs["before"] = parse_date(fc.before)
    if fc.contains:
        kwargs["contains"] = fc.contains
    if fc.contains_any:
        kwargs["contains_any"] = fc.contains_any
    if fc.excludes:
        kwargs["excludes"] = fc.excludes
    if fc.regex:
        kwargs["regex"] = fc.regex
    if fc.has_media is not None:
        kwargs["has_media"] = fc.has_media
    if fc.from_users:
        kwargs["from_users"] = fc.from_users
    if fc.exclude_users:
        kwargs["exclude_users"] = fc.exclude_users
    if fc.is_reply is not None:
        kwargs["is_reply"] = fc.is_reply
    if fc.is_forward is not None:
        kwargs["is_forward"] = fc.is_forward
    if fc.has_links is not None:
        kwargs["has_links"] = fc.has_links
    if not kwargs:
        return None
    return MessageFilter(**kwargs)
