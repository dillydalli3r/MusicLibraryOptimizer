"""Auto-detection of external encoder tools in the .dependencies folder."""
import os
import re

from .paths import DEPS_DIR

def _parse_version(s):
    if not s:
        return None
    clean = str(s).strip().lstrip("vV")
    parts = []
    for p in clean.split("."):
        m = re.match(r"(\d+)", p)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts) if parts else None


def _version_is_older(a, b):
    va, vb = _parse_version(a), _parse_version(b)
    if va is None or vb is None:
        return False
    return va < vb


def _detect_tool(prefix, deps_dir):
    if not os.path.isdir(deps_dir):
        return None, None

    cands = []
    for entry in os.listdir(deps_dir):
        full = os.path.join(deps_dir, entry)
        if not os.path.isdir(full):
            continue
        if not entry.lower().startswith(prefix.lower()):
            continue
        m = re.search(r"v?\s*(\d+(?:\.\d+)*)", entry)
        if not m:
            continue
        try:
            v = tuple(int(x) for x in m.group(1).split("."))
        except ValueError:
            continue
        cands.append((v, m.group(1), entry))

    if not cands:
        return None, None

    cands.sort(reverse=True)
    return cands[0][1], cands[0][2]


_TOOLS_CACHE = None
_CACHE_LOCK = __import__("threading").Lock()


def detect_all_tools():
    global _TOOLS_CACHE
    with _CACHE_LOCK:
        if _TOOLS_CACHE is not None:
            return _TOOLS_CACHE

    tools = {}

    if not os.path.isdir(DEPS_DIR):
        with _CACHE_LOCK:
            _TOOLS_CACHE = tools
        return tools

    fv, ff = _detect_tool("flac", DEPS_DIR)
    if ff:
        d = os.path.join(DEPS_DIR, ff)
        if os.path.isfile(os.path.join(d, "flac.exe")):
            tools["flac"] = {
                "version": fv,
                "flac_exe": os.path.join(d, "flac.exe"),
                "metaflac_exe": (
                    os.path.join(d, "metaflac.exe")
                    if os.path.isfile(os.path.join(d, "metaflac.exe"))
                    else None
                ),
            }

    jv, jf = _detect_tool("libjxl", DEPS_DIR)
    if jf:
        d = os.path.join(DEPS_DIR, jf)
        if os.path.isfile(os.path.join(d, "cjxl.exe")):
            tools["libjxl"] = {
                "version": jv,
                "cjxl_exe": os.path.join(d, "cjxl.exe"),
                "djxl_exe": (
                    os.path.join(d, "djxl.exe")
                    if os.path.isfile(os.path.join(d, "djxl.exe"))
                    else None
                ),
            }

    lv, lf = _detect_tool("libjpeg-turbo", DEPS_DIR)
    if lf:
        d = os.path.join(DEPS_DIR, lf)
        if os.path.isfile(os.path.join(d, "jpegtran.exe")):
            tools["libjpeg_turbo"] = {
                "version": lv,
                "jpegtran_exe": os.path.join(d, "jpegtran.exe"),
            }

    ov, of = _detect_tool("oxipng", DEPS_DIR)
    if of:
        d = os.path.join(DEPS_DIR, of)
        if os.path.isfile(os.path.join(d, "oxipng.exe")):
            tools["oxipng"] = {
                "version": ov,
                "oxipng_exe": os.path.join(d, "oxipng.exe"),
            }

    av, af = _detect_tool("audioauditor", DEPS_DIR)
    if af:
        d = os.path.join(DEPS_DIR, af)
        if os.path.isfile(os.path.join(d, "AudioAuditorCLI.exe")):
            tools["audioauditor"] = {
                "version": av,
                "cli_exe": os.path.join(d, "AudioAuditorCLI.exe"),
            }

    rv, rf = _detect_tool("rsgain", DEPS_DIR)
    if rf:
        d = os.path.join(DEPS_DIR, rf)
        if os.path.isfile(os.path.join(d, "rsgain.exe")):
            tools["rsgain"] = {
                "version": rv,
                "rsgain_exe": os.path.join(d, "rsgain.exe"),
            }

    fv2, ff2 = _detect_tool("ffmpeg", DEPS_DIR)
    if ff2:
        d = os.path.join(DEPS_DIR, ff2)
        if (os.path.isfile(os.path.join(d, "ffmpeg.exe"))
                and os.path.isfile(os.path.join(d, "ffprobe.exe"))):
            tools["ffmpeg"] = {
                "version": fv2,
                "ffmpeg_exe": os.path.join(d, "ffmpeg.exe"),
                "ffprobe_exe": os.path.join(d, "ffprobe.exe"),
            }

    pv, pf = _detect_tool("php", DEPS_DIR)
    if pf:
        d = os.path.join(DEPS_DIR, pf)
        if os.path.isfile(os.path.join(d, "php.exe")):
            tools["php"] = {
                "version": pv,
                "php_exe": os.path.join(d, "php.exe"),
            }

    lc_v, lc_f = _detect_tool("logchecker", DEPS_DIR)
    if lc_f:
        d = os.path.join(DEPS_DIR, lc_f)
        phar = os.path.join(d, "logchecker.phar")
        if os.path.isfile(phar):
            tools["logchecker"] = {
                "version": lc_v,
                "phar_path": phar,
                "php_exe": tools.get("php", {}).get("php_exe"),
            }

    with _CACHE_LOCK:
        _TOOLS_CACHE = tools
    return tools


SIMPLE_DR_METER_DIRNAME = "simple-dr-meter"


def simple_dr_meter_path():
    """Path to simple-dr-meter's main.py, or None when not downloaded."""
    candidate = os.path.join(DEPS_DIR, SIMPLE_DR_METER_DIRNAME, "main.py")
    return candidate if os.path.isfile(candidate) else None

