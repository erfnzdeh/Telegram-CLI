"""Forwarding engine with batch operations and error handling."""

import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from telethon import TelegramClient, events
from telethon.tl.types import Message
from telethon import errors

from .logger import ForwarderLogger
from .state import StateManager, JobType
from .errors import (
    AccountLimitedError,
    SourceRestrictedError,
    DestinationError,
    handle_long_flood_wait,
    GracefulShutdown,
)
from .utils import (
    is_forwardable,
    check_forward_restrictions,
    check_delete_permission,
    estimate_message_count,
    format_estimate,
)


@dataclass
class ForwardResult:
    """Result of a forwarding operation."""
    success: List[Tuple[int, int]] = field(default_factory=list)  # [(msg_id, dest_id), ...]
    failed: List[Tuple[int, int, str]] = field(default_factory=list)  # [(msg_id, dest_id, error), ...]
    skipped: List[Tuple[int, str]] = field(default_factory=list)  # [(msg_id, reason), ...]
    
    @property
    def success_count(self) -> int:
        return len(self.success)
    
    @property
    def failed_count(self) -> int:
        return len(self.failed)
    
    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


class Forwarder:
    """Handles message forwarding with batch operations and error handling."""
    
    # Maximum messages per API call (Telegram limit)
    MAX_BATCH_SIZE = 100
    
    def __init__(
        self,
        client: TelegramClient,
        logger: ForwarderLogger,
        state: StateManager,
        shutdown: Optional[GracefulShutdown] = None,
        delay_between_batches: float = 1.0,
        delay_between_destinations: float = 0.5,
    ):
        """Initialize forwarder.
        
        Args:
            client: Telethon client
            logger: Logger instance
            state: State manager for progress tracking
            shutdown: Optional shutdown handler
            delay_between_batches: Delay between batch operations (seconds)
            delay_between_destinations: Delay between destinations (seconds)
        """
        self.client = client
        self.logger = logger
        self.state = state
        self.shutdown = shutdown
        self.delay_between_batches = delay_between_batches
        self.delay_between_destinations = delay_between_destinations
        self._live_handler = None
    
    async def _forward_single_message(
        self,
        message: Message,
        dest_id: int,
        drop_author: bool = False,
        retry_count: int = 3
    ) -> Optional[Message]:
        """Forward a single message with retries.
        
        Args:
            message: Message to forward
            dest_id: Destination chat ID
            drop_author: Remove "Forwarded from" header
            retry_count: Number of retries on transient errors
            
        Returns:
            Forwarded message or None if failed
        """
        for attempt in range(retry_count):
            try:
                result = await self.client.forward_messages(
                    dest_id,
                    message,
                    drop_author=drop_author,
                    drop_media_captions=False
                )
                return result[0] if isinstance(result, list) else result
                
            except errors.FloodWaitError as e:
                await handle_long_flood_wait(e.seconds, self.logger)
                # Continue to retry
                
            except Exception as e:
                if attempt < retry_count - 1:
                    wait_time = (attempt + 1) * 2  # 2s, 4s, 6s
                    self.logger.verbose(f"Retry {attempt + 1}/{retry_count} for msg {message.id} in {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    raise
        
        return None
    
    async def _forward_messages_batch(
        self,
        messages: List[Message],
        dest_id: int,
        drop_author: bool = False
    ) -> List[Message]:
        """Forward multiple messages to ONE destination in a SINGLE API call.
        
        If batch forwarding fails with server errors, falls back to one-by-one.
        
        Args:
            messages: List of messages to forward
            dest_id: Destination chat ID
            drop_author: Remove "Forwarded from" header
            
        Returns:
            List of forwarded messages
            
        Raises:
            AccountLimitedError: If account is spam-limited
        """
        if not messages:
            return []
        
        try:
            result = await self.client.forward_messages(
                dest_id,
                messages,  # Pass entire list - single API call!
                drop_author=drop_author,
                drop_media_captions=False
            )
            return result if isinstance(result, list) else [result]
            
        except errors.FloodWaitError as e:
            # flood_sleep_threshold handles waits < threshold automatically
            # This only triggers for longer waits
            await handle_long_flood_wait(e.seconds, self.logger)
            return await self._forward_messages_batch(messages, dest_id, drop_author)
            
        except errors.PeerFloodError:
            raise AccountLimitedError("Account limited. Check @SpamBot on Telegram.")
        
        except Exception as e:
            # Check if this is a server-side error that warrants fallback
            error_name = type(e).__name__
            if 'Worker' in error_name or 'Busy' in error_name or 'Retry' in error_name or 'timeout' in str(e).lower():
                self.logger.warning(f"Batch forward failed ({error_name}), falling back to one-by-one...")
                return await self._forward_one_by_one(messages, dest_id, drop_author)
            else:
                # Re-raise other errors
                raise
    
    async def _forward_one_by_one(
        self,
        messages: List[Message],
        dest_id: int,
        drop_author: bool = False
    ) -> List[Message]:
        """Forward messages one by one (fallback for when batch fails).
        
        Slower but more reliable when Telegram servers are busy.
        
        Args:
            messages: List of messages to forward
            dest_id: Destination chat ID
            drop_author: Remove "Forwarded from" header
            
        Returns:
            List of successfully forwarded messages
        """
        results = []
        
        for i, message in enumerate(messages):
            try:
                result = await self._forward_single_message(message, dest_id, drop_author)
                if result:
                    results.append(result)
                
                # Progress indicator for one-by-one mode
                if (i + 1) % 10 == 0:
                    self.logger.verbose(f"  One-by-one progress: {i + 1}/{len(messages)}")
                
                # Small delay between messages to avoid overwhelming Telegram
                await asyncio.sleep(0.3)
                
            except errors.FloodWaitError as e:
                await handle_long_flood_wait(e.seconds, self.logger)
                # Retry this message
                try:
                    result = await self._forward_single_message(message, dest_id, drop_author)
                    if result:
                        results.append(result)
                except Exception:
                    self.logger.warning(f"Failed to forward msg {message.id} after flood wait")
                    
            except errors.PeerFloodError:
                raise AccountLimitedError("Account limited. Check @SpamBot on Telegram.")
                
            except Exception as e:
                self.logger.warning(f"Failed to forward msg {message.id}: {e}")
                # Continue with next message
        
        self.logger.verbose(f"  One-by-one complete: {len(results)}/{len(messages)} succeeded")
        return results
    
    async def forward_to_destinations(
        self,
        messages: List[Message],
        dest_ids: List[int],
        drop_author: bool = False,
        delete_after: bool = False,
        source_id: Optional[int] = None
    ) -> ForwardResult:
        """Forward message batch to multiple destinations with error handling.
        
        Args:
            messages: List of messages to forward
            dest_ids: List of destination chat IDs
            drop_author: Remove "Forwarded from" header
            delete_after: Delete from source after forwarding
            source_id: Source chat ID (for deletion)
            
        Returns:
            ForwardResult with success/failed/skipped info
        """
        result = ForwardResult()
        
        if not messages:
            return result
        
        msg_ids = {m.id for m in messages}
        
        # Forward to each destination (batched per destination)
        for dest_id in dest_ids:
            try:
                forwarded = await self._forward_messages_batch(messages, dest_id, drop_author)
                
                # Track which messages succeeded
                forwarded_ids = set()
                for fwd in forwarded:
                    if fwd and hasattr(fwd, 'fwd_from') and fwd.fwd_from:
                        # The original message ID is in fwd_from for forwarded messages
                        # But when using drop_author, we need to match by position
                        pass
                    forwarded_ids.add(fwd.id if fwd else None)
                
                # If we got back the same number of messages, all succeeded
                if len(forwarded) == len(messages):
                    for msg in messages:
                        result.success.append((msg.id, dest_id))
                    self.logger.verbose(f"Forwarded {len(messages)} msgs to {dest_id}")
                else:
                    # Partial success (from one-by-one fallback)
                    # We can't easily track which exact messages failed, so count them
                    for i, msg in enumerate(messages):
                        if i < len(forwarded) and forwarded[i]:
                            result.success.append((msg.id, dest_id))
                        else:
                            result.failed.append((msg.id, dest_id, "Failed in fallback mode"))
                    self.logger.verbose(f"Forwarded {len(forwarded)}/{len(messages)} msgs to {dest_id}")
                
                # Small delay between destinations to avoid rate limits
                if len(dest_ids) > 1:
                    await asyncio.sleep(self.delay_between_destinations)
                    
            except errors.ChatWriteForbiddenError:
                for msg in messages:
                    result.failed.append((msg.id, dest_id, "No write permission"))
                self.logger.error(f"Cannot write to {dest_id}")
                
            except errors.ChannelPrivateError:
                for msg in messages:
                    result.failed.append((msg.id, dest_id, "Private channel"))
                self.logger.error(f"Private channel {dest_id}")
                
            except errors.UserBannedInChannelError:
                for msg in messages:
                    result.failed.append((msg.id, dest_id, "Banned from channel"))
                self.logger.error(f"Banned from {dest_id}")
                
            except errors.ChatAdminRequiredError:
                for msg in messages:
                    result.failed.append((msg.id, dest_id, "Admin rights required"))
                self.logger.error(f"Admin rights required for {dest_id}")
                
            except AccountLimitedError:
                raise  # Propagate - stop all operations
                
            except errors.MessageIdInvalidError:
                for msg in messages:
                    result.failed.append((msg.id, dest_id, "Message deleted"))
                self.logger.warning(f"Some messages were deleted from source")
                
            except errors.FileReferenceExpiredError:
                # Try to re-fetch and retry
                self.logger.verbose("File reference expired, retrying with fresh messages")
                try:
                    msg_ids = [m.id for m in messages]
                    fresh_messages = await self.client.get_messages(source_id or messages[0].chat_id, ids=msg_ids)
                    fresh_messages = [m for m in fresh_messages if m is not None]
                    if fresh_messages:
                        await self._forward_messages_batch(fresh_messages, dest_id, drop_author)
                        for msg in fresh_messages:
                            result.success.append((msg.id, dest_id))
                except Exception as e:
                    for msg in messages:
                        result.failed.append((msg.id, dest_id, f"Media unavailable: {e}"))
                    
            except Exception as e:
                for msg in messages:
                    result.failed.append((msg.id, dest_id, str(e)))
                self.logger.error(f"Failed forwarding to {dest_id}: {e}")
        
        # Delete successfully forwarded messages from source
        if delete_after:
            # Find messages that succeeded for ALL destinations
            msg_success_count = {}
            for msg_id, dest_id in result.success:
                msg_success_count[msg_id] = msg_success_count.get(msg_id, 0) + 1
            
            # Only delete messages that succeeded for all destinations
            msgs_to_delete = [
                msg for msg in messages 
                if msg_success_count.get(msg.id, 0) == len(dest_ids)
            ]
            
            if msgs_to_delete:
                await self._safe_delete_batch(msgs_to_delete, source_id)
                self.logger.verbose(f"Deleted {len(msgs_to_delete)}/{len(messages)} messages from source")
        
        return result
    
    async def _safe_delete_batch(self, messages: List[Message], chat_id: Optional[int] = None):
        """Safely delete messages from source.
        
        Args:
            messages: Messages to delete
            chat_id: Chat ID to delete from
        """
        if not messages:
            return
        
        try:
            msg_ids = [m.id for m in messages]
            target = chat_id or messages[0].chat_id
            
            self.logger.debug(f"Attempting to delete {len(msg_ids)} messages from {target}")
            
            # For private chats, we can only delete our own messages for both parties
            # For channels/groups where we're admin, we can delete any message
            result = await self.client.delete_messages(target, msg_ids, revoke=True)
            
            # result is an AffectedMessages object with pts_count
            deleted_count = getattr(result, 'pts_count', len(msg_ids))
            self.logger.verbose(f"Deleted {deleted_count} messages from source")
            
        except errors.ChatAdminRequiredError:
            self.logger.warning("Cannot delete: admin rights required")
        except errors.MessageDeleteForbiddenError:
            self.logger.warning("Cannot delete: message deletion forbidden (not your message or too old)")
        except Exception as e:
            self.logger.warning(f"Failed to delete messages: {type(e).__name__}: {e}")
    
    async def forward_all(
        self,
        source_id: int,
        dest_ids: List[int],
        drop_author: bool = False,
        delete_after: bool = False,
        batch_size: int = 100,
        min_id: int = 0,
        dry_run: bool = False
    ) -> Tuple[int, int, int]:
        """Forward all messages using efficient batch API calls.
        
        Args:
            source_id: Source chat ID
            dest_ids: List of destination chat IDs
            drop_author: Remove "Forwarded from" header
            delete_after: Delete from source after forwarding
            batch_size: Messages per batch (max 100)
            min_id: Minimum message ID (for resume)
            dry_run: If True, don't actually forward
            
        Returns:
            Tuple of (processed, skipped, failed)
        """
        # Clamp batch size to max
        batch_size = min(batch_size, self.MAX_BATCH_SIZE)
        
        batch = []
        processed = 0
        skipped = 0
        failed = 0
        
        total_estimate = await estimate_message_count(self.client, source_id, min_id)
        
        self.logger.info(f"Starting forward-all from {source_id}")
        self.logger.info(f"Estimated messages: {format_estimate(total_estimate)}")
        
        async for message in self.client.iter_messages(
            source_id,
            min_id=min_id,
            reverse=True  # Oldest first
        ):
            # Check for shutdown
            if self.shutdown and self.shutdown.shutdown_requested:
                self.logger.info("Shutdown requested, saving progress...")
                break
            
            # Filter non-forwardable messages
            forwardable, reason = is_forwardable(message)
            if not forwardable:
                skipped += 1
                self.logger.verbose(f"Skip msg {message.id}: {reason}")
                continue
            
            batch.append(message)
            
            # When batch is full, forward it
            if len(batch) >= batch_size:
                if not dry_run:
                    result = await self.forward_to_destinations(
                        batch, dest_ids, drop_author, delete_after, source_id
                    )
                    failed += result.failed_count // len(dest_ids)  # Per message
                
                processed += len(batch)
                
                # Checkpoint after each batch
                self.state.update_progress(batch[-1].id, processed, skipped, failed)
                if self.shutdown:
                    self.shutdown.update_progress(batch[-1].id)
                
                self.logger.progress(processed, total_estimate)
                
                batch = []  # Reset for next batch
                
                # Rate limit protection between batches
                await asyncio.sleep(self.delay_between_batches)
        
        # Forward remaining messages in last partial batch
        if batch:
            if not dry_run:
                result = await self.forward_to_destinations(
                    batch, dest_ids, drop_author, delete_after, source_id
                )
                failed += result.failed_count // len(dest_ids)
            
            processed += len(batch)
            self.state.update_progress(batch[-1].id, processed, skipped, failed)
        
        self.logger.progress_done()
        self.logger.info(f"Complete: {processed} forwarded, {skipped} skipped, {failed} failed")
        
        return processed, skipped, failed
    
    async def forward_last(
        self,
        source_id: int,
        dest_ids: List[int],
        count: int,
        drop_author: bool = False,
        delete_after: bool = False,
        dry_run: bool = False
    ) -> Tuple[int, int, int]:
        """Forward the last N messages efficiently.
        
        Args:
            source_id: Source chat ID
            dest_ids: List of destination chat IDs
            count: Number of messages to forward
            drop_author: Remove "Forwarded from" header
            delete_after: Delete from source after forwarding
            dry_run: If True, don't actually forward
            
        Returns:
            Tuple of (processed, skipped, failed)
        """
        self.logger.info(f"Fetching last {count} messages from {source_id}...")
        
        # Collect messages (newest first, then reverse)
        messages = []
        skipped = 0
        
        async for message in self.client.iter_messages(source_id, limit=count):
            forwardable, reason = is_forwardable(message)
            if forwardable:
                messages.append(message)
            else:
                skipped += 1
                self.logger.verbose(f"Skip msg {message.id}: {reason}")
        
        # Reverse to forward oldest first (maintains order)
        messages.reverse()
        
        if not messages:
            self.logger.info("No forwardable messages found")
            return 0, skipped, 0
        
        self.logger.info(f"Found {len(messages)} forwardable messages (skipped {skipped})")
        
        if dry_run:
            self.logger.info("[DRY RUN] Would forward these messages")
            return len(messages), skipped, 0
        
        # Forward in batches of 100 (API limit)
        processed = 0
        failed = 0
        
        for i in range(0, len(messages), self.MAX_BATCH_SIZE):
            batch = messages[i:i + self.MAX_BATCH_SIZE]
            
            result = await self.forward_to_destinations(
                batch, dest_ids, drop_author, delete_after, source_id
            )
            
            processed += len(batch)
            failed += result.failed_count // len(dest_ids)
            
            self.logger.progress(processed, len(messages))
            
            if i + self.MAX_BATCH_SIZE < len(messages):
                await asyncio.sleep(self.delay_between_batches)
        
        self.logger.progress_done()
        self.logger.info(f"Forwarded {processed} messages")
        
        return processed, skipped, failed
    
    async def start_live_forward(
        self,
        source_id: int,
        dest_ids: List[int],
        drop_author: bool = False,
        delete_after: bool = False
    ):
        """Start real-time forwarding of new messages.
        
        Args:
            source_id: Source chat ID
            dest_ids: List of destination chat IDs
            drop_author: Remove "Forwarded from" header
            delete_after: Delete from source after forwarding
        """
        self.logger.info(f"Starting live forwarding from {source_id}")
        self.logger.info(f"Destinations: {', '.join(map(str, dest_ids))}")
        self.logger.info("Press Ctrl+C to stop...")
        
        @self.client.on(events.NewMessage(chats=[source_id]))
        async def handler(event):
            message = event.message
            
            forwardable, reason = is_forwardable(message)
            if not forwardable:
                self.logger.verbose(f"Skip live msg {message.id}: {reason}")
                return
            
            try:
                # Single message, but still use batch method for consistency
                result = await self.forward_to_destinations(
                    [message], dest_ids, drop_author, delete_after, source_id
                )
                
                if result.success:
                    self.logger.verbose(f"Forwarded new message {message.id}")
                    
            except AccountLimitedError as e:
                self.logger.error(f"Account limited! Stopping live forward: {e}")
                raise  # Will disconnect the handler
            except Exception as e:
                self.logger.error(f"Live forward failed: {e}")
        
        self._live_handler = handler
        
        # Run until disconnected
        await self.client.run_until_disconnected()
    
    def stop_live_forward(self):
        """Stop live forwarding."""
        if self._live_handler:
            self.client.remove_event_handler(self._live_handler)
            self._live_handler = None
    
    async def delete_last(
        self,
        chat_id: int,
        count: int,
        dry_run: bool = False
    ) -> Tuple[int, int]:
        """Delete last N messages from a chat.
        
        Args:
            chat_id: Chat ID to delete from
            count: Number of messages to delete
            dry_run: If True, don't actually delete
            
        Returns:
            Tuple of (deleted, failed)
        """
        deleted = 0
        failed = 0
        
        self.logger.info(f"{'[DRY RUN] ' if dry_run else ''}Deleting {count} messages from {chat_id}")
        
        # Collect messages
        messages = []
        async for msg in self.client.iter_messages(chat_id, limit=count):
            messages.append(msg)
        
        if not messages:
            self.logger.warning("No messages found")
            return 0, 0
        
        self.logger.info(f"Found {len(messages)} messages to delete")
        
        if dry_run:
            for msg in messages:
                self.logger.verbose(f"Would delete: {msg.id}")
            return len(messages), 0
        
        # Delete in batches
        batch_size = self.MAX_BATCH_SIZE
        for i in range(0, len(messages), batch_size):
            if self.shutdown and self.shutdown.shutdown_requested:
                self.logger.info("Shutdown requested, stopping...")
                break
            
            batch = messages[i:i + batch_size]
            msg_ids = [m.id for m in batch]
            
            try:
                result = await self.client.delete_messages(chat_id, msg_ids, revoke=True)
                batch_deleted = getattr(result, 'pts_count', len(msg_ids))
                deleted += batch_deleted
                self.logger.verbose(f"Deleted batch: {batch_deleted} messages")
            except errors.ChatAdminRequiredError:
                self.logger.error("Admin rights required to delete messages")
                failed += len(batch)
            except errors.MessageDeleteForbiddenError:
                self.logger.warning(f"Cannot delete some messages (not yours or too old)")
                failed += len(batch)
            except Exception as e:
                self.logger.error(f"Delete failed: {type(e).__name__}: {e}")
                failed += len(batch)
            
            # Small delay between batches
            if i + batch_size < len(messages):
                await asyncio.sleep(0.5)
        
        return deleted, failed
    
    async def delete_all(
        self,
        chat_id: int,
        batch_size: int = 100,
        dry_run: bool = False
    ) -> Tuple[int, int]:
        """Delete all messages from a chat.
        
        Args:
            chat_id: Chat ID to delete from
            batch_size: Messages per batch (max 100)
            dry_run: If True, don't actually delete
            
        Returns:
            Tuple of (deleted, failed)
        """
        batch_size = min(batch_size, self.MAX_BATCH_SIZE)
        deleted = 0
        failed = 0
        
        self.logger.info(f"{'[DRY RUN] ' if dry_run else ''}Deleting all messages from {chat_id}")
        
        # Get total count for progress
        total = await estimate_message_count(self.client, chat_id)
        self.logger.info(f"Total messages: {format_estimate(total)}")
        
        batch = []
        processed = 0
        
        async for msg in self.client.iter_messages(chat_id):
            if self.shutdown and self.shutdown.shutdown_requested:
                self.logger.info("Shutdown requested, stopping...")
                break
            
            batch.append(msg)
            
            if len(batch) >= batch_size:
                if dry_run:
                    processed += len(batch)
                    self.logger.verbose(f"Would delete: {len(batch)} messages")
                else:
                    msg_ids = [m.id for m in batch]
                    try:
                        result = await self.client.delete_messages(chat_id, msg_ids, revoke=True)
                        batch_deleted = getattr(result, 'pts_count', len(msg_ids))
                        deleted += batch_deleted
                        processed += len(batch)
                    except errors.ChatAdminRequiredError:
                        self.logger.error("Admin rights required to delete messages")
                        failed += len(batch)
                    except errors.MessageDeleteForbiddenError:
                        self.logger.warning(f"Cannot delete some messages (not yours or too old)")
                        failed += len(batch)
                    except Exception as e:
                        self.logger.error(f"Delete failed: {type(e).__name__}: {e}")
                        failed += len(batch)
                
                # Progress update
                if total > 0:
                    pct = (processed / total) * 100
                    self.logger.info(f"Progress: {processed}/{total} ({pct:.1f}%)")
                
                batch = []
                await asyncio.sleep(self.delay_between_batches)
        
        # Process remaining
        if batch:
            if dry_run:
                processed += len(batch)
            else:
                msg_ids = [m.id for m in batch]
                try:
                    result = await self.client.delete_messages(chat_id, msg_ids, revoke=True)
                    batch_deleted = getattr(result, 'pts_count', len(msg_ids))
                    deleted += batch_deleted
                except Exception as e:
                    self.logger.error(f"Delete failed: {type(e).__name__}: {e}")
                    failed += len(batch)
        
        if dry_run:
            return processed, 0
        
        return deleted, failed
    
    async def verify_delete_operation(
        self,
        chat_id: int,
        count: Optional[int] = None,
        skip_confirm: bool = False,
        dry_run: bool = False
    ) -> bool:
        """Verify and display delete operation details before starting.
        
        Args:
            chat_id: Chat ID to delete from
            count: Number of messages (None for all)
            skip_confirm: Skip confirmation prompt
            dry_run: Whether this is a dry run
            
        Returns:
            True if operation should proceed, False otherwise
        """
        # Get chat info
        try:
            chat_info = await self.client.get_entity(chat_id)
            chat_name = getattr(chat_info, 'title', None) or getattr(chat_info, 'first_name', str(chat_id))
        except Exception:
            chat_name = str(chat_id)
        
        # Estimate count
        if count:
            total = count
        else:
            total = await estimate_message_count(self.client, chat_id)
        
        self.logger.info(f"Chat: {chat_id} ({chat_name})")
        self.logger.info(f"Messages to delete: {format_estimate(total) if not count else count}")
        if dry_run:
            self.logger.info("Mode: DRY RUN (no actual deletion)")
        
        # Check delete permission
        me = await self.client.get_me()
        can_delete, delete_reason = await check_delete_permission(self.client, chat_id, me.id)
        if can_delete:
            self.logger.info(f"Permission: {delete_reason}")
        else:
            self.logger.error(f"Cannot delete: {delete_reason}")
            return False
        
        if not skip_confirm and not dry_run:
            try:
                self.logger.warning("WARNING: This action cannot be undone!")
                confirm = input("\nProceed with deletion? [y/N]: ").strip().lower()
                if confirm != 'y':
                    self.logger.info("Aborted by user")
                    return False
            except EOFError:
                self.logger.info("Aborted (no input)")
                return False
        
        return True
    
    async def verify_operation(
        self,
        source_id: int,
        dest_ids: List[int],
        drop_author: bool = False,
        delete_after: bool = False,
        count: Optional[int] = None,
        min_id: int = 0,
        skip_confirm: bool = False
    ) -> bool:
        """Verify and display operation details before starting.
        
        Args:
            source_id: Source chat ID
            dest_ids: List of destination chat IDs
            drop_author: Whether to drop author
            delete_after: Whether to delete after forwarding
            count: Message count (for forward-last)
            min_id: Minimum message ID (for resume)
            skip_confirm: Skip confirmation prompt
            
        Returns:
            True if operation should proceed, False otherwise
        """
        # Check source restrictions first
        can_forward, reason = await check_forward_restrictions(self.client, source_id)
        if not can_forward:
            self.logger.error(f"Cannot forward: {reason}")
            return False
        
        # Estimate count
        if count:
            total = count
        else:
            total = await estimate_message_count(self.client, source_id, min_id)
        
        mode = "forward (drop author)" if drop_author else "forward"
        
        # Get source info
        try:
            source_info = await self.client.get_entity(source_id)
            source_name = getattr(source_info, 'title', None) or getattr(source_info, 'first_name', str(source_id))
        except Exception:
            source_name = str(source_id)
        
        self.logger.info(f"Source: {source_id} ({source_name})")
        self.logger.info(f"Destinations: {', '.join(map(str, dest_ids))}")
        self.logger.info(f"Estimated: {format_estimate(total)}")
        self.logger.info(f"Mode: {mode}")
        self.logger.info(f"Batch size: {self.MAX_BATCH_SIZE} messages per API call")
        
        # Check delete permission
        if delete_after:
            me = await self.client.get_me()
            can_delete, delete_reason = await check_delete_permission(self.client, source_id, me.id)
            if can_delete:
                self.logger.info(f"Delete after forward: YES ({delete_reason})")
            else:
                self.logger.error(f"Delete after forward: NO ({delete_reason})")
                return False
        
        if not skip_confirm:
            try:
                confirm = input("\nProceed? [y/N]: ").strip().lower()
                if confirm != 'y':
                    self.logger.info("Aborted by user")
                    return False
            except EOFError:
                self.logger.info("Aborted (no input)")
                return False
        
        return True


async def test_permissions(
    client: TelegramClient,
    source_id: int,
    dest_ids: List[int],
    delete_after: bool = False
) -> List[Tuple[str, bool, str]]:
    """Verify permissions for a forwarding operation.
    
    Args:
        client: Telethon client
        source_id: Source chat ID
        dest_ids: List of destination chat IDs
        delete_after: Whether delete permission should be checked
        
    Returns:
        List of (check_name, passed, reason) tuples
    """
    checks = []
    
    # Check source access
    try:
        async for _ in client.iter_messages(source_id, limit=1):
            checks.append(("Read source", True, "Can read messages"))
            break
        else:
            checks.append(("Read source", True, "No messages (empty chat)"))
    except errors.ChannelPrivateError:
        checks.append(("Read source", False, "Private channel - not a member"))
    except errors.ChannelInvalidError:
        checks.append(("Read source", False, "Invalid channel ID"))
    except Exception as e:
        checks.append(("Read source", False, str(e)))
    
    # Check forward restrictions on source
    can_forward, reason = await check_forward_restrictions(client, source_id)
    checks.append(("Forward from source", can_forward, reason or "Forwarding allowed"))
    
    # Check each destination
    for dest_id in dest_ids:
        try:
            # Try to send a test message
            msg = await client.send_message(dest_id, "Test message (will be deleted)")
            await client.delete_messages(dest_id, msg.id)
            checks.append((f"Write to {dest_id}", True, "Can send and delete"))
        except errors.ChatWriteForbiddenError:
            checks.append((f"Write to {dest_id}", False, "No write permission"))
        except errors.ChannelPrivateError:
            checks.append((f"Write to {dest_id}", False, "Private channel"))
        except errors.UserBannedInChannelError:
            checks.append((f"Write to {dest_id}", False, "Banned from channel"))
        except Exception as e:
            checks.append((f"Write to {dest_id}", False, str(e)))
    
    # Check delete permission for source
    if delete_after:
        me = await client.get_me()
        can_delete, delete_reason = await check_delete_permission(client, source_id, me.id)
        checks.append(("Delete from source", can_delete, delete_reason))
    
    return checks
