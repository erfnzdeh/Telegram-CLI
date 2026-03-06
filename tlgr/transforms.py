"""Message transformation functions.

Registry-based transforms plus inline TOML-defined regex transforms.
"""

from __future__ import annotations

import re
from typing import Any, Callable

TransformFunc = Callable[[str, dict[str, Any]], str]

TRANSFORMS: dict[str, TransformFunc] = {}


def register_transform(name: str):
    def decorator(func: TransformFunc) -> TransformFunc:
        TRANSFORMS[name] = func
        return func
    return decorator


def get_transform(name: str) -> TransformFunc | None:
    return TRANSFORMS.get(name)


def list_transforms() -> list[str]:
    return list(TRANSFORMS.keys())


# ---------------------------------------------------------------------------
# Built-in transforms
# ---------------------------------------------------------------------------

@register_transform("replace_mentions")
def replace_mentions(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    replacement = config.get("replacement", "")
    pattern = config.get("pattern", r"@[a-zA-Z0-9_]+")
    return re.sub(pattern, replacement, text)


@register_transform("remove_links")
def remove_links(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    replacement = config.get("replacement", "")
    return re.sub(r"https?://[^\s<>\"']+", replacement, text)


@register_transform("remove_hashtags")
def remove_hashtags(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    replacement = config.get("replacement", "")
    return re.sub(r"#[a-zA-Z0-9_]+", replacement, text)


@register_transform("strip_formatting")
def strip_formatting(text: str, config: dict[str, Any] | None = None) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


@register_transform("add_prefix")
def add_prefix(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    prefix = config.get("prefix", "")
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + text


@register_transform("add_suffix")
def add_suffix(text: str, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    suffix = config.get("suffix", "")
    if suffix and not suffix.startswith("\n"):
        suffix = "\n" + suffix
    return text + suffix


@register_transform("regex_replace")
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


# ---------------------------------------------------------------------------
# Transform chain
# ---------------------------------------------------------------------------

class TransformChain:
    def __init__(self):
        self.transforms: list[tuple[TransformFunc, dict[str, Any]]] = []

    def add(self, name: str, config: dict[str, Any] | None = None) -> TransformChain:
        func = get_transform(name)
        if func is None:
            raise ValueError(f"Unknown transform: {name}")
        self.transforms.append((func, config or {}))
        return self

    def add_inline(self, pattern: str, replacement: str = "", flags: str = "") -> TransformChain:
        """Add an inline regex transform (from TOML config)."""
        func = get_transform("regex_replace")
        assert func is not None
        self.transforms.append((func, {"pattern": pattern, "replacement": replacement, "flags": flags}))
        return self

    def apply(self, text: str) -> str:
        result = text
        for func, config in self.transforms:
            result = func(result, config)
        return result

    def __len__(self) -> int:
        return len(self.transforms)


def create_chain_from_spec(spec: str) -> TransformChain:
    """Create from spec string like 'replace_mentions,strip_formatting'."""
    chain = TransformChain()
    if not spec:
        return chain
    parts = re.split(r"(?<!\\),", spec)
    for part in parts:
        part = part.strip().replace("\\,", ",")
        if not part:
            continue
        if ":" in part:
            segments = part.split(":")
            name = segments[0]
            config: dict[str, Any] = {}
            for segment in segments[1:]:
                if "=" in segment:
                    key, value = segment.split("=", 1)
                    config[key] = value
            chain.add(name, config)
        else:
            chain.add(part)
    return chain


def create_chain_from_config(items: list) -> TransformChain:
    """Create from a list of config items (strings or TransformInline objects)."""
    from tlgr.core.config import TransformInline

    chain = TransformChain()
    for item in items:
        if isinstance(item, str):
            if ":" in item:
                segments = item.split(":")
                name = segments[0]
                config: dict[str, Any] = {}
                for segment in segments[1:]:
                    if "=" in segment:
                        k, v = segment.split("=", 1)
                        config[k] = v
                chain.add(name, config)
            else:
                chain.add(item)
        elif isinstance(item, TransformInline):
            chain.add_inline(item.pattern, item.replacement, item.flags)
        elif isinstance(item, dict):
            chain.add_inline(item.get("pattern", ""), item.get("replacement", ""), item.get("flags", ""))
    return chain
