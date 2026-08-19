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


def detect_all_tools():
    global _TOOLS_CACHE
    if _TOOLS_CACHE is not None:
        return _TOOLS_CACHE

    tools = {}

    if not os.path.isdir(DEPS_DIR):
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

    _TOOLS_CACHE = tools
    return tools

