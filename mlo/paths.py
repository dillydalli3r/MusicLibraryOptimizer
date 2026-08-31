"""Filesystem locations and format constants.

When frozen (PyInstaller) SCRIPT_DIR points at the exe's folder so that
config.json and the .dependencies toolchain live next to the executable.
"""
import os
import sys

# Marker written next to a PATH-installed CLI; first line is the folder
# that holds config.json and .dependencies.
HOME_MARKER = "mlo-home.txt"


def _resolve_script_dir():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    marker = os.path.join(base, HOME_MARKER)
    if os.path.isfile(marker):
        try:
            with open(marker, "r", encoding="utf-8-sig") as f:
                home = f.readline().strip()
            if home and os.path.isdir(home):
                return home
        except OSError:
            pass
    return base


SCRIPT_DIR = _resolve_script_dir()


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

# All image types that Pillow can read and that we can convert to JPEG/PNG
# Lossy types: jpg, jpeg, webp (lossy), avif, heic, heif
# Lossless types: png, bmp, gif, tiff, tif, webp (lossless), ppm, pgm, pbm, avif (lossless)
ALL_IMAGE_EXTS = (
    ".jpg", ".jpeg", ".png", ".jxl",
    ".bmp", ".gif", ".tiff", ".tif", ".webp", ".avif", ".heic", ".heif",
    ".ppm", ".pgm", ".pbm", ".svg",
)

# Lossless source types that we consider for lossless-to-PNG conversion
LOSSLESS_IMAGE_EXTS = (".png", ".bmp", ".gif", ".tiff", ".tif", ".ppm", ".pgm", ".pbm")

VALID_EXTENSIONS = IMAGE_EXTS
CONVERTIBLE_EXTENSIONS = ALL_IMAGE_EXTS

# Sidecar track covers: for a track like "01 - Song.flac" a sidecar cover
# is an image file in the same album folder with the same basename but an
# image extension, e.g. "01 - Song.jpg" / ".png" / ".jxl". This lets a few
# tracks have their own art while the rest fall back to the album cover.*.
SIDECAR_COVER_EXTS = IMAGE_EXTS


def get_sidecar_cover_path(album_dir, track_filename):
    """Return the sidecar cover path for a track if it exists, else None.

    Checks for an image file in *album_dir* whose basename matches the track's
    basename (without extension) and whose extension is in SIDECAR_COVER_EXTS.
    Case-insensitive, first match wins in SIDECAR_COVER_EXTS order.
    """
    base = os.path.splitext(track_filename)[0]
    # Also handle track_filename that may already be a full path
    base = os.path.basename(base)
    for ext in SIDECAR_COVER_EXTS:
        cand = os.path.join(album_dir, base + ext)
        # Case-insensitive check on Windows, but be explicit for cross-platform
        if os.path.isfile(cand):
            return cand
        # Try case-insensitive glob if exact case fails (e.g. .JPG vs .jpg)
        try:
            for f in os.listdir(album_dir):
                if f.lower() == (base + ext).lower():
                    cand2 = os.path.join(album_dir, f)
                    if os.path.isfile(cand2):
                        return cand2
        except OSError:
            pass
    return None


def is_sidecar_cover_file(album_dir, filename, all_track_basenames=None):
    """Whether *filename* in *album_dir* is a sidecar track cover.

    *filename* is a single filename (e.g. "01 - Song.jpg"). It is a sidecar
    if its basename (without ext) matches any track basename in the album
    (minus extension) and its extension is an image type. The album's
    standard cover.* files are *not* considered sidecars.
    """
    low = filename.lower()
    if low in ("cover.jpg", "cover.jpeg", "cover.png", "cover.jxl"):
        return False
    base, ext = os.path.splitext(filename)
    if ext.lower() not in SIDECAR_COVER_EXTS:
        return False
    if all_track_basenames is None:
        return True  # conservative: any image that is not cover.* could be sidecar
    return base.lower() in {b.lower() for b in all_track_basenames}


SKIP_DIRS = {".dependencies", ".mlo_trash", "__pycache__", "$RECYCLE.BIN",
             "System Volume Information", ".git", ".thumbnails", ".tmp"}


JPEG_QUALITY_MARKER = 1


PNG_OPTIMIZATION_LEVEL = 2


DEFAULT_DIGITAL_SOURCE = "Digital"

