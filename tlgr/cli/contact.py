"""Contact management commands."""

from __future__ import annotations

import click

from tlgr.core.output import output_result
from tlgr.ipc_client import ipc_request


@click.group("contact")
def contact_group() -> None:
    """Manage contacts."""


@contact_group.command("list")
@click.option("--account", "-a", default=None)
@click.pass_context
def contact_list(ctx: click.Context, account: str | None) -> None:
    """List all contacts."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("GET", f"/contact/list?account={acct}")
    fmt = ctx.obj.get("fmt", "human")
    if fmt == "json":
        output_result(result, fmt=fmt)
    else:
        output_result(
            result.get("contacts", []),
            fmt=fmt,
            columns=["id", "name", "username", "phone"],
        )


@contact_group.command("add")
@click.argument("phone")
@click.argument("name", required=False, default="")
@click.option("--account", "-a", default=None)
@click.pass_context
def contact_add(ctx: click.Context, phone: str, name: str, account: str | None) -> None:
    """Add a contact by phone number."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("POST", "/contact/add", body={"phone": phone, "name": name, "account": acct})
    output_result(result, fmt=ctx.obj.get("fmt", "human"))


@contact_group.command("remove")
@click.argument("user")
@click.option("--account", "-a", default=None)
@click.pass_context
def contact_remove(ctx: click.Context, user: str, account: str | None) -> None:
    """Remove a contact."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("POST", "/contact/remove", body={"user": user, "account": acct})
    output_result(result, fmt=ctx.obj.get("fmt", "human"))


@contact_group.command("search")
@click.argument("query")
@click.option("--account", "-a", default=None)
@click.pass_context
def contact_search(ctx: click.Context, query: str, account: str | None) -> None:
    """Search contacts."""
    acct = account or ctx.obj.get("account", "")
    result = ipc_request("GET", f"/contact/search?query={query}&account={acct}")
    fmt = ctx.obj.get("fmt", "human")
    if fmt == "json":
        output_result(result, fmt=fmt)
    else:
        output_result(result.get("contacts", []), fmt=fmt, columns=["id", "name", "username"])
