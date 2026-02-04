"""Command-line interface for Telegram Forwarder."""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from .config import ConfigManager, get_config_manager
from .logger import ForwarderLogger, get_logger
from .state import StateManager, JobType, JobStatus, get_state_manager
from .client import ClientWrapper, get_client
from .forwarder import Forwarder, test_permissions
from .daemon import DaemonManager, get_daemon_manager
from .errors import (
    ForwarderError,
    AccountLimitedError,
    ConfigurationError,
    SessionError,
    create_shutdown_handler,
)
from .utils import validate_chat_id
from .transforms import list_transforms, create_chain_from_spec
from .filters import MessageFilter, create_filter_from_args


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog='telegram-forwarder',
        description='Forward messages between Telegram chats',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # First-time setup
  telegram-forwarder login

  # List chats to get IDs
  telegram-forwarder list-chats

  # Forward last 50 messages
  telegram-forwarder forward-last -s -100123456 -d -100789012 --count 50

  # Forward without "Forwarded from" header
  telegram-forwarder forward-last -s -100123456 -d -100789012 --count 50 --drop-author

  # Forward all messages in batches
  telegram-forwarder forward-all -s -100123456 -d -100789012 --drop-author

  # Real-time forwarding
  telegram-forwarder forward-live -s -100123456 -d -100789012
"""
    )
    
    # Global flags
    parser.add_argument(
        '-v', '--verbose',
        action='count',
        default=0,
        help='Increase verbosity (can stack: -v, -vv, -vvv)'
    )
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress all output except errors'
    )
    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help='Skip confirmation prompts'
    )
    parser.add_argument(
        '-a', '--account',
        help='Account alias to use (default: active account)'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Login command
    login_parser = subparsers.add_parser('login', help='Authenticate with Telegram')
    login_parser.add_argument(
        '--api-id',
        type=int,
        help='Telegram API ID (from my.telegram.org)'
    )
    login_parser.add_argument(
        '--api-hash',
        help='Telegram API hash (from my.telegram.org)'
    )
    
    # Logout command
    subparsers.add_parser('logout', help='Clear session and log out')
    
    # List chats command
    list_parser = subparsers.add_parser('list-chats', help='List available chats with IDs')
    list_parser.add_argument(
        '--limit',
        type=int,
        default=50,
        help='Maximum number of chats to list (default: 50)'
    )
    list_parser.add_argument(
        '--archived',
        action='store_true',
        help='Include archived chats'
    )
    list_parser.add_argument(
        '-s', '--search',
        help='Search chats by name (case-insensitive)'
    )
    list_parser.add_argument(
        '--type',
        choices=['private', 'group', 'supergroup', 'channel', 'saved'],
        help='Filter by chat type'
    )
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Verify permissions for source/destination')
    test_parser.add_argument(
        '-s', '--source',
        required=True,
        help='Source chat ID or username'
    )
    test_parser.add_argument(
        '-d', '--dest',
        action='append',
        required=True,
        help='Destination chat ID (can be repeated for multiple destinations)'
    )
    test_parser.add_argument(
        '--delete',
        action='store_true',
        help='Check delete permission for source'
    )
    
    # Forward-last command
    forward_last_parser = subparsers.add_parser(
        'forward-last',
        help='Forward last X messages'
    )
    _add_forward_args(forward_last_parser)
    _add_filter_args(forward_last_parser)
    forward_last_parser.add_argument(
        '--count',
        type=int,
        required=True,
        help='Number of messages to forward'
    )
    
    # Forward-live command
    forward_live_parser = subparsers.add_parser(
        'forward-live',
        help='Start real-time forwarding of new messages'
    )
    _add_forward_args(forward_live_parser)
    _add_filter_args(forward_live_parser)
    forward_live_parser.add_argument(
        '--transform',
        help='Transform chain to apply (e.g., "replace_mentions", "replace_mentions,strip_formatting")'
    )
    forward_live_parser.add_argument(
        '--transform-config',
        help='Config for transform (e.g., "replacement=[removed]")'
    )
    forward_live_parser.add_argument(
        '--list-transforms',
        action='store_true',
        help='List available transforms and exit'
    )
    
    # Forward-all command
    forward_all_parser = subparsers.add_parser(
        'forward-all',
        help='Forward all messages in batches'
    )
    _add_forward_args(forward_all_parser)
    _add_filter_args(forward_all_parser)
    forward_all_parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Messages per batch (default: 100, max: 100)'
    )
    
    # Delete-last command
    delete_last_parser = subparsers.add_parser(
        'delete-last',
        help='Delete last X messages from a chat'
    )
    _add_delete_args(delete_last_parser)
    delete_last_parser.add_argument(
        '--count',
        type=int,
        required=True,
        help='Number of messages to delete'
    )
    
    # Delete-all command
    delete_all_parser = subparsers.add_parser(
        'delete-all',
        help='Delete all messages from a chat'
    )
    _add_delete_args(delete_all_parser)
    delete_all_parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Messages per batch (default: 100, max: 100)'
    )
    
    # Resume command
    resume_parser = subparsers.add_parser('resume', help='Resume an interrupted batch operation')
    resume_parser.add_argument(
        'job_id',
        nargs='?',
        help='Job ID to resume (shows list if not provided)'
    )
    
    # Status command
    subparsers.add_parser('status', help='Show progress of ongoing/interrupted jobs')
    
    # TUI command
    subparsers.add_parser('tui', help='Launch interactive terminal UI (requires rich library)')
    
    # Account management commands
    account_parser = subparsers.add_parser('account', help='Manage multiple Telegram accounts')
    account_subparsers = account_parser.add_subparsers(dest='account_command', help='Account commands')
    
    # account list
    account_subparsers.add_parser('list', help='List all registered accounts')
    
    # account add
    account_add_parser = account_subparsers.add_parser('add', help='Add a new account')
    account_add_parser.add_argument(
        'alias',
        help='Unique alias for the account (e.g., personal, work)'
    )
    account_add_parser.add_argument(
        '--api-id',
        type=int,
        help='Telegram API ID (will prompt if not provided)'
    )
    account_add_parser.add_argument(
        '--api-hash',
        help='Telegram API hash (will prompt if not provided)'
    )
    
    # account switch
    account_switch_parser = account_subparsers.add_parser('switch', help='Switch active account')
    account_switch_parser.add_argument(
        'alias',
        help='Account alias to switch to'
    )
    
    # account remove
    account_remove_parser = account_subparsers.add_parser('remove', help='Remove an account')
    account_remove_parser.add_argument(
        'alias',
        help='Account alias to remove'
    )
    account_remove_parser.add_argument(
        '--keep-data',
        action='store_true',
        help='Keep account data files (session, config)'
    )
    
    # account rename
    account_rename_parser = account_subparsers.add_parser('rename', help='Rename an account alias')
    account_rename_parser.add_argument(
        'old_alias',
        help='Current account alias'
    )
    account_rename_parser.add_argument(
        'new_alias',
        help='New account alias'
    )
    
    # account info
    account_info_parser = account_subparsers.add_parser('info', help='Show account details')
    account_info_parser.add_argument(
        'alias',
        nargs='?',
        help='Account alias (shows active if not specified)'
    )
    
    # Daemon list command
    subparsers.add_parser('list', help='List running background daemons')
    
    # Kill command (for daemon mode)
    kill_parser = subparsers.add_parser('kill', help='Kill a background daemon by PID')
    kill_parser.add_argument(
        'pid',
        nargs='?',
        type=int,
        help='Process ID to kill (kills all if not specified)'
    )
    kill_parser.add_argument(
        '-f', '--force',
        action='store_true',
        help='Force kill (SIGKILL instead of SIGTERM)'
    )
    kill_parser.add_argument(
        '--all',
        action='store_true',
        help='Kill all running daemons'
    )
    
    # Logs command
    logs_parser = subparsers.add_parser('logs', help='View daemon logs')
    logs_parser.add_argument(
        'pid',
        nargs='?',
        type=int,
        help='Process ID to view logs for (shows latest if not specified)'
    )
    logs_parser.add_argument(
        '-n', '--lines',
        type=int,
        default=50,
        help='Number of lines to show (default: 50)'
    )
    logs_parser.add_argument(
        '-f', '--follow',
        action='store_true',
        help='Follow log output (like tail -f)'
    )
    
    return parser


def _add_forward_args(parser: argparse.ArgumentParser):
    """Add common forward arguments to a parser."""
    parser.add_argument(
        '-s', '--source',
        required=True,
        help='Source chat ID or username'
    )
    parser.add_argument(
        '-d', '--dest',
        action='append',
        required=True,
        help='Destination chat ID (can be repeated for multiple destinations)'
    )
    parser.add_argument(
        '--drop-author',
        action='store_true',
        help='Remove "Forwarded from" header'
    )
    parser.add_argument(
        '--delete',
        action='store_true',
        help='Delete from source after forwarding'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview without executing'
    )
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run in background (daemon mode)'
    )


def _add_filter_args(parser: argparse.ArgumentParser):
    """Add message filter arguments to a parser."""
    filter_group = parser.add_argument_group('filters')
    
    # Type filters
    filter_group.add_argument(
        '--type',
        help='Only forward these types (comma-separated: photo,video,text,document,audio,voice,sticker)'
    )
    filter_group.add_argument(
        '--exclude-type',
        help='Exclude these types (comma-separated)'
    )
    
    # Date filters
    filter_group.add_argument(
        '--after',
        help='Only messages after this date (YYYY-MM-DD, or relative: 7d, 1w, 1m)'
    )
    filter_group.add_argument(
        '--before',
        help='Only messages before this date'
    )
    
    # Content filters
    filter_group.add_argument(
        '--contains',
        action='append',
        help='Must contain this text (can repeat, all must match)'
    )
    filter_group.add_argument(
        '--contains-any',
        action='append',
        dest='contains_any',
        help='Must contain any of these (can repeat)'
    )
    filter_group.add_argument(
        '--excludes',
        action='append',
        help='Must NOT contain this text (can repeat)'
    )
    filter_group.add_argument(
        '--regex',
        help='Must match this regex pattern'
    )
    
    # Media filters
    filter_group.add_argument(
        '--media-only',
        action='store_true',
        help='Only messages with media'
    )
    filter_group.add_argument(
        '--text-only',
        action='store_true',
        help='Only text messages (no media)'
    )
    filter_group.add_argument(
        '--min-size',
        help='Minimum file size (e.g., 1MB, 500KB)'
    )
    filter_group.add_argument(
        '--max-size',
        help='Maximum file size (e.g., 100MB)'
    )
    
    # Other filters
    filter_group.add_argument(
        '--no-replies',
        action='store_true',
        help='Exclude reply messages'
    )
    filter_group.add_argument(
        '--replies-only',
        action='store_true',
        help='Only reply messages'
    )
    filter_group.add_argument(
        '--no-forwards',
        action='store_true',
        help='Exclude forwarded messages'
    )
    filter_group.add_argument(
        '--forwards-only',
        action='store_true',
        help='Only forwarded messages'
    )
    filter_group.add_argument(
        '--no-links',
        action='store_true',
        help='Exclude messages with links'
    )
    filter_group.add_argument(
        '--links-only',
        action='store_true',
        help='Only messages with links'
    )


def _add_delete_args(parser: argparse.ArgumentParser):
    """Add common delete arguments to a parser."""
    parser.add_argument(
        '-c', '--chat',
        required=True,
        help='Chat ID or username to delete messages from'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview without executing'
    )


async def cmd_login(args, config_manager: ConfigManager, logger: ForwarderLogger):
    """Handle login command."""
    # Check for API credentials
    config = config_manager.get_config()
    
    if args.api_id:
        config.api_id = args.api_id
    if args.api_hash:
        config.api_hash = args.api_hash
    
    if not config.api_id or not config.api_hash:
        logger.info("API credentials required. Get them from https://my.telegram.org")
        try:
            if not config.api_id:
                config.api_id = int(input("Enter API ID: ").strip())
            if not config.api_hash:
                config.api_hash = input("Enter API Hash: ").strip()
        except (ValueError, EOFError):
            logger.error("Invalid API credentials")
            return 1
    
    # Save credentials
    config_manager.save(config)
    
    # Connect and login
    wrapper = ClientWrapper(config_manager, logger)
    try:
        is_authorized = await wrapper.connect()
        
        if is_authorized:
            me = wrapper.me
            logger.success(f"Already logged in as {me.first_name} (@{me.username or 'no username'})")
        else:
            await wrapper.login()
        
        await wrapper.disconnect()
        return 0
        
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return 1


async def cmd_logout(args, config_manager: ConfigManager, logger: ForwarderLogger):
    """Handle logout command."""
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        await wrapper.connect()
        await wrapper.logout()
        return 0
    except ConfigurationError:
        # Not configured, just clear any leftover files
        config_manager.clear_session(clear_credentials=True)
        logger.success("Session and credentials cleared")
        return 0
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        return 1


async def cmd_list_chats(args, config_manager: ConfigManager, logger: ForwarderLogger):
    """Handle list-chats command."""
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-cli login' first.")
            return 1
        
        search_term = getattr(args, 'search', None)
        type_filter = getattr(args, 'type', None)
        
        if search_term:
            logger.info(f"Searching chats for: '{search_term}'")
        if type_filter:
            logger.info(f"Filtering by type: {type_filter}")
        
        logger.info("-" * 60)
        
        count = 0
        matched = 0
        async for chat_id, title, chat_type in wrapper.list_chats(
            limit=None if search_term else args.limit,  # No limit when searching
            archived=args.archived
        ):
            count += 1
            
            # Apply search filter
            if search_term:
                if search_term.lower() not in title.lower():
                    continue
            
            # Apply type filter
            if type_filter:
                # Normalize type names for comparison
                type_lower = chat_type.lower().strip()
                if type_filter.lower() != type_lower:
                    continue
            
            print(f"{chat_id:>15}  [{chat_type:^10}]  {title}")
            matched += 1
            
            # Apply limit after filtering
            if args.limit and matched >= args.limit:
                break
        
        logger.info("-" * 60)
        if search_term or type_filter:
            logger.info(f"Found {matched} matching chats (scanned {count})")
        else:
            logger.info(f"Listed {matched} chats")
        
        await wrapper.disconnect()
        return 0
        
    except Exception as e:
        logger.error(f"Failed to list chats: {e}")
        return 1


async def cmd_test(args, config_manager: ConfigManager, logger: ForwarderLogger):
    """Handle test command."""
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-cli login' first.")
            return 1
        
        # Parse chat IDs
        source_id = validate_chat_id(args.source)
        dest_ids = [validate_chat_id(d) for d in args.dest]
        
        logger.info("Testing permissions...")
        logger.info("-" * 60)
        
        checks = await test_permissions(
            wrapper.client,
            source_id,
            dest_ids,
            delete_after=args.delete
        )
        
        all_passed = True
        for check_name, passed, reason in checks:
            status = "OK" if passed else "FAIL"
            print(f"  [{status:^4}] {check_name}: {reason}")
            if not passed:
                all_passed = False
        
        logger.info("-" * 60)
        
        if all_passed:
            logger.success("All checks passed!")
        else:
            logger.error("Some checks failed")
        
        await wrapper.disconnect()
        return 0 if all_passed else 1
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return 1


async def cmd_forward_last(
    args,
    config_manager: ConfigManager,
    logger: ForwarderLogger,
    state_manager: StateManager
):
    """Handle forward-last command."""
    # Parse filters
    try:
        msg_filter = create_filter_from_args(args)
        if not msg_filter.is_empty():
            logger.info(f"Filters: {msg_filter.describe()}")
    except ValueError as e:
        logger.error(f"Invalid filter: {e}")
        return 1
    
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-cli login' first.")
            return 1
        
        # Parse chat IDs
        source_id = validate_chat_id(args.source)
        dest_ids = [validate_chat_id(d) for d in args.dest]
        
        # Create shutdown handler
        shutdown = create_shutdown_handler(state_manager, logger)
        
        try:
            # Create forwarder
            forwarder = Forwarder(
                client=wrapper.client,
                logger=logger,
                state=state_manager,
                shutdown=shutdown,
            )
            
            # Verify operation
            if not args.dry_run:
                proceed = await forwarder.verify_operation(
                    source_id=source_id,
                    dest_ids=dest_ids,
                    drop_author=args.drop_author,
                    delete_after=args.delete,
                    count=args.count,
                    skip_confirm=args.yes,
                )
                if not proceed:
                    return 1
            
            # Create job
            job = state_manager.create_job(
                job_type=JobType.FORWARD_LAST,
                source=source_id,
                destinations=dest_ids,
                drop_author=args.drop_author,
                delete_after=args.delete,
                count=args.count,
            )
            
            logger.info(f"Job ID: {job.job_id}")
            
            # Execute
            processed, skipped, failed = await forwarder.forward_last(
                source_id=source_id,
                dest_ids=dest_ids,
                count=args.count,
                drop_author=args.drop_author,
                delete_after=args.delete,
                dry_run=args.dry_run,
                msg_filter=msg_filter if not msg_filter.is_empty() else None,
            )
            
            if shutdown.shutdown_requested:
                state_manager.mark_interrupted()
                logger.info(f"Resume with: telegram-cli resume {job.job_id}")
            else:
                state_manager.mark_completed()
            
            await wrapper.disconnect()
            return 0 if failed == 0 else 1
            
        finally:
            shutdown.cleanup()
        
    except AccountLimitedError as e:
        logger.error(str(e))
        state_manager.mark_failed(str(e))
        return 1
    except Exception as e:
        logger.error(f"Forward failed: {e}")
        state_manager.mark_interrupted(str(e))
        return 1


async def cmd_forward_all(
    args,
    config_manager: ConfigManager,
    logger: ForwarderLogger,
    state_manager: StateManager
):
    """Handle forward-all command."""
    # Parse filters
    try:
        msg_filter = create_filter_from_args(args)
        if not msg_filter.is_empty():
            logger.info(f"Filters: {msg_filter.describe()}")
    except ValueError as e:
        logger.error(f"Invalid filter: {e}")
        return 1
    
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-cli login' first.")
            return 1
        
        # Parse chat IDs
        source_id = validate_chat_id(args.source)
        dest_ids = [validate_chat_id(d) for d in args.dest]
        
        # Create shutdown handler
        shutdown = create_shutdown_handler(state_manager, logger)
        
        try:
            # Create forwarder
            forwarder = Forwarder(
                client=wrapper.client,
                logger=logger,
                state=state_manager,
                shutdown=shutdown,
            )
            
            # Verify operation
            if not args.dry_run:
                proceed = await forwarder.verify_operation(
                    source_id=source_id,
                    dest_ids=dest_ids,
                    drop_author=args.drop_author,
                    delete_after=args.delete,
                    skip_confirm=args.yes,
                )
                if not proceed:
                    return 1
            
            # Create job
            job = state_manager.create_job(
                job_type=JobType.FORWARD_ALL,
                source=source_id,
                destinations=dest_ids,
                drop_author=args.drop_author,
                delete_after=args.delete,
                batch_size=min(args.batch_size, 100),
            )
            
            logger.info(f"Job ID: {job.job_id}")
            
            # Execute
            processed, skipped, failed = await forwarder.forward_all(
                source_id=source_id,
                dest_ids=dest_ids,
                drop_author=args.drop_author,
                delete_after=args.delete,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                msg_filter=msg_filter if not msg_filter.is_empty() else None,
            )
            
            if shutdown.shutdown_requested:
                state_manager.mark_interrupted()
                logger.info(f"Resume with: telegram-cli resume {job.job_id}")
            else:
                state_manager.mark_completed()
            
            await wrapper.disconnect()
            return 0 if failed == 0 else 1
            
        finally:
            shutdown.cleanup()
        
    except AccountLimitedError as e:
        logger.error(str(e))
        state_manager.mark_failed(str(e))
        return 1
    except Exception as e:
        logger.error(f"Forward failed: {e}")
        state_manager.mark_interrupted(str(e))
        return 1


async def cmd_forward_live(
    args,
    config_manager: ConfigManager,
    logger: ForwarderLogger,
    state_manager: StateManager
):
    """Handle forward-live command."""
    # Handle --list-transforms
    if getattr(args, 'list_transforms', False):
        transforms = list_transforms()
        logger.info("Available transforms:")
        logger.info("-" * 40)
        for name in sorted(transforms):
            logger.info(f"  {name}")
        logger.info("-" * 40)
        logger.info("Usage: --transform 'replace_mentions,strip_formatting'")
        logger.info("With config: --transform 'replace_mentions' --transform-config 'replacement=[removed]'")
        return 0
    
    # Parse filters
    try:
        msg_filter = create_filter_from_args(args)
        if not msg_filter.is_empty():
            logger.info(f"Filters: {msg_filter.describe()}")
    except ValueError as e:
        logger.error(f"Invalid filter: {e}")
        return 1
    
    # Parse transform chain if provided
    transform_chain = None
    if getattr(args, 'transform', None):
        try:
            # Build spec with config if provided
            spec = args.transform
            if getattr(args, 'transform_config', None):
                # Append config to the first transform
                parts = spec.split(',')
                if parts:
                    parts[0] = f"{parts[0]}:{args.transform_config}"
                    spec = ','.join(parts)
            
            transform_chain = create_chain_from_spec(spec)
            logger.info(f"Transform chain: {args.transform} ({len(transform_chain)} transforms)")
        except ValueError as e:
            logger.error(f"Invalid transform: {e}")
            return 1
    
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-cli login' first.")
            return 1
        
        # Parse chat IDs
        source_id = validate_chat_id(args.source)
        dest_ids = [validate_chat_id(d) for d in args.dest]
        
        # Create shutdown handler
        shutdown = create_shutdown_handler(state_manager, logger)
        
        try:
            # Create forwarder
            forwarder = Forwarder(
                client=wrapper.client,
                logger=logger,
                state=state_manager,
                shutdown=shutdown,
            )
            
            # Verify operation (no confirmation for live, just check permissions)
            proceed = await forwarder.verify_operation(
                source_id=source_id,
                dest_ids=dest_ids,
                drop_author=args.drop_author,
                delete_after=args.delete,
                skip_confirm=True,
            )
            if not proceed:
                return 1
            
            # Create job
            job = state_manager.create_job(
                job_type=JobType.FORWARD_LIVE,
                source=source_id,
                destinations=dest_ids,
                drop_author=args.drop_author,
                delete_after=args.delete,
            )
            
            logger.info(f"Job ID: {job.job_id}")
            
            # Start live forwarding
            await forwarder.start_live_forward(
                source_id=source_id,
                dest_ids=dest_ids,
                drop_author=args.drop_author,
                delete_after=args.delete,
                transform_chain=transform_chain,
                msg_filter=msg_filter if not msg_filter.is_empty() else None,
            )
            
            state_manager.mark_completed()
            return 0
            
        finally:
            shutdown.cleanup()
        
    except AccountLimitedError as e:
        logger.error(str(e))
        state_manager.mark_failed(str(e))
        return 1
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        state_manager.mark_completed()
        return 0
    except Exception as e:
        logger.error(f"Live forward failed: {e}")
        return 1


async def cmd_delete_last(
    args,
    config_manager: ConfigManager,
    logger: ForwarderLogger,
    state_manager: StateManager
):
    """Handle delete-last command."""
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-cli login' first.")
            return 1
        
        # Parse chat ID
        chat_id = validate_chat_id(args.chat)
        
        # Create shutdown handler
        shutdown = create_shutdown_handler(state_manager, logger)
        
        try:
            # Create forwarder
            forwarder = Forwarder(
                client=wrapper.client,
                logger=logger,
                state=state_manager,
                shutdown=shutdown,
            )
            
            # Verify delete operation
            proceed = await forwarder.verify_delete_operation(
                chat_id=chat_id,
                count=args.count,
                skip_confirm=args.yes,
                dry_run=args.dry_run,
            )
            if not proceed:
                return 1
            
            # Execute
            deleted, failed = await forwarder.delete_last(
                chat_id=chat_id,
                count=args.count,
                dry_run=args.dry_run,
            )
            
            logger.success(f"Complete: {deleted} deleted, {failed} failed")
            await wrapper.disconnect()
            return 0 if failed == 0 else 1
            
        finally:
            shutdown.cleanup()
        
    except AccountLimitedError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        return 1


async def cmd_delete_all(
    args,
    config_manager: ConfigManager,
    logger: ForwarderLogger,
    state_manager: StateManager
):
    """Handle delete-all command."""
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-cli login' first.")
            return 1
        
        # Parse chat ID
        chat_id = validate_chat_id(args.chat)
        
        # Create shutdown handler
        shutdown = create_shutdown_handler(state_manager, logger)
        
        try:
            # Create forwarder
            forwarder = Forwarder(
                client=wrapper.client,
                logger=logger,
                state=state_manager,
                shutdown=shutdown,
            )
            
            # Verify delete operation
            proceed = await forwarder.verify_delete_operation(
                chat_id=chat_id,
                count=None,  # All messages
                skip_confirm=args.yes,
                dry_run=args.dry_run,
            )
            if not proceed:
                return 1
            
            # Execute
            deleted, failed = await forwarder.delete_all(
                chat_id=chat_id,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            
            if shutdown.shutdown_requested:
                logger.info("Interrupted. Run the command again to continue.")
            
            logger.success(f"Complete: {deleted} deleted, {failed} failed")
            await wrapper.disconnect()
            return 0 if failed == 0 else 1
            
        finally:
            shutdown.cleanup()
        
    except AccountLimitedError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        return 1


async def cmd_resume(
    args,
    config_manager: ConfigManager,
    logger: ForwarderLogger,
    state_manager: StateManager
):
    """Handle resume command."""
    # List resumable jobs if no ID provided
    if not args.job_id:
        jobs = state_manager.get_resumable_jobs()
        
        if not jobs:
            logger.info("No resumable jobs found")
            return 0
        
        logger.info("Resumable jobs:")
        logger.info("-" * 60)
        for job in jobs:
            progress = f"{job.total_processed}/{job.total_messages}" if job.total_messages else f"{job.total_processed}"
            print(f"  {job.job_id}  {job.job_type:^12}  {progress} msgs  from {job.source}")
        logger.info("-" * 60)
        logger.info("Resume with: telegram-cli resume <job_id>")
        return 0
    
    # Resume specific job
    job = state_manager.resume_job(args.job_id)
    if not job:
        logger.error(f"Job {args.job_id} not found or not resumable")
        return 1
    
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-cli login' first.")
            return 1
        
        # Create shutdown handler
        shutdown = create_shutdown_handler(state_manager, logger)
        
        try:
            # Create forwarder
            forwarder = Forwarder(
                client=wrapper.client,
                logger=logger,
                state=state_manager,
                shutdown=shutdown,
            )
            
            logger.info(f"Resuming job {job.job_id}")
            logger.info(f"Already processed: {job.total_processed} messages")
            logger.info(f"Continuing from message ID: {job.last_message_id}")
            
            if job.job_type == JobType.FORWARD_ALL.value:
                processed, skipped, failed = await forwarder.forward_all(
                    source_id=job.source,
                    dest_ids=job.destinations,
                    drop_author=job.drop_author,
                    delete_after=job.delete_after,
                    batch_size=job.batch_size,
                    min_id=job.last_message_id,
                )
            else:
                logger.error(f"Cannot resume job type: {job.job_type}")
                return 1
            
            if shutdown.shutdown_requested:
                state_manager.mark_interrupted()
                logger.info(f"Resume with: telegram-cli resume {job.job_id}")
            else:
                state_manager.mark_completed()
            
            await wrapper.disconnect()
            return 0 if failed == 0 else 1
            
        finally:
            shutdown.cleanup()
        
    except AccountLimitedError as e:
        logger.error(str(e))
        state_manager.mark_failed(str(e))
        return 1
    except Exception as e:
        logger.error(f"Resume failed: {e}")
        state_manager.mark_interrupted(str(e))
        return 1


async def cmd_status(
    args,
    config_manager: ConfigManager,
    logger: ForwarderLogger,
    state_manager: StateManager
):
    """Handle status command."""
    jobs = state_manager.list_jobs()
    
    if not jobs:
        logger.info("No jobs found")
        return 0
    
    logger.info("Job history:")
    logger.info("-" * 80)
    
    for job in jobs[:20]:  # Show last 20
        progress = f"{job.total_processed}"
        if job.total_messages:
            pct = job.total_processed / job.total_messages * 100
            progress += f"/{job.total_messages} ({pct:.1f}%)"
        
        status_icon = {
            'completed': 'OK',
            'running': '>>',
            'interrupted': '||',
            'failed': 'XX',
            'pending': '..',
        }.get(job.status, '??')
        
        print(f"  [{status_icon}] {job.job_id}  {job.job_type:^12}  {progress} msgs  {job.status}")
        
        if job.last_error:
            print(f"       Error: {job.last_error[:50]}")
    
    logger.info("-" * 80)
    
    resumable = [j for j in jobs if j.is_resumable()]
    if resumable:
        logger.info(f"{len(resumable)} jobs can be resumed")
    
    return 0


async def cmd_tui(
    args,
    config_manager: ConfigManager,
    logger: ForwarderLogger
):
    """Handle tui command - launch interactive interface."""
    try:
        from .tui import run_tui
        return await run_tui(config_manager, logger)
    except ImportError:
        logger.error("TUI requires the 'rich' library.")
        logger.info("Install it with: pip install rich")
        return 1


async def cmd_account(args, logger: ForwarderLogger) -> int:
    """Handle account subcommands."""
    from .accounts import get_account_manager
    from .config import ConfigManager
    
    account_mgr = get_account_manager()
    
    # No subcommand - show current account
    if not args.account_command:
        active = account_mgr.get_active()
        if active:
            account = account_mgr.get_account(active)
            if account:
                logger.info(f"Active account: {active}")
                if account.username:
                    logger.info(f"  Username: @{account.username}")
                if account.first_name:
                    logger.info(f"  Name: {account.first_name}")
            else:
                logger.info(f"Active account: {active}")
        else:
            logger.info("No accounts configured.")
            logger.info("Add one with: telegram-cli account add <alias>")
        return 0
    
    # account list
    if args.account_command == 'list':
        accounts = account_mgr.list_accounts()
        active = account_mgr.get_active()
        
        if not accounts:
            logger.info("No accounts registered.")
            logger.info("Add one with: telegram-cli account add <alias>")
            return 0
        
        logger.info(f"Registered accounts ({len(accounts)}):")
        logger.info("-" * 60)
        
        for acc in accounts:
            marker = "*" if acc.alias == active else " "
            display = acc.display_name()
            print(f"  {marker} {acc.alias:<15}  {display}")
        
        logger.info("-" * 60)
        logger.info("* = active account")
        logger.info("Switch with: telegram-cli account switch <alias>")
        return 0
    
    # account add
    if args.account_command == 'add':
        alias = args.alias
        
        # Check if alias is valid
        try:
            account = account_mgr.add_account(alias)
            logger.info(f"Created account: {alias}")
        except ValueError as e:
            logger.error(str(e))
            return 1
        
        # Get API credentials
        api_id = args.api_id
        api_hash = args.api_hash
        
        if not api_id or not api_hash:
            logger.info("API credentials required. Get them from https://my.telegram.org")
            try:
                if not api_id:
                    api_id = int(input("Enter API ID: ").strip())
                if not api_hash:
                    api_hash = input("Enter API Hash: ").strip()
            except (ValueError, EOFError):
                logger.error("Invalid API credentials")
                account_mgr.remove_account(alias)
                return 1
        
        # Create config manager for this account
        config_manager = ConfigManager(account=alias)
        config = config_manager.get_config()
        config.api_id = api_id
        config.api_hash = api_hash
        config_manager.save(config)
        
        # Login
        from .client import ClientWrapper
        wrapper = ClientWrapper(config_manager, logger)
        
        try:
            is_authorized = await wrapper.connect()
            
            if is_authorized:
                me = wrapper.me
                logger.success(f"Already logged in as {me.first_name} (@{me.username or 'no username'})")
            else:
                me = await wrapper.login()
            
            # Update account info
            account_mgr.update_account(
                alias,
                phone=me.phone,
                username=me.username,
                first_name=me.first_name,
                user_id=me.id
            )
            
            await wrapper.disconnect()
            logger.success(f"Account '{alias}' configured successfully!")
            return 0
            
        except Exception as e:
            logger.error(f"Login failed: {e}")
            # Keep the account but note login failed
            return 1
    
    # account switch
    if args.account_command == 'switch':
        alias = args.alias
        
        if account_mgr.set_active(alias):
            account = account_mgr.get_account(alias)
            logger.success(f"Switched to account: {alias}")
            if account and account.username:
                logger.info(f"  Username: @{account.username}")
            return 0
        else:
            logger.error(f"Account '{alias}' not found.")
            logger.info("List accounts with: telegram-cli account list")
            return 1
    
    # account remove
    if args.account_command == 'remove':
        alias = args.alias
        
        account = account_mgr.get_account(alias)
        if not account:
            logger.error(f"Account '{alias}' not found.")
            return 1
        
        # Confirm
        if not args.yes:
            try:
                confirm = input(f"Remove account '{alias}'? [y/N]: ").strip().lower()
                if confirm != 'y':
                    logger.info("Cancelled.")
                    return 0
            except EOFError:
                logger.info("Cancelled.")
                return 0
        
        delete_data = not getattr(args, 'keep_data', False)
        
        if account_mgr.remove_account(alias, delete_data=delete_data):
            logger.success(f"Account '{alias}' removed.")
            if not delete_data:
                logger.info("Data files were kept.")
            return 0
        else:
            logger.error(f"Failed to remove account '{alias}'.")
            return 1
    
    # account rename
    if args.account_command == 'rename':
        old_alias = args.old_alias
        new_alias = args.new_alias
        
        try:
            if account_mgr.rename_account(old_alias, new_alias):
                logger.success(f"Renamed account '{old_alias}' to '{new_alias}'")
                return 0
            else:
                logger.error(f"Account '{old_alias}' not found.")
                return 1
        except ValueError as e:
            logger.error(str(e))
            return 1
    
    # account info
    if args.account_command == 'info':
        alias = args.alias or account_mgr.get_active()
        
        if not alias:
            logger.error("No account specified and no active account.")
            return 1
        
        account = account_mgr.get_account(alias)
        if not account:
            logger.error(f"Account '{alias}' not found.")
            return 1
        
        active = account_mgr.get_active()
        
        logger.info(f"Account: {account.alias}" + (" (active)" if alias == active else ""))
        if account.first_name:
            logger.info(f"  Name: {account.first_name}")
        if account.username:
            logger.info(f"  Username: @{account.username}")
        if account.phone:
            # Mask phone for privacy
            masked = f"{account.phone[:4]}...{account.phone[-2:]}" if len(account.phone) > 6 else "***"
            logger.info(f"  Phone: {masked}")
        if account.user_id:
            logger.info(f"  User ID: {account.user_id}")
        if account.created_at:
            logger.info(f"  Created: {account.created_at[:19]}")
        
        # Show account directory
        account_dir = account_mgr.get_account_dir(alias)
        logger.info(f"  Directory: {account_dir}")
        
        return 0
    
    logger.error(f"Unknown account command: {args.account_command}")
    return 1


def cmd_list_daemons(config_manager: ConfigManager) -> int:
    """Handle list command - show running daemons."""
    daemon_manager = get_daemon_manager(config_manager.config_dir)
    
    processes = daemon_manager.list_running()
    
    if not processes:
        print("No running daemons")
        return 0
    
    print(f"Running daemons ({len(processes)}):")
    print("-" * 70)
    print(f"{'PID':>8}  {'Command':<20}  {'Source':>12}  {'Started'}")
    print("-" * 70)
    
    for proc in processes:
        source = str(proc.source) if proc.source else "-"
        started = proc.started_at[:19] if proc.started_at else "-"
        print(f"{proc.pid:>8}  {proc.command:<20}  {source:>12}  {started}")
    
    print("-" * 70)
    print(f"Kill with: telegram-cli kill <PID>")
    print(f"View logs: telegram-cli logs <PID>")
    
    return 0


def cmd_kill(args, config_manager: ConfigManager) -> int:
    """Handle kill command - stop daemons."""
    daemon_manager = get_daemon_manager(config_manager.config_dir)
    
    # Kill all if --all flag or no PID specified
    if args.all or (args.pid is None):
        processes = daemon_manager.list_running()
        
        if not processes:
            print("No running daemons to kill")
            return 0
        
        if args.pid is None and not args.all:
            # No PID and no --all, show list instead
            print(f"Running daemons ({len(processes)}):")
            for proc in processes:
                print(f"  PID {proc.pid}: {proc.command}")
            print()
            print("Specify a PID or use --all to kill all:")
            print("  telegram-cli kill <PID>")
            print("  telegram-cli kill --all")
            return 0
        
        killed, failed = daemon_manager.kill_all()
        print(f"Killed {killed} daemons" + (f", {failed} failed" if failed else ""))
        return 0 if failed == 0 else 1
    
    # Kill specific PID
    success, message = daemon_manager.kill(args.pid, force=args.force)
    print(message)
    return 0 if success else 1


def cmd_logs(args, config_manager: ConfigManager) -> int:
    """Handle logs command - view daemon logs."""
    daemon_manager = get_daemon_manager(config_manager.config_dir)
    
    # If PID specified, use that log file
    if args.pid:
        log_file = daemon_manager.get_log_file(args.pid)
        if not log_file.exists():
            print(f"No logs found for PID {args.pid}")
            return 1
    else:
        # Find the most recent log file
        log_files = sorted(daemon_manager.logs_dir.glob("daemon_*.log"), 
                          key=lambda f: f.stat().st_mtime, reverse=True)
        if not log_files:
            print("No daemon logs found")
            return 0
        log_file = log_files[0]
        print(f"Showing logs from: {log_file.name}")
        print("-" * 50)
    
    if args.follow:
        # Follow mode - like tail -f
        import subprocess
        try:
            subprocess.run(['tail', '-f', str(log_file)])
        except KeyboardInterrupt:
            pass
        return 0
    else:
        # Show last N lines
        if not log_file.exists():
            print("Log file not found")
            return 1
        
        with open(log_file, 'r') as f:
            lines = f.readlines()
            for line in lines[-args.lines:]:
                print(line.rstrip())
        return 0


async def main_async(args: argparse.Namespace) -> int:
    """Async main function."""
    # Determine verbosity
    if args.quiet:
        verbosity = 0
    else:
        verbosity = 1 + args.verbose
    
    # Get account from args (--account / -a flag)
    account = getattr(args, 'account', None)
    
    # Initialize managers with account support
    config_manager = get_config_manager(account=account)
    logger = get_logger(config_manager.base_dir, verbosity)
    state_manager = get_state_manager(config_manager.jobs_file)
    
    # Show which account is being used (if multiple accounts exist)
    from .accounts import get_account_manager
    account_mgr = get_account_manager(config_manager.base_dir)
    if account_mgr.has_accounts() and verbosity >= 2:
        active = account_mgr.get_active()
        if active:
            logger.verbose(f"Using account: {active}")
    
    # Route to command handler
    command_handlers = {
        'login': lambda: cmd_login(args, config_manager, logger),
        'logout': lambda: cmd_logout(args, config_manager, logger),
        'list-chats': lambda: cmd_list_chats(args, config_manager, logger),
        'test': lambda: cmd_test(args, config_manager, logger),
        'forward-last': lambda: cmd_forward_last(args, config_manager, logger, state_manager),
        'forward-all': lambda: cmd_forward_all(args, config_manager, logger, state_manager),
        'forward-live': lambda: cmd_forward_live(args, config_manager, logger, state_manager),
        'delete-last': lambda: cmd_delete_last(args, config_manager, logger, state_manager),
        'delete-all': lambda: cmd_delete_all(args, config_manager, logger, state_manager),
        'resume': lambda: cmd_resume(args, config_manager, logger, state_manager),
        'status': lambda: cmd_status(args, config_manager, logger, state_manager),
        'tui': lambda: cmd_tui(args, config_manager, logger),
        'account': lambda: cmd_account(args, logger),
    }
    
    if args.command is None:
        # No command, show help
        create_parser().print_help()
        return 0
    
    handler = command_handlers.get(args.command)
    if handler is None:
        logger.error(f"Unknown command: {args.command}")
        return 1
    
    return await handler()


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Handle synchronous commands first
    if args.command == 'list':
        config_manager = get_config_manager()
        sys.exit(cmd_list_daemons(config_manager))
    
    if args.command == 'kill':
        config_manager = get_config_manager()
        sys.exit(cmd_kill(args, config_manager))
    
    if args.command == 'logs':
        config_manager = get_config_manager()
        sys.exit(cmd_logs(args, config_manager))
    
    # Check for daemon mode
    if hasattr(args, 'daemon') and args.daemon:
        config_manager = get_config_manager()
        daemon_manager = get_daemon_manager(config_manager.config_dir)
        
        # Get source/dest for tracking
        source = None
        dest = None
        if hasattr(args, 'source'):
            try:
                source = int(args.source) if args.source else None
            except ValueError:
                source = None
        if hasattr(args, 'dest'):
            dest = []
            for d in (args.dest or []):
                try:
                    dest.append(int(d))
                except ValueError:
                    pass
        
        print(f"Starting daemon...")
        
        # Daemonize - returns 0 in child, PID in parent
        child_pid = daemon_manager.daemonize(
            command=args.command,
            source=source,
            dest=dest
        )
        
        if child_pid > 0:
            # We're in the parent
            print(f"PID: {child_pid}")
            print(f"Logs: telegram-cli logs {child_pid}")
            print(f"Kill: telegram-cli kill {child_pid}")
            print(f"List: telegram-cli list")
            sys.exit(0)
        
        # We're in the child - continue with normal execution
    
    try:
        exit_code = asyncio.run(main_async(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
