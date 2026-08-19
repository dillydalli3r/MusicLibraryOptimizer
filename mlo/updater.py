"""Auto-update checker for Music Library Optimizer.

Checks GitHub releases for newer versions and downloads the installer.
"""
import json
import threading
import urllib.request

from .ui import log, c, Color

GITHUB_REPO = "dillydalli3r/MusicLibraryOptimizer"
GITHUB_RELEASES_URL = (
    f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
)
UPDATE_CHECK_INTERVAL_DAYS = 7

_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "MusicLibraryOptimizer/1.0.2",
}


def _get_current_version():
    try:
        from . import __version__
        return __version__
    except Exception:
        return "0.0.0"


def _version_tuple(v):
    """'v1.0.1' / '1.0.1' -> (1, 0, 1); anything weird -> (0, 0, 0)."""
    try:
        return tuple(int(x) for x in str(v).lstrip("vV").split("."))
    except Exception:
        return (0, 0, 0)


def _is_newer(remote, local):
    return _version_tuple(remote) > _version_tuple(local)


def _fetch_latest_release():
    """Return the newest stable (non-draft, non-prerelease) release dict.

    Uses the releases list (not /releases/latest, which 404s when the newest
    release is a draft) and returns (release_dict, version_tuple).
    """
    req = urllib.request.Request(GITHUB_RELEASES_URL, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        releases = json.load(resp)
    best = None
    best_ver = (0, 0, 0)
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tv = _version_tuple(rel.get("tag_name", ""))
        if tv > best_ver:
            best, best_ver = rel, tv
    return best


def _find_installer(data):
    """Pick the installer asset URL from a release."""
    for asset in data.get("assets", []):
        name = asset.get("name", "").lower()
        if name.endswith(".exe") and ("setup" in name or "installer" in name):
            return asset.get("browser_download_url")
    # Fallback: any .exe asset.
    for asset in data.get("assets", []):
        name = asset.get("name", "").lower()
        if name.endswith(".exe"):
            return asset.get("browser_download_url")
    return None


def check_for_updates(silent=False, callback=None):
    """Check GitHub for a newer release.

    callback(has_update: bool, version, download_url, notes, error) is always
    invoked once (from a worker thread) so the UI can give feedback for every
    outcome: update available / already latest / check failed.
    """
    def worker():
        try:
            data = _fetch_latest_release()
            if data is None:
                if callback:
                    callback(False, None, None, "", "No stable releases found")
                return
            latest = str(data.get("tag_name", "")).lstrip("vV")
            current = _get_current_version()
            has_update = _is_newer(latest, current)
            download_url = _find_installer(data) if has_update else None
            notes = (data.get("body") or "").strip()

            if not silent:
                if has_update:
                    log(f"Update available: v{latest} (current: v{current})",
                        Color.YELLOW)
                    if download_url:
                        log(f"  Download: {download_url}", Color.GREY)
                else:
                    log(f"Update check: already on latest version "
                        f"(v{current})", Color.GREEN)

            if callback:
                callback(has_update, latest, download_url, notes, None)

        except urllib.error.HTTPError as e:
            if callback:
                callback(False, None, None, "", f"HTTP {e.code}")
            elif not silent:
                log(f"Update check failed: HTTP {e.code}", Color.RED)
        except Exception as e:
            if callback:
                callback(False, None, None, "", str(e))
            elif not silent:
                log(f"Update check failed: {e}", Color.RED)

    threading.Thread(target=worker, daemon=True).start()


def download_and_run_installer(url, callback=None):
    """Download the installer and run it."""
    import os
    import subprocess
    import tempfile

    def worker():
        try:
            if not url:
                raise ValueError("no download URL")
            installer_path = os.path.join(
                tempfile.gettempdir(), "MusicLibraryOptimizer_Setup.exe")
            log("Downloading installer...")
            urllib.request.urlretrieve(url, installer_path)
            log("Running installer...")
            subprocess.Popen([installer_path], shell=True)
            if callback:
                callback(True)
        except Exception as e:
            log(f"Installer download/run failed: {e}", Color.RED)
            if callback:
                callback(False)

    threading.Thread(target=worker, daemon=True).start()


def maybe_auto_check():
    """Run update check if interval has passed; log to the console."""
    import time
    from .config import load_config, save_config

    config = load_config()
    last = config.get("last_update_check", 0)
    now = time.time()
    if now - last > UPDATE_CHECK_INTERVAL_DAYS * 86400:
        config["last_update_check"] = now
        save_config(config)
        check_for_updates(silent=False)