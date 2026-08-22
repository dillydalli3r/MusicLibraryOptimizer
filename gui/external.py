"""Auto-detection and launching of external taggers / players."""
import os
import shutil
import subprocess
import sys

EXTERNAL_TOOLS = {
    "mp3tag": {
        "label": "Mp3tag",
        "exe": "Mp3tag.exe",
        "which": ("mp3tag", "Mp3tag"),
        "dirs": (
            r"C:\Program Files\Mp3tag",
            r"C:\Program Files (x86)\Mp3tag",
        ),
        "config_key": "mp3tag_path",
        "args": [],
    },
    "picard": {
        "label": "MusicBrainz Picard",
        "exe": "picard.exe",
        "which": ("picard",),
        "dirs": (
            r"C:\Program Files\MusicBrainz Picard",
            r"C:\Program Files (x86)\MusicBrainz Picard",
            os.path.expandvars(r"%LocalAppData%\Programs\MusicBrainz Picard"),
        ),
        "config_key": "picard_path",
        "args": [],
    },
    "foobar2000": {
        "label": "foobar2000",
        "exe": "foobar2000.exe",
        "which": ("foobar2000",),
        "dirs": (
            r"C:\Program Files\foobar2000",
            r"C:\Program Files (x86)\foobar2000",
            r"C:\Program Files\foobar2000 (x64)",
        ),
        "config_key": "foobar2000_path",
        # /add enqueues the given files/folders into the current playlist.
        "args": ["/add"],
    },
}


def _registry_app_path(exe_name):
    """Look up HKLM/HKCU App Paths registration for an executable."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        subkey = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, subkey) as k:
                    value, _ = winreg.QueryValueEx(k, None)
                    if value and os.path.isfile(value):
                        return value
            except OSError:
                continue
    except Exception:
        pass
    return None


def find_external_tool(key, config=None):
    """Locate an external tagger exe: config override, registry App
    Paths, common install dirs, then PATH. None when not found."""
    spec = EXTERNAL_TOOLS[key]
    cfg_path = (config or {}).get(spec["config_key"], "")
    if cfg_path and os.path.isfile(cfg_path):
        return cfg_path

    found = _registry_app_path(spec["exe"])
    if found:
        return found

    for d in spec["dirs"]:
        candidate = os.path.join(d, spec["exe"])
        if os.path.isfile(candidate):
            return candidate

    for name in spec["which"]:
        found = shutil.which(name)
        if found:
            return found

    return None


def launch_external(key, dirs, config, log, parent=None):
    """Launch the tool with the given directories. Returns (ok, exe).

    `log` receives (message, tag) tuples for the console/status area.
    """
    spec = EXTERNAL_TOOLS[key]
    label = spec["label"]

    if not dirs:
        log(f"{label}: nothing selected. Check one or more albums (or "
            f"artists) in the library tree first.", "yellow")
        return False, None

    exe = find_external_tool(key, config)
    if not exe:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        ret = QMessageBox.question(
            parent, f"{label} not found",
            f"{label} could not be located automatically.\n\n"
            f"Locate the {spec['exe']} executable manually?")
        if ret != QMessageBox.StandardButton.Yes:
            return False, None
        exe, _ = QFileDialog.getOpenFileName(
            parent, f"Locate {spec['exe']}", "",
            "Executable (*.exe);;All files (*.*)")
        if not exe:
            return False, None
        config[spec["config_key"]] = os.path.normpath(exe)
        from mlo import save_config
        save_config(config)
        log(f"{label} path saved: {exe}", "muted")

    try:
        subprocess.Popen(
            [exe] + spec.get("args", []) + list(dirs),
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
    except Exception as e:
        log(f"Could not launch {label}: {e}", "red")
        return False, exe

    n = len(dirs)
    verb = "Enqueued" if spec.get("args") else "Opened"
    plural = "s" if n != 1 else ""
    log(f"{verb} {n} folder{plural} in {label}.", "green")
    return True, exe
