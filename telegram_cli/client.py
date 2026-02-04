"""Telethon client wrapper with optimized configuration."""

from pathlib import Path
from typing import Optional, List, Tuple, AsyncIterator

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import User, Chat, Channel, Dialog

from .config import Config, ConfigManager
from .logger import ForwarderLogger
from .errors import SessionError, ConfigurationError


def create_client(
    session_path: Path,
    api_id: int,
    api_hash: str,
    flood_sleep_threshold: int = 120,
    request_retries: int = 5,
    connection_retries: int = 5,
) -> TelegramClient:
    """Create a Telethon client with optimized settings.
    
    Args:
        session_path: Path to session file (without .session extension)
        api_id: Telegram API ID
        api_hash: Telegram API hash
        flood_sleep_threshold: Auto-sleep for flood waits under this threshold (seconds)
        request_retries: Number of times to retry failed requests
        connection_retries: Number of times to retry failed connections
        
    Returns:
        Configured TelegramClient instance
    """
    return TelegramClient(
        str(session_path),
        api_id,
        api_hash,
        # Auto-sleep for flood waits up to threshold (no manual handling needed)
        flood_sleep_threshold=flood_sleep_threshold,
        # Auto-retry on failures
        request_retries=request_retries,
        connection_retries=connection_retries,
        retry_delay=1,
        # Auto-reconnect on disconnect
        auto_reconnect=True,
        # Process updates in order for live forwarding
        sequential_updates=True,
    )


class ClientWrapper:
    """Wrapper around TelegramClient with convenience methods."""
    
    def __init__(
        self,
        config_manager: ConfigManager,
        logger: Optional[ForwarderLogger] = None
    ):
        """Initialize client wrapper.
        
        Args:
            config_manager: Configuration manager
            logger: Optional logger instance
        """
        self.config_manager = config_manager
        self.logger = logger
        self._client: Optional[TelegramClient] = None
        self._me: Optional[User] = None
    
    @property
    def client(self) -> TelegramClient:
        """Get the Telethon client.
        
        Raises:
            SessionError: If client is not initialized
        """
        if self._client is None:
            raise SessionError("Client not initialized. Call connect() first.")
        return self._client
    
    @property
    def me(self) -> User:
        """Get the current user.
        
        Raises:
            SessionError: If not logged in
        """
        if self._me is None:
            raise SessionError("Not logged in.")
        return self._me
    
    async def connect(self) -> bool:
        """Connect to Telegram.
        
        Returns:
            True if already authorized, False if login needed
            
        Raises:
            ConfigurationError: If API credentials are not configured
        """
        config = self.config_manager.get_config()
        
        if not config.is_configured():
            raise ConfigurationError(
                "API credentials not configured. "
                "Set TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables, "
                "or run 'telegram-forwarder login' to configure."
            )
        
        self._client = create_client(
            session_path=self.config_manager.session_path,
            api_id=config.api_id,
            api_hash=config.api_hash,
            flood_sleep_threshold=config.flood_sleep_threshold,
            request_retries=config.request_retries,
            connection_retries=config.connection_retries,
        )
        
        await self._client.connect()
        
        if await self._client.is_user_authorized():
            self._me = await self._client.get_me()
            return True
        
        return False
    
    async def login(
        self,
        phone: Optional[str] = None,
        code_callback=None,
        password_callback=None
    ) -> User:
        """Log in to Telegram.
        
        Args:
            phone: Phone number (will prompt if not provided)
            code_callback: Callback to get verification code
            password_callback: Callback to get 2FA password
            
        Returns:
            Current user
            
        Raises:
            SessionError: If login fails
        """
        if self._client is None:
            await self.connect()
        
        try:
            # Start the login flow
            if phone is None:
                phone = input("Enter phone number (with country code): ").strip()
            
            await self._client.send_code_request(phone)
            
            # Get verification code
            if code_callback:
                code = code_callback()
            else:
                code = input("Enter the verification code: ").strip()
            
            try:
                await self._client.sign_in(phone, code)
            except SessionPasswordNeededError:
                # 2FA enabled
                if password_callback:
                    password = password_callback()
                else:
                    import getpass
                    password = getpass.getpass("Enter 2FA password: ")
                
                await self._client.sign_in(password=password)
            
            self._me = await self._client.get_me()
            
            if self.logger:
                self.logger.success(f"Logged in as {self._me.first_name} (@{self._me.username or 'no username'})")
            
            return self._me
            
        except Exception as e:
            raise SessionError(f"Login failed: {e}")
    
    async def logout(self):
        """Log out, clear session, and remove credentials."""
        if self._client:
            try:
                await self._client.log_out()
            except Exception:
                pass
            await self._client.disconnect()
        
        self.config_manager.clear_session(clear_credentials=True)
        self._client = None
        self._me = None
        
        if self.logger:
            self.logger.success("Logged out, session and credentials cleared")
    
    async def disconnect(self):
        """Disconnect from Telegram."""
        if self._client:
            await self._client.disconnect()
    
    async def is_authorized(self) -> bool:
        """Check if currently authorized.
        
        Returns:
            True if authorized
        """
        if self._client is None:
            return False
        return await self._client.is_user_authorized()
    
    async def list_chats(
        self,
        limit: Optional[int] = None,
        archived: bool = False
    ) -> AsyncIterator[Tuple[int, str, str]]:
        """List available chats.
        
        Args:
            limit: Maximum number of chats to return
            archived: Include archived chats
            
        Yields:
            Tuples of (chat_id, chat_title, chat_type)
        """
        count = 0
        async for dialog in self.client.iter_dialogs(archived=archived):
            entity = dialog.entity
            
            # Determine chat type
            if isinstance(entity, User):
                # Check if this is "Saved Messages" (chat with yourself)
                if entity.is_self:
                    chat_type = "Saved"
                    title = "Saved Messages"
                else:
                    chat_type = "Private"
                    title = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                    if entity.username:
                        title += f" (@{entity.username})"
            elif isinstance(entity, Chat):
                chat_type = "Group"
                title = entity.title
            elif isinstance(entity, Channel):
                chat_type = "Channel" if not entity.megagroup else "Supergroup"
                title = entity.title
                if entity.username:
                    title += f" (@{entity.username})"
            else:
                chat_type = "Unknown"
                title = str(dialog.name)
            
            # Get proper chat ID
            chat_id = dialog.id
            
            yield (chat_id, title, chat_type)
            
            count += 1
            if limit and count >= limit:
                break
    
    async def get_chat_info(self, chat_id) -> dict:
        """Get information about a chat.
        
        Args:
            chat_id: Chat ID or username
            
        Returns:
            Dictionary with chat information
        """
        entity = await self.client.get_entity(chat_id)
        
        info = {
            'id': entity.id,
            'type': type(entity).__name__,
        }
        
        if isinstance(entity, User):
            info['title'] = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
            info['username'] = entity.username
            info['is_bot'] = entity.bot
        elif isinstance(entity, (Chat, Channel)):
            info['title'] = entity.title
            if isinstance(entity, Channel):
                info['username'] = entity.username
                info['megagroup'] = entity.megagroup
                info['noforwards'] = getattr(entity, 'noforwards', False)
        
        return info


async def get_client(
    config_manager: ConfigManager,
    logger: Optional[ForwarderLogger] = None,
    auto_connect: bool = True
) -> ClientWrapper:
    """Get a connected client wrapper.
    
    Args:
        config_manager: Configuration manager
        logger: Optional logger
        auto_connect: Whether to automatically connect
        
    Returns:
        ClientWrapper instance
    """
    wrapper = ClientWrapper(config_manager, logger)
    
    if auto_connect:
        await wrapper.connect()
    
    return wrapper
