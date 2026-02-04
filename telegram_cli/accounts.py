"""Account management for multi-account support.

This module provides functionality to manage multiple Telegram accounts,
including switching between accounts, storing account metadata, and
migrating from single-account setups.
"""

import json
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


@dataclass
class AccountInfo:
    """Information about a Telegram account."""
    alias: str
    phone: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    user_id: Optional[int] = None
    created_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountInfo":
        """Create from dictionary."""
        return cls(**data)
    
    def display_name(self) -> str:
        """Get a display name for the account."""
        if self.username:
            return f"@{self.username}"
        if self.first_name:
            return self.first_name
        if self.phone:
            # Mask phone number
            return f"{self.phone[:4]}...{self.phone[-2:]}"
        return self.alias


class AccountManager:
    """Manages multiple Telegram accounts.
    
    Directory structure:
        ~/.telegram-cli/
        ├── accounts.json          # Account registry
        ├── accounts/
        │   ├── personal/          # Account alias
        │   │   ├── config.json    # API credentials
        │   │   ├── session.session
        │   │   └── jobs.json
        │   └── work/
        │       └── ...
        └── logs/                   # Shared logs
    """
    
    ACCOUNTS_FILE = "accounts.json"
    ACCOUNTS_DIR = "accounts"
    DEFAULT_ACCOUNT = "default"
    
    def __init__(self, base_dir: Path):
        """Initialize account manager.
        
        Args:
            base_dir: Base configuration directory (~/.telegram-cli)
        """
        self.base_dir = base_dir
        self.accounts_file = base_dir / self.ACCOUNTS_FILE
        self.accounts_dir = base_dir / self.ACCOUNTS_DIR
        
        # Ensure directories exist
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        
        self._data: Optional[Dict[str, Any]] = None
    
    def _load(self) -> Dict[str, Any]:
        """Load accounts data from file."""
        if self._data is not None:
            return self._data
        
        if not self.accounts_file.exists():
            self._data = {"active": None, "accounts": {}}
            return self._data
        
        try:
            with open(self.accounts_file, 'r') as f:
                self._data = json.load(f)
                return self._data
        except (json.JSONDecodeError, IOError):
            self._data = {"active": None, "accounts": {}}
            return self._data
    
    def _save(self):
        """Save accounts data to file."""
        if self._data is None:
            return
        
        with open(self.accounts_file, 'w') as f:
            json.dump(self._data, f, indent=2)
        
        # Set restrictive permissions
        self.accounts_file.chmod(0o600)
    
    def get_active(self) -> Optional[str]:
        """Get the active account alias.
        
        Returns:
            Active account alias or None if no accounts exist
        """
        data = self._load()
        active = data.get("active")
        
        # Validate active account still exists
        if active and active in data.get("accounts", {}):
            return active
        
        # If no active, try to get first account
        accounts = data.get("accounts", {})
        if accounts:
            first = next(iter(accounts.keys()))
            self.set_active(first)
            return first
        
        return None
    
    def set_active(self, alias: str) -> bool:
        """Set the active account.
        
        Args:
            alias: Account alias to set as active
            
        Returns:
            True if successful, False if account doesn't exist
        """
        data = self._load()
        
        if alias not in data.get("accounts", {}):
            return False
        
        data["active"] = alias
        self._save()
        return True
    
    def list_accounts(self) -> List[AccountInfo]:
        """List all registered accounts.
        
        Returns:
            List of AccountInfo objects
        """
        data = self._load()
        accounts = []
        
        for alias, info in data.get("accounts", {}).items():
            accounts.append(AccountInfo.from_dict(info))
        
        return accounts
    
    def get_account(self, alias: str) -> Optional[AccountInfo]:
        """Get account info by alias.
        
        Args:
            alias: Account alias
            
        Returns:
            AccountInfo or None if not found
        """
        data = self._load()
        info = data.get("accounts", {}).get(alias)
        
        if info:
            return AccountInfo.from_dict(info)
        return None
    
    def add_account(self, alias: str) -> AccountInfo:
        """Register a new account.
        
        This creates the account directory structure but doesn't
        perform login. Use ConfigManager for the actual login.
        
        Args:
            alias: Unique alias for the account
            
        Returns:
            New AccountInfo
            
        Raises:
            ValueError: If alias already exists or is invalid
        """
        # Validate alias
        if not alias or not alias.replace('_', '').replace('-', '').isalnum():
            raise ValueError(
                f"Invalid alias '{alias}'. Use only letters, numbers, dashes, and underscores."
            )
        
        data = self._load()
        
        if alias in data.get("accounts", {}):
            raise ValueError(f"Account '{alias}' already exists")
        
        # Create account directory
        account_dir = self.accounts_dir / alias
        account_dir.mkdir(parents=True, exist_ok=True)
        
        # Create account info
        account = AccountInfo(
            alias=alias,
            created_at=datetime.now().isoformat()
        )
        
        # Save to registry
        if "accounts" not in data:
            data["accounts"] = {}
        data["accounts"][alias] = account.to_dict()
        
        # Set as active if this is the first account
        if not data.get("active"):
            data["active"] = alias
        
        self._save()
        return account
    
    def update_account(
        self,
        alias: str,
        phone: Optional[str] = None,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Optional[AccountInfo]:
        """Update account information after login.
        
        Args:
            alias: Account alias
            phone: Phone number
            username: Telegram username
            first_name: First name
            user_id: Telegram user ID
            
        Returns:
            Updated AccountInfo or None if not found
        """
        data = self._load()
        
        if alias not in data.get("accounts", {}):
            return None
        
        account_data = data["accounts"][alias]
        
        if phone is not None:
            account_data["phone"] = phone
        if username is not None:
            account_data["username"] = username
        if first_name is not None:
            account_data["first_name"] = first_name
        if user_id is not None:
            account_data["user_id"] = user_id
        
        self._save()
        return AccountInfo.from_dict(account_data)
    
    def remove_account(self, alias: str, delete_data: bool = True) -> bool:
        """Remove an account.
        
        Args:
            alias: Account alias to remove
            delete_data: If True, delete account data directory
            
        Returns:
            True if removed, False if not found
        """
        data = self._load()
        
        if alias not in data.get("accounts", {}):
            return False
        
        # Remove from registry
        del data["accounts"][alias]
        
        # Update active if this was the active account
        if data.get("active") == alias:
            remaining = list(data["accounts"].keys())
            data["active"] = remaining[0] if remaining else None
        
        self._save()
        
        # Delete data directory
        if delete_data:
            account_dir = self.accounts_dir / alias
            if account_dir.exists():
                shutil.rmtree(account_dir)
        
        return True
    
    def rename_account(self, old_alias: str, new_alias: str) -> bool:
        """Rename an account.
        
        Args:
            old_alias: Current alias
            new_alias: New alias
            
        Returns:
            True if renamed, False if not found
            
        Raises:
            ValueError: If new alias is invalid or already exists
        """
        # Validate new alias
        if not new_alias or not new_alias.replace('_', '').replace('-', '').isalnum():
            raise ValueError(
                f"Invalid alias '{new_alias}'. Use only letters, numbers, dashes, and underscores."
            )
        
        data = self._load()
        
        if old_alias not in data.get("accounts", {}):
            return False
        
        if new_alias in data.get("accounts", {}):
            raise ValueError(f"Account '{new_alias}' already exists")
        
        # Rename in registry
        account_data = data["accounts"].pop(old_alias)
        account_data["alias"] = new_alias
        data["accounts"][new_alias] = account_data
        
        # Update active if needed
        if data.get("active") == old_alias:
            data["active"] = new_alias
        
        self._save()
        
        # Rename directory
        old_dir = self.accounts_dir / old_alias
        new_dir = self.accounts_dir / new_alias
        if old_dir.exists():
            old_dir.rename(new_dir)
        
        return True
    
    def get_account_dir(self, alias: Optional[str] = None) -> Path:
        """Get the directory for an account.
        
        Args:
            alias: Account alias (uses active if not provided)
            
        Returns:
            Path to account directory
            
        Raises:
            ValueError: If no account is active/specified
        """
        if alias is None:
            alias = self.get_active()
        
        if alias is None:
            raise ValueError("No account specified and no active account")
        
        return self.accounts_dir / alias
    
    def has_accounts(self) -> bool:
        """Check if any accounts are registered."""
        data = self._load()
        return bool(data.get("accounts"))
    
    def needs_migration(self) -> bool:
        """Check if migration from legacy single-account setup is needed.
        
        Returns:
            True if there are legacy files to migrate
        """
        # Check for legacy session file at base dir
        legacy_session = self.base_dir / "session.session"
        legacy_config = self.base_dir / "config.json"
        
        # Migration needed if legacy files exist and no accounts registered
        return (
            (legacy_session.exists() or legacy_config.exists()) and
            not self.has_accounts()
        )
    
    def migrate_legacy(self) -> Optional[str]:
        """Migrate from legacy single-account setup.
        
        Moves existing session and config files to a new 'default' account.
        
        Returns:
            Alias of migrated account, or None if nothing to migrate
        """
        if not self.needs_migration():
            return None
        
        alias = self.DEFAULT_ACCOUNT
        
        # Create the default account
        try:
            self.add_account(alias)
        except ValueError:
            # Account already exists, use a numbered variant
            i = 1
            while True:
                try:
                    alias = f"{self.DEFAULT_ACCOUNT}{i}"
                    self.add_account(alias)
                    break
                except ValueError:
                    i += 1
                    if i > 100:
                        raise ValueError("Could not create migration account")
        
        account_dir = self.get_account_dir(alias)
        
        # Move legacy files
        files_to_move = [
            "session.session",
            "config.json",
            "jobs.json",
        ]
        
        for filename in files_to_move:
            legacy_file = self.base_dir / filename
            if legacy_file.exists():
                target = account_dir / filename
                shutil.move(str(legacy_file), str(target))
        
        # Also check for session without extension
        legacy_session_no_ext = self.base_dir / "session"
        if legacy_session_no_ext.exists():
            shutil.move(str(legacy_session_no_ext), str(account_dir / "session"))
        
        return alias


def get_account_manager(base_dir: Optional[Path] = None) -> AccountManager:
    """Get an AccountManager instance.
    
    Args:
        base_dir: Base configuration directory
        
    Returns:
        AccountManager instance
    """
    if base_dir is None:
        base_dir = Path.home() / ".telegram-cli"
    
    return AccountManager(base_dir)
