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
    
    # Forward-all command
    forward_all_parser = subparsers.add_parser(
        'forward-all',
        help='Forward all messages in batches'
    )
    _add_forward_args(forward_all_parser)
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
        help='Run in background (daemon mode). Stop with: telegram-forwarder stop'
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
            logger.error("Not logged in. Run 'telegram-forwarder login' first.")
            return 1
        
        logger.info("Available chats:")
        logger.info("-" * 60)
        
        count = 0
        async for chat_id, title, chat_type in wrapper.list_chats(
            limit=args.limit,
            archived=args.archived
        ):
            print(f"{chat_id:>15}  [{chat_type:^10}]  {title}")
            count += 1
        
        logger.info("-" * 60)
        logger.info(f"Listed {count} chats")
        
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
            logger.error("Not logged in. Run 'telegram-forwarder login' first.")
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
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-forwarder login' first.")
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
            )
            
            if shutdown.shutdown_requested:
                state_manager.mark_interrupted()
                logger.info(f"Resume with: telegram-forwarder resume {job.job_id}")
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
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-forwarder login' first.")
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
            )
            
            if shutdown.shutdown_requested:
                state_manager.mark_interrupted()
                logger.info(f"Resume with: telegram-forwarder resume {job.job_id}")
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
    wrapper = ClientWrapper(config_manager, logger)
    
    try:
        is_authorized = await wrapper.connect()
        if not is_authorized:
            logger.error("Not logged in. Run 'telegram-forwarder login' first.")
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
        logger.info("Resume with: telegram-forwarder resume <job_id>")
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
            logger.error("Not logged in. Run 'telegram-forwarder login' first.")
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
                logger.info(f"Resume with: telegram-forwarder resume {job.job_id}")
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
    print(f"Kill with: telegram-forwarder kill <PID>")
    print(f"View logs: telegram-forwarder logs <PID>")
    
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
            print("  telegram-forwarder kill <PID>")
            print("  telegram-forwarder kill --all")
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
    
    # Initialize managers
    config_manager = get_config_manager()
    logger = get_logger(config_manager.config_dir, verbosity)
    state_manager = get_state_manager(config_manager.jobs_file)
    
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
            print(f"Logs: telegram-forwarder logs {child_pid}")
            print(f"Kill: telegram-forwarder kill {child_pid}")
            print(f"List: telegram-forwarder list")
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
