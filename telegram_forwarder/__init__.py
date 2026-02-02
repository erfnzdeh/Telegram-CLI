"""Telegram CLI Autoforwarder - Forward messages between Telegram chats."""

__version__ = "1.0.0"

from .config import ConfigManager, get_config_manager
from .logger import ForwarderLogger, get_logger
from .state import StateManager, JobType, JobStatus, get_state_manager
from .client import ClientWrapper, create_client, get_client
from .forwarder import Forwarder, ForwardResult, test_permissions
from .daemon import DaemonManager, get_daemon_manager
from .errors import (
    ForwarderError,
    AccountLimitedError,
    SourceRestrictedError,
    DestinationError,
    MaxRetriesExceeded,
    SessionError,
    ConfigurationError,
)
from .utils import (
    MessageType,
    ChatType,
    detect_message_type,
    get_chat_type,
    is_forwardable,
    check_forward_restrictions,
    check_delete_permission,
    estimate_message_count,
    format_count,
    format_estimate,
    format_duration,
    format_size,
    validate_chat_id,
)
from .transforms import (
    TransformChain,
    get_transform,
    list_transforms,
    create_chain_from_spec,
)
from .filters import (
    MessageFilter,
    create_filter_from_args,
    parse_date,
    parse_size,
    parse_message_types,
)

__all__ = [
    # Version
    "__version__",
    # Config
    "ConfigManager",
    "get_config_manager",
    # Logger
    "ForwarderLogger",
    "get_logger",
    # State
    "StateManager",
    "JobType",
    "JobStatus",
    "get_state_manager",
    # Client
    "ClientWrapper",
    "create_client",
    "get_client",
    # Forwarder
    "Forwarder",
    "ForwardResult",
    "test_permissions",
    # Daemon
    "DaemonManager",
    "get_daemon_manager",
    # Errors
    "ForwarderError",
    "AccountLimitedError",
    "SourceRestrictedError",
    "DestinationError",
    "MaxRetriesExceeded",
    "SessionError",
    "ConfigurationError",
    # Utils
    "MessageType",
    "ChatType",
    "detect_message_type",
    "get_chat_type",
    "is_forwardable",
    "check_forward_restrictions",
    "check_delete_permission",
    "estimate_message_count",
    "format_count",
    "format_estimate",
    "format_duration",
    "format_size",
    "validate_chat_id",
    # Transforms
    "TransformChain",
    "get_transform",
    "list_transforms",
    "create_chain_from_spec",
    # Filters
    "MessageFilter",
    "create_filter_from_args",
    "parse_date",
    "parse_size",
    "parse_message_types",
]
