"""Utilities for message type detection, chat validation, and formatting."""

from enum import Enum
from typing import Tuple, Union

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
    User,
    Chat,
    Channel,
)


class MessageType(Enum):
    """Types of Telegram messages."""
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


class ChatType(Enum):
    """Types of Telegram chats."""
    PRIVATE = "private"      # User-to-user DM
    GROUP = "group"          # Basic group
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


def detect_message_type(message) -> MessageType:
    """Detect the type of a Telegram message.
    
    Args:
        message: Telethon Message object
        
    Returns:
        MessageType enum value
    """
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
        
        # Check for GIF by mime type if not already detected
        if is_animated or (hasattr(doc, 'mime_type') and doc.mime_type == 'image/gif'):
            return MessageType.GIF
        
        return MessageType.DOCUMENT
    
    return MessageType.UNSUPPORTED


async def get_chat_type(client, chat_id: Union[int, str]) -> ChatType:
    """Get the type of a Telegram chat.
    
    Args:
        client: Telethon client
        chat_id: Chat ID or username
        
    Returns:
        ChatType enum value
    """
    entity = await client.get_entity(chat_id)
    
    if isinstance(entity, User):
        return ChatType.PRIVATE
    
    if isinstance(entity, Chat):
        return ChatType.GROUP
    
    if isinstance(entity, Channel):
        if entity.megagroup:
            return ChatType.SUPERGROUP
        return ChatType.CHANNEL
    
    # Fallback
    return ChatType.GROUP


async def estimate_message_count(client, chat_id: Union[int, str], min_id: int = 0) -> int:
    """Estimate total messages in chat for progress display.
    
    Args:
        client: Telethon client
        chat_id: Chat ID to count messages for
        min_id: Minimum message ID (for resume operations)
        
    Returns:
        Estimated message count
    """
    latest_id = 0
    async for msg in client.iter_messages(chat_id, limit=1):
        latest_id = msg.id
    
    if latest_id == 0:
        return 0
    
    # If resuming, calculate remaining
    if min_id > 0:
        return max(0, latest_id - min_id)
    
    # Return latest ID as upper bound estimate
    return latest_id


def format_estimate(count: int) -> str:
    """Format message count with ~ prefix for estimates.
    
    Args:
        count: Number of messages
        
    Returns:
        Human-readable string like "~12.5K messages"
    """
    if count >= 1_000_000:
        return f"~{count / 1_000_000:.1f}M messages"
    if count >= 1000:
        return f"~{count / 1000:.1f}K messages"
    return f"~{count} messages"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string like "1h 30m" or "45s"
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    return f"{hours}h {mins}m"


def format_size(bytes_count: int) -> str:
    """Format byte size in human-readable format.
    
    Args:
        bytes_count: Size in bytes
        
    Returns:
        Formatted string like "1.5MB"
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_count < 1024:
            return f"{bytes_count:.1f}{unit}"
        bytes_count /= 1024
    return f"{bytes_count:.1f}TB"


def validate_chat_id(chat_id: str) -> Union[int, str]:
    """Validate and normalize chat ID input.
    
    Args:
        chat_id: Chat ID as string (can be numeric or @username)
        
    Returns:
        Normalized chat ID (int or username string)
        
    Raises:
        ValueError: If chat ID is invalid
    """
    if not chat_id:
        raise ValueError("Chat ID cannot be empty")
    
    # Try to parse as integer
    try:
        return int(chat_id)
    except ValueError:
        pass
    
    # Check if it's a username
    if chat_id.startswith('@'):
        return chat_id
    
    # Allow usernames without @ prefix
    if chat_id.replace('_', '').isalnum():
        return f"@{chat_id}"
    
    raise ValueError(f"Invalid chat ID: {chat_id}")


def is_forwardable(message) -> Tuple[bool, str]:
    """Check if a message can be forwarded.
    
    Args:
        message: Telethon Message object
        
    Returns:
        Tuple of (can_forward, reason_if_not)
    """
    # Service/action messages cannot be forwarded
    if message.action is not None:
        action_name = type(message.action).__name__
        return False, f"Service message: {action_name}"
    
    # Empty messages (no text and no media)
    if not message.text and not message.media:
        return False, "Empty message"
    
    # Self-destructing messages
    if message.media:
        if hasattr(message.media, 'ttl_seconds') and message.media.ttl_seconds:
            return False, "Self-destructing message"
    
    return True, ""


async def check_forward_restrictions(client, chat_id: Union[int, str]) -> Tuple[bool, str]:
    """Check if a chat allows forwarding.
    
    Args:
        client: Telethon client
        chat_id: Chat ID to check
        
    Returns:
        Tuple of (can_forward, reason_if_not)
    """
    try:
        entity = await client.get_entity(chat_id)
        
        # Check for noforwards flag on channels/groups
        if hasattr(entity, 'noforwards') and entity.noforwards:
            return False, "Source chat has forwarding disabled (noforwards)"
        
        return True, ""
    except Exception as e:
        return False, f"Cannot access chat: {e}"


async def check_delete_permission(client, chat_id: Union[int, str], user_id: int) -> Tuple[bool, str]:
    """Check if user can delete messages from a chat.
    
    Args:
        client: Telethon client
        chat_id: Chat ID to check
        user_id: User ID to check permissions for
        
    Returns:
        Tuple of (can_delete, reason)
    """
    from telethon.tl.functions.channels import GetParticipantRequest
    from telethon.tl.types import (
        ChannelParticipantCreator,
        ChannelParticipantAdmin,
    )
    
    try:
        entity = await client.get_entity(chat_id)
        
        # Private chats - can always delete own messages
        if isinstance(entity, User):
            return True, "Private chat - can delete own messages"
        
        # Basic groups - can delete own messages
        if isinstance(entity, Chat):
            return True, "Group - can delete own messages"
        
        # Channels/Supergroups - need to check admin rights
        if isinstance(entity, Channel):
            try:
                participant = await client(GetParticipantRequest(entity, user_id))
                p = participant.participant
                
                if isinstance(p, ChannelParticipantCreator):
                    return True, "Channel creator"
                
                if isinstance(p, ChannelParticipantAdmin):
                    if hasattr(p.admin_rights, 'delete_messages') and p.admin_rights.delete_messages:
                        return True, "Admin with delete permission"
                    return False, "Admin without delete permission"
                
                return False, "Not an admin"
            except Exception:
                return False, "Cannot verify admin status"
        
        return False, "Unknown chat type"
    except Exception as e:
        return False, f"Cannot check permissions: {e}"
