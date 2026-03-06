"""Text-manipulation processors."""

from __future__ import annotations

import re
from typing import Any

from tlgr.processors import register_processor


@register_processor("replace_mentions")
def replace_mentions(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    replacement = config.get("replacement", "")
    pattern = config.get("pattern", r"@[a-zA-Z0-9_]+")
    return re.sub(pattern, replacement, text)


@register_processor("remove_links")
def remove_links(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    replacement = config.get("replacement", "")
    return re.sub(r"https?://[^\s<>\"']+", replacement, text)


@register_processor("remove_hashtags")
def remove_hashtags(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    replacement = config.get("replacement", "")
    return re.sub(r"#[a-zA-Z0-9_]+", replacement, text)


@register_processor("strip_formatting")
def strip_formatting(text: str, config: dict[str, Any] | None = None) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


@register_processor("add_prefix")
def add_prefix(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    prefix = config.get("prefix", "")
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + text


@register_processor("add_suffix")
def add_suffix(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    suffix = config.get("suffix", "")
    if suffix and not suffix.startswith("\n"):
        suffix = "\n" + suffix
    return text + suffix
