"""Logging infrastructure with verbosity levels and file logging."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class ForwarderLogger:
    """Logger with multiple verbosity levels and file logging.
    
    Verbosity levels:
        0 = quiet (errors only)
        1 = normal (info + errors)
        2 = verbose (info + debug messages shown)
        3 = debug (all messages shown)
    """
    
    def __init__(self, config_dir: Path, verbosity: int = 1):
        """Initialize the logger.
        
        Args:
            config_dir: Directory to store log files
            verbosity: Verbosity level (0-3)
        """
        self.config_dir = config_dir
        self.log_dir = config_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.verbosity = verbosity
        self._progress_line_active = False
        
        # File logger - always logs everything
        self.file_logger = self._setup_file_logger()
    
    def _setup_file_logger(self) -> logging.Logger:
        """Set up file-based logger."""
        logger = logging.getLogger("telegram_cli")
        logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers to avoid duplicates
        logger.handlers.clear()
        
        # Create log file with date
        log_file = self.log_dir / f"forwarder_{datetime.now():%Y%m%d}.log"
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(levelname)-7s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(handler)
        
        return logger
    
    def _clear_progress(self):
        """Clear the progress line if active."""
        if self._progress_line_active:
            print('\r' + ' ' * 80 + '\r', end='', flush=True)
            self._progress_line_active = False
    
    def info(self, msg: str):
        """Normal output - shown at verbosity >= 1.
        
        Args:
            msg: Message to log
        """
        self.file_logger.info(msg)
        if self.verbosity >= 1:
            self._clear_progress()
            print(msg)
    
    def verbose(self, msg: str):
        """Detailed output - shown at verbosity >= 2.
        
        Args:
            msg: Message to log
        """
        self.file_logger.debug(msg)
        if self.verbosity >= 2:
            self._clear_progress()
            print(f"  {msg}")
    
    def debug(self, msg: str):
        """Debug output - shown at verbosity >= 3.
        
        Args:
            msg: Message to log
        """
        self.file_logger.debug(msg)
        if self.verbosity >= 3:
            self._clear_progress()
            print(f"    [DEBUG] {msg}")
    
    def error(self, msg: str):
        """Error output - always shown.
        
        Args:
            msg: Error message to log
        """
        self.file_logger.error(msg)
        self._clear_progress()
        print(f"ERROR: {msg}", file=sys.stderr)
    
    def warning(self, msg: str):
        """Warning output - shown at verbosity >= 1.
        
        Args:
            msg: Warning message to log
        """
        self.file_logger.warning(msg)
        if self.verbosity >= 1:
            self._clear_progress()
            print(f"WARNING: {msg}")
    
    def success(self, msg: str):
        """Success output - shown at verbosity >= 1.
        
        Args:
            msg: Success message to log
        """
        self.file_logger.info(msg)
        if self.verbosity >= 1:
            self._clear_progress()
            print(f"OK: {msg}")
    
    def progress(self, current: int, total: int, msg: str = ""):
        """Show progress indicator.
        
        Args:
            current: Current progress count
            total: Total count
            msg: Optional additional message
        """
        if self.verbosity < 1:
            return
        
        if total > 0:
            pct = current / total * 100
            bar_width = 30
            filled = int(bar_width * current / total)
            bar = '=' * filled + '-' * (bar_width - filled)
            status = f"\r[{bar}] {current}/{total} ({pct:.1f}%)"
        else:
            status = f"\r[...] {current} processed"
        
        if msg:
            status += f" {msg}"
        
        print(status, end='', flush=True)
        self._progress_line_active = True
    
    def progress_done(self):
        """Complete the progress line with a newline."""
        if self._progress_line_active:
            print()
            self._progress_line_active = False


def get_logger(config_dir: Optional[Path] = None, verbosity: int = 1) -> ForwarderLogger:
    """Get or create a logger instance.
    
    Args:
        config_dir: Directory for log files
        verbosity: Verbosity level
        
    Returns:
        ForwarderLogger instance
    """
    if config_dir is None:
        config_dir = Path.home() / ".telegram-cli"
    
    return ForwarderLogger(config_dir, verbosity)
