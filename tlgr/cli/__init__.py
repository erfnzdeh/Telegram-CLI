"""CLI entry point using Click with nested command groups."""

from __future__ import annotations

import sys

import click

from tlgr import __version__
from tlgr.core.errors import TlgrError, emit_error


class TlgrGroup(click.Group):
    """Custom group that handles errors and output formatting."""

    def invoke(self, ctx: click.Context) -> None:
        try:
            super().invoke(ctx)
        except TlgrError as e:
            use_json = ctx.params.get("json") or ctx.obj and ctx.obj.get("json")
            emit_error(e, use_json=bool(use_json))
            sys.exit(1)
        except (click.ClickException, click.exceptions.Exit, SystemExit):
            raise
        except Exception as e:
            use_json = ctx.params.get("json") or ctx.obj and ctx.obj.get("json")
            emit_error(e, use_json=bool(use_json))
            sys.exit(1)


@click.group(cls=TlgrGroup)
@click.version_option(__version__, prog_name="tlgr")
@click.option("--json", "use_json", is_flag=True, help="Output JSON to stdout.")
@click.option("--plain", "use_plain", is_flag=True, help="Output stable TSV for piping.")
@click.option("--account", "-a", default=None, help="Account alias to use.")
@click.pass_context
def cli(ctx: click.Context, use_json: bool, use_plain: bool, account: str | None) -> None:
    """tlgr — Full Telegram account control CLI."""
    ctx.ensure_object(dict)
    if use_json:
        ctx.obj["fmt"] = "json"
    elif use_plain:
        ctx.obj["fmt"] = "plain"
    else:
        ctx.obj["fmt"] = "human"
    ctx.obj["json"] = use_json
    ctx.obj["account"] = account or ""


# Import and register sub-groups
from tlgr.cli.account import account_group  # noqa: E402
from tlgr.cli.message import message_group  # noqa: E402
from tlgr.cli.chat import chat_group  # noqa: E402
from tlgr.cli.contact import contact_group  # noqa: E402
from tlgr.cli.profile import profile_group  # noqa: E402
from tlgr.cli.media import media_group  # noqa: E402
from tlgr.cli.daemon_cmd import daemon_group  # noqa: E402
from tlgr.cli.job import job_group  # noqa: E402
from tlgr.cli.config_cmd import config_group  # noqa: E402
from tlgr.cli.completion import completion_group  # noqa: E402

cli.add_command(account_group, "account")
cli.add_command(message_group, "message")
cli.add_command(chat_group, "chat")
cli.add_command(contact_group, "contact")
cli.add_command(profile_group, "profile")
cli.add_command(media_group, "media")
cli.add_command(daemon_group, "daemon")
cli.add_command(job_group, "job")
cli.add_command(config_group, "config")
cli.add_command(completion_group, "completion")
