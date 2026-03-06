"""Message commands — send, list, get, delete, search, pin, react."""

from __future__ import annotations

import sys

import click

from tlgr.core.output import emit
from tlgr.ipc_client import ipc_request


@click.group("message")
def message_group() -> None:
    """Send, read, search, and manage messages."""


@message_group.command("send")
@click.argument("chat")
@click.argument("text", required=False, default="")
@click.option("--file", "file_path", default=None, help="File to attach.")
@click.option("--caption", default=None, help="Caption for file.")
@click.option("--reply-to", type=int, default=None, help="Reply to message ID.")
@click.option("--silent", is_flag=True, help="Send without notification.")
@click.option("--account", "-a", default=None)
@click.pass_context
def message_send(
    ctx: click.Context,
    chat: str,
    text: str,
    file_path: str | None,
    caption: str | None,
    reply_to: int | None,
    silent: bool,
    account: str | None,
) -> None:
    """Send a message to a chat."""
    acct = account or ctx.obj.get("account", "")
    body = {
        "chat": chat,
        "text": text,
        "account": acct,
        "silent": silent,
    }
    if file_path:
        body["file"] = file_path
    if caption:
        body["caption"] = caption
    if reply_to:
        body["reply_to"] = reply_to
    if ctx.obj.get("dry_run"):
        emit(ctx.obj, {"dry_run": True, "op": "message.send", **body})
        return
    result = ipc_request("POST", "/message/send", body=body)
    emit(ctx.obj, result, columns=["id", "chat_id", "date"])


@message_group.command("list")
@click.argument("chat")
@click.option("--limit", "-n", type=int, default=20)
@click.option("--offset-id", type=int, default=0)
@click.option("--sender", is_flag=True, help="Include sender info.")
@click.option("--media", is_flag=True, help="Include media metadata.")
@click.option("--reactions", is_flag=True, help="Include reactions.")
@click.option("--entities", is_flag=True, help="Include entities.")
@click.option("--account", "-a", default=None)
@click.pass_context
def message_list(
    ctx: click.Context,
    chat: str,
    limit: int,
    offset_id: int,
    sender: bool,
    media: bool,
    reactions: bool,
    entities: bool,
    account: str | None,
) -> None:
    """List recent messages from a chat."""
    acct = account or ctx.obj.get("account", "")
    params = f"chat={chat}&limit={limit}&offset_id={offset_id}&account={acct}"
    if sender:
        params += "&sender=1"
    if media:
        params += "&media=1"
    if reactions:
        params += "&reactions=1"
    if entities:
        params += "&entities=1"
    result = ipc_request("GET", f"/message/list?{params}")
    fmt = ctx.obj.get("fmt", "human")
    if fmt == "json":
        emit(ctx.obj, result)
    else:
        emit(ctx.obj, result.get("messages", []), columns=["id", "date", "text"])


@message_group.command("get")
@click.argument("chat")
@click.argument("msg_id", type=int)
@click.option("--account", "-a", default=None)
@click.pass_context
def message_get(ctx: click.Context, chat: str, msg_id: int, account: str | None) -> None:
    """Get a single message with full metadata."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("GET", f"/message/get?chat={chat}&msg_id={msg_id}&account={acct}")
    emit(ctx.obj, result)


@message_group.command("delete")
@click.argument("chat")
@click.argument("msg_ids", nargs=-1, type=int, required=True)
@click.option("--account", "-a", default=None)
@click.pass_context
def message_delete(ctx: click.Context, chat: str, msg_ids: tuple[int, ...], account: str | None) -> None:
    """Delete messages from a chat."""
    acct = account or ctx.obj.get("account", "")
    if ctx.obj.get("dry_run"):
        emit(ctx.obj, {"dry_run": True, "op": "message.delete", "chat": chat, "msg_ids": list(msg_ids)})
        return
    result = ipc_request("POST", "/message/delete", body={
        "chat": chat, "msg_ids": list(msg_ids), "account": acct,
    })
    emit(ctx.obj, result, columns=["deleted"])


@message_group.command("search")
@click.argument("chat")
@click.argument("query")
@click.option("--local", is_flag=True, help="Client-side regex search.")
@click.option("--regex", default=None, help="Regex pattern (with --local).")
@click.option("--limit", "-n", type=int, default=20)
@click.option("--account", "-a", default=None)
@click.pass_context
def message_search(
    ctx: click.Context,
    chat: str,
    query: str,
    local: bool,
    regex: str | None,
    limit: int,
    account: str | None,
) -> None:
    """Search messages in a chat."""
    acct = account or ctx.obj.get("account", "")
    params = f"chat={chat}&query={query}&limit={limit}&account={acct}"
    if local:
        params += "&local=1"
    if regex:
        params += f"&regex={regex}"
    result = ipc_request("GET", f"/message/search?{params}")
    fmt = ctx.obj.get("fmt", "human")
    if fmt == "json":
        emit(ctx.obj, result)
    else:
        emit(ctx.obj, result.get("messages", []), columns=["id", "date", "text"])


@message_group.command("pin")
@click.argument("chat")
@click.argument("msg_id", type=int)
@click.option("--account", "-a", default=None)
@click.pass_context
def message_pin(ctx: click.Context, chat: str, msg_id: int, account: str | None) -> None:
    """Pin a message in a chat."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("POST", "/message/pin", body={"chat": chat, "msg_id": msg_id, "account": acct})
    emit(ctx.obj, result)


@message_group.command("react")
@click.argument("chat")
@click.argument("msg_id", type=int)
@click.argument("emoji")
@click.option("--account", "-a", default=None)
@click.pass_context
def message_react(ctx: click.Context, chat: str, msg_id: int, emoji: str, account: str | None) -> None:
    """React to a message with an emoji."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("POST", "/message/react", body={"chat": chat, "msg_id": msg_id, "emoji": emoji, "account": acct})
    emit(ctx.obj, result)
