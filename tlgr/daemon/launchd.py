"""macOS LaunchAgent management for the tlgr daemon.

Installs/uninstalls a plist in ~/Library/LaunchAgents so the daemon
starts at login and restarts automatically if it crashes.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

SERVICE_LABEL = "dev.tlgr.daemon"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def _python_executable() -> str:
    """Return the absolute path to the current Python interpreter."""
    return sys.executable


def _build_plist(base: Path, log_dir: Path) -> dict:
    log_dir.mkdir(parents=True, exist_ok=True)
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [
            _python_executable(),
            "-m",
            "tlgr.daemon.server",
            "--base",
            str(base),
            "--foreground",
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "StandardOutPath": str(log_dir / "daemon.log"),
        "StandardErrorPath": str(log_dir / "daemon.log"),
    }


def is_installed() -> bool:
    return PLIST_PATH.exists()


def is_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{SERVICE_LABEL}"],
        capture_output=True,
    )
    return result.returncode == 0


def install(base: Path, log_dir: Path) -> Path:
    """Write the plist and load it into launchd. Returns the plist path."""
    if is_loaded():
        unload()

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist_data = _build_plist(base, log_dir)
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist_data, f)

    _load()
    return PLIST_PATH


def uninstall() -> bool:
    """Unload and remove the plist. Returns True if anything was removed."""
    removed = False
    if is_loaded():
        unload()
        removed = True
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        removed = True
    return removed


def _load() -> None:
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH)],
        check=True,
    )


def unload() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{SERVICE_LABEL}"],
        capture_output=True,
    )


def kickstart() -> None:
    """Force-(re)start the service via launchctl."""
    subprocess.run(
        [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/{SERVICE_LABEL}",
        ],
        check=True,
    )
