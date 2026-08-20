"""GUI constants, theme and reusable widgets for the desktop app."""
import os
import re
import shutil
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk


SCRIPT_NAMES = {
    1: "Format Lyrics",
    2: "Format CUEs",
    3: "Optimize FLACs",
    4: "Grade Library",
    5: "Process Images",
    6: "Audit Library",
    7: "DR & ReplayGain",
    8: "Auto Tagging",
}

# Sidebar button icons (script id -> glyph).
SIDEBAR_ICONS = {
    1: "\u270e",   # lyrics
    2: "\u266b",   # cue
    3: "\u2699",   # flac
    4: "\u2605",   # grade
    5: "\u25a6",   # images
    6: "\u2713",   # audit
    7: "\u2249",   # DR
    8: "\u2726",   # auto tag
}


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
    ("jpeg_progressive", "JPEG Progressive Output", "bool", None),
    ("png_optimization_level", "PNG Optimization Level (0-6)", "int", (0, 6)),
    ("force_reencode_images", "Force Re-encode Images", "bool", None),
    ("optimize_lrc", "Optimize LRC Files", "bool", None),
    ("optimize_embedded_lyrics", "Optimize Embedded Lyrics", "bool", None),
    ("lyrics_format", "Lyrics Format", "choice", ("EMBEDDED", "LRC", "BOTH")),
    ("lrc_timestamp_precision", "LRC Timestamp Decimals", "choice", ("2", "3")),
    ("lrc_strip_metadata", "Remove LRC Metadata Lines", "bool", None),
    ("lrc_collapse_blank_lines", "Collapse Blank Lyric Lines", "bool", None),
    ("append_final_newline", "Append Final Newline", "bool", None),
    ("keep_empty_cue_lines", "Keep Empty CUE Lines", "bool", None),
    ("keep_other_cue_lines", "Keep Other CUE Lines", "bool", None),
    ("cue_file_type", "CUE FILE Type", "choice", ("WAVE", "MP3")),
    ("normalize_media_source", "Normalize MEDIA/SOURCE", "bool", None),
    ("digital_media_source_value", "Digital SOURCE Value", "str", None),
    ("fix_instrumental_from_lyrics", "Fix INSTRUMENTAL from Lyrics", "bool", None),
    ("write_audit_tag", "Write AUDIT Tags", "bool", None),
    ("write_log_grade", "Write LOG_GRADE Tags", "bool", None),
    ("write_replaygain_tags", "Write ReplayGain Tags", "bool", None),
    ("write_dynamic_range_tags", "Write Dynamic Range Tags", "bool", None),
    ("grade_verbose", "Grade Verbose Output", "bool", None),
    ("grade_include_music", "Grading: Allow Music Files", "bool", None),
    ("grade_include_cover", "Grading: Allow Cover Art", "bool", None),
    ("grade_include_cue", "Grading: Allow .cue Files", "bool", None),
    ("grade_include_log", "Grading: Allow .log Files", "bool", None),
    ("grade_include_lrc", "Grading: Allow .lrc Files", "bool", None),
    ("grade_include_other", "Grading: Allow Other File Types", "bool", None),
    ("audit_thorough", "Thorough Audit (slower)", "bool", None),
    ("force_audit", "Force Audit (ignore AUDIT tags)", "bool", None),
    ("audit_cutoff_allow", "Audit Cutoff Allowance (Hz, 0=default)", "int", (0, 24000)),
    ("audit_verify_cd_checksums", "Verify CD Rips vs .log Checksums", "bool", None),
    ("audit_clipping", "Audit Clipping Detection", "bool", None),
    ("audit_mqa", "Audit MQA Detection", "bool", None),
    ("audit_ai", "Audit AI Detection", "bool", None),
    ("audit_fake_stereo", "Audit Fake Stereo Detection", "bool", None),
    ("audit_silence", "Audit Silence Detection", "bool", None),
    ("audit_dynamic_range", "Audit Dynamic Range", "bool", None),
    ("audit_true_peak", "Audit True Peak", "bool", None),
    ("audit_lufs", "Audit LUFS", "bool", None),
    ("audit_bpm", "Audit BPM", "bool", None),
    ("dr_replaygain_enabled", "DR/ReplayGain Enabled", "bool", None),
    ("replaygain_skip_existing", "ReplayGain Skip Existing", "bool", None),
    ("force_dr_replaygain", "Force DR/ReplayGain", "bool", None),
    ("auto_advisory", "Auto Album Advisory", "bool", None),
    ("auto_instrumental", "Auto Instrumental Tag", "bool", None),
    ("force_auto_tag", "Force Auto Tagging", "bool", None),
    ("auto_advance", "Auto-Advance Between Scripts", "bool", None),
    ("worker_limit", "Worker Limit (0=Auto)", "int", (0, 64)),
    ("check_updates_on_start", "Check for Updates on Start", "bool", None),
    ("auto_update_on_start", "Auto-Install Updates on Start", "bool", None),
    ("update_check_interval_days", "Update Check Interval (days)", "int", (1, 30)),
    ("update_close_other_instances", "Close Other Instances for Updates", "bool", None),
    ("confirm_before_update", "Confirm Before Installing Updates", "bool", None),
    ("show_sidecar_files", "Show Other Files in Library (.cue .log .lrc .jxl .jpg .png)", "bool", None),
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




class WrapFrame(ttk.Frame):
    """A frame that lays its children left-to-right and wraps them onto new
    rows when they no longer fit the available width. This keeps toolbar
    buttons from overlapping when the window gets too narrow."""

    def __init__(self, master, gap=8, **kw):
        super().__init__(master, **kw)
        self._gap = gap
        self._items = []
        self.bind("<Configure>", self._relayout)

    def add(self, widget):
        self._items.append(widget)
        self._relayout()

    def _relayout(self, event=None):
        if not self._items:
            return
        for w in self._items:
            w.grid_forget()
        width = self.winfo_width() or 1
        row = 0
        col = 0
        x = 0
        for w in self._items:
            rw = w.winfo_reqwidth() + self._gap
            if col > 0 and x + rw > width:
                row += 1
                col = 0
                x = 0
            w.grid(row=row, column=col, sticky="w",
                   padx=(0, self._gap), pady=(0, 4))
            col += 1
            x += rw




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
    "jpeg_progressive":
        "Ask jpegtran to write progressive JPEG output. This is still "
        "lossless and can improve streaming size without changing pixels.",
    "png_optimization_level":
        "oxipng optimization effort 0-6. Higher levels use more CPU for "
        "smaller lossless PNG files.",
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
    "lrc_timestamp_precision":
        "Write lyric timestamps with two or three decimal places.",
    "lrc_strip_metadata":
        "Remove [ar:], [ti:], [al:] and other LRC metadata lines.",
    "lrc_collapse_blank_lines":
        "Collapse repeated blank lyric lines while retaining intentional "
        "single spacing.",
    "append_final_newline":
        "Add one final LF byte to formatted .cue, .lrc, and embedded lyric "
        "text. Off by default for the existing byte-minimal format.",
    "keep_empty_cue_lines":
        "Preserve blank lines when formatting .cue files.",
    "keep_other_cue_lines":
        "Preserve non-standard CUE lines (PREGAP, REM, etc.) instead of "
        "dropping them.",
    "cue_file_type":
        "FILE line type written by the CUE formatter: WAVE or MP3.",
    "normalize_media_source":
        "Enforce the MEDIA/SOURCE rule: albums with MEDIA 'Digital Media' "
        "must have SOURCE populated; all other albums must not have SOURCE.",
    "digital_media_source_value":
        "Fallback SOURCE value written on Digital Media albums whose tracks "
        "are missing SOURCE. Existing values are never overwritten.",
    "fix_instrumental_from_lyrics":
        "When lyrics are present, change INSTRUMENTAL=1 to INSTRUMENTAL=0 "
        "during lyric formatting.",
    "write_audit_tag":
        "Persist AudioAuditor's REAL/FAKE verdict in the AUDIT tag.",
    "write_log_grade":
        "Persist CD rip-log scores in LOG_GRADE tags.",
    "write_replaygain_tags":
        "Allow rsgain to write the four REPLAYGAIN_* tags.",
    "write_dynamic_range_tags":
        "Allow simple-dr-meter results to write DYNAMIC RANGE tags.",
    "grade_verbose":
        "Include the per-track tag dump in grading reports.",
    "grade_include_music":
        "Allow audio files when grading an album folder.",
    "grade_include_cover":
        "Allow cover images (.jpg/.jpeg/.png/.jxl) when grading.",
    "grade_include_cue":
        "Allow .cue sheets when grading.",
    "grade_include_log":
        "Allow .log rip logs when grading.",
    "grade_include_lrc":
        "Allow .lrc lyric sidecars when grading.",
    "grade_include_other":
        "Allow every other file type when grading. When off, any file that "
        "is not music/cover/cue/log/lrc fails the album (extra files).",
    "audit_thorough":
        "Audit Library: enable AudioAuditor's full-track detectors "
        "(silence, dynamic range, true peak, LUFS, BPM). Much slower than "
        "the default fast scan but produces deeper metrics.",
    "force_audit":
        "Audit Library: re-audit files that already carry an AUDIT tag "
        "and re-score rip logs even when LOG_GRADE is present. The "
        "Force ▾ menu in the Library tab sets this per-run.",
    "audit_verify_cd_checksums":
        "For MEDIA=CD rips, verify each track against the CRC-32 checksum "
        "in its .log and write AUDIT=REAL/FAKE from that. The checksum "
        "result takes precedence over AudioAuditor for those files.",
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
    "dr_replaygain_enabled":
        "DR & ReplayGain (script 7): calculate Dynamic Range (via "
        "simple-dr-meter) and ReplayGain (via rsgain) tags. Requires the "
        "dependencies to be downloaded.",
    "replaygain_skip_existing":
        "ReplayGain: skip files that already carry REPLAYGAIN_TRACK_GAIN "
        "(rsgain -S). If album tags are on, a single missing file re-scans "
        "the whole album.",
    "force_dr_replaygain":
        "DR & ReplayGain: re-calculate everything even when tags are "
        "already present. The Force ▾ menu in the Library tab sets this "
        "per-run.",
    "auto_advisory":
        "Auto Tagging: derive ALBUMITUNESADVISORY from each track's manual "
        "ITUNESADVISORY (0 unrated / 1 explicit / 2 edited-safe). Any "
        "explicit track -> 1, else any safe -> 2, else 0. Counts all "
        "tracks including every disc.",
    "auto_instrumental":
        "Auto Tagging: set INSTRUMENTAL from lyrics presence — 0 when the "
        "track has lyrics (embedded LYRICS or .lrc), otherwise 1.",
    "force_auto_tag":
        "Auto Tagging: rewrite tags even when already correct. The Force ▾ "
        "menu in the Library tab sets this per-run.",
    "auto_advance":
        "Sequence runs (Run All / custom): when off, the app pauses for "
        "confirmation between scripts — the GUI shows a Continue button.",
    "worker_limit":
        "Maximum worker threads per processing pass. 0 automatically sizes "
        "pools from CPU count and file count.",
    "check_updates_on_start":
        "Check GitHub for a new release when the app starts (once per "
        "interval). Works for both the portable and the installed version. "
        "You can always check manually via ⓘ About → Check for Updates.",
    "auto_update_on_start":
        "Automatically download and install a newer release found at "
        "startup (an idle app only). Honors 'Confirm Before Installing "
        "Updates': when that is on you still get the confirmation dialog.",
    "update_check_interval_days":
        "How often automatic GitHub release checks are attempted.",
    "update_close_other_instances":
        "Ask other Music Library Optimizer windows to close before an update "
        "installer starts. Busy instances prevent the update.",
    "confirm_before_update":
        "Ask for confirmation before downloading and installing an update.",
    "show_sidecar_files":
        "Show non-audio files (.cue/.log/.lrc/.jxl/.jpg/.png) in the library "
        "viewer, each with its own grade row.",
    "run_all_order":
        "Execution order used by the Run All button.",
}

