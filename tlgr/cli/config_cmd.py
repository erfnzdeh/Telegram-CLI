"""Config management commands — init, validate, path, get, set, list, unset."""

from __future__ import annotations

import sys
from typing import Any

import click

from tlgr.core.config import CONFIG_DIR, load_app_config, load_webhook_config, _load_toml, _save_toml
from tlgr.core.output import output_result
from tlgr.gateway.config import load_gateway_configs

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

_CONFIG_FILE = CONFIG_DIR / "config.toml"

# Documented config keys with their TOML section + key + description.
_KNOWN_KEYS: dict[str, tuple[str, str, str]] = {
    "output": ("defaults", "output", "Default output mode: human | json | plain"),
    "drop_author": ("defaults", "drop_author", "Strip author on forwarded messages"),
    "delete_after": ("defaults", "delete_after", "Delete source after forwarding"),
    "default_account": ("accounts", "default", "Default account alias"),
    "auto_start": ("daemon", "auto_start", "Auto-start daemon on CLI use"),
    "log_level": ("daemon", "log_level", "Daemon log level: debug | info | warning | error"),
}


def _coerce_value(raw: str) -> Any:
    """Best-effort coerce a CLI string to a native TOML type."""
    low = raw.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


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
        output_result({"created": created, "path": str(CONFIG_DIR)}, fmt=fmt)
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


@config_group.command("path")
@click.pass_context
def config_path(ctx: click.Context) -> None:
    """Print the configuration directory path."""
    fmt = ctx.obj.get("fmt", "human") if ctx.obj else "human"
    output_result({"path": str(CONFIG_DIR)}, fmt=fmt, columns=["path"])


@config_group.command("keys")
@click.pass_context
def config_keys(ctx: click.Context) -> None:
    """List all known configuration keys."""
    fmt = ctx.obj.get("fmt", "human") if ctx.obj else "human"
    if fmt == "json":
        rows = {k: {"section": sec, "key": key, "description": desc} for k, (sec, key, desc) in _KNOWN_KEYS.items()}
        output_result({"keys": rows}, fmt=fmt)
    else:
        rows = [{"key": k, "section": sec, "description": desc} for k, (sec, _, desc) in _KNOWN_KEYS.items()]
        output_result(rows, fmt=fmt, columns=["key", "section", "description"])


@config_group.command("list")
@click.pass_context
def config_list(ctx: click.Context) -> None:
    """List all config values."""
    fmt = ctx.obj.get("fmt", "human") if ctx.obj else "human"
    raw = _load_toml(_CONFIG_FILE)
    if fmt == "json":
        output_result(raw, fmt=fmt)
    else:
        rows = []
        for key_name, (section, field, _desc) in _KNOWN_KEYS.items():
            val = raw.get(section, {}).get(field, "")
            rows.append({"key": key_name, "value": str(val)})
        output_result(rows, fmt=fmt, columns=["key", "value"])


@config_group.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx: click.Context, key: str) -> None:
    """Get a config value by key."""
    fmt = ctx.obj.get("fmt", "human") if ctx.obj else "human"
    if key not in _KNOWN_KEYS:
        click.echo(f"Error: unknown config key {key!r}. Run: tlgr config keys", err=True)
        sys.exit(2)
    section, field, _ = _KNOWN_KEYS[key]
    raw = _load_toml(_CONFIG_FILE)
    val = raw.get(section, {}).get(field)
    output_result({"key": key, "value": val}, fmt=fmt, columns=["key", "value"])


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Set a config value."""
    fmt = ctx.obj.get("fmt", "human") if ctx.obj else "human"
    if key not in _KNOWN_KEYS:
        click.echo(f"Error: unknown config key {key!r}. Run: tlgr config keys", err=True)
        sys.exit(2)
    section, field, _ = _KNOWN_KEYS[key]
    raw = _load_toml(_CONFIG_FILE)
    if section not in raw:
        raw[section] = {}
    raw[section][field] = _coerce_value(value)
    _save_toml(_CONFIG_FILE, raw)
    output_result({"key": key, "value": raw[section][field], "updated": True}, fmt=fmt)


@config_group.command("unset")
@click.argument("key")
@click.pass_context
def config_unset(ctx: click.Context, key: str) -> None:
    """Remove a config key (reset to default)."""
    fmt = ctx.obj.get("fmt", "human") if ctx.obj else "human"
    if key not in _KNOWN_KEYS:
        click.echo(f"Error: unknown config key {key!r}. Run: tlgr config keys", err=True)
        sys.exit(2)
    section, field, _ = _KNOWN_KEYS[key]
    raw = _load_toml(_CONFIG_FILE)
    removed = False
    if section in raw and field in raw[section]:
        del raw[section][field]
        if not raw[section]:
            del raw[section]
        removed = True
        _save_toml(_CONFIG_FILE, raw)
    output_result({"key": key, "removed": removed}, fmt=fmt)
