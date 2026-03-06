"""Job management commands."""

from __future__ import annotations

import os
import sys

import click

from tlgr.core.config import CONFIG_DIR
from tlgr.core.output import output_result
from tlgr.ipc_client import ipc_request


@click.group("job")
def job_group() -> None:
    """Manage background jobs."""


@job_group.command("list")
@click.pass_context
def job_list(ctx: click.Context) -> None:
    """List configured jobs and their status."""
    result = ipc_request("GET", "/job/list")
    fmt = ctx.obj.get("fmt", "human")
    if fmt == "json":
        output_result(result, fmt=fmt)
    else:
        output_result(
            result.get("jobs", []),
            fmt=fmt,
            columns=["name", "type", "enabled", "running"],
        )


@job_group.command("add")
def job_add() -> None:
    """Open routes.toml in $EDITOR to add a job."""
    jobs_path = CONFIG_DIR / "jobs.toml"
    if not jobs_path.exists():
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text('# Add jobs here. See tlgr docs for format.\n# [[jobs]]\n# name = "my-job"\n# type = "autoforward"\n# source = "@channel"\n# destinations = ["@dest"]\n')
    editor = os.environ.get("EDITOR", "vi")
    os.execlp(editor, editor, str(jobs_path))


@job_group.command("remove")
@click.argument("name")
@click.pass_context
def job_remove(ctx: click.Context, name: str) -> None:
    """Remove a job by name."""
    result = ipc_request("POST", "/job/remove", body={"name": name})
    output_result(result, fmt=ctx.obj.get("fmt", "human"))


@job_group.command("enable")
@click.argument("name")
@click.pass_context
def job_enable(ctx: click.Context, name: str) -> None:
    """Enable a disabled job."""
    result = ipc_request("POST", "/job/enable", body={"name": name})
    output_result(result, fmt=ctx.obj.get("fmt", "human"))


@job_group.command("disable")
@click.argument("name")
@click.pass_context
def job_disable(ctx: click.Context, name: str) -> None:
    """Disable a job without removing it."""
    result = ipc_request("POST", "/job/disable", body={"name": name})
    output_result(result, fmt=ctx.obj.get("fmt", "human"))
