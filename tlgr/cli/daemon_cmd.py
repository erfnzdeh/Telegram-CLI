"""Daemon lifecycle commands."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time

import click

from tlgr.core.config import CONFIG_DIR, get_socket_path, get_pid_path, get_logs_dir
from tlgr.core.output import output_result
from tlgr.daemon.lifecycle import read_pid, stop_daemon


@click.group("daemon")
def daemon_group() -> None:
    """Manage the tlgr daemon."""


@daemon_group.command("start")
@click.option("--foreground", is_flag=True, help="Run in foreground (don't fork).")
@click.pass_context
def daemon_start(ctx: click.Context, foreground: bool) -> None:
    """Start the daemon (forks to background by default)."""
    existing = read_pid()
    if existing:
        click.echo(f"Daemon already running (pid={existing})", err=True)
        sys.exit(1)

    if foreground:
        from tlgr.daemon.server import DaemonServer
        from tlgr.daemon.lifecycle import setup_logging
        from tlgr.core.config import load_app_config
        import asyncio

        cfg = load_app_config()
        setup_logging(CONFIG_DIR, cfg.daemon.log_level)
        server = DaemonServer(CONFIG_DIR)
        asyncio.run(server.run())
    else:
        proc = subprocess.Popen(
            [sys.executable, "-m", "tlgr.daemon.server", "--base", str(CONFIG_DIR)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        sock = get_socket_path()
        for _ in range(40):
            time.sleep(0.25)
            if sock.exists():
                pid = read_pid()
                fmt = ctx.obj.get("fmt", "human")
                output_result({"started": True, "pid": pid or proc.pid}, fmt=fmt)
                return
        click.echo("Daemon did not start within 10 seconds", err=True)
        sys.exit(1)


@daemon_group.command("stop")
@click.pass_context
def daemon_stop(ctx: click.Context) -> None:
    """Stop the daemon."""
    if stop_daemon():
        for _ in range(20):
            time.sleep(0.25)
            if not get_pid_path().exists():
                break
        output_result({"stopped": True}, fmt=ctx.obj.get("fmt", "human"))
    else:
        click.echo("Daemon is not running", err=True)
        sys.exit(1)


@daemon_group.command("restart")
@click.pass_context
def daemon_restart(ctx: click.Context) -> None:
    """Restart the daemon."""
    if read_pid():
        stop_daemon()
        for _ in range(20):
            time.sleep(0.25)
            if not get_pid_path().exists():
                break

    proc = subprocess.Popen(
        [sys.executable, "-m", "tlgr.daemon.server", "--base", str(CONFIG_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    sock = get_socket_path()
    for _ in range(40):
        time.sleep(0.25)
        if sock.exists():
            pid = read_pid()
            fmt = ctx.obj.get("fmt", "human")
            output_result({"restarted": True, "pid": pid or proc.pid}, fmt=fmt)
            return
    click.echo("Daemon did not start within 10 seconds", err=True)
    sys.exit(1)


@daemon_group.command("install")
@click.option("--force", is_flag=True, help="Reinstall even if already installed.")
@click.pass_context
def daemon_install(ctx: click.Context, force: bool) -> None:
    """Install as a system service (auto-start on login, restart on crash).

    macOS: creates a LaunchAgent plist.
    """
    if platform.system() != "Darwin":
        click.echo("Service installation is only supported on macOS for now.", err=True)
        sys.exit(1)

    from tlgr.daemon.launchd import is_installed, install

    if is_installed() and not force:
        click.echo("Service already installed. Use --force to reinstall.", err=True)
        sys.exit(1)

    plist_path = install(CONFIG_DIR, get_logs_dir())
    fmt = ctx.obj.get("fmt", "human")
    output_result({"installed": True, "plist": str(plist_path)}, fmt=fmt)


@daemon_group.command("uninstall")
@click.pass_context
def daemon_uninstall(ctx: click.Context) -> None:
    """Remove the system service (stop auto-start on login)."""
    if platform.system() != "Darwin":
        click.echo("Service installation is only supported on macOS for now.", err=True)
        sys.exit(1)

    from tlgr.daemon.launchd import uninstall

    if uninstall():
        output_result({"uninstalled": True}, fmt=ctx.obj.get("fmt", "human"))
    else:
        click.echo("Service is not installed.", err=True)
        sys.exit(1)


@daemon_group.command("status")
@click.pass_context
def daemon_status(ctx: click.Context) -> None:
    """Show daemon status."""
    pid = read_pid()
    if pid:
        try:
            from tlgr.ipc_client import ipc_request
            result = ipc_request("GET", "/daemon/status")
            output_result(result, fmt=ctx.obj.get("fmt", "human"), columns=["running", "pid", "uptime_seconds", "accounts"])
        except Exception:
            output_result({"running": True, "pid": pid, "uptime_seconds": "?", "accounts": "?"}, fmt=ctx.obj.get("fmt", "human"))
    else:
        output_result({"running": False}, fmt=ctx.obj.get("fmt", "human"), columns=["running"])


@daemon_group.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
@click.option("--lines", "-n", type=int, default=50, help="Number of lines to show.")
def daemon_logs(follow: bool, lines: int) -> None:
    """View daemon logs."""
    log_file = get_logs_dir() / "daemon.log"
    if not log_file.exists():
        click.echo("No log file found", err=True)
        sys.exit(1)

    if follow:
        os.execlp("tail", "tail", "-f", "-n", str(lines), str(log_file))
    else:
        os.execlp("tail", "tail", "-n", str(lines), str(log_file))
