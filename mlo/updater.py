"""Safe GitHub update checking and Windows shutdown coordination."""
import base64
import ctypes
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

from .ui import log, c, Color

GITHUB_REPO = "dillydalli3r/MusicLibraryOptimizer"
GITHUB_RELEASES_URL = (
    f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
)
UPDATE_CHECK_INTERVAL_DAYS = 7
_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "MusicLibraryOptimizer",
}
_APP_TITLE_PREFIX = "Music Library Optimizer v"
_INSTANCE_DIR = os.path.join(tempfile.gettempdir(), "MusicLibraryOptimizer", "instances")
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
# DETACHED_PROCESS: the helper must not be attached to the caller's console,
# otherwise the console host tears it down (CTRL_CLOSE_EVENT) the moment the
# app exits -- leaving setup never launched.
_DETACHED_PROCESS = 0x00000008 if os.name == "nt" else 0


def _spawn_survivable(cmd_list):
    """Start a process that keeps running after this app exits.

    ``Win32_Process.Create`` spawns the process as a child of the WMI
    provider service instead of this app, so it survives console teardown
    and process-tree cleanup. The bootstrap is run synchronously so the
    orphan is guaranteed to exist before the caller returns / exits.
    Falls back to a detached Popen when the bootstrap fails.
    """
    cmdline = subprocess.list2cmdline(cmd_list)
    # Escape single quotes for the PowerShell single-quoted string.
    cmdline_ps = cmdline.replace("'", "''")
    ps_code = (
        "Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{CommandLine='" + cmdline_ps + "'} | Out-Null"
    )
    encoded = base64.b64encode(ps_code.encode("utf-16-le")).decode("ascii")
    bootstrap = [
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-EncodedCommand", encoded,
    ]
    try:
        result = subprocess.run(
            bootstrap,
            creationflags=_CREATE_NO_WINDOW | _DETACHED_PROCESS,
            close_fds=True,
            timeout=20,
        )
        if result.returncode != 0:
            raise RuntimeError(f"WMI bootstrap rc={result.returncode}")
    except Exception:
        subprocess.Popen(
            cmd_list,
            creationflags=_CREATE_NO_WINDOW | _DETACHED_PROCESS,
            close_fds=True,
        )


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
    """Return the newest stable (non-draft, non-prerelease) release dict."""
    req = urllib.request.Request(GITHUB_RELEASES_URL, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        releases = json.load(resp)
    best = None
    best_ver = (0, 0, 0)
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        version = _version_tuple(release.get("tag_name", ""))
        if version > best_ver:
            best, best_ver = release, version
    return best


def _find_installer(data):
    """Pick the x64 installer asset, never a portable executable."""
    candidates = []
    for asset in data.get("assets", []):
        name = str(asset.get("name", ""))
        lower = name.lower()
        if not lower.endswith(".exe"):
            continue
        if "setup" in lower or "installer" in lower:
            candidates.append(asset.get("browser_download_url"))
    return next((url for url in candidates if url), None)


def check_for_updates(silent=False, callback=None):
    """Check GitHub for a newer release on a worker thread.

    ``callback`` receives ``(has_update, version, download_url, notes,
    error)`` from the worker thread. Front-ends must marshal UI work through
    their own event queue.
    """
    def worker():
        try:
            data = _fetch_latest_release()
            if data is None:
                result = (False, None, None, "", "No stable releases found")
            else:
                latest = str(data.get("tag_name", "")).lstrip("vV")
                current = _get_current_version()
                download_url = _find_installer(data)
                # A newer tag with no usable installer asset is not an
                # updatable release for this app.
                has_update = _is_newer(latest, current) and bool(download_url)
                notes = (data.get("body") or "").strip()
                result = (has_update, latest, download_url, notes, None)
                if not silent:
                    if has_update:
                        log(f"Update available: v{latest} (current: v{current})",
                            Color.YELLOW)
                    else:
                        log(f"Update check: already on latest version (v{current})",
                            Color.GREEN)
            if callback:
                callback(*result)
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

    threading.Thread(target=worker, daemon=True, name="mlo-update-check").start()


def _download_installer(url):
    if not url or not str(url).lower().startswith("https://"):
        raise ValueError("invalid installer URL")
    path = os.path.join(
        tempfile.gettempdir(),
        f"MusicLibraryOptimizer_Setup_{uuid.uuid4().hex}.exe",
    )
    request = urllib.request.Request(url, headers={"User-Agent": _HEADERS["User-Agent"]})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, open(path, "wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        if os.path.getsize(path) < 64 * 1024:
            raise ValueError("downloaded installer is unexpectedly small")
        with open(path, "rb") as exe:
            if exe.read(2) != b"MZ":
                raise ValueError("downloaded file is not a Windows executable")
        return path
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def download_and_prepare_installer(url, callback=None):
    """Download an installer and report its verified path.

    The callback receives ``(ok, installer_path, error)`` from a worker
    thread. It does not launch the installer while the application is alive.
    """
    def worker():
        try:
            log("Downloading installer...")
            path = _download_installer(url)
            log("Installer downloaded and verified.")
            if callback:
                callback(True, path, None)
        except Exception as e:
            log(f"Installer download failed: {e}", Color.RED)
            if callback:
                callback(False, None, str(e))

    threading.Thread(target=worker, daemon=True, name="mlo-update-download").start()


def _atomic_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def register_instance(pid=None):
    """Register a GUI process so updates can coordinate all instances."""
    pid = int(pid or os.getpid())
    path = os.path.join(_INSTANCE_DIR, f"{pid}.json")
    try:
        _atomic_json(path, {"pid": pid, "busy": False, "updated": time.time()})
        return path
    except OSError:
        return None


def update_instance(path, busy=False, reason=""):
    if not path:
        return
    try:
        _atomic_json(path, {
            "pid": os.getpid(), "busy": bool(busy),
            "reason": str(reason)[:120], "updated": time.time(),
        })
    except OSError:
        pass


def unregister_instance(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _pid_is_running(pid):
    try:
        if os.name == "nt":
            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not process:
                # Cannot open the process (e.g. it is elevated and we are
                # not). Assume it is alive: the wait helper will simply keep
                # waiting until it actually exits or the timeout is reached.
                return True
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(process)
            return code.value == 259
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def registered_instances():
    """Return live instance state records and remove stale records."""
    records = []
    try:
        os.makedirs(_INSTANCE_DIR, exist_ok=True)
        paths = [os.path.join(_INSTANCE_DIR, name)
                 for name in os.listdir(_INSTANCE_DIR) if name.endswith(".json")]
    except OSError:
        return records
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
            pid = int(record.get("pid", 0))
            if pid and _pid_is_running(pid):
                records.append(record)
            else:
                os.remove(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            try:
                os.remove(path)
            except OSError:
                pass
    return records


def app_instance_pids():
    """Return PIDs of registered instances plus visible app windows."""
    pids = {int(record["pid"]) for record in registered_instances()
            if record.get("pid")}
    if os.name != "nt":
        return pids
    try:
        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        get_pid = user32.GetWindowThreadProcessId
        get_pid.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        get_pid.restype = ctypes.c_ulong
        get_text = user32.GetWindowTextW
        get_text.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]

        def visit(hwnd, _):
            title = ctypes.create_unicode_buffer(256)
            get_text(hwnd, title, len(title))
            if title.value.startswith(_APP_TITLE_PREFIX):
                value = ctypes.c_ulong()
                get_pid(hwnd, ctypes.byref(value))
                if value.value:
                    pids.add(value.value)
            return True

        user32.EnumWindows(enum_proc(visit), 0)
    except Exception:
        pass
    return pids


def busy_instance_pids(exclude_pid=None):
    exclude_pid = int(exclude_pid or 0)
    return {
        int(record["pid"]): str(record.get("reason", "working"))
        for record in registered_instances()
        if int(record.get("pid", 0)) != exclude_pid and record.get("busy")
    }


def request_close_instances(pids):
    """Ask other GUI instances to close via WM_CLOSE; never force-kill them."""
    if os.name != "nt":
        return
    targets = {int(pid) for pid in pids}
    if not targets:
        return
    try:
        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        get_pid = user32.GetWindowThreadProcessId
        get_pid.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        get_pid.restype = ctypes.c_ulong

        def visit(hwnd, _):
            value = ctypes.c_ulong()
            get_pid(hwnd, ctypes.byref(value))
            if value.value in targets:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            return True

        user32.EnumWindows(enum_proc(visit), 0)
    except Exception:
        pass


def launch_installer_after_shutdown(installer_path, pids, timeout=180):
    """Launch a hidden helper that waits for every app PID before setup.

    All given PIDs (including the caller's own) are waited on: the caller
    exits right after spawning the helper, so its PID drops off the list
    almost immediately. The helper also deletes the downloaded installer
    once setup has finished.
    """
    if not os.path.isfile(installer_path):
        raise FileNotFoundError(installer_path)
    pids = sorted({int(pid) for pid in pids if int(pid) > 0})
    if os.name != "nt":
        subprocess.Popen([installer_path])
        return

    script = os.path.join(
        tempfile.gettempdir(), f"mlo_update_wait_{uuid.uuid4().hex}.ps1"
    )
    # Avoid @(pipeline) expressions: under "powershell.exe -File" they parse
    # unpredictably in PowerShell 5.1 and collapse to a single value, which
    # would let setup start while app processes are still running.
    script_text = r'''
param([string]$Installer, [string]$Pids = "", [int]$Timeout)
$ids = @()
foreach ($tok in ($Pids -split ' ')) {
    if ($tok -match '^\d+$') { $ids += [int]$tok }
}
$deadline = (Get-Date).AddSeconds($Timeout)
while ((Get-Date) -lt $deadline) {
    $alive = @()
    foreach ($procId in $ids) {
        if (Get-Process -Id $procId -ErrorAction SilentlyContinue) { $alive += $procId }
    }
    if ($alive.Count -eq 0) {
        Start-Process -FilePath $Installer -Wait
        Remove-Item -LiteralPath $Installer -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
        exit 0
    }
    Start-Sleep -Seconds 1
}
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
exit 2
'''
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write(script_text)
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden", "-File", script,
        "-Installer", os.path.abspath(installer_path),
        # Space-separated list: PowerShell 5.1 binds "-Pids a,b" as a
        # single int (commas are a thousands separator), so pass a string.
        "-Pids", " ".join(str(pid) for pid in pids),
        "-Timeout", str(int(timeout)),
    ]
    _spawn_survivable(command)


def maybe_auto_check(callback=None):
    """Run an update check when the configured interval has passed.

    The timestamp is persisted only after GitHub returns a valid release
    response, so network failures do not suppress the next check for a week.
    """
    from .config import load_config, save_config

    config = load_config()
    last = config.get("last_update_check", 0)
    interval = config.get("update_check_interval_days", UPDATE_CHECK_INTERVAL_DAYS)
    if time.time() - last <= interval * 86400:
        return

    def done(has_update, version, url, notes, error):
        if error is None:
            config["last_update_check"] = time.time()
            save_config(config)
        if callback:
            callback(has_update, version, url, notes, error)

    check_for_updates(silent=False, callback=done)
