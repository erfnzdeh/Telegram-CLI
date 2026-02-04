"""Daemon mode support for running multiple background processes."""

import json
import os
import sys
import signal
import atexit
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


class DaemonProcess:
    """Represents a single daemon process."""
    
    def __init__(
        self,
        pid: int,
        command: str,
        source: Optional[int] = None,
        dest: Optional[List[int]] = None,
        started_at: Optional[str] = None,
        log_file: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        account: Optional[str] = None
    ):
        self.pid = pid
        self.command = command
        self.source = source
        self.dest = dest or []
        self.started_at = started_at or datetime.now().isoformat()
        self.log_file = log_file
        self.args = args or {}  # Full args for restart capability
        self.account = account  # Account alias used
    
    def is_running(self) -> bool:
        """Check if this process is still running."""
        try:
            os.kill(self.pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'pid': self.pid,
            'command': self.command,
            'source': self.source,
            'dest': self.dest,
            'started_at': self.started_at,
            'log_file': self.log_file,
            'args': self.args,
            'account': self.account,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DaemonProcess":
        """Create from dictionary."""
        return cls(**data)


class DaemonManager:
    """Manages multiple daemon (background) processes."""
    
    def __init__(self, config_dir: Path):
        """Initialize daemon manager.
        
        Args:
            config_dir: Directory for PID files and logs
        """
        self.config_dir = config_dir
        self.pids_file = config_dir / "daemons.json"
        self.logs_dir = config_dir / "logs"
        
        # Ensure directories exist
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        self._current_pid: Optional[int] = None
    
    def _load_processes(self) -> Dict[int, DaemonProcess]:
        """Load all daemon processes from file."""
        if not self.pids_file.exists():
            return {}
        
        try:
            with open(self.pids_file, 'r') as f:
                data = json.load(f)
                return {
                    int(pid): DaemonProcess.from_dict(proc)
                    for pid, proc in data.items()
                }
        except (json.JSONDecodeError, IOError):
            return {}
    
    def _save_processes(self, processes: Dict[int, DaemonProcess]):
        """Save all daemon processes to file."""
        data = {str(pid): proc.to_dict() for pid, proc in processes.items()}
        with open(self.pids_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _cleanup_dead_processes(self) -> Dict[int, DaemonProcess]:
        """Remove dead processes from tracking."""
        processes = self._load_processes()
        alive = {pid: proc for pid, proc in processes.items() if proc.is_running()}
        
        if len(alive) != len(processes):
            self._save_processes(alive)
        
        return alive
    
    def list_running(self) -> List[DaemonProcess]:
        """List all running daemon processes.
        
        Returns:
            List of running DaemonProcess objects
        """
        processes = self._cleanup_dead_processes()
        return list(processes.values())
    
    def get_log_file(self, pid: Optional[int] = None) -> Path:
        """Get log file path for a daemon.
        
        Args:
            pid: Process ID (uses current if None)
            
        Returns:
            Path to log file
        """
        if pid is None:
            pid = os.getpid()
        return self.logs_dir / f"daemon_{pid}.log"
    
    def daemonize(
        self,
        command: str,
        source: Optional[int] = None,
        dest: Optional[List[int]] = None,
        args: Optional[Dict[str, Any]] = None,
        account: Optional[str] = None
    ) -> int:
        """Fork the process and run in background.
        
        Args:
            command: Command being run (for display)
            source: Source chat ID
            dest: Destination chat IDs
            
        Returns:
            PID of the daemon (in parent), doesn't return in child
        """
        # First fork
        try:
            pid = os.fork()
            if pid > 0:
                # Parent - wait a moment for child to register
                import time
                time.sleep(0.1)
                return pid
        except OSError as e:
            sys.stderr.write(f"Fork #1 failed: {e}\n")
            sys.exit(1)
        
        # Decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0)
        
        # Second fork
        try:
            pid = os.fork()
            if pid > 0:
                # First child exits
                os._exit(0)
        except OSError as e:
            sys.stderr.write(f"Fork #2 failed: {e}\n")
            sys.exit(1)
        
        # Now in daemon process
        self._current_pid = os.getpid()
        
        # Redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        
        # Open log file for output
        log_file = self.get_log_file(self._current_pid)
        log_handle = open(log_file, 'a')
        
        # Redirect stdin to /dev/null
        with open('/dev/null', 'r') as devnull:
            os.dup2(devnull.fileno(), sys.stdin.fileno())
        
        # Redirect stdout and stderr to log file
        os.dup2(log_handle.fileno(), sys.stdout.fileno())
        os.dup2(log_handle.fileno(), sys.stderr.fileno())
        
        # Register this daemon
        self._register_daemon(command, source, dest, str(log_file), args, account)
        
        # Remove from registry on exit
        atexit.register(self._unregister_daemon)
        
        # Return 0 to indicate we're in the daemon
        return 0
    
    def _register_daemon(
        self,
        command: str,
        source: Optional[int],
        dest: Optional[List[int]],
        log_file: str,
        args: Optional[Dict[str, Any]] = None,
        account: Optional[str] = None
    ):
        """Register this daemon in the process list."""
        processes = self._load_processes()
        
        processes[self._current_pid] = DaemonProcess(
            pid=self._current_pid,
            command=command,
            source=source,
            dest=dest,
            log_file=log_file,
            args=args,
            account=account,
        )
        
        self._save_processes(processes)
    
    def _unregister_daemon(self):
        """Unregister this daemon from the process list."""
        if self._current_pid is None:
            return
        
        processes = self._load_processes()
        if self._current_pid in processes:
            del processes[self._current_pid]
            self._save_processes(processes)
    
    def kill(self, pid: int, force: bool = False) -> tuple[bool, str]:
        """Kill a specific daemon by PID.
        
        Args:
            pid: Process ID to kill
            force: If True, use SIGKILL instead of SIGTERM
            
        Returns:
            Tuple of (success, message)
        """
        processes = self._load_processes()
        
        if pid not in processes:
            # Check if it's a running process anyway
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False, f"Process {pid} not found"
            except PermissionError:
                return False, f"Permission denied for PID {pid}"
        
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            
            # Wait for process to terminate
            import time
            for _ in range(10):  # Wait up to 5 seconds
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    # Process terminated
                    if pid in processes:
                        del processes[pid]
                        self._save_processes(processes)
                    return True, f"Process {pid} stopped"
            
            # Force kill if still running and not already forced
            if not force:
                os.kill(pid, signal.SIGKILL)
                if pid in processes:
                    del processes[pid]
                    self._save_processes(processes)
                return True, f"Process {pid} force killed"
            
            return False, f"Process {pid} did not terminate"
            
        except PermissionError:
            return False, f"Permission denied to kill process {pid}"
        except ProcessLookupError:
            if pid in processes:
                del processes[pid]
                self._save_processes(processes)
            return True, f"Process {pid} was not running"
    
    def kill_all(self) -> tuple[int, int]:
        """Kill all running daemons.
        
        Returns:
            Tuple of (killed_count, failed_count)
        """
        processes = self.list_running()
        killed = 0
        failed = 0
        
        for proc in processes:
            success, _ = self.kill(proc.pid)
            if success:
                killed += 1
            else:
                failed += 1
        
        return killed, failed
    
    def get_process(self, pid: int) -> Optional[DaemonProcess]:
        """Get a specific daemon process.
        
        Args:
            pid: Process ID
            
        Returns:
            DaemonProcess or None
        """
        processes = self._cleanup_dead_processes()
        return processes.get(pid)


    def get_saved_configs(self) -> List[DaemonProcess]:
        """Get all saved daemon configurations (for restore after reboot).
        
        Unlike list_running(), this returns ALL saved configs regardless of
        whether they're currently running. Used by 'daemon restore' command.
        
        Returns:
            List of DaemonProcess objects with saved configurations
        """
        if not self.pids_file.exists():
            return []
        
        try:
            with open(self.pids_file, 'r') as f:
                data = json.load(f)
                return [
                    DaemonProcess.from_dict(proc)
                    for proc in data.values()
                    if proc.get('args')  # Only return configs that have args (can be restored)
                ]
        except (json.JSONDecodeError, IOError):
            return []
    
    def save_config_for_restore(
        self,
        command: str,
        source: Optional[int],
        dest: Optional[List[int]],
        args: Dict[str, Any],
        account: Optional[str] = None
    ):
        """Save a daemon configuration for future restore (before daemonizing).
        
        This is called from the parent process before fork so the config
        is available for restore even if the process hasn't started yet.
        
        Args:
            command: Command name (e.g., 'forward-live')
            source: Source chat ID
            dest: Destination chat IDs
            args: Full args dict for restart
            account: Account alias
        """
        # Use a placeholder PID that will be updated after fork
        # We use negative timestamps as temporary IDs
        temp_id = -int(datetime.now().timestamp() * 1000)
        
        processes = self._load_processes()
        processes[temp_id] = DaemonProcess(
            pid=temp_id,
            command=command,
            source=source,
            dest=dest,
            args=args,
            account=account,
        )
        self._save_processes(processes)
        
        return temp_id


def get_daemon_manager(config_dir: Path) -> DaemonManager:
    """Get a DaemonManager instance.
    
    Args:
        config_dir: Configuration directory
        
    Returns:
        DaemonManager instance
    """
    return DaemonManager(config_dir)
