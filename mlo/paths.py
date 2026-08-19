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


AUDIO_EXTS = (".flac", ".ogg", ".opus", ".aac", ".m4a", ".mp3")


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".jxl")


VALID_EXTENSIONS = IMAGE_EXTS


SKIP_DIRS = {".dependencies"}


JPEG_QUALITY_MARKER = 1


PNG_OPTIMIZATION_LEVEL = 2


DEFAULT_DIGITAL_SOURCE = "Digital"

