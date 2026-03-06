"""Config init and validate commands."""

from __future__ import annotations

import sys

import click

from tlgr.core.config import CONFIG_DIR, load_app_config, load_webhook_config
from tlgr.core.output import output_result
from tlgr.gateway.config import load_gateway_configs


@click.group("config")
def config_group() -> None:
    """Manage configuration files."""


@config_group.command("init")
@click.pass_context
def config_init(ctx: click.Context) -> None:
    """Create default configuration files."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    created = []

    config_path = CONFIG_DIR / "config.toml"
    if not config_path.exists():
        config_path.write_text(
            '[defaults]\ndrop_author = false\ndelete_after = false\noutput = "human"\n\n'
            '[accounts]\ndefault = ""\n\n'
            "[daemon]\nauto_start = true\n"
            'log_level = "info"\n'
        )
        created.append("config.toml")

    jobs_path = CONFIG_DIR / "jobs.yaml"
    if not jobs_path.exists():
        jobs_path.write_text(
            "# Gateway jobs configuration\n"
            "# See https://github.com/tlgrcli/tlgr for full reference.\n"
            "#\n"
            "# jobs:\n"
            "#   - name: example\n"
            "#     account: main\n"
            "#     filters:\n"
            "#       chat_type: private\n"
            "#     actions:\n"
            '#       - reply: "hello!"\n'
        )
        created.append("jobs.yaml")

    webhook_path = CONFIG_DIR / "webhook.toml"
    if not webhook_path.exists():
        webhook_path.write_text(
            "[webhook]\nenabled = false\n"
            'url = ""\ntoken = ""\n'
            'events = ["new_message"]\n\n'
            "[webhook.retry]\nenabled = true\nmax_attempts = 3\nbackoff_base = 2\n\n"
            "[webhook.filters]\nchats = []\n"
        )
        created.append("webhook.toml")

    fmt = ctx.obj.get("fmt", "human")
    if created:
        output_result(
            {"created": created, "path": str(CONFIG_DIR)},
            fmt=fmt,
        )
    else:
        output_result({"message": "All config files already exist", "path": str(CONFIG_DIR)}, fmt=fmt)


@config_group.command("validate")
@click.pass_context
def config_validate(ctx: click.Context) -> None:
    """Validate configuration files."""
    errors = []

    try:
        load_app_config()
    except Exception as e:
        errors.append(f"config.toml: {e}")

    try:
        configs = load_gateway_configs()
        for cfg in configs:
            if not cfg.name:
                errors.append("jobs.yaml: job missing 'name' field")
            if not cfg.actions:
                errors.append(f"jobs.yaml: job '{cfg.name}' has no actions")
            for ac in cfg.actions:
                from tlgr.actions import get_action
                if get_action(ac.name) is None:
                    errors.append(f"jobs.yaml: job '{cfg.name}' has unknown action '{ac.name}'")
    except Exception as e:
        errors.append(f"jobs.yaml: {e}")

    try:
        load_webhook_config()
    except Exception as e:
        errors.append(f"webhook.toml: {e}")

    fmt = ctx.obj.get("fmt", "human")
    if errors:
        output_result({"valid": False, "errors": errors}, fmt=fmt)
        sys.exit(1)
    else:
        output_result({"valid": True, "files": ["config.toml", "jobs.yaml", "webhook.toml"]}, fmt=fmt)
