#!/usr/bin/env python3
"""
Music Library Optimizer - Desktop Application
=============================================
Modern dark-themed GUI front-end for the `mlo` core package.

Layout
------
    mlo/            organized core package (all processing logic)
    app.py          this GUI entry point
    config.json     persisted settings (created on first save)
    .dependencies/  external encoder toolchain (flac, libjxl,
                    libjpeg-turbo, oxipng)

Requires:  pip install mutagen
Optional:  pip install Pillow tqdm
"""

import os
import re
import shutil
import subprocess
import sys
import queue
import time
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

from mlo import (
    load_config, save_config,
    run_format_lyrics, run_format_cues, run_optimize_flacs,
    run_grade_library, run_process_images, run_audit_library,
)
from mlo import stats as stats_mod
from mlo import tools as tools_mod
from mlo import fetchdeps
from mlo import updater
from mlo.config import DEFAULT_CONFIG
from mlo.paths import DEFAULT_DIGITAL_SOURCE, DEPS_DIR, SCRIPT_DIR
from mlo.deps import HAS_MUTAGEN, HAS_PIL
from mlo.report import print_results, print_grade_results, print_combined_results
from mlo.ui import set_file_lines

SCRIPT_NAMES = {
    1: "Format Lyrics",
    2: "Format CUEs",
    3: "Optimize FLACs",
    4: "Grade Library",
    5: "Process Images",
    6: "Audit Library",
}

RUNNERS = {
    1: ("Format Lyrics", run_format_lyrics),
    2: ("Format CUEs", run_format_cues),
    3: ("Optimize FLACs", run_optimize_flacs),
    4: ("Grade Library", run_grade_library),
    5: ("Process Images", run_process_images),
    6: ("Audit Library", run_audit_library),
}

# Tag keys offered by the "Add tag" menu of the full tag editor.
# Display name -> raw container key (vorbis-friendly names; ID3 IDs and
# MP4 atoms included for the container-aware user).
COMMON_TAGS = [
    ("Title", "TITLE"), ("Album", "ALBUM"), ("Artist", "ARTIST"),
    ("Album Artist", "ALBUMARTIST"), ("Track Number", "TRACKNUMBER"),
    ("Disc Number", "DISCNUMBER"), ("Genre", "GENRE"),
    ("Date", "DATE"), ("Year", "YEAR"), ("Composer", "COMPOSER"),
    ("Lyricist", "LYRICIST"), ("Copyright", "COPYRIGHT"),
    ("Comment", "COMMENT"), ("Lyrics", "LYRICS"), ("BPM", "BPM"),
    ("Media", "MEDIA"), ("Source", "SOURCE"),
    ("Instrumental (0/1)", "INSTRUMENTAL"),
    ("iTunes Advisory (0/1)", "ITUNESADVISORY"),
    ("ReplayGain Track Gain", "REPLAYGAIN_TRACK_GAIN"),
    ("ReplayGain Track Peak", "REPLAYGAIN_TRACK_PEAK"),
    ("ReplayGain Album Gain", "REPLAYGAIN_ALBUM_GAIN"),
    ("ReplayGain Album Peak", "REPLAYGAIN_ALBUM_PEAK"),
]
RAW_TAGS = [
    ("ID3 TIT2", "TIT2"), ("ID3 TALB", "TALB"), ("ID3 TPE1", "TPE1"),
    ("ID3 TPE2", "TPE2"), ("ID3 TRCK", "TRCK"), ("ID3 TPOS", "TPOS"),
    ("ID3 TCON", "TCON"), ("ID3 TDRC", "TDRC"), ("ID3 TCOM", "TCOM"),
    ("MP4 \u00a9nam", "\u00a9nam"), ("MP4 \u00a9alb", "\u00a9alb"),
    ("MP4 \u00a9ART", "\u00a9ART"), ("MP4 \u00a9day", "\u00a9day"),
    ("MP4 \u00a9gen", "\u00a9gen"), ("MP4 \u00a9wrt", "\u00a9wrt"),
    ("MP4 \u00a9cmt", "\u00a9cmt"), ("MP4 \u00a9lyr", "\u00a9lyr"),
]

# Library tree columns: id -> (heading, width, visible-by-default).
# The TAGS heading doubles as the key for its compact layout:
# G=Genre A=Advisory I=Instrumental L=Lyrics AA=Album Advisory.
TREE_COLUMNS = {
    "grade": ("GRADE", 74, True),
    "audit": ("AUDIT", 80, True),
    "checks": ("CHECKS", 88, False),
    "tracks": ("TRACKS", 58, True),
    "media": ("MEDIA", 100, True),
    "cover": ("COVER", 110, True),
    "tags": ("TAGS · G A I L AA", 300, True),
}

CONFIG_FIELDS = [
    # (key, label, kind, extra)
    ("flac_level", "FLAC Level (0-8)", "int", (0, 8)),
    ("add_seektables", "Add SeekTables", "bool", None),
    ("force_reencode_flac", "Force Re-encode FLACs", "bool", None),
    ("jpegxl_effort", "JPEG XL Effort (1-10)", "int", (1, 10)),
    ("reencode_images", "Re-encode Images", "bool", None),
    ("reencode_to_jxl", "Re-encode to JXL", "bool", None),
    ("convert_jxl_back", "Convert JXL Back to JPEG/PNG", "bool", None),
    ("rename_to_cover", "Rename Images to cover.<ext>", "bool", None),
    ("remove_alpha", "Remove Alpha from PNGs", "bool", None),
    ("force_reencode_images", "Force Re-encode Images", "bool", None),
    ("optimize_lrc", "Optimize LRC Files", "bool", None),
    ("optimize_embedded_lyrics", "Optimize Embedded Lyrics", "bool", None),
    ("lyrics_format", "Lyrics Format", "choice", ("EMBEDDED", "LRC", "BOTH")),
    ("keep_empty_cue_lines", "Keep Empty CUE Lines", "bool", None),
    ("keep_other_cue_lines", "Keep Other CUE Lines", "bool", None),
    ("normalize_media_source", "Normalize MEDIA/SOURCE", "bool", None),
    ("digital_media_source_value", "Digital SOURCE Value", "str", None),
    ("grade_verbose", "Grade Verbose Output", "bool", None),
    ("audit_thorough", "Thorough Audit (slower)", "bool", None),
    ("force_audit", "Force Audit (ignore AUDIT tags)", "bool", None),
    ("audit_cutoff_allow", "Audit Cutoff Allowance (Hz, 0=default)", "int", (0, 24000)),
    ("audit_clipping", "Audit Clipping Detection", "bool", None),
    ("audit_mqa", "Audit MQA Detection", "bool", None),
    ("audit_ai", "Audit AI Detection", "bool", None),
    ("audit_fake_stereo", "Audit Fake Stereo Detection", "bool", None),
    ("audit_silence", "Audit Silence Detection", "bool", None),
    ("audit_dynamic_range", "Audit Dynamic Range", "bool", None),
    ("audit_true_peak", "Audit True Peak", "bool", None),
    ("audit_lufs", "Audit LUFS", "bool", None),
    ("audit_bpm", "Audit BPM", "bool", None),
    ("auto_advance", "Auto-Advance Between Scripts", "bool", None),
    ("run_all_order", "Run All Order", "choice", None),
    ("compact_ui", "Compact UI Mode", "bool", None),
]

# ----------------------------------------------------------------------
# Palette (black & white)
# ----------------------------------------------------------------------
BG = "#0d0d0d"          # window background
PANEL = "#141414"       # raised panels / header / status bar
SIDEBAR = "#101010"     # sidebar
CARD = "#161616"        # card surfaces (tree / console)
FIELD = "#1a1a1a"       # entry fields / console
BORDER = "#262626"
BORDER_STRONG = "#333333"
TEXT = "#e8e8e8"
BRIGHT = "#ffffff"
MUTED = "#8f8f8f"
ACCENT = "#f2f2f2"
ACCENT_DARK = "#3a3a3a"
GREEN = "#8ccf6a"
RED = "#e06c75"
YELLOW = "#d8b25e"

UI_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"


def _pick_ui_family():
    """Prefer Segoe UI Variable (Windows 11) with a safe fallback."""
    try:
        families = set(tkfont.families())
        for name in ("Segoe UI Variable Text", "Segoe UI Variable"):
            if name in families:
                return name
    except Exception:
        pass
    return "Segoe UI"


def _font(size=10, weight="normal"):
    return (UI_FAMILY, size, weight)


def _sfont(size=10):
    """Semibold variant of the UI family (synthesized when needed)."""
    if UI_FAMILY.startswith("Segoe UI"):
        return ("Segoe UI Semibold", size)
    return (UI_FAMILY, size, "bold")


# ----------------------------------------------------------------------
# External tagging tools (Mp3tag / MusicBrainz Picard)
# ----------------------------------------------------------------------
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
    """Locate an external tagger exe: config override, registry App Paths,
    common install dirs, then PATH. Returns None when not found."""
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


ANSI_TAG = {
    "0": "fg", "1": "bold", "90": "grey", "91": "red", "92": "green",
    "93": "yellow", "94": "blue", "95": "magenta", "96": "cyan",
}
ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")
ANSI_PARTIAL_RE = re.compile(r"\x1b\[([0-9;]*)$")


def apply_window_chrome(widget, bg=BG, border=BORDER):
    """Dark-mode title bar that matches the app palette.

    Uses the undocumented-but-stable DWM window attributes available on
    Windows 10 2004+ / Windows 11: immersive dark mode, exact caption and
    border colors, and title text color. Silently no-ops elsewhere.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        hwnd = ctypes.windll.user32.GetParent(widget.winfo_id())

        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
            value = ctypes.c_int(1)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4) == 0:
                break

        def color_ref(hexstr):
            # Windows COLORREFs are 0x00BBGGRR.
            r = int(hexstr[1:3], 16)
            g = int(hexstr[3:5], 16)
            b = int(hexstr[5:7], 16)
            return ctypes.c_int(r | (g << 8) | (b << 16))

        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color_ref(bg)), 4)
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(color_ref(TEXT)), 4)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(color_ref(border)), 4)
    except Exception:
        pass


class QueueStream:
    """File-like object that parses ANSI colors and feeds the GUI queue."""

    def __init__(self, q):
        self.q = q
        self.buf = ""
        self.tag = "fg"
        # True when a queued "out" chunk still owes its implicit newline:
        # lets a standalone print() (write("\n")) render a blank line
        # instead of being silently discarded.
        self._line_pending = False

    def write(self, s):
        if not s:
            self.q.put(("nl", None))
            return 0
        if s == "\n":
            if self._line_pending:
                self._line_pending = False
                return len(s)
            self.q.put(("nl", None))
            return len(s)

        self.buf += s.replace("\r\n", "\n").replace("\r", "")

        # Hold back a trailing incomplete escape sequence for the next write.
        hold = ""
        m = ANSI_PARTIAL_RE.search(self.buf)
        if m:
            hold = m.group(0)
            self.buf = self.buf[: m.start()]

        segments = []
        pos = 0
        for m2 in ANSI_RE.finditer(self.buf):
            if m2.start() > pos:
                segments.append((self.buf[pos: m2.start()], self.tag))
            codes = [c for c in m2.group(1).split(";") if c]
            new_tag = "fg"
            for code in codes:
                if code in ANSI_TAG:
                    new_tag = ANSI_TAG[code]
            self.tag = new_tag
            pos = m2.end()

        if pos < len(self.buf):
            segments.append((self.buf[pos:], self.tag))

        self.buf = hold
        if segments:
            self._line_pending = True
            self.q.put(("out", segments))
        return len(s)

    def flush(self):
        pass


# ======================================================================
# Tooltips
# ======================================================================
class ToolTip:
    """Minimal dark tooltip attached to a widget."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<Destroy>", self._hide, add="+")

    def _show(self, _=None):
        if self.tip or not self.text:
            return
        if not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self.text, justify=tk.LEFT, wraplength=400,
            background="#202020", foreground=TEXT,
            padx=10, pady=6, font=_font(9),
        ).pack()

    def _hide(self, _=None):
        if self.tip:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


def _blend(c1, c2, t):
    """Linear blend between two #rrggbb colors, t in [0, 1]."""
    def parse(c):
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    r1, g1, b1 = parse(c1)
    r2, g2, b2 = parse(c2)
    return "#{:02x}{:02x}{:02x}".format(
        round(r1 + (r2 - r1) * t),
        round(g1 + (g2 - g1) * t),
        round(b1 + (b2 - b1) * t),
    )


class ToggleSwitch(tk.Canvas):
    """Pill-style boolean toggle used for every on/off setting.

    Replaces ttk checkbuttons, whose small indicators render
    inconsistently on dark clam themes and look lost inside wide grid
    columns. Bound two-way to a tk.BooleanVar; animates between states.
    """

    WIDTH, HEIGHT, PAD = 42, 22, 3
    KNOB = "#ffffff"
    TRACK_OFF = "#2f2f2f"

    def __init__(self, master, variable, bg=CARD, command=None):
        super().__init__(
            master, width=self.WIDTH, height=self.HEIGHT,
            highlightthickness=0, background=bg, cursor="hand2",
        )
        self.variable = variable
        self.command = command
        self._target = 1.0 if variable.get() else 0.0
        self._pos = self._target
        self._anim_job = None
        self._trace = variable.trace_add("write", self._on_var_write)
        self.bind("<Button-1>", lambda e: self._toggle())
        self.bind("<Destroy>", lambda e: self._cleanup(), add="+")
        self._draw()

    def _cleanup(self):
        try:
            self.variable.trace_remove("write", self._trace)
        except Exception:
            pass

    def _toggle(self):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _on_var_write(self, *_):
        self._target = 1.0 if self.variable.get() else 0.0
        if self._anim_job is None:
            self._step()

    def _step(self):
        delta = self._target - self._pos
        if abs(delta) < 0.02:
            self._pos = self._target
            self._anim_job = None
        else:
            self._pos += delta * 0.35
            self._anim_job = self.after(12, self._step)
        self._draw()

    def _draw(self):
        self.delete("all")
        p = self.PAD
        x1, y1 = p, p
        x2, y2 = self.WIDTH - p, self.HEIGHT - p
        r = (y2 - y1) / 2

        track = _blend(self.TRACK_OFF, ACCENT, self._pos)
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=track, outline=track)
        self.create_oval(x1, y1, x1 + 2 * r, y2, fill=track, outline=track)
        self.create_oval(x2 - 2 * r, y1, x2, y2, fill=track, outline=track)

        kx = x1 + self._pos * (x2 - 2 * r - x1)
        self.create_oval(kx, y1, kx + 2 * r, y2, fill=self.KNOB, outline="")


FIELD_DESCRIPTIONS = {
    "music_folder":
        "Root folder scanned recursively by every script.",
    "flac_level":
        "flac.exe compression level 0-8. Higher levels produce smaller "
        "files at the cost of encoding speed.",
    "add_seektables":
        "When off (default), SEEKTABLE blocks are actively removed from "
        "FLAC files to save space.",
    "force_reencode_flac":
        "Re-encode every FLAC even when its ENCODER marker tags say it is "
        "already optimized. Slow — normally unnecessary.",
    "jpegxl_effort":
        "cjxl encoding effort 1-10. Higher effort compresses better but "
        "takes much longer.",
    "reencode_images":
        "Master switch for image processing. When off, the Process Images "
        "script does nothing.",
    "reencode_to_jxl":
        "Convert JPEG/PNG covers losslessly to JPEG XL (.jxl). When off, "
        "JPEG/PNG are optimized in place instead.",
    "convert_jxl_back":
        "Convert existing .jxl files back to JPEG/PNG (djxl + "
        "jpegtran/oxipng). Useful for player compatibility.",
    "rename_to_cover":
        "Rename every processed image to cover.<ext> in its album folder.",
    "remove_alpha":
        "Flatten alpha transparency out of PNG images before encoding. "
        "Requires Pillow.",
    "force_reencode_images":
        "Reprocess images even when their ENCODER marker tags are current.",
    "optimize_lrc":
        "Clean and normalize .lrc lyric sidecar files (timestamps, blank "
        "lines, metadata removal).",
    "optimize_embedded_lyrics":
        "Clean embedded LYRICS tags the same way.",
    "lyrics_format":
        "Where lyrics should live: EMBEDDED in tags, LRC sidecar files, or "
        "BOTH. Conversion happens during Format Lyrics.",
    "keep_empty_cue_lines":
        "Preserve blank lines when formatting .cue files.",
    "keep_other_cue_lines":
        "Preserve non-standard CUE lines (PREGAP, REM, etc.) instead of "
        "dropping them.",
    "normalize_media_source":
        "Enforce the MEDIA/SOURCE rule: albums with MEDIA 'Digital Media' "
        "must have SOURCE populated; all other albums must not have SOURCE.",
    "digital_media_source_value":
        "Fallback SOURCE value written on Digital Media albums whose tracks "
        "are missing SOURCE. Existing values are never overwritten.",
    "grade_verbose":
        "Include the per-track tag dump in grading reports.",
    "audit_thorough":
        "Audit Library: enable AudioAuditor's full-track detectors "
        "(silence, dynamic range, true peak, LUFS, BPM). Much slower than "
        "the default fast scan but produces deeper metrics.",
    "force_audit":
        "Audit Library: re-audit files that already carry an AUDIT tag "
        "and re-score rip logs even when LOG_GRADE is present. The "
        "Force ▾ menu in the Library tab sets this per-run.",
    "audit_cutoff_allow":
        "AudioAuditor's --cutoff-allow threshold in Hz. Files whose "
        "spectral cutoff is at or above this value are NOT flagged as "
        "fake. 0 = use the CLI default (19600 Hz). Raise it (e.g. 20000) "
        "if genuine HD masters are being misread as transcoded lossy.",
    "audit_clipping":
        "Audit: detect clipped samples (--no-clipping when off). "
        "Loud modern masters often clip at the true-peak ceiling and are "
        "still genuine lossless; turn this off to stop 'clipping' warnings.",
    "audit_mqa":
        "Audit: detect MQA encoding markers (--no-mqa when off).",
    "audit_ai":
        "Audit: detect AI-generated audio via the standard watermark "
        "detector (--no-ai when off). Can false-positive on well-mastered "
        "digital sources.",
    "audit_fake_stereo":
        "Audit: detect fake stereo (mono upmixed to stereo) "
        "(--no-fake-stereo when off).",
    "audit_silence":
        "Audit: detect excessive silence (--no-silence when off). Quiet "
        "passages in classical/ambient music can trigger false warnings.",
    "audit_dynamic_range":
        "Audit: measure dynamic range (--no-dynamic-range when off). "
        "Only used in Thorough mode.",
    "audit_true_peak":
        "Audit: measure true-peak levels (--no-true-peak when off). "
        "Only used in Thorough mode.",
    "audit_lufs":
        "Audit: measure integrated loudness LUFS (--no-lufs when off). "
        "Only used in Thorough mode.",
    "audit_bpm":
        "Audit: detect BPM (--no-bpm when off). Only used in Thorough "
        "mode.",
    "auto_advance":
        "Sequence runs (Run All / custom): when off, the app pauses for "
        "confirmation between scripts — the GUI shows a Continue button.",
    "run_all_order":
        "Execution order used by the Run All button.",
}


# ======================================================================
# Dependencies manager dialog
# ======================================================================
class DependenciesDialog(tk.Toplevel):
    """Download / update the external toolchain from GitHub."""

    KEYS = ("flac", "libjxl", "libjpeg_turbo", "oxipng", "audioauditor")

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Dependencies")
        self.configure(background=PANEL)
        self.transient(app)
        self.grab_set()
        self.minsize(720, 440)
        self.busy = False
        self.q = queue.Queue()
        self.latest = {}

        outer = ttk.Frame(self, padding=18)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="Toolchain", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Downloads the latest official Windows builds from GitHub "
                 "releases into the .dependencies folder next to the app. "
                 "AudioAuditor provides the Audit Library script.",
            style="Muted.TLabel", wraplength=660, justify=tk.LEFT,
        ).pack(anchor="w", pady=(2, 12))

        grid = ttk.Frame(outer)
        grid.pack(fill=tk.X)
        for col, width in ((0, 26), (1, 16), (2, 16), (3, 14), (4, 28)):
            grid.columnconfigure(col, minsize=width)

        headers = ("Tool", "Installed", "Latest", "", "Status")
        for col, text in enumerate(headers):
            ttk.Label(grid, text=text.upper(), style="Section.TLabel").grid(
                row=0, column=col, sticky="w", padx=6, pady=(0, 6)
            )

        self.rows = {}
        installed = fetchdeps.installed_versions()
        for i, key in enumerate(self.KEYS, start=1):
            inst = installed.get(key, "")
            self.rows[key] = {
                "installed": tk.StringVar(value=inst or "—"),
                "latest": tk.StringVar(value="…"),
                "status": tk.StringVar(value=""),
                "button": None,
                "installed_version": inst,
            }
            row = self.rows[key]
            ttk.Label(grid, text=fetchdeps.DISPLAY_NAMES[key]).grid(
                row=i, column=0, sticky="w", padx=6, pady=3
            )
            ttk.Label(grid, textvariable=row["installed"],
                      foreground=GREEN if inst else MUTED).grid(
                row=i, column=1, sticky="w", padx=6, pady=3
            )
            ttk.Label(grid, textvariable=row["latest"]).grid(
                row=i, column=2, sticky="w", padx=6, pady=3
            )
            btn = ttk.Button(grid, text="…", width=10,
                             command=lambda k=key: self._install([k]))
            btn.grid(row=i, column=3, sticky="w", padx=6, pady=3)
            row["button"] = btn
            ttk.Label(grid, textvariable=row["status"],
                      foreground=MUTED).grid(
                row=i, column=4, sticky="w", padx=6, pady=3
            )

        btns = ttk.Frame(outer)
        btns.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(btns, text="Install / Update All",
                   style="Accent.TButton",
                   command=lambda: self._install(list(self.KEYS))).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Refresh",
                   command=self._check_latest).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btns, text="Open Folder",
                   command=self._open_folder).pack(side=tk.RIGHT, padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, lambda: apply_window_chrome(self))
        self.after(120, self._poll)
        self._check_latest()

    # ------------------------------------------------------------------
    def _on_close(self):
        if self.busy:
            if not messagebox.askyesno(
                "Download in progress",
                "A download is still running. Close anyway? The remaining "
                "tools will not be installed.", parent=self,
            ):
                return
        self.destroy()

    def _open_folder(self):
        if os.path.isdir(DEPS_DIR):
            os.startfile(DEPS_DIR)
        else:
            messagebox.showinfo(
                "Not created yet", "The .dependencies folder does not exist yet.",
                parent=self,
            )

    def _set_busy(self, flag):
        self.busy = flag
        state = tk.DISABLED if flag else tk.NORMAL
        for row in self.rows.values():
            row["button"].configure(state=state)

    def _check_latest(self):
        def work():
            try:
                self.q.put(("latest", fetchdeps.latest_versions()))
            except Exception as e:
                self.q.put(("neterr", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _install(self, keys):
        if self.busy:
            return

        def work():
            self.q.put(("busy", True))
            for key in keys:
                name = fetchdeps.DISPLAY_NAMES[key]
                self.q.put(("status", key, "Downloading…", TEXT))
                try:
                    def prog(done, total, _name=name):
                        self.app.log_q.put(
                            ("prog", (done, total, f"Downloading {_name}"))
                        )
                    version = fetchdeps.install_dependency(
                        key,
                        log=lambda m: self.app.log(m, tag="muted"),
                        progress=prog,
                    )
                    self.q.put(("installed", key, version))
                except Exception as e:
                    self.app.log(f"Dependency install failed ({name}): {e}",
                                 tag="red")
                    self.q.put(("fail", key, str(e)))
            fetchdeps.refresh_tool_cache()
            self.q.put(("busy", False))
        threading.Thread(target=work, daemon=True).start()

    def _row_button_text(self, key):
        row = self.rows[key]
        inst = row["installed_version"]
        latest = self.latest.get(key)
        if not inst:
            return "Download"
        if latest and tools_mod._version_is_older(inst, latest):
            return "Update"
        return "Reinstall"

    def _poll(self):
        try:
            while True:
                kind, *payload = self.q.get_nowait()
                if kind == "latest":
                    self.latest = payload[0]
                    for key in self.KEYS:
                        self.rows[key]["latest"].set(self.latest.get(key, "?"))
                        self.rows[key]["button"].configure(
                            text=self._row_button_text(key)
                        )
                elif kind == "neterr":
                    for key in self.KEYS:
                        self.rows[key]["latest"].set("unavailable")
                        self.rows[key]["status"].set("")
                    self.app.log(
                        f"Could not query GitHub for latest versions: {payload[0]}",
                        tag="yellow",
                    )
                elif kind == "status":
                    key, text, color = payload
                    self.rows[key]["status"].set(text)
                elif kind == "installed":
                    key, version = payload
                    row = self.rows[key]
                    row["installed_version"] = version
                    row["installed"].set(version)
                    row["status"].set("Installed")
                    row["button"].configure(text=self._row_button_text(key))
                    self.app._update_dep_label()
                elif kind == "fail":
                    key, err = payload
                    self.rows[key]["status"].set(f"Failed: {err[:60]}")
                elif kind == "busy":
                    self._set_busy(payload[0])
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(120, self._poll)


# ======================================================================
# Configuration dialog
# ======================================================================
class ConfigDialog(tk.Toplevel):
    def __init__(self, parent, config, on_saved):
        super().__init__(parent)
        self.config = config
        self.on_saved = on_saved
        self.vars = {}

        self.title("Settings")
        self.configure(background=PANEL)
        self.transient(parent)
        self.grab_set()
        self.minsize(760, 640)

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0, background=PANEL)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas, style="Panel.TFrame")

        inner.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        # Keep the content frame as wide as the canvas so rows stretch
        # when the dialog is resized (otherwise everything stays at the
        # initial requested width).
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(inner_id, width=e.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        canvas.bind(
            "<Enter>",
            lambda e: canvas.bind_all(
                "<MouseWheel>",
                lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units"),
            ),
        )
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # --- Library folder -------------------------------------------------
        row = 0
        folder_header = ttk.Label(inner, text="Library Folder", style="H2.Panel.TLabel")
        folder_header.grid(row=row, column=0, sticky="w", padx=5, pady=(0, 4))
        ToolTip(folder_header, FIELD_DESCRIPTIONS["music_folder"])
        row += 1
        folder_frame = ttk.Frame(inner, style="Panel.TFrame")
        folder_frame.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 12))
        folder_frame.columnconfigure(0, weight=1)
        folder_var = tk.StringVar(value=config.get("music_folder", ""))
        self.vars["music_folder"] = folder_var
        ttk.Entry(folder_frame, textvariable=folder_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(folder_frame, text="Browse…", command=lambda: self._browse(folder_var)).grid(
            row=0, column=1, padx=(8, 0)
        )
        row += 1

        # --- Option groups ---------------------------------------------------
        groups = [
            ("FLAC", ["flac_level", "add_seektables", "force_reencode_flac"]),
            ("Images", [
                "jpegxl_effort", "reencode_images", "reencode_to_jxl",
                "convert_jxl_back", "rename_to_cover", "remove_alpha",
                "force_reencode_images",
            ]),
            ("Lyrics", [
                "optimize_lrc", "optimize_embedded_lyrics", "lyrics_format",
            ]),
            ("CUE Sheets", ["keep_empty_cue_lines", "keep_other_cue_lines"]),
            ("Tags", ["normalize_media_source", "digital_media_source_value"]),
            ("Audio Auditor", [
                "audit_thorough", "force_audit", "audit_cutoff_allow",
                "audit_clipping", "audit_mqa", "audit_ai",
                "audit_fake_stereo", "audit_silence", "audit_dynamic_range",
                "audit_true_peak", "audit_lufs", "audit_bpm",
            ]),
            ("Interface", ["grade_verbose", "auto_advance", "compact_ui"]),
        ]
        field_lookup = {f[0]: f for f in CONFIG_FIELDS}

        for group_title, keys in groups:
            ttk.Label(inner, text=group_title, style="H2.Panel.TLabel").grid(
                row=row, column=0, sticky="w", padx=5, pady=(8, 4)
            )
            row += 1
            box = ttk.Frame(inner, style="Card.TFrame")
            box.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 4))
            box.columnconfigure(1, weight=1)

            for i, key in enumerate(keys):
                _, label, kind, extra = field_lookup[key]
                field_label = ttk.Label(box, text=label, style="Card.TLabel")
                field_label.grid(row=i, column=0, sticky="w", padx=(10, 12), pady=4)
                ToolTip(field_label, FIELD_DESCRIPTIONS.get(key, ""))
                if kind == "bool":
                    var = tk.BooleanVar(value=bool(config.get(key, False)))
                    widget = ToggleSwitch(box, var, bg=CARD)
                    widget.grid(row=i, column=1, sticky="e", padx=(0, 10), pady=4)
                elif kind == "int":
                    var = tk.IntVar(value=int(config.get(key, 0)))
                    widget = ttk.Spinbox(
                        box, from_=extra[0], to=extra[1], textvariable=var, width=8
                    )
                    widget.grid(row=i, column=1, sticky="e", padx=(0, 10), pady=4)
                elif kind == "choice":
                    var = tk.StringVar(value=str(config.get(key, extra[0])).upper())
                    if var.get() not in extra:
                        var.set(extra[0])
                    widget = ttk.Combobox(
                        box, textvariable=var, values=list(extra),
                        state="readonly", width=16,
                    )
                    widget.grid(row=i, column=1, sticky="e", padx=(0, 10), pady=4)
                else:
                    var = tk.StringVar(value=str(config.get(key, "")))
                    widget = ttk.Entry(box, textvariable=var)
                    widget.grid(row=i, column=1, sticky="ew", padx=(0, 10), pady=4)
                ToolTip(widget, FIELD_DESCRIPTIONS.get(key, ""))
                self.vars[key] = var
            row += 1

        # --- Run All order ----------------------------------------------------
        order_header = ttk.Label(inner, text="Run All Order", style="H2.Panel.TLabel")
        order_header.grid(row=row, column=0, sticky="w", padx=5, pady=(8, 4))
        ToolTip(order_header, FIELD_DESCRIPTIONS["run_all_order"])
        row += 1
        order_box = ttk.Frame(inner, style="Card.TFrame")
        order_box.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 4))
        current = list(config.get("run_all_order", [1, 2, 3, 5, 4]))
        for sid in SCRIPT_NAMES:
            if sid not in current:
                current.append(sid)
        self.order_vars = []
        for i, sid in enumerate(current[:len(SCRIPT_NAMES)]):
            ttk.Label(order_box, text=f"{i + 1}.", style="Card.TLabel").grid(
                row=0, column=i, padx=(10, 2) if i == 0 else (0, 2), pady=6
            )
            sv = tk.StringVar(value=SCRIPT_NAMES[sid])
            self.order_vars.append(sv)
            ttk.Combobox(
                order_box, textvariable=sv, width=12, state="readonly",
                values=[SCRIPT_NAMES[n] for n in sorted(SCRIPT_NAMES)],
            ).grid(row=0, column=i, padx=(0, 8), pady=6)
        row += 1

        # --- Encoder Tags ------------------------------------------------------
        tag_header = ttk.Label(inner, text="Encoder Tags", style="H2.Panel.TLabel")
        tag_header.grid(row=row, column=0, sticky="w", padx=5, pady=(8, 4))
        ToolTip(tag_header, "Which ENCODER marker tags each file type gets.\n"
                            "ENCODER_PROGRAM: encoder name\n"
                            "ENCODER_QUALITY: compression level\n"
                            "ENCODER_VERSION: encoder version\n"
                            "FLAC uses Vorbis comments, JPEG/JXL use XMP, "
                            "PNG uses tEXt chunks.\n"
                            "Disabling QUALITY + VERSION makes files "
                            "unidentifiable, so they are always re-encoded.")
        row += 1
        tag_box = ttk.Frame(inner, style="Card.TFrame")
        tag_box.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 4))
        tag_box.columnconfigure(0, weight=1)
        self.encoder_tag_vars = {}
        tag_types = [
            ("flac", "FLAC (.flac)"),
            ("jpeg", "JPEG (.jpg/.jpeg)"),
            ("png", "PNG (.png)"),
            ("jxl", "JPEG XL (.jxl)"),
        ]
        for c, col in enumerate(("Tag", "Program", "Quality", "Version")):
            ttk.Label(tag_box, text=col, style="Card.TLabel",
                      font=_sfont(9)).grid(
                row=0, column=c, padx=(10 if c == 0 else 4, 8), pady=(8, 2),
                sticky="w" if c == 0 else "e")
        for i, (ftype, label) in enumerate(tag_types, start=1):
            ttk.Label(tag_box, text=label, style="Card.TLabel").grid(
                row=i, column=0, sticky="w", padx=(10, 8), pady=5)
            self.encoder_tag_vars[ftype] = {}
            for j, key in enumerate(("ENCODER_PROGRAM", "ENCODER_QUALITY",
                                     "ENCODER_VERSION"), start=1):
                var = tk.BooleanVar(
                    value=bool((config.get("encoder_tags") or {}).get(ftype, {}).get(key, True))
                )
                self.encoder_tag_vars[ftype][key] = var
                ToggleSwitch(tag_box, var, bg=CARD).grid(
                    row=i, column=j, padx=(0, 8), pady=5, sticky="e")
        row += 1

        # --- Dependency status -------------------------------------------------
        enc_header = ttk.Frame(inner, style="Panel.TFrame")
        enc_header.grid(row=row, column=0, sticky="ew", padx=5, pady=(8, 4))
        enc_header.columnconfigure(0, weight=1)
        enc_label = ttk.Label(enc_header, text="Detected Tools",
                              style="H2.Panel.TLabel")
        enc_label.grid(row=0, column=0, sticky="w")
        ToolTip(enc_label, "Versions auto-detected from the .dependencies "
                           "folder. Use Dependencies to download or update "
                           "them.")
        ttk.Button(enc_header, text="Manage…",
                   command=lambda: DependenciesDialog(self.master)).grid(
            row=0, column=1, sticky="e"
        )
        row += 1
        tools = tools_mod.detect_all_tools()
        found = {
            "flac": tools.get("flac", {}).get("version"),
            "libjxl": tools.get("libjxl", {}).get("version"),
            "libjpeg-turbo": tools.get("libjpeg_turbo", {}).get("version"),
            "oxipng": tools.get("oxipng", {}).get("version"),
            "auditor": tools.get("audioauditor", {}).get("version"),
        }
        ver_lines = "   ".join(
            f"{name} {'v' + ver if ver else '—'}" for name, ver in found.items()
        )
        ttk.Label(
            inner, text=ver_lines, style="Card.TLabel",
            font=("Consolas", 9),
        ).grid(row=row, column=0, sticky="w", padx=15)
        if not any(found.values()):
            ttk.Label(
                inner, foreground=YELLOW, background=PANEL,
                text="No tools found. Place flac / libjxl / libjpeg-turbo / oxipng /\n"
                     "AudioAuditor folders inside .dependencies next to the app.",
                justify=tk.LEFT,
            ).grid(row=row + 1, column=0, sticky="w", padx=15, pady=4)
        row += 2

        ttk.Label(
            inner, text="Digital SOURCE Value: written to SOURCE when MEDIA is "
                        '"Digital Media" and SOURCE is missing.\nExisting values '
                        "are preserved.", style="Card.TLabel",
        ).grid(row=row, column=0, sticky="w", padx=15, pady=(4, 0))

        # --- Buttons ------------------------------------------------------------
        btns = ttk.Frame(self, padding=(16, 12))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Reset to Defaults", command=self._reset_defaults).pack(
            side=tk.LEFT
        )
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self._save).pack(
            side=tk.RIGHT, padx=5
        )

        inner.columnconfigure(0, weight=1)
        canvas.configure(width=max(inner.winfo_reqwidth(), 560))
        self.after(150, lambda: apply_window_chrome(self))

    def _reset_defaults(self):
        if not messagebox.askyesno(
            "Reset settings",
            "Restore every setting to its default value?\n"
            "Nothing is written to disk until you press Save.",
            parent=self,
        ):
            return
        defaults = DEFAULT_CONFIG.copy()
        self.vars["music_folder"].set(defaults.get("music_folder", ""))
        for key, _label, kind, extra in CONFIG_FIELDS:
            if key == "run_all_order":
                continue
            var = self.vars[key]
            d = defaults.get(key)
            try:
                if kind == "bool":
                    var.set(bool(d))
                elif kind == "int":
                    var.set(int(d))
                elif kind == "choice":
                    var.set(str(d).upper())
                else:
                    var.set(str(d))
            except (ValueError, tk.TclError):
                pass
        order = defaults.get("run_all_order", [1, 2, 3, 5, 4])
        for sv, sid in zip(self.order_vars, order):
            sv.set(SCRIPT_NAMES[sid])
        default_tags = defaults.get("encoder_tags") or {}
        for ftype, fields in self.encoder_tag_vars.items():
            for key, var in fields.items():
                var.set(bool(default_tags.get(ftype, {}).get(key, True)))

    def _browse(self, var):
        path = filedialog.askdirectory(parent=self, initialdir=var.get() or "/")
        if path:
            var.set(path)

    def _save(self):
        for key, label, kind, extra in CONFIG_FIELDS:
            if key == "run_all_order":
                continue
            var = self.vars[key]
            try:
                if kind == "bool":
                    self.config[key] = bool(var.get())
                elif kind == "int":
                    v = int(var.get())
                    if not (extra[0] <= v <= extra[1]):
                        raise ValueError
                    self.config[key] = v
                elif kind == "choice":
                    self.config[key] = var.get().upper()
                else:
                    self.config[key] = var.get().strip()
            except (ValueError, tk.TclError):
                messagebox.showerror(
                    "Invalid value", f"'{label}' has an invalid value.", parent=self
                )
                return

        self.config["music_folder"] = self.vars["music_folder"].get().strip()

        encoder_tags = self.config.get("encoder_tags") or {}
        for ftype, fields in self.encoder_tag_vars.items():
            encoder_tags[ftype] = {
                key: bool(var.get()) for key, var in fields.items()
            }
        self.config["encoder_tags"] = encoder_tags

        name_to_id = {v: k for k, v in SCRIPT_NAMES.items()}
        order = []
        for sv in self.order_vars:
            sid = name_to_id.get(sv.get())
            if sid and sid not in order:
                order.append(sid)
        self.config["run_all_order"] = order or [1, 2, 3, 5, 4]

        if not str(self.config.get("digital_media_source_value", "")).strip():
            self.config["digital_media_source_value"] = DEFAULT_DIGITAL_SOURCE

        if not save_config(self.config):
            messagebox.showerror("Save failed", "Could not write config.json.", parent=self)
            return

        self.on_saved(self.config)
        self.destroy()


# ======================================================================
# Custom run order dialog
# ======================================================================
class CustomRunDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = []

        self.title("Custom Run")
        self.configure(background=PANEL)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        outer = ttk.Frame(self, padding=20)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="Run Order", style="H2.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Script numbers, comma-separated — e.g.  3,1,2,5",
                  style="Muted.TLabel",
                  ).pack(anchor="w", pady=(0, 8))

        self.entry_var = tk.StringVar()
        e = ttk.Entry(outer, textvariable=self.entry_var, width=24)
        e.pack(anchor="w",)
        e.focus_set()

        ttk.Label(outer, text="1 Format Lyrics    2 Format CUEs    3 Optimize FLACs\n"
                              "4 Grade Library    5 Process Images  6 Audit Library",
                  style="Muted.TLabel", justify=tk.LEFT).pack(anchor="w", pady=(10, 0))

        btns = ttk.Frame(outer)
        btns.pack(anchor="e", pady=(14, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btns, text="Run", style="Accent.TButton", command=self._ok).pack(
            side=tk.RIGHT, padx=5
        )

        self.bind("<Return>", lambda e: self._ok())
        self.after(150, lambda: apply_window_chrome(self))

    def _ok(self):
        order = []
        for part in self.entry_var.get().replace(" ", "").split(","):
            if part in tuple(str(n) for n in SCRIPT_NAMES) \
                    and int(part) not in order:
                order.append(int(part))
        if not order:
            messagebox.showinfo(
                "Invalid order",
                f"Enter at least one script number (1-{len(SCRIPT_NAMES)}).",
                parent=self)
            return
        self.result = order
        self.destroy()


# ======================================================================
# First-run setup wizard
# ======================================================================
class FirstRunWizard(tk.Toplevel):
    """Wizard shown on first launch to configure library folder and settings."""

    def __init__(self, parent, config, on_complete):
        super().__init__(parent)
        self.config = config
        self.on_complete = on_complete
        self.vars = {}

        self.title("Welcome to Music Library Optimizer")
        self.configure(background=PANEL)
        self.transient(parent)
        # Non-modal: the wizard never blocks the main window, so the app
        # always opens and stays responsive even if the wizard misbehaves.
        self.resizable(False, False)
        self.geometry("720x580")
        self.lift()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._skip)

        outer = ttk.Frame(self, padding=24)
        outer.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 16))
        ttk.Label(header, text="Music Library Optimizer", style="H1.TLabel").pack(anchor="w")
        ttk.Label(header,
                  text="Let's get you set up. Choose your music library folder and review the default settings.",
                  style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(4, 0))

        # Step indicator
        self.step = 0
        self.steps = ["Library Folder", "Settings Preset", "Dependencies", "Ready"]
        self.step_frame = ttk.Frame(outer)
        self.step_frame.pack(fill=tk.X, pady=(0, 16))
        self.step_labels = []
        for i, name in enumerate(self.steps):
            lbl = ttk.Label(self.step_frame, text=f"  {i+1}. {name}  ",
                            style="Muted.TLabel", borderwidth=1, relief="solid")
            lbl.pack(side=tk.LEFT, padx=2)
            self.step_labels.append(lbl)
        self._update_step_indicator()

        # Content area (swapped per step)
        self.content = ttk.Frame(outer)
        self.content.pack(fill=tk.BOTH, expand=True)

        # Navigation buttons
        nav = ttk.Frame(outer)
        nav.pack(fill=tk.X, pady=(16, 0))
        self.back_btn = ttk.Button(nav, text="← Back", command=self._go_back, state=tk.DISABLED)
        self.back_btn.pack(side=tk.LEFT)
        self.next_btn = ttk.Button(nav, text="Next →", style="Accent.TButton", command=self._go_next)
        self.next_btn.pack(side=tk.RIGHT)
        self.finish_btn = ttk.Button(nav, text="Finish", style="Accent.TButton", command=self._finish, state=tk.HIDDEN)
        self.finish_btn.pack(side=tk.RIGHT, padx=(0, 8))

        self._show_step(0)
        self.after(150, lambda: apply_window_chrome(self))

    def _update_step_indicator(self):
        for i, lbl in enumerate(self.step_labels):
            if i == self.step:
                lbl.configure(style="Section.TLabel", foreground=ACCENT)
            elif i < self.step:
                lbl.configure(style="Muted.TLabel", foreground=GREEN)
            else:
                lbl.configure(style="Muted.TLabel", foreground=MUTED)

    def _show_step(self, n):
        self.step = n
        for w in self.content.winfo_children():
            w.destroy()
        self._update_step_indicator()
        self.back_btn.configure(state=tk.NORMAL if n > 0 else tk.DISABLED)
        self.next_btn.configure(state=tk.NORMAL if n < len(self.steps) - 1 else tk.HIDDEN)
        self.finish_btn.configure(state=tk.HIDDEN)
        if n == 0:
            self._build_step_library()
        elif n == 1:
            self._build_step_preset()
        elif n == 2:
            self._build_step_deps()
        elif n == 3:
            self._build_step_ready()

    def _go_back(self):
        if self.step > 0:
            self._show_step(self.step - 1)

    def _go_next(self):
        if self.step == 0:
            if not self.vars.get("music_folder", "").get().strip():
                messagebox.showwarning("Required", "Please select a music library folder.", parent=self)
                return
        elif self.step == 1:
            pass  # preset step has no validation
        elif self.step == 2:
            pass
        if self.step < len(self.steps) - 1:
            self._show_step(self.step + 1)

    def _finish(self):
        # Save the music folder chosen in step 1
        folder = self.vars.get("music_folder", "").get().strip()
        if folder:
            self.config["music_folder"] = folder
        # Apply preset if selected
        if self.vars.get("use_preset", tk.BooleanVar(value=True)).get():
            self._apply_preset()
        # Mark first run complete
        self.config["first_run_done"] = True
        save_config(self.config)
        self.on_complete()
        self.destroy()

    def _skip(self):
        """Close the wizard without completing setup; the app keeps working."""
        self.config["first_run_done"] = True
        save_config(self.config)
        self.on_complete()
        self.destroy()

    def _build_step_library(self):
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=tk.BOTH, expand=True)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Where is your music library?", style="Card.TLabel",
                  font=_sfont(11)).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(box, text="Music Folder:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=8)
        folder_var = tk.StringVar(value=self.config.get("music_folder", ""))
        self.vars["music_folder"] = folder_var
        ttk.Entry(box, textvariable=folder_var, width=50).grid(
            row=1, column=1, sticky="ew", pady=8)
        ttk.Button(box, text="Browse…", command=lambda: self._browse(folder_var)).grid(
            row=1, column=2, padx=(8, 0), pady=8)

        ttk.Label(box,
                  text="This should be the root folder containing your artist folders "
                       "(e.g., F:\\Music\\Artists). The app scans recursively.",
                  style="Muted.Card.TLabel", wraplength=500).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _browse(self, var):
        path = filedialog.askdirectory(parent=self, initialdir=var.get() or "/")
        if path:
            var.set(path)

    def _build_step_preset(self):
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=tk.BOTH, expand=True)

        ttk.Label(box, text="Settings Preset", style="Card.TLabel",
                  font=_sfont(11)).pack(anchor="w", pady=(0, 8))

        ttk.Label(box,
                  text="The app comes with a recommended preset (enabled below). "
                       "You can customize any setting later in ⚙ Settings.",
                  style="Muted.Card.TLabel", wraplength=560).pack(anchor="w", pady=(0, 12))

        preset_var = tk.BooleanVar(value=True)
        self.vars["use_preset"] = preset_var
        ttk.Checkbutton(box, text="Use recommended preset",
                        variable=preset_var, style="TCheckbutton").pack(anchor="w")

        # Show preset summary
        preset_frame = ttk.Frame(box, style="Card.TFrame", padding=12)
        preset_frame.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(preset_frame, text="Preset includes:", style="Card.TLabel",
                  font=_sfont(9)).pack(anchor="w")
        for line in [
            "• FLAC: Level 8, no seektables, ENCODER tags on",
            "• Images: JPEG XL effort 10, convert to JXL, rename to cover",
            "• Lyrics: Embedded format, clean LRC & embedded",
            "• CUE: Normalize, drop empty/non-standard lines",
            "• MEDIA/SOURCE: Normalize (Digital Media → SOURCE=Digital)",
            "• Audio Audit: Fast scan, all detectors on, cutoff 19600 Hz",
            "• Auto-advance: On, Compact UI: Off",
        ]:
            ttk.Label(preset_frame, text=line, style="Muted.Card.TLabel",
                      font=_font(8)).pack(anchor="w")

    def _build_step_deps(self):
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=tk.BOTH, expand=True)

        ttk.Label(box, text="External Tools", style="Card.TLabel",
                  font=_sfont(11)).pack(anchor="w", pady=(0, 8))

        ttk.Label(box,
                  text="The app downloads required tools automatically on first use. "
                       "You can also manage them anytime from the sidebar → MANAGE → Dependencies.",
                  style="Muted.Card.TLabel", wraplength=560).pack(anchor="w", pady=(0, 12))

        tools = [
            ("FLAC", "flac.exe / metaflac.exe — FLAC encoding & tag editing"),
            ("libjxl", "cjxl.exe / djxl.exe — JPEG XL conversion"),
            ("libjpeg-turbo", "jpegtran.exe — JPEG lossless optimization"),
            ("oxipng", "oxipng.exe — PNG lossless optimization"),
            ("AudioAuditor", "AudioAuditorCLI.exe — Audio integrity audit"),
        ]
        for name, desc in tools:
            row = ttk.Frame(box, style="Card.TFrame")
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=name, style="Card.TLabel", font=_sfont(9), width=18).pack(side=tk.LEFT)
            ttk.Label(row, text=desc, style="Muted.Card.TLabel", font=_font(8)).pack(side=tk.LEFT)

    def _build_step_ready(self):
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=tk.BOTH, expand=True)

        ttk.Label(box, text="You're all set!", style="Card.TLabel",
                  font=_sfont(14), foreground=GREEN).pack(anchor="w", pady=(0, 16))

        ttk.Label(box,
                  text="Click Finish to save your settings and open the main window. "
                       "You can change anything later via ⚙ Settings or the sidebar.",
                  style="Muted.Card.TLabel", wraplength=560).pack(anchor="w")

        self.next_btn.configure(state=tk.HIDDEN)
        self.finish_btn.configure(state=tk.NORMAL)

    def _apply_preset(self):
        """Apply the recommended preset (excluding user-specific paths)."""
        # User-specific keys to NOT overwrite
        user_keys = {
            "music_folder", "mp3tag_path", "picard_path", "foobar2000_path",
            "last_update_check", "first_run_done",
        }
        for key, value in DEFAULT_CONFIG.items():
            if key not in user_keys:
                self.config[key] = value
        # Ensure encoder_tags preset is applied
        self.config["encoder_tags"] = DEFAULT_CONFIG["encoder_tags"].copy()
        # Run all order preset
        self.config["run_all_order"] = DEFAULT_CONFIG["run_all_order"].copy()


# ======================================================================
# Main application window
# ======================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        from mlo import __version__
        self.title(f"Music Library Optimizer v{__version__}")
        self.configure(background=BG)
        self.geometry("1180x760")
        self.minsize(880, 580)

        if not HAS_MUTAGEN:
            self.withdraw()
            messagebox.showerror(
                "Missing dependency",
                "mutagen is required.\n\nInstall it with:\n    pip install mutagen",
            )
            self.destroy()
            return

        self.config = load_config()
        self.log_q = queue.Queue()
        self.running = False
        self.run_buttons = []
        self._continue_event = threading.Event()
        self._continue_event.set()

        global UI_FAMILY
        UI_FAMILY = _pick_ui_family()

        # Set up styles before anything renders (wizard or main window).
        self._setup_style()
        self._monospace = self._pick_monospace()
        self._build_ui()

        try:
            icon_file = os.path.join(SCRIPT_DIR, "app_icon.ico")
            if os.path.isfile(icon_file):
                self.iconbitmap(default=icon_file)
        except tk.TclError:
            pass

        # Start the console plumbing (stdout redirect + log drain).
        self._start_console()

        # First-run wizard: the main window is always shown; the wizard is
        # a modal on top of it. Creating the modal against a *visible* root
        # maps reliably (a transient/grab on a withdrawn root may never
        # display, leaving the app with no visible window).
        if not self.config.get("first_run_done", False):
            self.after(150, self._show_first_run_wizard)

    def _show_first_run_wizard(self):
        """Create the first-run wizard inside the running event loop.

        Creation is guarded: if the wizard fails for any reason the main
        window stays fully usable rather than the app appearing to hang.
        """
        try:
            FirstRunWizard(self, self.config, self._after_first_run)
        except Exception:
            import traceback as _tb
            traceback.print_exc()
            self.log("First-run wizard could not be shown; you can configure "
                     "everything from ⚙ Settings.", tag="red")

    def _start_console(self):
        """Redirect stdout/stderr to the GUI console and start draining."""
        self.stdout_stream = QueueStream(self.log_q)
        self._real_stdout, self._real_stderr = sys.stdout, sys.stderr
        sys.stdout = self.stdout_stream
        sys.stderr = self.stdout_stream
        self.after(80, self._drain_log)
        self.after(150, lambda: apply_window_chrome(self))
        self.log("Music Library Optimizer ready.")
        if not HAS_PIL:
            self.log("WARNING: Pillow not found - PNG alpha removal will be skipped.",
                     tag="yellow")
        self.log(f"Library folder: {self.config.get('music_folder', '')}", tag="muted")
        # Auto-check for updates
        self.after(5000, lambda: updater.maybe_auto_check())

    # ------------------------------------------------------------------
    @staticmethod
    def _pick_monospace():
        try:
            families = set(tkfont.families())
            for name in ("Cascadia Code", "Cascadia Mono", "Consolas",
                         "Courier New"):
                if name in families:
                    return name
        except Exception:
            pass
        return "TkFixedFont"

    def _after_first_run(self):
        """Called when first-run wizard completes. Main window is already
        visible; just refresh the library with the chosen folder."""
        self._refresh_library(regrade=True)

    # ------------------------------------------------------------------
    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        base_font = _font(10)
        self.option_add("*Font", base_font)
        style.configure(".", background=BG, foreground=TEXT, borderwidth=0,
                        focuscolor=ACCENT)

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Side.TFrame", background=SIDEBAR)

        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Side.TLabel", background=SIDEBAR, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Muted.Panel.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED)
        style.configure("Muted.Side.TLabel", background=SIDEBAR, foreground=MUTED)
        style.configure("Accent.TLabel", foreground=ACCENT)
        style.configure("H1.TLabel", foreground=BRIGHT, font=_sfont(15))
        style.configure("H1.Panel.TLabel", background=PANEL, foreground=BRIGHT,
                        font=_sfont(15))
        style.configure("H2.TLabel", foreground=ACCENT, font=_sfont(10))
        style.configure("H2.Panel.TLabel", background=PANEL, foreground=ACCENT,
                        font=_sfont(10))
        # Small-caps style section headers. Two variants because the same
        # style is used on the sidebar (SIDEBAR bg) and over the window
        # background / cards (BG bg) - clam would otherwise paint a
        # mismatched rectangle behind the text.
        style.configure("Section.TLabel", background=BG, foreground=MUTED,
                        font=_sfont(8))
        style.configure("Section.Side.TLabel", background=SIDEBAR,
                        foreground=MUTED, font=_sfont(8))
        style.configure("Section.Card.TLabel", background=CARD,
                        foreground=MUTED, font=_sfont(8))

        # Buttons: flat surfaces with a visible hover ramp.
        style.configure("TButton", background="#1f1f1f", foreground=TEXT,
                        borderwidth=0, focusthickness=0, padding=(14, 8))
        style.map("TButton",
                  background=[("pressed", "#2e2e2e"), ("active", "#2a2a2a"),
                              ("disabled", "#181818")],
                  foreground=[("disabled", "#4a4a4a")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#0a0a0a")
        style.map("Accent.TButton",
                  background=[("pressed", "#cfcfcf"), ("active", BRIGHT),
                              ("disabled", "#2a2a2a")],
                  foreground=[("disabled", "#6a6a6a")])
        style.configure("Side.TButton", anchor="w", padding=(16, 11))
        style.configure("Side.Accent.TButton", anchor="w", padding=(16, 11),
                        background="#2e2e2e", foreground=BRIGHT)
        style.map("Side.Accent.TButton",
                  background=[("pressed", "#3d3d3d"), ("active", "#3a3a3a"),
                              ("disabled", "#181818")],
                  foreground=[("disabled", "#4a4a4a")])
        style.map("Side.TButton",
                  background=[("pressed", "#262626"), ("active", "#222222"),
                              ("disabled", "#161616")])
        style.configure("Small.TButton", padding=(10, 4), font=_font(9))

        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, borderwidth=1, padding=(8, 6))
        style.map("TEntry",
                  bordercolor=[("focus", "#6f6f6f")],
                  lightcolor=[("focus", "#6f6f6f")],
                  darkcolor=[("focus", "#6f6f6f")],
                  fieldbackground=[("readonly", FIELD)])

        style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=BORDER, arrowcolor=TEXT,
                        background="#1f1f1f", borderwidth=1,
                        lightcolor=BORDER, darkcolor=BORDER, arrowsize=11,
                        padding=(8, 5))
        style.map("TSpinbox", bordercolor=[("focus", "#6f6f6f")],
                  arrowcolor=[("disabled", MUTED)])

        style.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        borderwidth=1, arrowsize=11, padding=(8, 5))
        style.map("TCombobox",
                  fieldbackground=[("readonly", FIELD)],
                  foreground=[("readonly", TEXT)],
                  bordercolor=[("focus", "#6f6f6f")],
                  lightcolor=[("focus", "#6f6f6f")],
                  darkcolor=[("focus", "#6f6f6f")])
        self.option_add("*TCombobox*Listbox*Background", FIELD)
        self.option_add("*TCombobox*Listbox*Foreground", TEXT)
        self.option_add("*TCombobox*Listbox*selectBackground", ACCENT_DARK)
        self.option_add("*TCombobox*Listbox*selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox*BorderWidth", 1)
        self.option_add("*TCombobox*Listbox*HighlightThickness", 0)
        self.option_add("*TCombobox*Listbox*relief", "flat")

        # Note: booleans are rendered with ToggleSwitch (custom canvas),
        # not ttk checkbuttons - clam indicators render poorly on dark
        # themes.

        style.configure("TSeparator", background=BORDER)
        style.configure("Side.TSeparator", background="#1d1d1d")

        style.configure("TScrollbar", troughcolor="#121212", background="#2a2a2a",
                        bordercolor="#121212", arrowcolor=MUTED,
                        lightcolor="#2a2a2a", darkcolor="#2a2a2a",
                        relief="flat", gripcount=0)
        style.map("TScrollbar", background=[("active", "#3a3a3a")])

        style.configure("TNotebook", background=BG, borderwidth=0,
                        tabmargins=(0, 6, 0, 0))
        # Solid tab backgrounds only: "transparent" makes unselected tabs
        # render invisibly on some clam builds until hovered.
        style.configure("TNotebook.Tab", background="#141414",
                        foreground=MUTED, borderwidth=0,
                        padding=(22, 11), font=_sfont(9))
        style.map("TNotebook.Tab",
                  background=[("selected", CARD), ("active", "#1d1d1d")],
                  foreground=[("selected", BRIGHT), ("active", TEXT)])

        style.configure("Treeview", background="#121212", fieldbackground="#121212",
                        foreground=TEXT, borderwidth=0, rowheight=28,
                        font=_font(9))
        style.map("Treeview", background=[("selected", ACCENT_DARK)],
                  foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=CARD, foreground=MUTED,
                        borderwidth=0, padding=(10, 7), relief="flat",
                        font=_sfont(8))
        style.map("Treeview.Heading",
                  background=[("active", "#1f1f1f")])

        style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, relief="flat")
        style.configure("TLabelframe.Label", background=BG, foreground=MUTED,
                        font=_sfont(8))

        style.configure("Horizontal.TProgressbar", troughcolor="#1d1d1d",
                         background=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                         borderwidth=0, thickness=5)

        style.configure("TCheckbutton", background=BG, foreground=TEXT,
                        focuscolor=BG)

    # ------------------------------------------------------------------
    def _build_ui(self):
        # --- Folder bar ---------------------------------------------------
        folder_bar = ttk.Frame(self, padding=(18, 16, 18, 8))
        folder_bar.pack(fill=tk.X)
        folder_bar.columnconfigure(1, weight=1)
        ttk.Label(folder_bar, text="LIBRARY FOLDER", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        self.folder_var = tk.StringVar(value=self.config.get("music_folder", ""))
        ttk.Entry(folder_bar, textvariable=self.folder_var).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(folder_bar, text="Browse…", command=self._pick_folder).grid(
            row=0, column=2, padx=(10, 0)
        )

        # --- Main area ------------------------------------------------------
        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(main, style="Side.TFrame", padding=(16, 16))
        sidebar.grid(row=0, column=0, sticky="nswe")

        # Branded header
        brand = ttk.Frame(sidebar, style="Side.TFrame")
        brand.pack(fill=tk.X, pady=(0, 16))
        brand_text = ttk.Frame(brand, style="Side.TFrame")
        brand_text.pack(side=tk.LEFT)
        ttk.Label(brand_text, text="Music Library",
                  style="Side.TLabel", font=_sfont(13), foreground=BRIGHT).pack(anchor="w")
        ttk.Label(brand_text, text="Optimizer",
                  style="Side.TLabel", font=_sfont(13), foreground=BRIGHT).pack(anchor="w")

        ttk.Label(sidebar, text="RUN SCRIPTS", style="Section.Side.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        for sid, name in SCRIPT_NAMES.items():
            b = ttk.Button(
                sidebar, text=name, style="Side.TButton",
                command=lambda s=sid: self._run_scripts([s], f"RUN — {SCRIPT_NAMES[s]}"),
            )
            b.pack(fill=tk.X, pady=2)
            self.run_buttons.append(b)

        ttk.Label(sidebar, text="BATCH", style="Section.Side.TLabel").pack(
            anchor="w", pady=(18, 8)
        )
        b = ttk.Button(sidebar, text="Run All", style="Side.Accent.TButton",
                       command=self._run_all)
        b.pack(fill=tk.X, pady=2)
        ToolTip(b, "Run every script in order.\n"
                "Enable ⚡ Force in the Library tab to force re-encoding.")
        self.run_buttons.append(b)
        b = ttk.Button(sidebar, text="Run Custom…", style="Side.TButton",
                       command=self._run_custom)
        b.pack(fill=tk.X, pady=2)
        self.run_buttons.append(b)

        ttk.Label(sidebar, text="MANAGE", style="Section.Side.TLabel").pack(
            anchor="w", pady=(18, 8)
        )
        b = ttk.Button(sidebar, text="Dependencies…", style="Side.TButton",
                       command=self._open_deps)
        b.pack(fill=tk.X, pady=2)
        self.run_buttons.append(b)

        self.dep_label = ttk.Label(sidebar, text="", style="Muted.Side.TLabel",
                                   font=_font(8))
        self.dep_label.pack(side=tk.BOTTOM, anchor="w", pady=(8, 0))
        self._update_dep_label()

        # --- Notebook (Library + Console tabs) ------------------------------
        notebook = ttk.Notebook(main)
        notebook.grid(row=0, column=1, sticky="nswe", padx=16, pady=(8, 8))

        # --- Library tab ---------------------------------------------------
        library_frame = ttk.Frame(notebook, padding=(16, 12))
        notebook.add(library_frame, text="Library")
        library_frame.columnconfigure(0, weight=1)
        library_frame.rowconfigure(3, weight=1)

        toolbar = ttk.Frame(library_frame)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.opt_selected_btn = ttk.Button(
            toolbar, text="Optimize Selected", style="Accent.TButton",
            command=self._optimize_selected)
        self.opt_selected_btn.pack(side=tk.LEFT)
        ToolTip(self.opt_selected_btn, "Run the full pipeline on the checked items.\n"
                "Enable ⚡ Force options to re-process everything regardless "
                "of state.")
        # Force: master pill + per-feature menu.
        force_box = ttk.Frame(toolbar)
        force_box.pack(side=tk.LEFT, padx=(14, 0))
        self.force_flac_var = tk.BooleanVar(
            value=self.config.get("force_flac_ui", False))
        self.force_images_var = tk.BooleanVar(
            value=self.config.get("force_images_ui", False))
        self.force_audit_var = tk.BooleanVar(
            value=self.config.get("force_audit_ui", False))
        self.force_var = tk.BooleanVar(
            value=(self.force_flac_var.get() and self.force_images_var.get()
                   and self.force_audit_var.get()))
        force_toggle = ToggleSwitch(
            force_box, self.force_var, bg=BG, command=self._on_force_master)
        force_toggle.pack(side=tk.LEFT)
        force_hint = ("Force: re-process everything regardless of state.\n"
                      "Use the ▾ menu to toggle each force option "
                      "individually.\nApplies to Optimize Selected, Run All "
                      "and Run Custom.")
        ToolTip(force_toggle, force_hint)
        ttk.Label(force_box, text="Force", style="Muted.TLabel").pack(
            side=tk.LEFT, padx=(8, 2))
        force_menu_btn = ttk.Button(force_box, text="▾", style="Small.TButton",
                                    width=2, command=self._show_force_menu)
        force_menu_btn.pack(side=tk.LEFT)
        ToolTip(force_menu_btn, "Configure individual force options.")
        ttk.Button(toolbar, text="Refresh", style="Small.TButton",
                   command=lambda: self._refresh_library(regrade=True)).pack(
            side=tk.LEFT, padx=(12, 0))
        ttk.Button(toolbar, text="Clear Selection", style="Small.TButton",
                   command=self._clear_selection).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="Select All", style="Small.TButton",
                   command=self._select_all).pack(side=tk.LEFT, padx=(8, 0))

        self.sel_label_var = tk.StringVar(value="0 selected")
        ttk.Label(toolbar, textvariable=self.sel_label_var,
                  style="Muted.TLabel").pack(side=tk.LEFT, padx=(14, 0))

        # External tools: enqueue the checked folders in foobar2000, or
        # open them in Mp3tag / Picard.
        self.foobar_btn = ttk.Button(
            toolbar, text="Enqueue in foobar2000", style="Small.TButton",
            command=lambda: self._open_in_external("foobar2000"))
        self.foobar_btn.pack(side=tk.RIGHT)
        ToolTip(self.foobar_btn, "Enqueue the selected folder(s) in "
                                 "foobar2000 (/add).")
        self.mp3tag_btn = ttk.Button(toolbar, text="Mp3tag",
                                     style="Small.TButton",
                                     command=lambda: self._open_in_external("mp3tag"))
        self.mp3tag_btn.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(self.mp3tag_btn, "Open the selected folder(s) in Mp3tag.")
        self.picard_btn = ttk.Button(toolbar, text="Picard",
                                     style="Small.TButton",
                                     command=lambda: self._open_in_external("picard"))
        self.picard_btn.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(self.picard_btn, "Open the selected folder(s) in MusicBrainz "
                                 "Picard.")

        self.compact_var = tk.BooleanVar(value=self.config.get("compact_ui", False))
        compact_toggle = tk.Checkbutton(
            toolbar, text="Compact grades", variable=self.compact_var,
            command=self._on_compact_toggle,
            background=BG, foreground=TEXT, selectcolor=BG,
            activebackground=BG, activeforeground=TEXT,
            highlightthickness=0, bd=0, font=_font(9),
        )
        compact_toggle.pack(side=tk.RIGHT, padx=(0, 14))

        # Filter row
        filter_frame = ttk.Frame(library_frame, style="Card.TFrame",
                                 padding=(12, 8))
        filter_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        filter_frame.columnconfigure(1, weight=1)
        ttk.Label(filter_frame, text="Album Artist:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self.albumartist_var = tk.StringVar(value="")
        self.albumartist_entry = ttk.Entry(filter_frame,
                                           textvariable=self.albumartist_var)
        self.albumartist_entry.grid(row=0, column=1, sticky="ew")
        self.albumartist_entry.bind("<KeyRelease>", self._on_albumartist_change)
        ttk.Button(filter_frame, text="Clear", style="Small.TButton",
                   command=self._clear_filter).grid(row=0, column=2, padx=(8, 0))

        self.bad_only_var = tk.BooleanVar(value=False)
        bad_box = ttk.Frame(filter_frame, style="Card.TFrame")
        bad_box.grid(row=0, column=3, sticky="e", padx=(14, 0))
        bad_toggle = ToggleSwitch(bad_box, self.bad_only_var, bg=CARD,
                                  command=self._on_filter_change)
        bad_toggle.pack(side=tk.LEFT)
        ToolTip(bad_toggle, "Hide passing albums — show only failed / ungraded ones.")
        ttk.Label(bad_box, text="Bad only",
                  style="Card.TLabel").pack(side=tk.LEFT, padx=(8, 0))

        self.sort_var = tk.StringVar()
        self._sort_labels = {
            "name": "Name (A–Z)",
            "grade_bad": "Grade — worst first",
            "grade_good": "Grade — best first",
        }
        self._sort_rev = {v: k for k, v in self._sort_labels.items()}
        sort_key = self.config.get("library_sort", "name")
        if sort_key not in self._sort_labels:
            sort_key = "name"
        self.sort_var.set(self._sort_labels[sort_key])
        sort_box = ttk.Combobox(
            filter_frame, state="readonly", width=22, textvariable=self.sort_var,
            values=list(self._sort_labels.values()),
        )
        sort_box.grid(row=0, column=4, sticky="e", padx=(14, 0))
        sort_box.bind("<<ComboboxSelected>>", self._on_sort_change)

        # Directory tree + grades inside a bordered card
        tree_card = tk.Frame(library_frame, background=BORDER,
                             highlightthickness=1, highlightbackground=BORDER)
        tree_card.grid(row=3, column=0, sticky="nswe")
        tree_card.rowconfigure(0, weight=1)
        tree_card.columnconfigure(0, weight=1)

        tree_box = ttk.Frame(tree_card, style="Card.TFrame")
        tree_box.grid(row=0, column=0, sticky="nswe")
        tree_box.rowconfigure(0, weight=1)
        tree_box.columnconfigure(0, weight=1)

        self.library_tree = ttk.Treeview(
            tree_box, show="tree headings", selectmode="none"
        )
        self.library_tree.configure(columns=tuple(TREE_COLUMNS))
        for col_id, (heading, width, _default) in TREE_COLUMNS.items():
            self.library_tree.heading(col_id, text=heading)
            self.library_tree.column(col_id, width=width, anchor="w",
                                     stretch=False)

        # Row states: green = graded pass, purple = audited only,
        # blue = graded + audited, yellow = warnings/mixed, red = failing.
        self.library_tree.tag_configure(
            "pass", background="#132018", foreground="#a8dc8c")
        self.library_tree.tag_configure(
            "audited", background="#221532", foreground="#c9a2f2")
        self.library_tree.tag_configure(
            "both", background="#101f38", foreground="#93b8e8")
        self.library_tree.tag_configure(
            "mixed", background="#211f14", foreground="#e3cf95")
        self.library_tree.tag_configure(
            "fail", background="#241417", foreground="#e58a93")
        self.library_tree.tag_configure("pending", background="#141414")

        # Restore persisted column visibility (right-click a column
        # heading to toggle; the choice is saved to config.json).
        self._col_visible = dict(
            (c, default) for c, (_h, _w, default) in TREE_COLUMNS.items())
        saved_cols = self.config.get("library_columns") or {}
        for c in self._col_visible:
            self._col_visible[c] = bool(saved_cols.get(c, self._col_visible[c]))
        self._apply_column_visibility()

        v_scroll = ttk.Scrollbar(tree_box, orient=tk.VERTICAL,
                                 command=self.library_tree.yview)
        h_scroll = ttk.Scrollbar(tree_box, orient=tk.HORIZONTAL,
                                 command=self.library_tree.xview)
        self.library_tree.configure(yscrollcommand=v_scroll.set,
                                    xscrollcommand=h_scroll.set)
        self.library_tree.grid(row=0, column=0, sticky="nswe")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.library_tree.bind("<Button-1>", self._on_tree_click)
        self.library_tree.bind("<Double-1>", self._on_tree_double)
        self.library_tree.bind("<Button-3>", self._on_tree_menu)
        self.library_tree.bind("<Control-a>", self._select_all)
        self.library_tree.bind("<Control-A>", self._select_all)
        self.bind("<Control-a>", self._select_all_global)
        self.bind("<Control-A>", self._select_all_global)
        self._last_anchor = None
        ToolTip(self.library_tree, "Ctrl+A select all · Ctrl+click toggle · Shift+click range")

        # Library model state
        self._lib_folder = self.folder_var.get().strip()
        self._lyrics_format = str(
            self.config.get("lyrics_format", "EMBEDDED")
        ).upper()
        self._artists = {}
        self._folder_artist = {}
        self._grade_cache = {}
        self._checked = {}
        self._item_paths = {}
        self._item_base = {}
        self._path_items = {}
        self._agg = {}
        self._root_item = None
        self._scan_q = queue.Queue()
        self._library_busy = False
        self._filter_job = None
        self._scan_draining = False

        # Populate library initially
        self._refresh_library()

        # --- Console tab ---------------------------------------------------
        console_tab = ttk.Frame(notebook, padding=(16, 12))
        console_tab.columnconfigure(0, weight=1)
        console_tab.rowconfigure(0, weight=1)
        notebook.add(console_tab, text="Console")

        # Determine compact mode
        compact = self.compact_var.get()

        # Adjust padding based on compact mode
        panel_inner_pad = (8, 4, 8, 8) if compact else (14, 10, 14, 12)
        button_pad = (4, 6) if compact else (6, 12)
        label_font = _font(8) if compact else _font(9)
        text_font = (self._monospace, 8) if compact else (self._monospace, 10)

        # Recreate the console inside the tab (same as before but in a tab)
        console_panel = ttk.Frame(console_tab, padding=panel_inner_pad)
        console_panel.grid(row=0, column=0, sticky="nswe")
        console_panel.rowconfigure(1, weight=1)
        console_panel.columnconfigure(0, weight=1)

        bar = ttk.Frame(console_panel)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6 if compact else 8))
        ttk.Label(bar, text="CONSOLE", style="Section.TLabel").pack(side=tk.LEFT)

        self.autoscroll_var = tk.BooleanVar(value=True)
        auto = ttk.Frame(bar)
        auto.pack(side=tk.RIGHT)
        ToggleSwitch(auto, self.autoscroll_var, bg=BG).pack(side=tk.LEFT)
        ttk.Label(auto, text="Auto-scroll", style="Muted.TLabel",
                  font=label_font).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bar, text="Clear", style="Small.TButton",
                   command=self._clear_console).pack(side=tk.RIGHT, padx=button_pad)
        ttk.Button(bar, text="Copy All", style="Small.TButton",
                   command=self._copy_console).pack(side=tk.RIGHT, padx=button_pad)

        console_card = tk.Frame(console_panel, background=BORDER,
                                highlightthickness=1,
                                highlightbackground=BORDER)
        console_card.grid(row=1, column=0, sticky="nswe")
        console_card.rowconfigure(0, weight=1)
        console_card.columnconfigure(0, weight=1)

        console_box = ttk.Frame(console_card, style="Card.TFrame")
        console_box.grid(row=0, column=0, sticky="nswe")
        console_box.rowconfigure(0, weight=1)
        console_box.columnconfigure(0, weight=1)

        self.console = tk.Text(
            console_box, wrap="none", state=tk.DISABLED,
            background="#111111", foreground=TEXT, borderwidth=0,
            insertbackground=TEXT, highlightthickness=0, padx=12, pady=10,
            font=text_font, undo=False,
        )
        ysb = ttk.Scrollbar(console_box, orient=tk.VERTICAL, command=self.console.yview)
        xsb = ttk.Scrollbar(console_box, orient=tk.HORIZONTAL, command=self.console.xview)
        self.console.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.console.grid(row=0, column=0, sticky="nswe")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        self._console_bold_font = tkfont.Font(
            family=self._monospace, size=10, weight="bold")
        tag_colors = {
            "fg": TEXT, "bold": BRIGHT, "grey": MUTED, "red": RED,
            "green": GREEN, "yellow": YELLOW, "blue": "#d6d6d6",
            "magenta": "#c9c9c9", "cyan": "#a6a6a6",
        }
        for tag, color in tag_colors.items():
            if tag == "bold":
                self.console.tag_configure(tag, foreground=color,
                                           font=self._console_bold_font)
            else:
                self.console.tag_configure(tag, foreground=color)
        for tag in ("muted",):
            self.console.tag_configure(tag, foreground=MUTED)

        menu = tk.Menu(self.console, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        menu.add_command(label="Copy", command=lambda: self.console.event_generate("<<Copy>>"))
        menu.add_command(label="Select All", command=lambda: self.console.tag_add("sel", "1.0", "end"))
        menu.add_separator()
        menu.add_command(label="Clear", command=self._clear_console)
        self.console.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        # --- Status bar --------------------------------------------------------
        ttk.Separator(self).pack(fill=tk.X, side=tk.BOTTOM)
        status = ttk.Frame(self, style="Panel.TFrame", padding=(16, 8))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        status.columnconfigure(1, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        left = ttk.Frame(status, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="w")
        ttk.Button(left, text="\u2699  Settings", style="Small.TButton",
                   command=self._open_config).pack(side=tk.LEFT)
        ttk.Button(left, text="\u24d8  About", style="Small.TButton",
                   command=self._show_about).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(status, textvariable=self.status_var,
                  style="Panel.TLabel").grid(row=0, column=1, sticky="w",
                                             padx=(12, 0))
        right = ttk.Frame(status, style="Panel.TFrame")
        right.grid(row=0, column=2, sticky="e")
        self.continue_btn = ttk.Button(
            right, text="Continue ▶", style="Accent.TButton",
            command=self._continue
        )
        self.prog_label_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.prog_label_var,
                  style="Muted.Panel.TLabel").pack(side=tk.LEFT, padx=(0, 10))
        self.progress = ttk.Progressbar(right, mode="determinate", length=240)
        self.progress.pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Console plumbing
    # ------------------------------------------------------------------
    def log(self, msg, tag=None):
        self.log_q.put(("out", [(msg.rstrip("\n"), tag or "fg")]))

    def _clear_console(self):
        self.console.configure(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Library view
    # ------------------------------------------------------------------
    def _checked_text(self, path, base):
        """Compose row text with a selection checkbox prefix."""
        return ("☑ " if self._checked.get(path, False) else "☐ ") + base

    def _refresh_library(self, regrade=False):
        """Start a background scan + grade of the library folder."""
        folder = self.folder_var.get().strip()
        self._lib_folder = folder
        self._lyrics_format = str(
            self.config.get("lyrics_format", "EMBEDDED")
        ).upper()
        if regrade:
            self._grade_cache.clear()
        if not folder or not os.path.isdir(folder):
            self._artists = {}
            self._folder_artist = {}
            self._root_albums = []
            self._rebuild_tree()
            return
        self._scan_q = queue.Queue()
        self._library_busy = True
        if hasattr(self, "status_var"):
            self.status_var.set("Scanning library…")
        threading.Thread(
            target=self._library_worker, args=(regrade,), daemon=True
        ).start()
        # One persistent drain loop serves every scan and the one-shot
        # re-grades queued by the tag editor; start it only once.
        if not self._scan_draining:
            self._scan_draining = True
            self._drain_library()

    def _library_worker(self, regrade):
        # Capture the queue object: if the user starts a new scan, this
        # worker keeps filling the (abandoned) old queue instead of
        # mixing stale results into the new one.
        q = self._scan_q
        try:
            from mlo.stats import _find_albums
            from mlo.grader import _grade_album

            folder = self._lib_folder
            albums = _find_albums(folder)
            artists = {}
            root_albums = []

            for album_dir in albums:
                parent = os.path.dirname(album_dir)
                if parent == folder:
                    root_albums.append(album_dir)
                else:
                    artists.setdefault(parent, []).append(album_dir)

            q.put(("data", artists, root_albums))

            todo = [a for albs in artists.values() for a in albs]
            todo.extend(root_albums)
            if not regrade:
                todo = [a for a in todo if a not in self._grade_cache]

            from concurrent.futures import ThreadPoolExecutor, as_completed

            def grade_one(album_dir):
                try:
                    return album_dir, _grade_album(album_dir, self._lyrics_format)
                except Exception:
                    return album_dir, None

            workers = max(2, min(8, (os.cpu_count() or 2)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(grade_one, a) for a in todo]
                # as_completed (not pool.map) so finished albums render
                # immediately instead of waiting on slower predecessors.
                for fut in as_completed(futures):
                    album_dir, result = fut.result()
                    if result is None:
                        result = {"error": True, "path": album_dir}
                    q.put(("grade", album_dir, result))
        except Exception:
            pass
        q.put(("done",))

    def _drain_library(self):
        try:
            while True:
                kind, *payload = self._scan_q.get_nowait()
                if kind == "data":
                    self._artists, self._root_albums = payload
                    self._rebuild_tree()
                elif kind == "grade":
                    album_dir, result = payload
                    # Grade results carry the album's artist tag; enrich
                    # the folder -> artist map used by the filter.
                    artist = (result or {}).get("album_artist")
                    if artist:
                        parent = os.path.dirname(album_dir)
                        if parent and parent not in self._folder_artist:
                            self._folder_artist[parent] = artist
                    self._update_grade(album_dir, result)
                elif kind == "done":
                    self._library_busy = False
                    if hasattr(self, "status_var"):
                        self.status_var.set("Library scan complete")
                    if self._sort_mode() != "name" or self.bad_only_var.get():
                        self._rebuild_tree()
        except queue.Empty:
            pass
        self.after(120, self._drain_library)

    def _collect_open(self):
        """Return the set of paths of currently expanded tree items."""
        open_paths = set()
        stack = list(self.library_tree.get_children(""))
        while stack:
            item = stack.pop()
            if item in self._item_paths and self.library_tree.item(item, "open"):
                open_paths.add(self._item_paths[item])
            stack.extend(self.library_tree.get_children(item))
        return open_paths

    def _rebuild_tree(self):
        """Build the library tree from cached scan + grade data."""
        tree = self.library_tree
        open_paths = self._collect_open()
        scroll_frac = tree.yview()[0] if tree.get_children("") else 0.0
        for item in tree.get_children():
            tree.delete(item)
        self._item_paths = {}
        self._item_base = {}
        self._path_items = {}
        self._agg = {}
        self._agg_total = {}
        self._root_item = None

        compact = self.compact_var.get()
        tree.configure(show="tree" if compact else "tree headings")

        folder = self._lib_folder or self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            tree.insert("", "end",
                        text="No library folder set — use Browse to pick one")
            return

        filter_text = self.albumartist_var.get().strip().lower()
        artists = getattr(self, "_artists", {})
        root_albums = getattr(self, "_root_albums", [])
        folder_artist = getattr(self, "_folder_artist", {})

        root_text = f"All Folders ({os.path.basename(folder)})"
        self._root_item = tree.insert("", "end", text="", open=True)
        self._item_paths[self._root_item] = folder
        self._item_base[self._root_item] = root_text
        self._agg[self._root_item] = [0, 0, 0, 0, 0, set(), 0,
                                      set(), set(), set(), set(), 0, 0,
                                      set()]
        self._agg_total[self._root_item] = 0

        shown_any = False
        for parent_dir, album_dirs in sorted(
                artists.items(), key=lambda kv: self._artist_sort_key(kv[0])):
            artist_name = os.path.basename(parent_dir) or parent_dir
            tag_artist = folder_artist.get(parent_dir, "")
            if filter_text and filter_text not in artist_name.lower() \
                    and filter_text not in tag_artist.lower():
                continue
            visible = [d for d in album_dirs if self._album_visible(d)]
            if self.bad_only_var.get() and not visible:
                continue
            shown_any = True
            artist_item = tree.insert(self._root_item, "end", text="",
                                      open=False)
            self._item_paths[artist_item] = parent_dir
            self._item_base[artist_item] = artist_name
            self._agg[artist_item] = [0, 0, 0, 0, 0, set(), 0,
                                      set(), set(), set(), set(), 0, 0,
                                      set()]
            count_for_total = len(visible) if self.bad_only_var.get() else len(album_dirs)
            self._agg_total[artist_item] = count_for_total
            self._agg_total[self._root_item] += count_for_total
            for album_dir in sorted(visible, key=self._album_sort_key):
                self._insert_album(tree, artist_item, album_dir)

        root_visible = [d for d in root_albums if self._album_visible(d)]
        for album_dir in sorted(root_visible, key=self._album_sort_key):
            shown_any = True
            self._insert_album(tree, self._root_item, album_dir)
            self._agg_total[self._root_item] += 1

        tree.item(self._root_item, text=self._checked_text(
            folder, root_text + f" — {len(self._grade_cache)} graded"))

        for item_id, path in self._item_paths.items():
            if path in open_paths:
                tree.item(item_id, open=True)

        # Re-accumulate aggregates for albums already in the cache
        for item_id, path in self._item_paths.items():
            res = self._grade_cache.get(path)
            if res is None:
                continue
            parent = tree.parent(item_id)
            if parent:
                self._add_agg(parent, res)
                grand = tree.parent(parent)
                if grand:
                    self._add_agg(grand, res)

        self._apply_agg(self._root_item)
        for child in tree.get_children(self._root_item):
            self._apply_agg(child)
        self._apply_check_state(self._root_item)

        if filter_text and not shown_any:
            tree.insert("", "end", text="No albums match the filter")
        self._update_selection_label()
        if scroll_frac:
            tree.after_idle(lambda f=scroll_frac: tree.yview_moveto(f))

    def _album_visible(self, album_dir):
        """Bad-only filter: hide graded albums that passed."""
        if not self.bad_only_var.get():
            return True
        res = self._grade_cache.get(album_dir)
        if not res or "error" in res:
            return True
        return res["pass_count"] != res["total_checks"]

    def _insert_album(self, tree, parent_item, album_dir):
        base = os.path.basename(album_dir)
        item = tree.insert(parent_item, "end",
                           text=self._checked_text(album_dir, base),
                           open=False, tags=("pending",))
        self._item_paths[item] = album_dir
        self._item_base[item] = base
        self._path_items.setdefault(album_dir, set()).add(item)
        res = self._grade_cache.get(album_dir)
        if res is None:
            tree.item(item, values=("…", "…", "", "", "", "", ""))
        else:
            self._apply_album_grade(tree, item, album_dir, res)
        return item

    # ------------------------------------------------------------------
    # Row states: green = graded pass, purple = audited only,
    # blue = graded + audited, yellow = warnings / mixed, red = failing.
    # ------------------------------------------------------------------
    AUDIT_BAD = ("FAKE",)
    AUDIT_WARN = ("MIX", "WARN", "UNKNOWN")

    @classmethod
    def _row_state(cls, grade_ok, audit):
        """Pick the tree row tag from (grade passed?, audit verdict).

        grade_ok: True = all checks pass, False = failing, None = partial
        (aggregates) - full albums/tracks always pass a real boolean.
        audit:   REAL / FAKE / Mix (compared case-insensitively).
        """
        audit = str(audit).upper() if audit else None
        if audit in cls.AUDIT_BAD:
            return "fail"
        if audit == "REAL":
            return "both" if grade_ok else "audited"
        if audit in cls.AUDIT_WARN:
            return "mixed" if grade_ok else "fail"
        if grade_ok is None:
            return "mixed"
        return "pass" if grade_ok else "fail"

    def _fmt_tag_val(self, v, max_len=10):
        s = str(v).strip() if v is not None else ""
        if not s or s == "INCONSISTENT":
            return "—"
        return s[:max_len]

    def _fmt_vals(self, vals, max_n=3, max_len=10):
        clean = sorted(
            str(v).strip() for v in vals
            if v is not None and str(v).strip()
            and str(v).strip() != "INCONSISTENT"
        )
        if not clean:
            return "—"
        out = "|".join(v[:max_len] for v in clean[:max_n])
        if len(clean) > max_n:
            out += f"+{len(clean) - max_n}"
        return out

    def _sum_key(self, res, key):
        vals = set()
        for tr in res.get("tracks") or []:
            v = (tr.get("values") or {}).get(key)
            if v is not None and str(v).strip():
                vals.add(str(v).strip())
        return self._fmt_vals(vals)

    def _track_tags_txt(self, tr, aa_value=None):
        """TAGS layout: G A I L AA (matches the column-heading key)."""
        v = tr.get("values") or {}
        lyr = 1 if (tr.get("lyrics_embedded") or tr.get("lyrics_lrc")) else 0
        return (
            f"G:{self._fmt_tag_val(v.get('GENRE'), 12)} "
            f"A:{self._fmt_tag_val(v.get('ITUNESADVISORY'), 8)} "
            f"I:{self._fmt_tag_val(v.get('INSTRUMENTAL'), 4)} "
            f"L:{lyr} "
            f"AA:{self._fmt_tag_val(aa_value, 8)}"
        )

    def _album_tags_txt(self, res):
        """TAGS layout: G A I L AA (matches the column-heading key)."""
        av = res.get("album_values") or {}
        tracks = res.get("tracks") or []
        lyr = sum(
            1 for tr in tracks
            if tr.get("lyrics_embedded") or tr.get("lyrics_lrc")
        )
        tot = res.get("track_count") or 0
        return (
            f"G:{self._sum_key(res, 'GENRE')} "
            f"A:{self._sum_key(res, 'ITUNESADVISORY')} "
            f"I:{self._sum_key(res, 'INSTRUMENTAL')} "
            f"L:{lyr}/{tot} "
            f"AA:{self._fmt_tag_val(av.get('ALBUMITUNESADVISORY'), 8)}"
        )

    def _apply_album_grade(self, tree, item, album_dir, res):
        if "error" in res:
            tree.item(item, values=("ERR", "ERR", "", "", "", "", ""),
                      tags=("fail",))
            return
        ok = res["pass_count"] == res["total_checks"]
        audit = res.get("audit_summary")
        aa_value = (res.get("album_values") or {}).get("ALBUMITUNESADVISORY")
        tree.item(item, values=(
            "PASS" if ok else "FAIL",
            audit or "—",
            f"{res['pass_count']}/{res['total_checks']}",
            res["track_count"],
            res["media"],
            res["cover_file"] or "MISSING",
            self._album_tags_txt(res),
        ), tags=(self._row_state(ok, audit),))
        if not self.compact_var.get():
            for child in tree.get_children(item):
                # Drop the row from the path maps so stale item ids (Tk
                # never reuses them) don't accumulate across re-grades.
                p = self._item_paths.pop(child, None)
                if p is not None:
                    s = self._path_items.get(p)
                    if s is not None:
                        s.discard(child)
                        if not s:
                            del self._path_items[p]
                self._item_base.pop(child, None)
                tree.delete(child)
            for tr in res["tracks"]:
                self._insert_track(tree, item, album_dir, tr, aa_value)

    def _insert_track(self, tree, album_item, album_dir, tr, aa_value=None):
        path = os.path.join(album_dir, tr["file"])
        issues = tr.get("issues") or []
        ok = not issues and not tr.get("unreadable")
        audit = tr.get("audit")
        base = tr["file"]
        item = tree.insert(album_item, "end",
                           text=self._checked_text(path, base),
                           open=False,
                           tags=(self._row_state(ok, audit),))
        self._item_paths[item] = path
        self._item_base[item] = base
        self._path_items.setdefault(path, set()).add(item)
        tree.item(item, values=(
            "OK" if ok else "FAIL",
            audit or "—",
            str(len(issues)) if issues else "",
            "—",
            tr["values"].get("MEDIA") or "",
            "—",
            self._track_tags_txt(tr, aa_value),
        ))

    def _update_grade(self, album_dir, result):
        was_cached = album_dir in self._grade_cache
        self._grade_cache[album_dir] = result
        tree = self.library_tree
        items = self._path_items.get(album_dir)
        item = next(iter(items), None) if items else None
        if item is None:
            return
        self._apply_album_grade(tree, item, album_dir, result)
        if not was_cached:
            parent = tree.parent(item)
            if parent:
                self._add_agg(parent, result)
                grand = tree.parent(parent)
                if grand:
                    self._add_agg(grand, result)

    def _add_agg(self, item, res):
        agg = self._agg.get(item)
        if agg is None:
            return
        agg[0] += 1
        if "error" not in res:
            agg[1] += 1 if res["pass_count"] == res["total_checks"] else 0
            agg[2] += res["total_checks"]
            agg[3] += res["pass_count"]
            agg[4] += res["track_count"]
            if res.get("media"):
                agg[5].add(str(res["media"]))
            agg[6] += 1 if res.get("cover_file") else 0
            av = res.get("album_values") or {}
            aa = av.get("ALBUMITUNESADVISORY")
            if aa is not None and str(aa).strip():
                agg[7].add(str(aa).strip())
            for tr in res.get("tracks") or []:
                v = tr.get("values") or {}
                for idx, key in ((8, "ITUNESADVISORY"), (9, "GENRE"),
                                 (10, "INSTRUMENTAL")):
                    val = v.get(key)
                    if val is not None and str(val).strip():
                        agg[idx].add(str(val).strip())
                if tr.get("lyrics_embedded") or tr.get("lyrics_lrc"):
                    agg[11] += 1
            agg[12] += res.get("track_count") or 0
            if res.get("audit_summary"):
                agg[13].add(str(res["audit_summary"]))
        self._apply_agg(item)

    def _apply_agg(self, item):
        agg = self._agg.get(item)
        if agg is None:
            return
        (albums, passed, checks, pass_checks, tracks, media_set, covers,
         aa_set, ta_set, genre_set, inst_set, lyrics, track_total,
         audit_set) = agg
        grade_txt = f"{passed}/{albums}" if albums else "—"
        from mlo.grader import summarize_audits
        audit_txt = summarize_audits(audit_set) or "—"
        checks_txt = f"{pass_checks}/{checks}" if checks else "—"
        media_txt = "Mixed" if len(media_set) > 1 \
            else (next(iter(media_set), "") or "—")
        cover_txt = f"{covers}/{albums}" if albums else "—"
        tags_txt = (
            f"G:{self._fmt_vals(genre_set)} "
            f"A:{self._fmt_vals(ta_set)} "
            f"I:{self._fmt_vals(inst_set)} "
            f"L:{lyrics}/{track_total} "
            f"AA:{self._fmt_vals(aa_set)}"
        ) if albums else ""
        self.library_tree.item(item, values=(
            grade_txt, audit_txt, checks_txt, tracks or "—", media_txt,
            cover_txt, tags_txt))
        expected = self._agg_total.get(item, albums)
        if albums and albums >= expected:
            if passed == albums:
                grade_ok = True
            elif passed == 0:
                grade_ok = False
            else:
                grade_ok = None  # partially passing -> mixed at best
            self.library_tree.item(
                item, tags=(self._row_state(grade_ok, audit_txt),))

    def _apply_check_state(self, item):
        path = self._item_paths.get(item)
        base = self._item_base.get(item)
        if path and base is not None:
            self.library_tree.item(item, text=self._checked_text(path, base))
        for child in self.library_tree.get_children(item):
            self._apply_check_state(child)

    def _on_tree_click(self, event):
        item = self.library_tree.identify_row(event.y)
        if not item:
            return
        if self.library_tree.identify_region(event.x, event.y) not in ("tree", "cell"):
            return
        bbox = self.library_tree.bbox(item, column="#0")
        if bbox and event.x < bbox[0] - 8:
            self.library_tree.item(
                item, open=not bool(self.library_tree.item(item, "open"))
            )
            return
        if event.state & 0x0001:  # Shift held -> range select
            self._select_range(item)
        else:
            # Plain click or Ctrl+click toggles the single item and
            # becomes the anchor for a later Shift+click range.
            self._toggle_item(item)
            self._last_anchor = item

    def _on_tree_double(self, event):
        item = self.library_tree.identify_row(event.y)
        if item:
            self.library_tree.item(
                item, open=not bool(self.library_tree.item(item, "open"))
            )

    def _tree_items_in_order(self):
        """Flattened list of tree items in display order."""
        items = []

        def walk(parent):
            for child in self.library_tree.get_children(parent):
                items.append(child)
                walk(child)

        walk("")
        return items

    def _select_range(self, target):
        """Shift+click: check every item between the anchor and target."""
        items = self._tree_items_in_order()
        anchor = getattr(self, "_last_anchor", None) or target
        try:
            lo, hi = sorted((items.index(anchor), items.index(target)))
        except ValueError:
            lo = hi = len(items) - 1
        for iid in items[lo:hi + 1]:
            path = self._item_paths.get(iid)
            base = self._item_base.get(iid)
            if path and base is not None:
                self._checked[path] = True
        if self._root_item is not None:
            self._apply_check_state(self._root_item)
        self._update_selection_label()
        self._last_anchor = target

    def _toggle_item(self, item):
        path = self._item_paths.get(item)
        base = self._item_base.get(item)
        if not path or base is None:
            return
        self._checked[path] = not self._checked.get(path, False)
        self.library_tree.item(item, text=self._checked_text(path, base))
        self._update_selection_label()

    def _select_all(self, event=None):
        """Ctrl+A: check every item in the tree (except the root)."""
        self._checked.clear()
        for item_id, path in self._item_paths.items():
            if path and item_id != self._root_item:
                self._checked[path] = True
        if self._root_item is not None:
            self._apply_check_state(self._root_item)
        self._update_selection_label()
        return "break"

    def _select_all_global(self, event=None):
        """Ctrl+A bound on the app window; ignore when typing in an Entry."""
        w = self.focus_get()
        if w is not None and isinstance(w, (ttk.Entry, tk.Entry)):
            return None
        return self._select_all(event)

    def _update_selection_label(self):
        n = sum(1 for c in self._checked.values() if c)
        self.sel_label_var.set(f"{n} selected")
        if not self.running:
            self.opt_selected_btn.configure(
                state=tk.NORMAL if n else tk.DISABLED
            )

    def _clear_selection(self):
        self._checked.clear()
        if self._root_item is not None:
            self._apply_check_state(self._root_item)
        self._update_selection_label()

    def _clear_filter(self):
        self.albumartist_var.set("")
        self._rebuild_tree()

    def _optimize_selected(self):
        targets = [p for p, c in self._checked.items() if c]
        if not targets:
            return
        order = list(self.config.get("run_all_order", [1, 2, 3, 5, 4]))
        # Optimize Selected always finishes with an audio audit so the
        # AUDIT tags (and the viewer's audit column) stay current.
        if 6 not in order:
            order.append(6)
        self._run_scripts(
            order, f"OPTIMIZE SELECTED ({len(targets)} items)", targets=targets
        )

    def _on_compact_toggle(self):
        self.config["compact_ui"] = self.compact_var.get()
        save_config(self.config)
        self.library_tree.configure(
            show="tree" if self.compact_var.get() else "tree headings")
        self._refresh_console_compact()

    def _on_force_master(self):
        """Master Force pill: on = every force option on, off = all off."""
        on = self.force_var.get()
        self.force_flac_var.set(on)
        self.force_images_var.set(on)
        self.force_audit_var.set(on)
        self._save_force_config()

    def _on_force_option(self):
        """An individual force option changed: the master pill reflects
        whether all of them are on."""
        self.force_var.set(self.force_flac_var.get()
                           and self.force_images_var.get()
                           and self.force_audit_var.get())
        self._save_force_config()

    def _save_force_config(self):
        self.config["force_ui"] = self.force_var.get()
        self.config["force_flac_ui"] = self.force_flac_var.get()
        self.config["force_images_ui"] = self.force_images_var.get()
        self.config["force_audit_ui"] = self.force_audit_var.get()
        save_config(self.config)

    def _show_force_menu(self):
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        menu.add_command(label="Force options", state=tk.DISABLED)
        menu.add_separator()
        for var, label in (
            (self.force_flac_var, "Re-encode FLACs"),
            (self.force_images_var, "Re-encode images"),
            (self.force_audit_var, "Audit"),
        ):
            menu.add_checkbutton(label=label, variable=var, onvalue=True,
                                 offvalue=False,
                                 command=self._on_force_option)
        menu.add_separator()
        menu.add_command(label="All on",
                         command=lambda: (self.force_var.set(True),
                                          self._on_force_master()))
        menu.add_command(label="All off",
                         command=lambda: (self.force_var.set(False),
                                          self._on_force_master()))
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        try:
            menu.grab_release()
        except tk.TclError:
            pass

    def _on_albumartist_change(self, event=None):
        """Handle album artist filter text change (debounced: rebuilding
        the whole tree on every keystroke is far too costly)."""
        if self._filter_job is not None:
            try:
                self.after_cancel(self._filter_job)
            except Exception:
                pass
        self._filter_job = self.after(200, self._apply_filter)

    def _apply_filter(self):
        self._filter_job = None
        self._rebuild_tree()

    def _on_filter_change(self):
        """Bad-only toggle changed."""
        self._rebuild_tree()

    def _on_sort_change(self, event=None):
        """Grade sort combobox changed."""
        key = self._sort_rev.get(self.sort_var.get(), "name")
        self.config["library_sort"] = key
        save_config(self.config)
        self._rebuild_tree()

    def _sort_mode(self):
        key = self._sort_rev.get(self.sort_var.get(), "name")
        return key if key in ("grade_bad", "grade_good") else "name"

    def _album_sort_key(self, d):
        """Sort key for an album dir: graded-first, then pass ratio, then name."""
        res = self._grade_cache.get(d)
        name = os.path.basename(d).lower()
        mode = self._sort_mode()
        if mode == "name":
            return (0, 0.0, name)
        if not res or "error" in res:
            return (1, 0.0, name)
        frac = res["pass_count"] / max(1, res["total_checks"])
        if mode == "grade_good":
            frac = -frac
        return (0, frac, name)

    def _artist_sort_key(self, parent_dir):
        """Sort key for an artist folder: worst album ratio, then name."""
        albums = (getattr(self, "_artists", {}) or {}).get(parent_dir, [])
        name = os.path.basename(parent_dir).lower()
        mode = self._sort_mode()
        if mode == "name":
            return (0, 0.0, name)
        worst = 1.0
        graded_any = False
        for d in albums:
            res = self._grade_cache.get(d)
            if res and "error" not in res:
                graded_any = True
                frac = res["pass_count"] / max(1, res["total_checks"])
                worst = min(worst, frac)
        if not graded_any:
            return (1, 0.0, name)
        if mode == "grade_good":
            worst = -worst
        return (0, worst, name)

    def _refresh_console_compact(self):
        """Update console fonts when compact mode toggles."""
        compact = self.compact_var.get()
        try:
            self.console.configure(font=(self._monospace, 8 if compact else 10))
            self._console_bold_font.configure(size=8 if compact else 10)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Grade details + tag editing
    # ------------------------------------------------------------------
    def _find_album_for_item(self, item):
        """Return (album_dir, cached grade result) for an album or track row."""
        path = self._item_paths.get(item)
        if not path:
            return None, None
        res = self._grade_cache.get(path)
        if res is not None:
            return path, res
        parent = self.library_tree.parent(item)
        while parent:
            p = self._item_paths.get(parent)
            if p and p in self._grade_cache:
                return p, self._grade_cache[p]
            parent = self.library_tree.parent(parent)
        return None, None

    # ------------------------------------------------------------------
    # Column visibility (right-click any column heading)
    # ------------------------------------------------------------------
    def _apply_column_visibility(self):
        # Tk 8.6 has no per-column -display option; the widget-level
        # displaycolumns list is the supported way to hide columns.
        shown = [c for c in TREE_COLUMNS if self._col_visible.get(c, True)]
        try:
            self.library_tree.configure(displaycolumns=shown or ["#all"])
        except tk.TclError:
            self.library_tree.configure(displaycolumns="#all")

    def _toggle_column(self, col):
        self._col_visible[col] = not self._col_visible[col]
        self.config["library_columns"] = dict(self._col_visible)
        save_config(self.config)
        self._apply_column_visibility()

    def _show_column_menu(self, event):
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        menu.add_command(label="Columns", state=tk.DISABLED)
        menu.add_separator()
        for col, (heading, _w, _d) in TREE_COLUMNS.items():
            var = tk.BooleanVar(value=self._col_visible.get(col, True))
            menu.add_checkbutton(
                label=heading.replace(" · G A I L AA", ""),
                variable=var, onvalue=True, offvalue=False,
                command=lambda c=col: self._toggle_column(c),
            )
        menu.add_separator()
        menu.add_command(label="TAGS key: G Genre · A Advisory · "
                               "I Instrumental · L Lyrics · AA Album Advisory",
                         state=tk.DISABLED)
        menu.tk_popup(event.x_root, event.y_root)
        try:
            menu.grab_release()
        except tk.TclError:
            pass

    def _on_tree_menu(self, event):
        """Right-click context menu on the library tree."""
        region = self.library_tree.identify_region(event.x, event.y)
        if region in ("heading", "separator"):
            self._show_column_menu(event)
            return
        item = self.library_tree.identify_row(event.y)
        if not item:
            return
        path = self._item_paths.get(item)
        album_dir, res = self._find_album_for_item(item)

        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        if res is not None:
            menu.add_command(label="Grade details…",
                             command=lambda: self._show_grade_details(item))
        if album_dir:
            is_track = path is not None and path != album_dir
            menu.add_command(
                label="Edit track tags…" if is_track else "Edit album tags…",
                command=lambda: self._open_tag_editor(
                    album_dir, path if is_track else None))
        target_dir = path if (path and os.path.isdir(path)) else album_dir
        if target_dir:
            menu.add_separator()
            menu.add_command(
                label="Enqueue in foobar2000",
                command=lambda: self._open_in_external(
                    "foobar2000", [target_dir]))
            menu.add_command(
                label="Open in Mp3tag",
                command=lambda: self._open_in_external("mp3tag", [target_dir]))
            menu.add_command(
                label="Open in Picard",
                command=lambda: self._open_in_external("picard", [target_dir]))
        if menu.index("end") is not None:
            menu.tk_popup(event.x_root, event.y_root)
        try:
            menu.grab_release()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # External taggers (Mp3tag / MusicBrainz Picard)
    # ------------------------------------------------------------------
    def _selected_album_dirs(self):
        """Unique directories covered by the checked tree items.

        Track rows map to their album folder; artist/root rows count as
        the folder itself.
        """
        dirs = []
        seen = set()
        for path, on in self._checked.items():
            if not on or not path:
                continue
            d = os.path.dirname(path) if os.path.isfile(path) else path
            if d and d not in seen and os.path.isdir(d):
                seen.add(d)
                dirs.append(d)
        return sorted(dirs)

    def _open_in_external(self, key, dirs=None):
        """Launch Mp3tag / Picard with the given (or selected) folders."""
        spec = EXTERNAL_TOOLS[key]
        label = spec["label"]
        if dirs is None:
            dirs = self._selected_album_dirs()
        if not dirs:
            self.status_var.set(f"No folders selected — check items in the "
                                f"library tree first.")
            self.log(f"{label}: nothing selected. Tick one or more albums "
                     f"(or artists) in the library tree first.", tag="yellow")
            return

        exe = find_external_tool(key, self.config)
        if not exe:
            if not messagebox.askyesno(
                f"{label} not found",
                f"{label} could not be located automatically.\n\n"
                f"Locate the {spec['exe']} executable manually?",
            ):
                return
            exe = filedialog.askopenfilename(
                parent=self, title=f"Locate {spec['exe']}",
                filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
            )
            if not exe:
                return
            self.config[spec["config_key"]] = os.path.normpath(exe)
            save_config(self.config)
            self.log(f"{label} path saved: {exe}", tag="muted")

        try:
            # GUI application: Popen without waiting; CREATE_NO_WINDOW keeps
            # any console-stub launcher from flashing a window.
            subprocess.Popen(
                [exe] + spec.get("args", []) + dirs,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
        except Exception as e:
            self.log(f"Could not launch {label}: {e}", tag="red")
            messagebox.showerror(label, f"Could not launch {label}:\n{e}")
            return

        n = len(dirs)
        verb = "Enqueued" if spec.get("args") else "Opened"
        self.log(f"{verb} {n} folder{'s' if n != 1 else ''} in {label}.",
                 tag="green")
        self.status_var.set(
            f"{verb} {n} folder{'s' if n != 1 else ''} in {label}.")

    def _show_grade_details(self, item):
        """Dialog listing exactly which grade checks failed."""
        album_dir, res = self._find_album_for_item(item)
        if res is None:
            return
        path = self._item_paths.get(item)
        track_file = path if (album_dir and path != album_dir) else None

        win = tk.Toplevel(self)
        win.title("Grade Details" + (
            f" — {os.path.basename(track_file)}"
            if track_file else f" — {os.path.basename(album_dir)}"
        ))
        win.configure(background=PANEL)
        win.transient(self)
        win.grab_set()
        win.geometry("680x520")
        win.minsize(560, 360)

        box = ttk.Frame(win, padding=14)
        box.pack(fill=tk.BOTH, expand=True)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)

        txt = tk.Text(box, wrap="none", state=tk.DISABLED, background=FIELD,
                      foreground=TEXT, borderwidth=0, insertbackground=TEXT,
                      highlightthickness=0, font=(self._monospace, 9))
        ysb = ttk.Scrollbar(box, orient=tk.VERTICAL, command=txt.yview)
        xsb = ttk.Scrollbar(box, orient=tk.HORIZONTAL, command=txt.xview)
        txt.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        txt.grid(row=0, column=0, sticky="nswe")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        for tag, color in (("red", RED), ("green", GREEN), ("bold", BRIGHT)):
            txt.tag_configure(tag, foreground=color)
        txt.tag_configure("bold", font=_font(9, "bold"))

        def emit(text, style=None):
            txt.configure(state=tk.NORMAL)
            txt.insert(tk.END, text + "\n", style or ())
            txt.configure(state=tk.DISABLED)

        from mlo.grader import format_grade_report
        emit(os.path.basename(album_dir), "bold")
        for text, style in format_grade_report(
                res, self._lyrics_format, track_file=track_file):
            emit(text, style)

        btn = ttk.Frame(box)
        btn.grid(row=2, column=0, sticky="e", pady=(8, 0))
        ttk.Button(btn, text="Close", style="Small.TButton",
                   command=win.destroy).pack()

    def _open_tag_editor(self, album_dir, track_path=None):
        """Dialog to edit every textual tag on a track / album's tracks."""
        if track_path:
            files = [track_path]
        else:
            from mlo.stats import is_audio_file
            files = sorted(
                os.path.join(album_dir, f)
                for f in os.listdir(album_dir) if is_audio_file(f))
        if not files:
            messagebox.showinfo("Edit Tags", "No audio files to edit.")
            return

        from mlo.audio import AudioFile
        first = AudioFile(files[0])
        if first.audio is None:
            messagebox.showerror(
                "Edit Tags",
                f"Cannot read {os.path.basename(files[0])}: {first.error}")
            return

        title = ("Tag Editor — " + os.path.basename(track_path)
                 if track_path else
                 f"Tag Editor — {os.path.basename(album_dir)} "
                 f"({len(files)} files)")

        win = tk.Toplevel(self)
        win.title(title)
        win.configure(background=PANEL)
        win.transient(self)
        win.grab_set()
        win.minsize(560, 360)

        outer = ttk.Frame(win, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        card = ttk.Frame(outer, style="Card.TFrame")
        card.grid(row=0, column=0, sticky="nswe")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(0, weight=1)

        canvas = tk.Canvas(card, background=CARD, highlightthickness=0)
        vsb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nswe")
        vsb.grid(row=0, column=1, sticky="ns")

        rows_frame = ttk.Frame(canvas, style="Card.TFrame")
        rows_frame.columnconfigure(1, weight=1)
        window_id = canvas.create_window((0, 0), window=rows_frame, anchor="nw")
        rows_frame.bind(
            "<Configure>",
            lambda e: (canvas.configure(scrollregion=canvas.bbox("all")),
                       canvas.itemconfigure(window_id, width=e.width)))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(window_id, width=e.width))

        def close():
            canvas.unbind_all("<MouseWheel>")
            win.destroy()

        existing = first.all_tags()
        seen = {}
        for key in list(existing) + [k for _, k in COMMON_TAGS]:
            folded = key.lower()
            if folded not in seen:
                seen[folded] = key
        keys = sorted(seen.values(), key=str.lower)
        row_meta = {}

        def add_row(key):
            row = ttk.Frame(rows_frame, style="Card.TFrame")
            row.grid(row=len(row_meta), column=0, sticky="ew", padx=10, pady=2)
            row.columnconfigure(1, weight=1)
            var = tk.StringVar(value=existing.get(key, ""))
            var._row_widget = row
            row_meta[key] = var
            ttk.Button(
                row, text="\u00d7", style="Small.TButton", width=2,
                command=lambda k=key: remove_row(k)
            ).grid(row=0, column=0, padx=(0, 8))
            ttk.Label(row, text=key, style="Card.TLabel",
                      font=_sfont(9)).grid(
                row=0, column=1, sticky="w", padx=(0, 12))
            ttk.Entry(row, textvariable=var).grid(
                row=0, column=2, sticky="ew", padx=(0, 6))
            self._relabel_tag_rows(rows_frame)

        def remove_row(key):
            var = row_meta.pop(key)
            var._row_widget.destroy()
            self._relabel_tag_rows(rows_frame)

        for key in keys:
            add_row(key)

        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        footer = ttk.Frame(outer)
        footer.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(1, weight=1)

        ttk.Button(
            footer, text="Add tag\u2026", style="Small.TButton",
            command=lambda: self._add_tag_menu(footer, row_meta, add_row)
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            footer,
            text="Empty value removes the tag. Applies to all listed files.",
            style="Muted.TLabel", font=_font(8),
        ).grid(row=0, column=1, sticky="w", padx=(10, 0))

        btns = ttk.Frame(footer)
        btns.grid(row=0, column=2, sticky="e")
        ttk.Button(btns, text="Save", style="Accent.TButton",
                   command=lambda: self._save_tag_editor(
                       win, album_dir, files, row_meta, close)
                   ).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", style="Small.TButton",
                   command=close).pack(side=tk.RIGHT, padx=(0, 8))

        win.protocol("WM_DELETE_WINDOW", close)
        win.bind("<Escape>", lambda e: close())

    def _relabel_tag_rows(self, rows_frame):
        for i, r in enumerate(rows_frame.winfo_children()):
            r.grid_configure(row=i)

    def _add_tag_menu(self, parent, row_meta, add_row):
        """Popup menu of common tags + custom entry to add a new row."""
        menu = tk.Menu(parent, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        for label, key in COMMON_TAGS:
            if key not in row_meta:
                menu.add_command(label=label, command=lambda k=key: add_row(k))
        menu.add_separator()
        for label, key in RAW_TAGS:
            if key not in row_meta:
                menu.add_command(label=label, command=lambda k=key: add_row(k))
        menu.add_separator()
        menu.add_command(label="Custom tag\u2026",
                         command=lambda: self._custom_tag(row_meta, add_row))
        try:
            menu.tk_popup(parent.winfo_pointerx(), parent.winfo_pointery())
        finally:
            menu.grab_release()

    def _custom_tag(self, row_meta, add_row):
        import tkinter.simpledialog as simpledialog
        key = simpledialog.askstring("Add tag", "Tag key:")
        if key and key.strip() and key.strip() not in row_meta:
            add_row(key.strip())

    def _save_tag_editor(self, win, album_dir, files, row_meta, close):
        """Write edited tag values (per-file diff) on a worker thread, then
        re-grade. The dialog closes immediately; progress lands in the
        console / status bar."""
        changes = {key: var.get().strip() for key, var in row_meta.items()}
        close()

        def work():
            from mlo.audio import AudioFile
            modified_files = 0
            errors = []

            for path in files:
                af = AudioFile(path)
                if af.audio is None:
                    errors.append(f"{os.path.basename(path)}: {af.error}")
                    continue

                current = af.all_tags()
                file_changed = False
                for key, new in changes.items():
                    cur_key = None
                    cur_str = ""
                    for k, v in current.items():
                        if k.lower() == key.lower():
                            cur_key = k
                            cur_str = str(v).strip()
                            break
                    if cur_str == new:
                        continue
                    if new == "":
                        if cur_str and af.delete_any_tag(key):
                            file_changed = True
                    else:
                        target = cur_key or key
                        if af.set_any_tag(target, new):
                            file_changed = True
                        else:
                            errors.append(
                                f"{os.path.basename(path)}: {af.error}")
                if file_changed:
                    modified_files += 1

            if errors:
                self.log("Tag edit errors: " + "; ".join(errors), tag="red")
            if modified_files:
                self.log(f"Edited tags in {modified_files} file(s): "
                         f"{os.path.basename(album_dir)}", tag="green")
                self.log_q.put(("status", "Tags updated — re-grading album…"))
                self._regrade_album(album_dir)
            else:
                self.log_q.put(("status", "No tag changes saved."))

        threading.Thread(target=work, daemon=True).start()

    def _regrade_album(self, album_dir):
        """Re-grade a single album in the background and refresh its row."""
        def run():
            try:
                from mlo.grader import _grade_album
                result = _grade_album(album_dir, self._lyrics_format)
            except Exception:
                result = None
            if result is None:
                result = {"error": True, "path": album_dir}
            self._scan_q.put(("grade", album_dir, result))

        threading.Thread(target=run, daemon=True).start()

    def _regrade_targets(self, targets):
        """Queue background re-grades for the albums covered by run
        targets (files resolve to their album folder; artist folders
        expand to their albums; anything unknown falls back to a full
        library refresh)."""
        albums = set()
        full = False
        for t in targets:
            if not t:
                continue
            d = os.path.dirname(t) if os.path.isfile(t) else t
            if d in self._grade_cache:
                albums.add(d)
            elif d in (self._artists or {}):
                albums.update(self._artists[d])
            else:
                full = True
        if full or not albums:
            self._refresh_library(regrade=True)
            return
        for d in sorted(albums):
            self._regrade_album(d)

    def _copy_console(self):
        text = self.console.get("1.0", tk.END).strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set("Console output copied to clipboard.")

    def _drain_log(self):
        try:
            while True:
                kind, payload = self.log_q.get_nowait()
                if kind == "out":
                    self.console.configure(state=tk.NORMAL)
                    if payload and payload[-1][0].endswith("\n"):
                        stripped = payload[-1][0].rstrip("\n")
                        payload = list(payload)
                        payload[-1] = (stripped, payload[-1][1])
                    for text, tag in payload:
                        if text:
                            self.console.insert(tk.END, text, tag)
                    self.console.insert(tk.END, "\n", "fg")
                    self.console.configure(state=tk.DISABLED)
                    if self.autoscroll_var.get():
                        self.console.see(tk.END)
                elif kind == "nl":
                    self.console.configure(state=tk.NORMAL)
                    self.console.insert(tk.END, "\n", "fg")
                    self.console.configure(state=tk.DISABLED)
                    if self.autoscroll_var.get():
                        self.console.see(tk.END)
                elif kind == "prog":
                    done, total, desc = payload
                    if total:
                        self.progress.configure(maximum=total, value=min(done, total))
                        self.prog_label_var.set(f"{desc}  {done}/{total}")
                    else:
                        self.progress.configure(value=0)
                        self.prog_label_var.set("")
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "done":
                    self._set_running(False)
                    self.status_var.set(f"Ready — completed in {payload:.1f}s")
                    self.progress.configure(value=0)
                    self.prog_label_var.set("")
                    # Runs may have changed tags (audit verdicts, lyrics,
                    # MEDIA/SOURCE): refresh the library view so grades,
                    # the AUDIT column and row colors stay current.
                    pending = getattr(self, "_regrade_after", None)
                    self._regrade_after = None
                    if pending == "all":
                        self._refresh_library(regrade=True)
                    elif pending:
                        self._regrade_targets(pending)
                elif kind == "pause":
                    self.continue_btn.pack(side=tk.LEFT, padx=(0, 10))
                    self.status_var.set(f"Paused — Continue to run {payload}")
        except queue.Empty:
            pass
        self.after(80, self._drain_log)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _pick_folder(self):
        path = filedialog.askdirectory(initialdir=self.folder_var.get() or "/")
        if path:
            self.folder_var.set(path)
            self.config["music_folder"] = path
            save_config(self.config)
            self.log(f"Library folder set to: {path}")
            self._refresh_library(regrade=True)

    def _open_config(self):
        if self.running:
            messagebox.showinfo("Busy", "Wait for the current operation to finish.")
            return
        # The dialog mutates the live config dict; snapshot the values that
        # decide whether a full (expensive) library re-grade is needed.
        self._pre_save_snapshot = (
            self.config.get("music_folder", ""),
            str(self.config.get("lyrics_format", "EMBEDDED")).upper(),
        )
        ConfigDialog(self, self.config, self._config_saved)

    def _config_saved(self, cfg):
        self.config = cfg
        self.folder_var.set(cfg.get("music_folder", ""))
        self.log("Settings saved.", tag="green")
        old_folder, old_fmt = getattr(self, "_pre_save_snapshot", (None, None))
        folder_changed = cfg.get("music_folder", "") != old_folder
        fmt_changed = str(cfg.get("lyrics_format", "EMBEDDED")).upper() != old_fmt
        self._refresh_library(regrade=folder_changed or fmt_changed)

    def _show_about(self):
        """Show About dialog with version info and update check."""
        from mlo import __version__
        win = tk.Toplevel(self)
        win.title("About Music Library Optimizer")
        win.configure(background=PANEL)
        win.transient(self)
        win.grab_set()
        win.geometry("480x360")
        win.resizable(False, False)

        box = ttk.Frame(win, padding=24)
        box.pack(fill=tk.BOTH, expand=True)

        try:
            icon_file = os.path.join(SCRIPT_DIR, "app_icon.ico")
            if os.path.isfile(icon_file):
                win.iconbitmap(default=icon_file)
        except tk.TclError:
            pass

        ttk.Label(box, text="Music Library Optimizer", style="H1.TLabel").pack(anchor="w")
        ttk.Label(box, text=f"Version {__version__}", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))

        ttk.Separator(box).pack(fill=tk.X, pady=(0, 12))

        ttk.Label(box,
                  text="Lossless audio & image processing suite for maintaining "
                       "a tagged, graded, audited music library.",
                  style="Muted.TLabel", wraplength=400).pack(anchor="w", pady=(0, 8))

        ttk.Label(box,
                  text="GitHub: https://github.com/dillydalli3r/MusicLibraryOptimizer",
                  style="Muted.TLabel", wraplength=400).pack(anchor="w", pady=(0, 16))

        ttk.Separator(box).pack(fill=tk.X, pady=(0, 12))

        def check_updates():
            btn.configure(state=tk.DISABLED, text="Checking...")
            def cb(version, url, notes):
                if version:
                    win.after(0, lambda: self._show_update_dialog(version, url, notes))
                else:
                    win.after(0, lambda: self._show_no_update())
                win.after(0, lambda: btn.configure(state=tk.NORMAL, text="Check for Updates"))
            updater.check_for_updates(silent=False, callback=cb)

        def open_github():
            import webbrowser
            webbrowser.open("https://github.com/dillydalli3r/MusicLibraryOptimizer")

        btn_frame = ttk.Frame(box)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        btn = ttk.Button(btn_frame, text="Check for Updates", style="Accent.TButton",
                         command=check_updates)
        btn.pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="View on GitHub", style="Small.TButton",
                   command=open_github).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(box, text="Close", style="Small.TButton",
                   command=win.destroy).pack(side=tk.RIGHT, pady=(16, 0))

    def _show_update_dialog(self, version, url, notes):
        win = tk.Toplevel(self)
        win.title("Update Available")
        win.configure(background=PANEL)
        win.transient(self)
        win.grab_set()
        win.geometry("520x380")
        win.resizable(False, False)

        box = ttk.Frame(win, padding=24)
        box.pack(fill=tk.BOTH, expand=True)

        ttk.Label(box, text=f"Update Available: v{version}", style="H1.TLabel", foreground=GREEN).pack(anchor="w")
        ttk.Label(box, text="A new version is ready to download.", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))

        if notes:
            txt = tk.Text(box, wrap="word", height=8, background=FIELD, foreground=TEXT,
                          borderwidth=0, font=_font(9))
            txt.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
            txt.insert("1.0", notes)
            txt.configure(state=tk.DISABLED)

        def download_and_install():
            btn.configure(state=tk.DISABLED, text="Downloading...")
            updater.download_and_run_installer(url, lambda ok: win.after(0, win.destroy))
        btn = ttk.Button(box, text="Download & Install", style="Accent.TButton",
                         command=download_and_install)
        btn.pack(side=tk.LEFT, pady=(12, 0))
        ttk.Button(box, text="Later", style="Small.TButton",
                   command=win.destroy).pack(side=tk.RIGHT, pady=(12, 0))

    def _show_no_update(self):
        messagebox.showinfo("No Updates", "You are already on the latest version.", parent=self)

    def _run_all(self):
        order = self.config.get("run_all_order", [1, 2, 3, 5, 4])
        self._run_scripts(order, "RUN ALL SCRIPTS")

    def _run_custom(self):
        if self.running:
            return
        dlg = CustomRunDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self._run_scripts(dlg.result, "CUSTOM RUN ORDER")

    def _set_running(self, flag, label=""):
        self.running = flag
        state = tk.DISABLED if flag else tk.NORMAL
        for b in self.run_buttons:
            b.configure(state=state)
        if hasattr(self, "opt_selected_btn"):
            if flag:
                self.opt_selected_btn.configure(state=tk.DISABLED)
            else:
                self._update_selection_label()
        self.status_var.set(f"Running: {label}" if flag else "Ready")
        if flag:
            self.progress.configure(maximum=100, value=0)
            self.prog_label_var.set("")

    def _continue(self):
        self.continue_btn.pack_forget()
        self.status_var.set("Running…")
        self._continue_event.set()

    def _open_deps(self):
        if self.running:
            messagebox.showinfo("Busy", "Wait for the current operation to finish.")
            return
        DependenciesDialog(self)

    def _update_dep_label(self):
        if not hasattr(self, "dep_label"):
            return
        n = len(tools_mod.detect_all_tools())
        total = len(fetchdeps.DISPLAY_NAMES)
        self.dep_label.configure(
            text=f"{n}/{total} tools detected" if n else "No tools detected"
        )

    def _run_scripts(self, script_ids, title, targets=None):
        if self.running:
            messagebox.showinfo("Busy", "An operation is already running.")
            return

        folder = self.folder_var.get().strip()
        if folder:
            self.config["music_folder"] = folder

        self._set_running(True, title)
        self.log("")
        self.log("─" * 74, tag="muted")
        self.log(f"{title}", tag="bold")
        self.log(f"Scripts: {' → '.join(SCRIPT_NAMES[s] for s in script_ids)}", tag="muted")
        if targets:
            self.log(f"Targets: {len(targets)} selected item(s)", tag="muted")
            self._regrade_after = list(targets)
        else:
            self._regrade_after = "all"
        self.log("─" * 74, tag="muted")

        t = threading.Thread(
            target=self._worker,
            args=(list(script_ids), title, targets,
                  self.force_flac_var.get(),
                  self.force_images_var.get(),
                  self.force_audit_var.get()),
            daemon=True
        )
        t.start()

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _worker(self, script_ids, title, targets=None, force_flac=False,
                force_images=False, force_audit=False):
        started = time.monotonic()
        prev_tqdm, prev_hook = stats_mod.tqdm, stats_mod.progress_hook
        stats_mod.tqdm = None
        stats_mod.progress_hook = lambda done, total, desc: self.log_q.put(
            ("prog", (done, total, desc))
        )
        set_file_lines(True)

        # Runners never mutate the config; a copy lets us scope a run to
        # user-selected directories/tracks without affecting the app.
        run_cfg = self.config
        if targets or force_flac or force_images or force_audit:
            run_cfg = self.config.copy()
            if targets:
                run_cfg["targets"] = list(targets)
            if force_flac:
                run_cfg["force_reencode_flac"] = True
            if force_images:
                run_cfg["force_reencode_images"] = True
            if force_audit:
                run_cfg["force_audit"] = True

        per_script = []
        total_bytes_added = total_bytes_removed = total_errors = 0
        all_errors = []

        try:
            for i, script_id in enumerate(script_ids):
                name, runner = RUNNERS[script_id]

                # Honor Auto-Advance: pause between scripts when disabled.
                if i > 0 and not run_cfg.get("auto_advance", True):
                    self._continue_event.clear()
                    self.log_q.put(("pause", name))
                    self.log(f"⏸ Paused before {name} (Auto-Advance is off)",
                             tag="yellow")
                    self._continue_event.wait()

                self.log("")
                self.log(f"▶ Starting {name}", tag="blue")

                try:
                    s = runner(run_cfg)
                except Exception as e:
                    self.log(f"FATAL in {name}: {e}")
                    traceback.print_exc(file=self.stdout_stream)
                    s = new_stats_stub()
                    s["error_count"] = 1
                    s["errors"] = [(name, str(e))]

                per_script.append((name, s))

                if not s.get("is_grader"):
                    total_bytes_added += s.get("total_bytes_added", 0)
                    total_bytes_removed += s.get("total_bytes_removed", 0)
                    total_errors += s.get("error_count", 0)
                    all_errors.extend(s.get("errors", []))

                if s.get("is_grader"):
                    print_grade_results(s, title=f"RESULTS — {name}")
                else:
                    print_results(s, title=f"RESULTS — {name}")

            if len(script_ids) > 1:
                print_combined_results(
                    per_script, title="COMBINED RESULTS — ALL SCRIPTS"
                )

                if all_errors:
                    self.log("Errors:", tag="red")
                    for path, err in all_errors[:50]:
                        self.log(f"  - {path}", tag="red")
                        self.log(f"      {err}", tag="red")
                    if len(all_errors) > 50:
                        self.log(f"  … and {len(all_errors) - 50} more.", tag="red")

            elapsed = time.monotonic() - started
            self.log("")
            self.log(f"✔ {title} completed in {elapsed:.1f}s", tag="green")

        except Exception:
            traceback.print_exc(file=self.stdout_stream)

        finally:
            stats_mod.tqdm, stats_mod.progress_hook = prev_tqdm, prev_hook
            set_file_lines(False)
            # Queue-based completion: never touch Tk from the worker thread.
            self.log_q.put(("done", time.monotonic() - started))

    # ------------------------------------------------------------------
    def on_destroy(self):
        if self.running:
            if not messagebox.askyesno(
                "Operation in progress",
                "An operation is still running. Closing now may leave files "
                "half-processed. Close anyway?",
            ):
                return
        sys.stdout, sys.stderr = self._real_stdout, self._real_stderr
        self.destroy()


def new_stats_stub():
    return {
        "total_scanned": 0, "modified_count": 0, "unchanged_count": 0,
        "skipped_count": 0, "error_count": 0,
        "total_bytes_added": 0, "total_bytes_removed": 0, "errors": [],
    }


def main():
    app = App()
    if app.winfo_exists():
        app.protocol("WM_DELETE_WINDOW", app.on_destroy)
        app.mainloop()


if __name__ == "__main__":
    main()
