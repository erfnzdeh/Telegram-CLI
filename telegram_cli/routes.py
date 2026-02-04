"""Route configuration for multi-source forwarding with per-destination transforms.

This module handles YAML-based route configuration that allows:
- Multiple source → destination mappings
- Per-destination transforms and filters
- Named routes for selective execution
- Global defaults with per-route overrides
"""

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union

from .transforms import TransformChain, get_transform
from .filters import MessageFilter, parse_message_types, parse_date, parse_size


@dataclass
class DestinationConfig:
    """Configuration for a single destination."""
    
    chat: str  # Chat ID or @username
    transforms: Optional[TransformChain] = None
    filters: Optional[MessageFilter] = None
    
    def __repr__(self):
        return f"DestinationConfig(chat={self.chat})"


@dataclass
class RouteConfig:
    """Configuration for a single forwarding route."""
    
    name: str
    source: str  # Chat ID or @username
    destinations: List[DestinationConfig]
    drop_author: bool = False
    delete_after: bool = False
    
    # Route-level transforms/filters (applied to all destinations without their own)
    transforms: Optional[TransformChain] = None
    filters: Optional[MessageFilter] = None
    
    def __repr__(self):
        dest_str = ", ".join(d.chat for d in self.destinations)
        return f"RouteConfig(name={self.name}, source={self.source}, destinations=[{dest_str}])"


@dataclass
class RoutesConfig:
    """Top-level routes configuration."""
    
    routes: List[RouteConfig] = field(default_factory=list)
    
    # Global defaults
    defaults: Dict[str, Any] = field(default_factory=dict)
    
    def get_route(self, name: str) -> Optional[RouteConfig]:
        """Get a route by name."""
        for route in self.routes:
            if route.name == name:
                return route
        return None
    
    def get_routes(self, names: Optional[List[str]] = None) -> List[RouteConfig]:
        """Get routes by names, or all routes if names is None."""
        if names is None:
            return self.routes
        return [r for r in self.routes if r.name in names]


def _parse_transforms(transforms_config: Any) -> Optional[TransformChain]:
    """Parse transforms configuration into a TransformChain.
    
    Supports formats:
        - String: "replace_mentions"
        - List of strings: ["replace_mentions", "strip_formatting"]
        - List of dicts: [{"replace_mentions": {"replacement": "[user]"}}]
        - Mixed: ["replace_mentions", {"regex_replace": {"pattern": "..."}}]
    """
    if transforms_config is None:
        return None
    
    chain = TransformChain()
    
    # Handle string format
    if isinstance(transforms_config, str):
        chain.add(transforms_config)
        return chain
    
    # Handle list format
    if isinstance(transforms_config, list):
        for item in transforms_config:
            if isinstance(item, str):
                # Simple transform name
                chain.add(item)
            elif isinstance(item, dict):
                # Transform with config: {"name": {config}}
                for name, config in item.items():
                    if config is None:
                        config = {}
                    chain.add(name, config)
            else:
                raise ValueError(f"Invalid transform format: {item}")
        return chain
    
    raise ValueError(f"Invalid transforms format: {transforms_config}")


def _parse_filters(filters_config: Dict[str, Any]) -> Optional[MessageFilter]:
    """Parse filters configuration into a MessageFilter."""
    if not filters_config:
        return None
    
    filter_kwargs = {}
    
    # Type filters
    if 'types' in filters_config:
        types_val = filters_config['types']
        if isinstance(types_val, str):
            filter_kwargs['types'] = parse_message_types(types_val)
        elif isinstance(types_val, list):
            filter_kwargs['types'] = parse_message_types(','.join(types_val))
    
    if 'exclude_types' in filters_config:
        types_val = filters_config['exclude_types']
        if isinstance(types_val, str):
            filter_kwargs['exclude_types'] = parse_message_types(types_val)
        elif isinstance(types_val, list):
            filter_kwargs['exclude_types'] = parse_message_types(','.join(types_val))
    
    # Date filters
    if 'after' in filters_config:
        filter_kwargs['after'] = parse_date(filters_config['after'])
    
    if 'before' in filters_config:
        filter_kwargs['before'] = parse_date(filters_config['before'])
    
    # Content filters
    if 'contains' in filters_config:
        val = filters_config['contains']
        filter_kwargs['contains'] = [val] if isinstance(val, str) else val
    
    if 'contains_any' in filters_config:
        val = filters_config['contains_any']
        filter_kwargs['contains_any'] = [val] if isinstance(val, str) else val
    
    if 'excludes' in filters_config:
        val = filters_config['excludes']
        filter_kwargs['excludes'] = [val] if isinstance(val, str) else val
    
    if 'regex' in filters_config:
        filter_kwargs['regex'] = filters_config['regex']
    
    # Media filters
    if 'media_only' in filters_config and filters_config['media_only']:
        filter_kwargs['has_media'] = True
    elif 'text_only' in filters_config and filters_config['text_only']:
        filter_kwargs['has_media'] = False
    
    if 'has_media' in filters_config:
        filter_kwargs['has_media'] = filters_config['has_media']
    
    if 'min_size' in filters_config:
        filter_kwargs['min_size'] = parse_size(filters_config['min_size'])
    
    if 'max_size' in filters_config:
        filter_kwargs['max_size'] = parse_size(filters_config['max_size'])
    
    # Other filters
    if 'no_replies' in filters_config and filters_config['no_replies']:
        filter_kwargs['is_reply'] = False
    elif 'replies_only' in filters_config and filters_config['replies_only']:
        filter_kwargs['is_reply'] = True
    elif 'is_reply' in filters_config:
        filter_kwargs['is_reply'] = filters_config['is_reply']
    
    if 'no_forwards' in filters_config and filters_config['no_forwards']:
        filter_kwargs['is_forward'] = False
    elif 'forwards_only' in filters_config and filters_config['forwards_only']:
        filter_kwargs['is_forward'] = True
    elif 'is_forward' in filters_config:
        filter_kwargs['is_forward'] = filters_config['is_forward']
    
    if 'no_links' in filters_config and filters_config['no_links']:
        filter_kwargs['has_links'] = False
    elif 'links_only' in filters_config and filters_config['links_only']:
        filter_kwargs['has_links'] = True
    elif 'has_links' in filters_config:
        filter_kwargs['has_links'] = filters_config['has_links']
    
    if not filter_kwargs:
        return None
    
    return MessageFilter(**filter_kwargs)


def _parse_destination(dest_config: Union[str, Dict[str, Any]], defaults: Dict[str, Any] = None) -> DestinationConfig:
    """Parse a destination configuration.
    
    Supports formats:
        - String: "@channelname" or "-1001234567890"
        - Dict: {"chat": "@channel", "transforms": [...], "filters": {...}}
    """
    if defaults is None:
        defaults = {}
    
    if isinstance(dest_config, str):
        return DestinationConfig(chat=dest_config)
    
    if isinstance(dest_config, dict):
        chat = dest_config.get('chat')
        if not chat:
            raise ValueError("Destination must have a 'chat' field")
        
        transforms = _parse_transforms(dest_config.get('transforms'))
        filters = _parse_filters(dest_config.get('filters', {}))
        
        return DestinationConfig(
            chat=str(chat),
            transforms=transforms,
            filters=filters,
        )
    
    raise ValueError(f"Invalid destination format: {dest_config}")


def _parse_route(route_config: Dict[str, Any], defaults: Dict[str, Any] = None) -> RouteConfig:
    """Parse a single route configuration."""
    if defaults is None:
        defaults = {}
    
    name = route_config.get('name')
    if not name:
        raise ValueError("Route must have a 'name' field")
    
    source = route_config.get('source')
    if not source:
        raise ValueError(f"Route '{name}' must have a 'source' field")
    
    destinations_raw = route_config.get('destinations', [])
    if not destinations_raw:
        raise ValueError(f"Route '{name}' must have at least one destination")
    
    # Parse destinations
    destinations = [_parse_destination(d, defaults) for d in destinations_raw]
    
    # Parse route-level options with defaults
    drop_author = route_config.get('drop_author', defaults.get('drop_author', False))
    delete_after = route_config.get('delete_after', defaults.get('delete_after', False))
    
    # Parse route-level transforms and filters
    transforms = _parse_transforms(route_config.get('transforms'))
    filters = _parse_filters(route_config.get('filters', {}))
    
    return RouteConfig(
        name=name,
        source=str(source),
        destinations=destinations,
        drop_author=drop_author,
        delete_after=delete_after,
        transforms=transforms,
        filters=filters,
    )


def load_routes(config_path: Union[str, Path]) -> RoutesConfig:
    """Load routes configuration from a YAML file.
    
    Args:
        config_path: Path to the YAML configuration file
        
    Returns:
        RoutesConfig object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)
    
    if not data:
        raise ValueError(f"Empty config file: {config_path}")
    
    # Parse defaults
    defaults = data.get('defaults', {})
    
    # Parse routes
    routes_raw = data.get('routes', [])
    if not routes_raw:
        raise ValueError("Config must have at least one route")
    
    routes = [_parse_route(r, defaults) for r in routes_raw]
    
    return RoutesConfig(routes=routes, defaults=defaults)


def validate_routes(config: RoutesConfig) -> List[str]:
    """Validate routes configuration.
    
    Returns a list of warning messages (empty if all valid).
    """
    warnings = []
    names_seen = set()
    
    for route in config.routes:
        # Check for duplicate names
        if route.name in names_seen:
            warnings.append(f"Duplicate route name: {route.name}")
        names_seen.add(route.name)
        
        # Check for empty destinations
        if not route.destinations:
            warnings.append(f"Route '{route.name}' has no destinations")
        
        # Check transform names are valid
        if route.transforms:
            for func, _ in route.transforms.transforms:
                if func is None:
                    warnings.append(f"Route '{route.name}' has invalid transform")
        
        for dest in route.destinations:
            if dest.transforms:
                for func, _ in dest.transforms.transforms:
                    if func is None:
                        warnings.append(f"Route '{route.name}' destination '{dest.chat}' has invalid transform")
    
    return warnings


def create_example_config() -> str:
    """Generate an example routes configuration YAML."""
    return '''# Telegram Forwarder Routes Configuration
# Save this file and use with: telegram-cli forward-live --config routes.yaml

# Global defaults (can be overridden per-route)
defaults:
  drop_author: false
  delete_after: false

routes:
  # Simple route: one source to multiple destinations
  - name: "news-backup"
    source: "@news_channel"
    destinations:
      - "@backup_channel"
      - "@archive_channel"
    drop_author: true
  
  # Route with per-destination transforms
  - name: "tech-filtered"
    source: "@tech_channel"
    destinations:
      # Destination with transforms
      - chat: "@general_backup"
        transforms:
          - replace_mentions:
              replacement: "[user]"
          - strip_formatting
      
      # Destination with filters (media only)
      - chat: "@media_archive"
        filters:
          media_only: true
      
      # Simple destination (no transforms or filters)
      - "@raw_backup"
  
  # Route with route-level filters (applied to all destinations)
  - name: "crypto-signals"
    source: "@crypto_source"
    destinations:
      - "@signals_group"
    filters:
      contains_any:
        - "BUY"
        - "SELL"
    transforms:
      - remove_links
  
  # Route with regex filtering
  - name: "important-only"
    source: "@announcements"
    destinations:
      - chat: "@important_backup"
        filters:
          regex: "(?i)(urgent|important|breaking)"
    drop_author: true
  
  # Route with date and type filters
  - name: "recent-photos"
    source: "@photo_channel"
    destinations:
      - "@photo_backup"
    filters:
      types:
        - photo
        - video
      after: "7d"  # Only last 7 days

# Available transforms:
#   - replace_mentions: Remove or replace @mentions
#       replacement: Text to replace with (default: "")
#   - remove_links: Remove URLs
#       replacement: Text to replace with (default: "")
#   - remove_hashtags: Remove #hashtags
#       replacement: Text to replace with (default: "")
#   - strip_formatting: Clean up extra whitespace
#   - add_prefix: Add text at the beginning
#       prefix: Text to add
#   - add_suffix: Add text at the end
#       suffix: Text to add
#   - regex_replace: Custom regex replacement
#       pattern: Regex pattern
#       replacement: Replacement text
#       flags: Regex flags (i=case-insensitive, m=multiline, s=dotall)

# Available filters:
#   types: [photo, video, text, document, audio, voice, sticker, ...]
#   exclude_types: [...]
#   after: Date or relative (7d, 1w, 1m)
#   before: Date or relative
#   contains: Must contain all these words
#   contains_any: Must contain any of these words
#   excludes: Must NOT contain these words
#   regex: Must match this pattern
#   media_only: true/false
#   text_only: true/false
#   min_size: "1MB"
#   max_size: "100MB"
#   no_replies: true
#   replies_only: true
#   no_forwards: true
#   forwards_only: true
#   no_links: true
#   links_only: true
'''
