"""Agent-friendly helper commands."""

from __future__ import annotations

import json
import sys

import click

from tlgr.core.errors import EXIT_CODE_MAP


@click.group("agent")
def agent_group() -> None:
    """Agent-friendly helpers (schema, exit codes)."""


@agent_group.command("exit-codes")
@click.pass_context
def agent_exit_codes(ctx: click.Context) -> None:
    """Print stable exit codes for automation."""
    fmt = ctx.obj.get("fmt", "human") if ctx.obj else "human"

    if fmt == "json":
        json.dump({"exit_codes": EXIT_CODE_MAP}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return

    rows = sorted(
        ((info["code"], name, info["description"]) for name, info in EXIT_CODE_MAP.items()),
        key=lambda r: r[0],
    )
    seen: set[int] = set()
    click.echo(f"{'CODE':<6} {'NAME':<22} DESCRIPTION")
    for code, name, desc in rows:
        marker = "" if code not in seen else " (alias)"
        seen.add(code)
        click.echo(f"{code:<6} {name:<22} {desc}{marker}")
