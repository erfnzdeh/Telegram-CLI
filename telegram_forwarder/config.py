"""Configuration management for Telegram Forwarder."""

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
    session_name: str = "telegram_forwarder"
    
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
    """Manages configuration loading and saving."""
    
    DEFAULT_CONFIG_DIR = Path.home() / ".telegram-forwarder"
    CONFIG_FILE = "config.json"
    
    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize config manager.
        
        Args:
            config_dir: Directory for config files (defaults to ~/.telegram-forwarder)
        """
        self.config_dir = config_dir or self.DEFAULT_CONFIG_DIR
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / self.CONFIG_FILE
        self._config: Optional[Config] = None
    
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


def get_config_manager(config_dir: Optional[Path] = None) -> ConfigManager:
    """Get a ConfigManager instance.
    
    Args:
        config_dir: Optional custom config directory
        
    Returns:
        ConfigManager instance
    """
    return ConfigManager(config_dir)
