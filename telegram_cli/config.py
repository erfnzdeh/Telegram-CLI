"""Configuration management for Telegram CLI."""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class Config:
    """Application configuration."""
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    session_name: str = "session"
    
    # Defaults
    batch_size: int = 100
    delay_between_batches: float = 1.0
    delay_between_destinations: float = 0.5
    flood_sleep_threshold: int = 120
    request_retries: int = 5
    connection_retries: int = 5
    
    def is_configured(self) -> bool:
        """Check if API credentials are configured."""
        return self.api_id is not None and self.api_hash is not None


class ConfigManager:
    """Manages configuration loading and saving.
    
    Supports multi-account mode where each account has its own directory
    under ~/.telegram-cli/accounts/<alias>/
    """
    
    DEFAULT_CONFIG_DIR = Path.home() / ".telegram-cli"
    LEGACY_CONFIG_DIR = Path.home() / ".telegram-forwarder"  # For migration
    CONFIG_FILE = "config.json"
    
    def __init__(
        self,
        config_dir: Optional[Path] = None,
        account: Optional[str] = None,
        base_dir: Optional[Path] = None
    ):
        """Initialize config manager.
        
        Args:
            config_dir: Explicit directory for config files (overrides account)
            account: Account alias to use (loads from accounts/<alias>/)
            base_dir: Base directory (defaults to ~/.telegram-cli)
        """
        self.base_dir = base_dir or self.DEFAULT_CONFIG_DIR
        self.account = account
        
        if config_dir:
            # Explicit config_dir takes precedence
            self.config_dir = config_dir
        elif account:
            # Account-specific directory
            self.config_dir = self.base_dir / "accounts" / account
        else:
            # Legacy mode: use base directory directly
            self.config_dir = self.base_dir
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / self.CONFIG_FILE
        self._config: Optional[Config] = None
    
    @property
    def logs_dir(self) -> Path:
        """Get path to shared logs directory."""
        return self.base_dir / "logs"
    
    @property
    def session_path(self) -> Path:
        """Get path to session file."""
        return self.config_dir / "session"
    
    @property
    def jobs_file(self) -> Path:
        """Get path to jobs state file."""
        return self.config_dir / "jobs.json"
    
    def load(self) -> Config:
        """Load configuration from file and environment.
        
        Environment variables take precedence over config file.
        
        Returns:
            Config object
        """
        config = Config()
        
        # Load from file if exists
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    if 'api_id' in data:
                        config.api_id = data['api_id']
                    if 'api_hash' in data:
                        config.api_hash = data['api_hash']
                    if 'session_name' in data:
                        config.session_name = data['session_name']
                    if 'batch_size' in data:
                        config.batch_size = data['batch_size']
                    if 'delay_between_batches' in data:
                        config.delay_between_batches = data['delay_between_batches']
                    if 'delay_between_destinations' in data:
                        config.delay_between_destinations = data['delay_between_destinations']
            except (json.JSONDecodeError, IOError):
                pass
        
        # Environment variables override file config
        env_api_id = os.environ.get('TELEGRAM_API_ID')
        env_api_hash = os.environ.get('TELEGRAM_API_HASH')
        
        if env_api_id:
            try:
                config.api_id = int(env_api_id)
            except ValueError:
                pass
        
        if env_api_hash:
            config.api_hash = env_api_hash
        
        self._config = config
        return config
    
    def save(self, config: Config):
        """Save configuration to file.
        
        Args:
            config: Config object to save
        """
        data = {
            'api_id': config.api_id,
            'api_hash': config.api_hash,
            'session_name': config.session_name,
            'batch_size': config.batch_size,
            'delay_between_batches': config.delay_between_batches,
            'delay_between_destinations': config.delay_between_destinations,
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Set restrictive permissions
        self.config_file.chmod(0o600)
        
        self._config = config
    
    def get_config(self) -> Config:
        """Get current config, loading if necessary.
        
        Returns:
            Config object
        """
        if self._config is None:
            return self.load()
        return self._config
    
    def set_credentials(self, api_id: int, api_hash: str):
        """Set API credentials and save.
        
        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
        """
        config = self.get_config()
        config.api_id = api_id
        config.api_hash = api_hash
        self.save(config)
    
    def clear_session(self, clear_credentials: bool = True):
        """Delete the session file and optionally the config.
        
        Args:
            clear_credentials: If True, also delete config.json with API credentials
        """
        # Delete session file
        session_file = self.session_path.with_suffix('.session')
        if session_file.exists():
            session_file.unlink()
        
        # Also try without suffix
        if self.session_path.exists():
            self.session_path.unlink()
        
        # Delete config file with credentials
        if clear_credentials and self.config_file.exists():
            self.config_file.unlink()
            self._config = None
    
    def has_session(self) -> bool:
        """Check if a session file exists."""
        return (
            self.session_path.with_suffix('.session').exists() or
            self.session_path.exists()
        )


def get_config_manager(
    config_dir: Optional[Path] = None,
    account: Optional[str] = None,
    base_dir: Optional[Path] = None,
    auto_migrate: bool = True
) -> ConfigManager:
    """Get a ConfigManager instance.
    
    This function handles multi-account mode automatically:
    1. If account is specified, uses that account's directory
    2. If no account, checks for active account in AccountManager
    3. If no accounts exist, checks for legacy migration
    
    Args:
        config_dir: Explicit config directory (overrides account)
        account: Account alias to use
        base_dir: Base directory for all config
        auto_migrate: If True, auto-migrate legacy setups
        
    Returns:
        ConfigManager instance
    """
    from .accounts import get_account_manager
    
    if base_dir is None:
        base_dir = ConfigManager.DEFAULT_CONFIG_DIR
    
    # If explicit config_dir, use it directly
    if config_dir:
        return ConfigManager(config_dir=config_dir, base_dir=base_dir)
    
    # Get account manager
    account_mgr = get_account_manager(base_dir)
    
    # Handle migration from legacy setup
    if auto_migrate and account_mgr.needs_migration():
        migrated = account_mgr.migrate_legacy()
        if migrated:
            account = migrated
    
    # Also check for legacy .telegram-forwarder directory
    legacy_dir = ConfigManager.LEGACY_CONFIG_DIR
    if auto_migrate and legacy_dir.exists() and not account_mgr.has_accounts():
        # Migrate from old .telegram-forwarder to new .telegram-cli
        import shutil
        
        # Move all files to new location first
        for item in legacy_dir.iterdir():
            target = base_dir / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
        
        # Now check if migration to accounts is needed
        if account_mgr.needs_migration():
            migrated = account_mgr.migrate_legacy()
            if migrated:
                account = migrated
        
        # Try to remove legacy dir if empty
        try:
            legacy_dir.rmdir()
        except OSError:
            pass
    
    # If no account specified, try to get active account
    if not account:
        account = account_mgr.get_active()
    
    # If still no account and none exist, we're in initial setup
    if not account and not account_mgr.has_accounts():
        # Return base config manager for initial login
        return ConfigManager(base_dir=base_dir)
    
    return ConfigManager(account=account, base_dir=base_dir)
