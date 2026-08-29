#!/usr/bin/env python3
"""MusicLibraryOptimizer system-tray app (Windows taskbar).

Shows a tray icon while the backend runs and provides:
  * Open app (browser)
  * Restart backend
  * Auto-start on login (Windows registry Run key, HKCU — no admin needed)
  * Stop backend + Exit

Launched by "Start Music Library Optimizer.bat". If pystray is missing it
degrades to the plain launcher (start backend + open browser + exit).
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8000
URL = f"http://127.0.0.1:{PORT}"

try:
    import pystray
    from PIL import Image, ImageDraw
    HAVE_TRAY = True
except ImportError:
    HAVE_TRAY = False


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


class Backend:
    """Owns the uvicorn child process (when started by us)."""

    def __init__(self):
        self.proc = None

    def ensure_running(self):
        if port_open(PORT):
            return "already-running"
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.main:app",
             "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=ROOT,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            time.sleep(1)
            if port_open(PORT):
                return "started"
        return "failed"

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
            return True
        return False


backend = Backend()


# --------------------------------------------------------------------------- #
# Auto-start on login (Windows HKCU Run key — per-user, no admin required)
# --------------------------------------------------------------------------- #
AUTOSTART_NAME = "MusicLibraryOptimizer"


def _autostart_command():
    exe = shutil.which("pythonw") or sys.executable
    return f'"{exe}" "{os.path.join(ROOT, "tray.py")}"'


def autostart_enabled():
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, AUTOSTART_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled):
    if os.name != "nt":
        return False
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        if enabled:
            winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(k, AUTOSTART_NAME)
            except FileNotFoundError:
                pass
    return autostart_enabled() == enabled


# --------------------------------------------------------------------------- #
# Tray menu actions
# --------------------------------------------------------------------------- #
def on_open(icon, item):
    webbrowser.open(URL)


def on_restart(icon, item):
    backend.stop()
    time.sleep(1)
    backend.ensure_running()
    webbrowser.open(URL)


def on_autostart(icon, item):
    enabled = autostart_enabled()
    set_autostart(not enabled)


def on_exit(icon, item):
    backend.stop()
    icon.stop()


def _menu():
    items = [
        pystray.MenuItem("Open MusicLibraryOptimizer", on_open, default=True),
        pystray.MenuItem("Restart backend", on_restart),
    ]
    if os.name == "nt":
        items.append(
            pystray.MenuItem(
                "Auto-start on login",
                on_autostart,
                checked=lambda item: autostart_enabled(),
            )
        )
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Exit (stop backend)", on_exit))
    return pystray.Menu(*items)


def make_icon():
    size = 64
    img = Image.new("RGBA", (size, size), (10, 10, 12, 255))
    d = ImageDraw.Draw(img)
    heights = (0.30, 0.36, 0.44, 0.58, 0.74, 0.88, 0.97)
    colors = [(139, 92, 246), (124, 58, 237), (99, 102, 241), (79, 70, 229),
              (67, 56, 202), (55, 48, 163), (49, 46, 129)]
    margin = size * 0.12
    gap = size * 0.03
    bar_w = (size - 2 * margin - (len(heights) - 1) * gap) / len(heights)
    base_y = size - margin
    for i, (h, c) in enumerate(zip(heights, colors)):
        x0 = margin + i * (bar_w + gap)
        bar_h = h * (size - 2 * margin)
        d.rectangle([x0, base_y - bar_h, x0 + bar_w, base_y], fill=c + (255,))
    return img


def run_tray():
    status = backend.ensure_running()
    if status == "failed":
        # no console on pythonw — fall back to a spawned console for errors
        try:
            subprocess.Popen(["cmd", "/c", "echo Backend failed to start & pause"],
                             creationflags=0x08000000)
        except Exception:
            pass
        return
    icon = pystray.Icon("MusicLibraryOptimizer", make_icon(),
                        "MusicLibraryOptimizer — backend running",
                        menu=_menu())
    if status == "started":
        threading.Thread(target=lambda: (time.sleep(2), webbrowser.open(URL)),
                         daemon=True).start()
    icon.run()


def run_plain():
    """Fallback when pystray is unavailable."""
    status = backend.ensure_running()
    webbrowser.open(URL)
    if status == "failed":
        print("Backend failed to start — run `python -m uvicorn server.main:app` "
              "to see errors.")


if __name__ == "__main__":
    if HAVE_TRAY:
        run_tray()
    else:
        run_plain()