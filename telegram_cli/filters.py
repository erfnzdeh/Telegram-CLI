"""Message filtering for selective forwarding.

This module provides filters that can be applied to messages
to selectively forward based on various criteria.
"""

import re
from datetime import datetime, timezone
from typing import List, Optional, Callable, Any
from dataclasses import dataclass, field

from telethon.tl.types import Message

from .utils import MessageType, detect_message_type


@dataclass
class MessageFilter:
    """Filter configuration for message selection.
    
    All conditions are AND-ed together. A message must pass all
    specified filters to be included.
    """
    
    # Type filters
    types: Optional[List[MessageType]] = None
    exclude_types: Optional[List[MessageType]] = None
    
    # Date filters
    after: Optional[datetime] = None
    before: Optional[datetime] = None
    
    # Content filters
    contains: Optional[List[str]] = None  # Must contain ALL of these
    contains_any: Optional[List[str]] = None  # Must contain ANY of these
    excludes: Optional[List[str]] = None  # Must NOT contain ANY of these
    regex: Optional[str] = None  # Must match this regex
    
    # Media filters
    has_media: Optional[bool] = None
    min_size: Optional[int] = None  # Minimum file size in bytes
    max_size: Optional[int] = None  # Maximum file size in bytes
    
    # Sender filters
    from_users: Optional[List[int]] = None  # Only from these user IDs
    exclude_users: Optional[List[int]] = None  # Not from these user IDs
    
    # Other filters
    is_reply: Optional[bool] = None
    is_forward: Optional[bool] = None
    has_links: Optional[bool] = None
    
    # Compiled regex (internal)
    _compiled_regex: Optional[re.Pattern] = field(default=None, repr=False)
    
    def __post_init__(self):
        """Compile regex if provided."""
        if self.regex:
            try:
                self._compiled_regex = re.compile(self.regex, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern: {e}")
    
    def matches(self, message: Message) -> tuple[bool, str]:
        """Check if a message matches all filter criteria.
        
        Args:
            message: Telethon Message object
            
        Returns:
            Tuple of (matches, reason). If matches is False, reason
            explains why the message was filtered out.
        """
        # Type filter
        if self.types:
            msg_type = detect_message_type(message)
            if msg_type not in self.types:
                return False, f"type {msg_type.value} not in {[t.value for t in self.types]}"
        
        if self.exclude_types:
            msg_type = detect_message_type(message)
            if msg_type in self.exclude_types:
                return False, f"type {msg_type.value} is excluded"
        
        # Date filter
        msg_date = message.date
        if msg_date and self.after:
            # Ensure both are timezone-aware for comparison
            after_dt = self.after
            if after_dt.tzinfo is None:
                after_dt = after_dt.replace(tzinfo=timezone.utc)
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            if msg_date < after_dt:
                return False, f"date {msg_date} is before {after_dt}"
        
        if msg_date and self.before:
            before_dt = self.before
            if before_dt.tzinfo is None:
                before_dt = before_dt.replace(tzinfo=timezone.utc)
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            if msg_date > before_dt:
                return False, f"date {msg_date} is after {before_dt}"
        
        # Content filters
        text = message.text or message.message or ''
        text_lower = text.lower()
        
        if self.contains:
            for keyword in self.contains:
                if keyword.lower() not in text_lower:
                    return False, f"missing keyword: {keyword}"
        
        if self.contains_any:
            found = any(kw.lower() in text_lower for kw in self.contains_any)
            if not found:
                return False, f"none of keywords found: {self.contains_any}"
        
        if self.excludes:
            for keyword in self.excludes:
                if keyword.lower() in text_lower:
                    return False, f"contains excluded keyword: {keyword}"
        
        if self._compiled_regex:
            if not self._compiled_regex.search(text):
                return False, f"does not match regex: {self.regex}"
        
        # Media filters
        if self.has_media is not None:
            has_media = message.media is not None
            if has_media != self.has_media:
                return False, f"has_media={has_media}, expected {self.has_media}"
        
        if self.min_size is not None or self.max_size is not None:
            file_size = get_message_file_size(message)
            if file_size is not None:
                if self.min_size is not None and file_size < self.min_size:
                    return False, f"file size {file_size} < min {self.min_size}"
                if self.max_size is not None and file_size > self.max_size:
                    return False, f"file size {file_size} > max {self.max_size}"
        
        # Sender filters
        sender_id = message.sender_id
        if self.from_users and sender_id not in self.from_users:
            return False, f"sender {sender_id} not in allowed list"
        
        if self.exclude_users and sender_id in self.exclude_users:
            return False, f"sender {sender_id} is excluded"
        
        # Other filters
        if self.is_reply is not None:
            is_reply = message.reply_to is not None
            if is_reply != self.is_reply:
                return False, f"is_reply={is_reply}, expected {self.is_reply}"
        
        if self.is_forward is not None:
            is_forward = message.forward is not None
            if is_forward != self.is_forward:
                return False, f"is_forward={is_forward}, expected {self.is_forward}"
        
        if self.has_links is not None:
            has_links = bool(message.entities and any(
                hasattr(e, 'url') or e.__class__.__name__ in ('MessageEntityUrl', 'MessageEntityTextUrl')
                for e in message.entities
            ))
            if has_links != self.has_links:
                return False, f"has_links={has_links}, expected {self.has_links}"
        
        return True, "passed all filters"
    
    def is_empty(self) -> bool:
        """Check if no filters are configured."""
        return all([
            self.types is None,
            self.exclude_types is None,
            self.after is None,
            self.before is None,
            self.contains is None,
            self.contains_any is None,
            self.excludes is None,
            self.regex is None,
            self.has_media is None,
            self.min_size is None,
            self.max_size is None,
            self.from_users is None,
            self.exclude_users is None,
            self.is_reply is None,
            self.is_forward is None,
            self.has_links is None,
        ])
    
    def describe(self) -> str:
        """Get a human-readable description of active filters."""
        parts = []
        
        if self.types:
            parts.append(f"types: {[t.value for t in self.types]}")
        if self.exclude_types:
            parts.append(f"exclude types: {[t.value for t in self.exclude_types]}")
        if self.after:
            parts.append(f"after: {self.after.strftime('%Y-%m-%d %H:%M')}")
        if self.before:
            parts.append(f"before: {self.before.strftime('%Y-%m-%d %H:%M')}")
        if self.contains:
            parts.append(f"contains: {self.contains}")
        if self.contains_any:
            parts.append(f"contains any: {self.contains_any}")
        if self.excludes:
            parts.append(f"excludes: {self.excludes}")
        if self.regex:
            parts.append(f"regex: {self.regex}")
        if self.has_media is not None:
            parts.append(f"has_media: {self.has_media}")
        if self.min_size:
            parts.append(f"min_size: {format_size(self.min_size)}")
        if self.max_size:
            parts.append(f"max_size: {format_size(self.max_size)}")
        if self.from_users:
            parts.append(f"from_users: {self.from_users}")
        if self.exclude_users:
            parts.append(f"exclude_users: {self.exclude_users}")
        if self.is_reply is not None:
            parts.append(f"is_reply: {self.is_reply}")
        if self.is_forward is not None:
            parts.append(f"is_forward: {self.is_forward}")
        if self.has_links is not None:
            parts.append(f"has_links: {self.has_links}")
        
        return ", ".join(parts) if parts else "no filters"


def get_message_file_size(message: Message) -> Optional[int]:
    """Get the file size of a message's media, if any.
    
    Args:
        message: Telethon Message object
        
    Returns:
        File size in bytes, or None if no file
    """
    if not message.media:
        return None
    
    # Try to get document size
    if hasattr(message.media, 'document') and message.media.document:
        return getattr(message.media.document, 'size', None)
    
    # Try to get photo size (largest)
    if hasattr(message.media, 'photo') and message.media.photo:
        sizes = getattr(message.media.photo, 'sizes', [])
        if sizes:
            # Get the largest size
            for size in reversed(sizes):
                if hasattr(size, 'size'):
                    return size.size
    
    return None


def format_size(size_bytes: int) -> str:
    """Format size in bytes to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


def parse_size(size_str: str) -> int:
    """Parse size string like '10MB' to bytes.
    
    Args:
        size_str: Size string (e.g., '10MB', '1.5GB', '500KB')
        
    Returns:
        Size in bytes
        
    Raises:
        ValueError: If format is invalid
    """
    size_str = size_str.strip().upper()
    
    units = {
        'B': 1,
        'KB': 1024,
        'K': 1024,
        'MB': 1024 * 1024,
        'M': 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
        'G': 1024 * 1024 * 1024,
    }
    
    for unit, multiplier in sorted(units.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(unit):
            try:
                value = float(size_str[:-len(unit)])
                return int(value * multiplier)
            except ValueError:
                raise ValueError(f"Invalid size format: {size_str}")
    
    # Assume bytes if no unit
    try:
        return int(size_str)
    except ValueError:
        raise ValueError(f"Invalid size format: {size_str}")


def parse_date(date_str: str) -> datetime:
    """Parse date string to datetime.
    
    Supports formats:
        - YYYY-MM-DD
        - YYYY-MM-DD HH:MM
        - YYYY-MM-DD HH:MM:SS
        - Relative: 1d, 7d, 1w, 1m (days, weeks, months ago)
        
    Args:
        date_str: Date string
        
    Returns:
        datetime object (UTC)
        
    Raises:
        ValueError: If format is invalid
    """
    from datetime import timedelta
    
    date_str = date_str.strip()
    
    # Check for relative dates
    relative_match = re.match(r'^(\d+)([dwmh])$', date_str.lower())
    if relative_match:
        value = int(relative_match.group(1))
        unit = relative_match.group(2)
        
        now = datetime.now(timezone.utc)
        
        if unit == 'h':
            return now - timedelta(hours=value)
        elif unit == 'd':
            return now - timedelta(days=value)
        elif unit == 'w':
            return now - timedelta(weeks=value)
        elif unit == 'm':
            return now - timedelta(days=value * 30)
    
    # Try absolute date formats
    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
        '%d/%m/%Y %H:%M',
        '%d/%m/%Y',
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    
    raise ValueError(
        f"Invalid date format: {date_str}. "
        "Use YYYY-MM-DD, YYYY-MM-DD HH:MM, or relative like 7d, 1w, 1m"
    )


def parse_message_types(types_str: str) -> List[MessageType]:
    """Parse comma-separated message types.
    
    Args:
        types_str: Comma-separated types (e.g., "photo,video,text")
        
    Returns:
        List of MessageType
        
    Raises:
        ValueError: If type is invalid
    """
    types = []
    valid_types = {t.value: t for t in MessageType}
    
    for type_str in types_str.split(','):
        type_str = type_str.strip().lower()
        if not type_str:
            continue
        
        if type_str not in valid_types:
            valid = ", ".join(valid_types.keys())
            raise ValueError(f"Invalid message type: {type_str}. Valid types: {valid}")
        
        types.append(valid_types[type_str])
    
    return types


def create_filter_from_args(args) -> MessageFilter:
    """Create a MessageFilter from CLI arguments.
    
    Args:
        args: argparse Namespace with filter arguments
        
    Returns:
        MessageFilter instance
    """
    filter_kwargs = {}
    
    # Type filters
    if getattr(args, 'type', None):
        filter_kwargs['types'] = parse_message_types(args.type)
    
    if getattr(args, 'exclude_type', None):
        filter_kwargs['exclude_types'] = parse_message_types(args.exclude_type)
    
    # Date filters
    if getattr(args, 'after', None):
        filter_kwargs['after'] = parse_date(args.after)
    
    if getattr(args, 'before', None):
        filter_kwargs['before'] = parse_date(args.before)
    
    # Content filters
    if getattr(args, 'contains', None):
        filter_kwargs['contains'] = args.contains
    
    if getattr(args, 'contains_any', None):
        filter_kwargs['contains_any'] = args.contains_any
    
    if getattr(args, 'excludes', None):
        filter_kwargs['excludes'] = args.excludes
    
    if getattr(args, 'regex', None):
        filter_kwargs['regex'] = args.regex
    
    # Media filters
    if getattr(args, 'media_only', False):
        filter_kwargs['has_media'] = True
    elif getattr(args, 'text_only', False):
        filter_kwargs['has_media'] = False
    
    if getattr(args, 'min_size', None):
        filter_kwargs['min_size'] = parse_size(args.min_size)
    
    if getattr(args, 'max_size', None):
        filter_kwargs['max_size'] = parse_size(args.max_size)
    
    # Other filters
    if getattr(args, 'no_replies', False):
        filter_kwargs['is_reply'] = False
    elif getattr(args, 'replies_only', False):
        filter_kwargs['is_reply'] = True
    
    if getattr(args, 'no_forwards', False):
        filter_kwargs['is_forward'] = False
    elif getattr(args, 'forwards_only', False):
        filter_kwargs['is_forward'] = True
    
    if getattr(args, 'no_links', False):
        filter_kwargs['has_links'] = False
    elif getattr(args, 'links_only', False):
        filter_kwargs['has_links'] = True
    
    return MessageFilter(**filter_kwargs)
