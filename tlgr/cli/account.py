"""Account management commands — these run WITHOUT the daemon."""

from __future__ import annotations

import json
import sys

import click

from tlgr.core.accounts import AccountManager
from tlgr.core.config import CONFIG_DIR
from tlgr.core.output import emit


def _get_mgr() -> AccountManager:
    return AccountManager(CONFIG_DIR)


@click.group("account")
def account_group() -> None:
    """Manage Telegram accounts."""


@account_group.command("add")
@click.argument("phone")
@click.option("--alias", default=None, help="Alias for this account.")
@click.pass_context
def account_add(ctx: click.Context, phone: str, alias: str | None) -> None:
    """Authenticate a new Telegram account (interactive — requires human input)."""
    import asyncio
    from tlgr.core.client import ClientWrapper

    mgr = _get_mgr()
    if alias is None:
        alias = phone.replace("+", "").replace(" ", "")[-6:]
    account = mgr.add_account(alias)

    api_id_str = input("Telegram API ID (from my.telegram.org): ").strip()
    api_hash = input("Telegram API Hash: ").strip()
    api_id = int(api_id_str)
    mgr.save_credentials(api_id, api_hash, alias)

    session_path = mgr.get_session_path(alias)
    client = ClientWrapper(session_path, api_id, api_hash)

    async def _login():
        await client.connect()
        me = await client.login(phone=phone)
        mgr.update_account(
            alias,
            phone=me.phone,
            username=me.username,
            first_name=me.first_name,
            user_id=me.id,
        )
        await client.disconnect()
        return me

    me = asyncio.run(_login())
    emit(
        ctx.obj,
        {"alias": alias, "user_id": me.id, "name": me.first_name, "username": me.username},
        columns=["alias", "user_id", "name", "username"],
    )


@account_group.command("list")
@click.pass_context
def account_list(ctx: click.Context) -> None:
    """List all registered accounts."""
    mgr = _get_mgr()
    active = mgr.get_active()
    accounts = mgr.list_accounts()
    rows = []
    for a in accounts:
        rows.append({
            "alias": ("* " + a.alias) if a.alias == active else ("  " + a.alias),
            "user_id": a.user_id or "",
            "name": a.display_name(),
            "phone": a.phone or "",
        })
    if not rows:
        rows = [{"alias": "(no accounts)", "user_id": "", "name": "", "phone": ""}]
    emit(ctx.obj, rows, columns=["alias", "user_id", "name", "phone"])


@account_group.command("switch")
@click.argument("alias")
@click.pass_context
def account_switch(ctx: click.Context, alias: str) -> None:
    """Set the default account."""
    mgr = _get_mgr()
    if not mgr.set_active(alias):
        click.echo(f"Account '{alias}' not found", err=True)
        sys.exit(1)
    emit(ctx.obj, {"active": alias}, columns=["active"])


@account_group.command("remove")
@click.argument("alias")
@click.confirmation_option(prompt="Remove this account and all its data?")
@click.pass_context
def account_remove(ctx: click.Context, alias: str) -> None:
    """Remove an account and its session data."""
    mgr = _get_mgr()
    if not mgr.remove_account(alias):
        click.echo(f"Account '{alias}' not found", err=True)
        sys.exit(1)
    emit(ctx.obj, {"removed": alias}, columns=["removed"])


@account_group.command("rename")
@click.argument("old")
@click.argument("new")
@click.pass_context
def account_rename(ctx: click.Context, old: str, new: str) -> None:
    """Rename an account alias."""
    mgr = _get_mgr()
    if not mgr.rename_account(old, new):
        click.echo(f"Account '{old}' not found", err=True)
        sys.exit(1)
    emit(ctx.obj, {"old": old, "new": new}, columns=["old", "new"])


@account_group.command("info")
@click.argument("alias", required=False)
@click.pass_context
def account_info(ctx: click.Context, alias: str | None) -> None:
    """Show account details."""
    mgr = _get_mgr()
    if alias is None:
        alias = mgr.get_active()
    if alias is None:
        click.echo("No active account", err=True)
        sys.exit(1)
    acct = mgr.get_account(alias)
    if acct is None:
        click.echo(f"Account '{alias}' not found", err=True)
        sys.exit(1)
    emit(ctx.obj, acct.to_dict(), columns=["alias", "user_id", "username", "first_name", "phone", "created_at"])


@account_group.command("sync")
@click.argument("alias", required=False)
@click.pass_context
def account_sync(ctx: click.Context, alias: str | None) -> None:
    """Sync stored account info from the live Telegram profile."""
    from tlgr.ipc_client import ipc_request

    mgr = _get_mgr()
    if alias is None:
        alias = mgr.get_active()
    if alias is None:
        click.echo("No active account", err=True)
        sys.exit(1)
    acct = mgr.get_account(alias)
    if acct is None:
        click.echo(f"Account '{alias}' not found", err=True)
        sys.exit(1)

    profile = ipc_request("GET", f"/profile/get?account={alias}")
    mgr.update_account(
        alias,
        phone=profile.get("phone"),
        username=profile.get("username"),
        first_name=profile.get("first_name"),
        user_id=profile.get("id"),
    )
    updated = mgr.get_account(alias)
    emit(ctx.obj, updated.to_dict(), columns=["alias", "user_id", "username", "first_name", "phone"])
