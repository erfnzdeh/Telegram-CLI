"""Custom exceptions and graceful shutdown handling."""

import asyncio
import signal
import sys
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .logger import ForwarderLogger
    from .state import StateManager


class ForwarderError(Exception):
    """Base exception for forwarder errors."""
    pass


class AccountLimitedError(ForwarderError):
    """Raised when PeerFloodError occurs - account may be spam-limited.
    
    This typically means the account has been flagged for spam-like behavior.
    Users should check @SpamBot on Telegram.
    """
    pass


class SourceRestrictedError(ForwarderError):
    """Raised when source chat has noforwards or other restrictions.
    
    This means the source chat has disabled forwarding and messages
    cannot be forwarded from it.
    """
    pass


class DestinationError(ForwarderError):
    """Raised when there's an issue with a destination chat.
    
    This could be permission issues, the chat being private, etc.
    """
    pass


class MaxRetriesExceeded(ForwarderError):
    """Raised when all retry attempts are exhausted."""
    pass


class SessionError(ForwarderError):
    """Raised when there's an issue with the Telegram session."""
    pass


class ConfigurationError(ForwarderError):
    """Raised when configuration is missing or invalid."""
    pass


async def handle_long_flood_wait(wait_seconds: int, logger: "ForwarderLogger") -> bool:
    """Handle flood waits longer than the automatic threshold.
    
    The Telethon client handles flood waits under flood_sleep_threshold
    automatically. This function handles longer waits manually.
    
    Args:
        wait_seconds: Number of seconds to wait
        logger: Logger instance for output
        
    Returns:
        True if we should retry, False to abort
        
    Raises:
        AccountLimitedError: If wait is too long (>1 hour)
    """
    if wait_seconds > 3600:  # More than 1 hour
        logger.error(f"Flood wait too long ({wait_seconds}s). Aborting.")
        raise AccountLimitedError(f"Flood wait {wait_seconds}s - check @SpamBot")
    
    logger.warning(f"Long flood wait: {wait_seconds}s. Sleeping...")
    
    # Show countdown for long waits (every 30 seconds)
    remaining = wait_seconds
    while remaining > 0:
        logger.info(f"  Resuming in {remaining}s...")
        sleep_time = min(30, remaining)
        await asyncio.sleep(sleep_time)
        remaining -= sleep_time
    
    return True


class GracefulShutdown:
    """Handles graceful shutdown on SIGINT/SIGTERM.
    
    When Ctrl+C is pressed:
    1. First press: Sets shutdown_requested flag, allows current batch to complete
    2. Second press: Forces immediate exit
    
    Usage:
        shutdown = GracefulShutdown(state_manager, logger)
        shutdown.setup()
        
        # In your loop:
        while not shutdown.shutdown_requested:
            # Process batch
            shutdown.check_shutdown()
    """
    
    def __init__(
        self,
        state_manager: Optional["StateManager"] = None,
        logger: Optional["ForwarderLogger"] = None
    ):
        """Initialize graceful shutdown handler.
        
        Args:
            state_manager: State manager for saving progress
            logger: Logger for output
        """
        self.state = state_manager
        self.logger = logger
        self.shutdown_requested = False
        self.current_message_id: Optional[int] = None
        self._original_sigint = None
        self._original_sigterm = None
    
    def setup(self):
        """Set up signal handlers for graceful shutdown."""
        self._original_sigint = signal.signal(signal.SIGINT, self._handler)
        self._original_sigterm = signal.signal(signal.SIGTERM, self._handler)
    
    def cleanup(self):
        """Restore original signal handlers."""
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm)
    
    def _handler(self, signum, frame):
        """Handle shutdown signal."""
        if self.shutdown_requested:
            # Second signal - force quit
            if self.logger:
                self.logger.warning("Force quit!")
            sys.exit(1)
        
        self.shutdown_requested = True
        if self.logger:
            self.logger.info("\nShutdown requested. Finishing current batch...")
    
    def update_progress(self, message_id: int):
        """Update current progress for checkpoint saving.
        
        Args:
            message_id: Last processed message ID
        """
        self.current_message_id = message_id
    
    def check_shutdown(self) -> bool:
        """Check if shutdown was requested and save progress.
        
        Call this between batches to check for shutdown requests.
        
        Returns:
            True if shutdown was requested, False otherwise
        """
        if not self.shutdown_requested:
            return False
        
        # Save checkpoint if we have state manager
        if self.state and self.current_message_id:
            self.state.save_checkpoint(self.current_message_id)
            job_id = self.state.current_job_id
            if self.logger:
                self.logger.info(f"Progress saved. Resume with: telegram-cli resume {job_id}")
        
        return True


def create_shutdown_handler(
    state_manager: Optional["StateManager"] = None,
    logger: Optional["ForwarderLogger"] = None
) -> GracefulShutdown:
    """Create and set up a graceful shutdown handler.
    
    Args:
        state_manager: State manager for saving progress
        logger: Logger for output
        
    Returns:
        Configured GracefulShutdown instance
    """
    handler = GracefulShutdown(state_manager, logger)
    handler.setup()
    return handler
