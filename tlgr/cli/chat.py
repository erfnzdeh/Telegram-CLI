"""Chat management commands."""

from __future__ import annotations

import click

from tlgr.core.output import output_result
from tlgr.ipc_client import ipc_request


@click.group("chat")
def chat_group() -> None:
    """List, create, and manage chats."""


@chat_group.command("list")
@click.option("--type", "chat_type", default=None, help="Filter: user, group, channel, bot.")
@click.option("--search", "-s", default=None, help="Filter by name.")
@click.option("--limit", "-n", type=int, default=None)
@click.option("--account", "-a", default=None)
@click.pass_context
def chat_list(
    ctx: click.Context,
    chat_type: str | None,
    search: str | None,
    limit: int | None,
    account: str | None,
) -> None:
    """List all chats/dialogs."""
    acct = account or ctx.obj.get("account", "")
    params = f"account={acct}"
    if chat_type:
        params += f"&type={chat_type}"
    if search:
        params += f"&search={search}"
    if limit:
        params += f"&limit={limit}"
    result = ipc_request("GET", f"/chat/list?{params}")
    fmt = ctx.obj.get("fmt", "human")
    if fmt == "json":
        output_result(result, fmt=fmt)
    else:
        output_result(
            result.get("chats", []),
            fmt=fmt,
            columns=["id", "name", "type", "username"],
            headers=["ID", "Name", "Type", "Username"],
        )


@chat_group.command("get")
@click.argument("chat")
@click.option("--account", "-a", default=None)
@click.pass_context
def chat_get(ctx: click.Context, chat: str, account: str | None) -> None:
    """Get chat info (members, permissions, etc.)."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("GET", f"/chat/get?chat={chat}&account={acct}")
    output_result(result, fmt=ctx.obj.get("fmt", "human"))


@chat_group.command("create")
@click.argument("name")
@click.option("--type", "chat_type", default="group", type=click.Choice(["group", "channel"]))
@click.option("--members", multiple=True, help="Users to add.")
@click.option("--account", "-a", default=None)
@click.pass_context
def chat_create(
    ctx: click.Context,
    name: str,
    chat_type: str,
    members: tuple[str, ...],
    account: str | None,
) -> None:
    """Create a new group or channel."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("POST", "/chat/create", body={
        "name": name, "type": chat_type, "members": list(members), "account": acct,
    })
    output_result(result, fmt=ctx.obj.get("fmt", "human"))


@chat_group.command("archive")
@click.argument("chat")
@click.option("--account", "-a", default=None)
@click.pass_context
def chat_archive(ctx: click.Context, chat: str, account: str | None) -> None:
    """Archive a chat."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("POST", "/chat/archive", body={"chat": chat, "account": acct})
    output_result(result, fmt=ctx.obj.get("fmt", "human"))


@chat_group.command("mute")
@click.argument("chat")
@click.argument("duration", type=int, required=False, default=None)
@click.option("--account", "-a", default=None)
@click.pass_context
def chat_mute(ctx: click.Context, chat: str, duration: int | None, account: str | None) -> None:
    """Mute a chat. Duration in seconds (omit for permanent)."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("POST", "/chat/mute", body={"chat": chat, "duration": duration, "account": acct})
    output_result(result, fmt=ctx.obj.get("fmt", "human"))


@chat_group.command("leave")
@click.argument("chat")
@click.option("--account", "-a", default=None)
@click.pass_context
def chat_leave(ctx: click.Context, chat: str, account: str | None) -> None:
    """Leave a chat or group."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("POST", "/chat/leave", body={"chat": chat, "account": acct})
    output_result(result, fmt=ctx.obj.get("fmt", "human"))
