"""Filesystem locations and format constants.

When frozen (PyInstaller) SCRIPT_DIR points at the exe's folder so that
config.json and the .dependencies toolchain live next to the executable.
"""
import os
import sys

if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")


DEPS_DIR = os.path.join(SCRIPT_DIR, ".dependencies")


def ensure_data_dirs():
    """Create .dependencies/ next to the app and verify the app folder is
    writable (so config.json can be saved there). Both the portable and the
    installed versions keep everything in their own folder.

    Returns None when OK, or a human-readable error string when the folder
    is not writable.
    """
    try:
        os.makedirs(DEPS_DIR, exist_ok=True)
        probe = os.path.join(SCRIPT_DIR, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        try:
            os.remove(probe)
        except OSError:
            pass
        return None
    except OSError as e:
        return f"{e}"


AUDIO_EXTS = (".flac", ".ogg", ".opus", ".aac", ".m4a", ".mp3")


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".jxl")


VALID_EXTENSIONS = IMAGE_EXTS


SKIP_DIRS = {".dependencies"}


JPEG_QUALITY_MARKER = 1


PNG_OPTIMIZATION_LEVEL = 2


DEFAULT_DIGITAL_SOURCE = "Digital"

