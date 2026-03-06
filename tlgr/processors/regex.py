"""Regex-based processor."""

from __future__ import annotations

import re
from typing import Any

from tlgr.processors import register_processor


@register_processor("regex_replace")
def regex_replace(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    pattern = config.get("pattern")
    if not pattern:
        return text
    replacement = config.get("replacement", "")
    flags_str = config.get("flags", "")
    flags = 0
    if "i" in flags_str:
        flags |= re.IGNORECASE
    if "m" in flags_str:
        flags |= re.MULTILINE
    if "s" in flags_str:
        flags |= re.DOTALL
    return re.sub(pattern, replacement, text, flags=flags)
