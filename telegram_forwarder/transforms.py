"""Message transformation functions for forward-live.

This module provides transformation functions that can modify message content
before forwarding. Users can create custom transforms by following the pattern.

Example custom transform:
    
    def my_transform(text: str, **kwargs) -> str:
        # Modify text as needed
        return text.upper()
    
    # Register it
    TRANSFORMS['my_transform'] = my_transform
"""

import re
from typing import Callable, Dict, Optional, Any


# Type alias for transform functions
# A transform takes text and optional kwargs, returns transformed text
TransformFunc = Callable[[str, Dict[str, Any]], str]


# Registry of available transforms
TRANSFORMS: Dict[str, TransformFunc] = {}


def register_transform(name: str):
    """Decorator to register a transform function.
    
    Usage:
        @register_transform('my_transform')
        def my_transform(text: str, **kwargs) -> str:
            return text.upper()
    """
    def decorator(func: TransformFunc) -> TransformFunc:
        TRANSFORMS[name] = func
        return func
    return decorator


def get_transform(name: str) -> Optional[TransformFunc]:
    """Get a transform function by name.
    
    Args:
        name: Transform name
        
    Returns:
        Transform function or None if not found
    """
    return TRANSFORMS.get(name)


def list_transforms() -> list[str]:
    """List all available transform names."""
    return list(TRANSFORMS.keys())


# =============================================================================
# Built-in Transforms
# =============================================================================


@register_transform('replace_mentions')
def replace_mentions(text: str, config: Dict[str, Any] = None) -> str:
    """Replace @mentions with a custom replacement.
    
    This transform finds all @username mentions and replaces them.
    
    Config options:
        replacement: What to replace mentions with (default: '')
        pattern: Custom regex pattern (default: @[a-zA-Z0-9_]+)
    
    Examples:
        # Remove all mentions
        replace_mentions("Check @channel for updates") 
        # -> "Check  for updates"
        
        # Replace with custom text
        replace_mentions("Follow @channel", {'replacement': '[removed]'})
        # -> "Follow [removed]"
    """
    if config is None:
        config = {}
    
    replacement = config.get('replacement', '')
    pattern = config.get('pattern', r'@[a-zA-Z0-9_]+')
    
    return re.sub(pattern, replacement, text)


@register_transform('remove_links')
def remove_links(text: str, config: Dict[str, Any] = None) -> str:
    """Remove URLs from text.
    
    Config options:
        replacement: What to replace links with (default: '')
    """
    if config is None:
        config = {}
    
    replacement = config.get('replacement', '')
    
    # Match http(s) URLs and t.me links
    url_pattern = r'https?://[^\s<>"\']+'
    
    return re.sub(url_pattern, replacement, text)


@register_transform('remove_hashtags')
def remove_hashtags(text: str, config: Dict[str, Any] = None) -> str:
    """Remove #hashtags from text.
    
    Config options:
        replacement: What to replace hashtags with (default: '')
    """
    if config is None:
        config = {}
    
    replacement = config.get('replacement', '')
    pattern = r'#[a-zA-Z0-9_]+'
    
    return re.sub(pattern, replacement, text)


@register_transform('strip_formatting')
def strip_formatting(text: str, config: Dict[str, Any] = None) -> str:
    """Clean up extra whitespace and newlines.
    
    Useful to run after other transforms that may leave gaps.
    """
    # Replace multiple spaces with single space
    text = re.sub(r'[ \t]+', ' ', text)
    # Replace multiple newlines with double newline (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Strip leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split('\n')]
    return '\n'.join(lines).strip()


@register_transform('add_prefix')
def add_prefix(text: str, config: Dict[str, Any] = None) -> str:
    """Add a prefix to the message.
    
    Config options:
        prefix: Text to add at the beginning (default: '')
    """
    if config is None:
        config = {}
    
    prefix = config.get('prefix', '')
    if prefix and not prefix.endswith('\n'):
        prefix += '\n'
    
    return prefix + text


@register_transform('add_suffix')
def add_suffix(text: str, config: Dict[str, Any] = None) -> str:
    """Add a suffix to the message.
    
    Config options:
        suffix: Text to add at the end (default: '')
    """
    if config is None:
        config = {}
    
    suffix = config.get('suffix', '')
    if suffix and not suffix.startswith('\n'):
        suffix = '\n' + suffix
    
    return text + suffix


@register_transform('regex_replace')
def regex_replace(text: str, config: Dict[str, Any] = None) -> str:
    """Apply custom regex replacement.
    
    Config options:
        pattern: Regex pattern to match (required)
        replacement: Replacement string (default: '')
        flags: Regex flags string like 'i' for case-insensitive (default: '')
    
    Example:
        regex_replace(text, {
            'pattern': r'\\bfoo\\b',
            'replacement': 'bar',
            'flags': 'i'
        })
    """
    if config is None:
        config = {}
    
    pattern = config.get('pattern')
    if not pattern:
        return text
    
    replacement = config.get('replacement', '')
    flags_str = config.get('flags', '')
    
    # Parse flags
    flags = 0
    if 'i' in flags_str:
        flags |= re.IGNORECASE
    if 'm' in flags_str:
        flags |= re.MULTILINE
    if 's' in flags_str:
        flags |= re.DOTALL
    
    return re.sub(pattern, replacement, text, flags=flags)


# =============================================================================
# Transform Chain
# =============================================================================


class TransformChain:
    """Chain multiple transforms together.
    
    Usage:
        chain = TransformChain()
        chain.add('replace_mentions', {'replacement': ''})
        chain.add('strip_formatting')
        
        result = chain.apply("Check @channel for updates")
    """
    
    def __init__(self):
        self.transforms: list[tuple[TransformFunc, Dict[str, Any]]] = []
    
    def add(self, name: str, config: Dict[str, Any] = None) -> 'TransformChain':
        """Add a transform to the chain.
        
        Args:
            name: Transform name
            config: Optional config for this transform
            
        Returns:
            Self for chaining
            
        Raises:
            ValueError: If transform not found
        """
        func = get_transform(name)
        if func is None:
            raise ValueError(f"Unknown transform: {name}")
        
        self.transforms.append((func, config or {}))
        return self
    
    def apply(self, text: str) -> str:
        """Apply all transforms in order.
        
        Args:
            text: Input text
            
        Returns:
            Transformed text
        """
        result = text
        for func, config in self.transforms:
            result = func(result, config)
        return result
    
    def __len__(self) -> int:
        return len(self.transforms)


def create_chain_from_spec(spec: str) -> TransformChain:
    """Create a transform chain from a specification string.
    
    Format: "transform1,transform2:key=value,transform3"
    
    Examples:
        "replace_mentions"
        "replace_mentions,strip_formatting"
        "replace_mentions:replacement=[redacted],strip_formatting"
        "regex_replace:pattern=@\\w+:replacement="
    
    Args:
        spec: Specification string
        
    Returns:
        TransformChain
    """
    chain = TransformChain()
    
    if not spec:
        return chain
    
    # Split by comma, but respect escaped commas
    parts = re.split(r'(?<!\\),', spec)
    
    for part in parts:
        part = part.strip().replace('\\,', ',')
        if not part:
            continue
        
        # Check for config (name:key=value:key2=value2)
        if ':' in part:
            segments = part.split(':')
            name = segments[0]
            config = {}
            
            for segment in segments[1:]:
                if '=' in segment:
                    key, value = segment.split('=', 1)
                    config[key] = value
            
            chain.add(name, config)
        else:
            chain.add(part)
    
    return chain
