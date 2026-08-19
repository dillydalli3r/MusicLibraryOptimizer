"""Auto-update checker for Music Library Optimizer.

Checks GitHub releases for newer versions and downloads the installer.
"""
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path

from .paths import SCRIPT_DIR, CONFIG_FILE
from .config import load_config
from .ui import log, c, Color

GITHUB_REPO = "dillydalli3r/MusicLibraryOptimizer"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_CHECK_INTERVAL_DAYS = 7


def _get_current_version():
    try:
        from . import __version__
        return __version__
    except Exception:
        return "1.0.0"


def _version_tuple(v):
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


def _is_newer(remote, local):
    return _version_tuple(remote) > _version_tuple(local)


def check_for_updates(silent=False, callback=None):
    """Check GitHub for a newer release.

    Args:
        silent: If True, only log when update found.
        callback: Optional function(version, download_url, notes) called when update found.

    Returns:
        (has_update, version, download_url, notes) or (False, None, None, None)
    """
    def worker():
        try:
            req = urllib.request.Request(
                GITHUB_API_URL,
                headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "MusicLibraryOptimizer/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)

            latest_version = data.get("tag_name", "").lstrip("v")
            current = _get_current_version()

            if not _is_newer(latest_version, current):
                if not silent:
                    log(f"Update check: already on latest version ({current})", tag="green")
                return

            # Find the installer asset
            download_url = None
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if name.endswith("_setup.exe") or name.endswith(".msi"):
                    download_url = asset.get("browser_download_url")
                    break

            notes = data.get("body", "").strip()

            if not silent:
                log(f"Update available: v{latest_version} (current: v{current})", tag="yellow")
                if download_url:
                    log(f"Download: {download_url}", tag="muted")

            if callback:
                callback(latest_version, download_url, notes)

        except urllib.error.HTTPError as e:
            if not silent:
                log(f"Update check failed: HTTP {e.code}", tag="red")
        except Exception as e:
            if not silent:
                log(f"Update check failed: {e}", tag="red")

    threading.Thread(target=worker, daemon=True).start()


def download_and_run_installer(url, callback=None):
    """Download the installer and run it."""
    import tempfile
    import subprocess

    def worker():
        try:
            tmpdir = tempfile.gettempdir()
            installer_path = os.path.join(tmpdir, "MusicLibraryOptimizer_Setup.exe")

            log(f"Downloading installer...", tag="muted")
            urllib.request.urlretrieve(url, installer_path)

            log(f"Running installer...", tag="muted")
            subprocess.Popen([installer_path], shell=True)

            if callback:
                callback(True)
        except Exception as e:
            log(f"Installer download/run failed: {e}", tag="red")
            if callback:
                callback(False)

    threading.Thread(target=worker, daemon=True).start()


def maybe_auto_check():
    """Run update check if interval has passed."""
    config = load_config()
    last_check = config.get("last_update_check", 0)
    import time
    now = time.time()
    if now - last_check > UPDATE_CHECK_INTERVAL_DAYS * 86400:
        config["last_update_check"] = now
        from .config import save_config
        save_config(config)
        check_for_updates(silent=True)