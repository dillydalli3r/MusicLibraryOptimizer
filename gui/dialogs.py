"""Dialogs: Settings, Custom Run, Grade Details, Tag Editor."""
import os
import threading

from PySide6.QtCore import Qt, Signal, QObject, QPoint
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget, QGridLayout, QFrame, QSizePolicy, QToolButton,
    QTextEdit,
)

from mlo import save_config, DEFAULT_CONFIG
from mlo.config import normalize_config
from mlo.paths import DEFAULT_DIGITAL_SOURCE, SCRIPT_DIR
from mlo import tools as tools_mod
from .console import pick_monospace
from .theme import THEME, ACCENT_PRESETS, apply_app_theme
from .widgets import ToggleSwitch, section_label

# Script numbers -> names (scripts 7/8 are selectable but never auto-added
# to a run order).
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
# Scripts that fill any unoccupied Run All slot by default.
BASE_RUN_ALL = [1, 2, 3, 5, 4]

# Tag keys offered by the "Add tag" menu of the full tag editor.
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

CONFIG_FIELDS = {
    # key -> (label, kind, extra)
    # FLAC
    "flac_level": ("FLAC Level (0-8)", "int", (0, 8)),
    "add_seektables": ("Add SeekTables", "bool", None),
    "force_reencode_flac": ("Force Re-encode FLACs", "bool", None),
    # Images
    "jpegxl_effort": ("JPEG XL Effort (1-10)", "int", (1, 10)),
    "reencode_images": ("Re-encode Images", "bool", None),
    "reencode_to_jxl": ("Re-encode to JXL", "bool", None),
    "convert_jxl_back": ("Convert JXL Back to JPEG/PNG", "bool", None),
    "rename_to_cover": ("Rename Images to cover.<ext>", "bool", None),
    "remove_alpha": ("Remove Alpha from PNGs", "bool", None),
    "jpeg_progressive": ("JPEG Progressive Output", "bool", None),
    "png_optimization_level": ("PNG Optimization Level (0-6)", "int", (0, 6)),
    "force_reencode_images": ("Force Re-encode Images", "bool", None),
    # Lyrics / LRC
    "optimize_lrc": ("Optimize LRC Files", "bool", None),
    "optimize_embedded_lyrics": ("Optimize Embedded Lyrics", "bool", None),
    "lyrics_format": ("Lyrics Format", "choice", ("EMBEDDED", "LRC", "BOTH")),
    "lrc_timestamp_precision": ("LRC Timestamp Decimals", "choice",
                                ("2", "3")),
    "lrc_strip_metadata": ("Remove LRC Metadata Lines", "bool", None),
    "lrc_collapse_blank_lines": ("Collapse Blank Lyric Lines", "bool", None),
    "append_final_newline": ("Append Final Newline", "bool", None),
    # CUE sheets
    "keep_empty_cue_lines": ("Keep Empty CUE Lines", "bool", None),
    "keep_other_cue_lines": ("Keep Other CUE Lines", "bool", None),
    "cue_file_type": ("CUE FILE Type", "choice", ("WAVE", "MP3")),
    # MEDIA / SOURCE + tag writes
    "normalize_media_source": ("Normalize MEDIA/SOURCE", "bool", None),
    "digital_media_source_value": ("Digital SOURCE Value", "str", None),
    "fix_instrumental_from_lyrics": ("Fix INSTRUMENTAL from Lyrics",
                                     "bool", None),
    "write_audit_tag": ("Write AUDIT Tags", "bool", None),
    "write_log_grade": ("Write LOG_GRADE Tags", "bool", None),
    "write_replaygain_tags": ("Write ReplayGain Tags", "bool", None),
    "write_dynamic_range_tags": ("Write Dynamic Range Tags", "bool", None),
    # Grading
    "grade_verbose": ("Grade Verbose Output", "bool", None),
    "grade_include_music": ("Grading: Allow Music Files", "bool", None),
    "grade_include_cover": ("Grading: Allow Cover Art", "bool", None),
    "grade_include_cue": ("Grading: Allow .cue Files", "bool", None),
    "grade_include_log": ("Grading: Allow .log Files", "bool", None),
    "grade_include_lrc": ("Grading: Allow .lrc Files", "bool", None),
    "grade_include_other": ("Grading: Allow Other File Types", "bool", None),
    # Audio audit
    "audit_thorough": ("Thorough Audit (slower)", "bool", None),
    "force_audit": ("Force Audit (ignore AUDIT tags)", "bool", None),
    "audit_cutoff_allow": ("Audit Cutoff Allowance (Hz, 0=default)", "int",
                           (0, 24000)),
    "audit_verify_cd_checksums": ("Verify CD Rips vs .log Checksums",
                                  "bool", None),
    "audit_clipping": ("Audit Clipping Detection", "bool", None),
    "audit_mqa": ("Audit MQA Detection", "bool", None),
    "audit_ai": ("Audit AI Detection", "bool", None),
    "audit_fake_stereo": ("Audit Fake Stereo Detection", "bool", None),
    "audit_silence": ("Audit Silence Detection", "bool", None),
    "audit_dynamic_range": ("Audit Dynamic Range", "bool", None),
    "audit_true_peak": ("Audit True Peak", "bool", None),
    "audit_lufs": ("Audit LUFS", "bool", None),
    "audit_bpm": ("Audit BPM", "bool", None),
    # DR & ReplayGain (script 7)
    "dr_replaygain_enabled": ("DR/ReplayGain Enabled", "bool", None),
    "replaygain_skip_existing": ("ReplayGain Skip Existing", "bool", None),
    "force_dr_replaygain": ("Force DR/ReplayGain", "bool", None),
    # Auto Tagging (script 8)
    "auto_advisory": ("Auto Album Advisory", "bool", None),
    "auto_instrumental": ("Auto Instrumental Tag", "bool", None),
    "force_auto_tag": ("Force Auto Tagging", "bool", None),
    # Interface
    "auto_advance": ("Auto-Advance Between Scripts", "bool", None),
    "worker_limit": ("Worker Limit (0=Auto)", "int", (0, 64)),
    # Updater
    "check_updates_on_start": ("Check for Updates on Start", "bool", None),
    "auto_update_on_start": ("Auto-Install Updates on Start", "bool", None),
    "update_check_interval_days": ("Update Check Interval (days)", "int",
                                   (1, 30)),
    "update_close_other_instances": ("Close Other Instances for Updates",
                                     "bool", None),
    "confirm_before_update": ("Confirm Before Installing Updates", "bool",
                              None),
}

# Tooltips shown on each settings label (ported from the Tk GUI).
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
        "You can always check manually via Manage → Check for Updates….",
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

# Bridge so tag-editor save threads (plain threads) can talk to the GUI
# thread safely.
class _SaverBridge(QObject):
    saved = Signal(str, int, list)     # album_dir, modified count, errors
    status = Signal(str)


SAVER_BRIDGE = _SaverBridge()


# ==========================================================================
# Settings
# ==========================================================================
class SettingsDialog(QDialog):
    def __init__(self, parent, config, on_saved):
        super().__init__(parent)
        self.config = config
        self.on_saved = on_saved
        self.vars = {}

        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumSize(780, 660)
        THEME.register_window(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # --- Library folder --------------------------------------------
        lay.addWidget(section_label("Library Folder"))
        folder_row = QHBoxLayout()
        self.vars["music_folder"] = QLineEdit(
            config.get("music_folder", ""))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.vars["music_folder"], 1)
        folder_row.addWidget(browse)
        lay.addLayout(folder_row)
        lay.addSpacing(8)

        # --- Appearance --------------------------------------------------
        lay.addWidget(section_label("Appearance"))
        card = self._card()
        g = QGridLayout(card)
        g.setContentsMargins(12, 10, 12, 10)
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(10)

        g.addWidget(QLabel("Theme"), 0, 0)
        theme_combo = QComboBox()
        theme_combo.addItem("Dark", "dark")
        theme_combo.addItem("Light", "light")
        theme_combo.addItem("Follow system", "system")
        mode = config.get("theme", "dark")
        theme_combo.setCurrentIndex(
            ["dark", "light", "system"].index(mode)
            if mode in ("dark", "light", "system") else 0)
        theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        g.addWidget(theme_combo, 0, 1, Qt.AlignmentFlag.AlignLeft)
        self.theme_combo = theme_combo

        g.addWidget(QLabel("Accent color"), 1, 0)
        accent_row = QWidget()
        al = QHBoxLayout(accent_row)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        self._swatches = []
        current = (config.get("accent_color") or "").lower()
        for name, hexval in ACCENT_PRESETS:
            sw = QPushButton()
            sw.setFixedSize(26, 26)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setToolTip(name)
            sw.setStyleSheet(
                f"QPushButton {{ background-color: {hexval}; border: none;"
                f" border-radius: 13px; }}"
                f"QPushButton:hover {{ border: 2px solid "
                f"{THEME.c('text')}; }}")
            sw.clicked.connect(
                lambda _c=False, h=hexval: self._pick_accent(h))
            if current == hexval.lower():
                sw.setStyleSheet(sw.styleSheet() +
                                 f"border: 2px solid {THEME.c('text')};")
            al.addWidget(sw)
            self._swatches.append(sw)
        custom = QPushButton("Custom…")
        custom.setProperty("variant", "small")
        custom.clicked.connect(self._pick_custom_accent)
        al.addWidget(custom)
        reset = QPushButton("Default")
        reset.setProperty("variant", "small")
        reset.clicked.connect(lambda: self._pick_accent(""))
        al.addWidget(reset)
        al.addStretch(1)
        g.addWidget(accent_row, 1, 1)
        lay.addWidget(card)

        note = QLabel("Theme and accent apply immediately - including the "
                      "window title bar - and are saved right away.")
        note.setProperty("role", "muted")
        lay.addWidget(note)
        lay.addSpacing(4)

        # --- Option groups (two fields per row) ---------------------------
        groups = [
            ("FLAC", [
                "flac_level", "add_seektables", "force_reencode_flac"]),
            ("Images", [
                "jpegxl_effort", "reencode_images", "reencode_to_jxl",
                "convert_jxl_back", "rename_to_cover", "remove_alpha",
                "jpeg_progressive", "png_optimization_level",
                "force_reencode_images"]),
            ("Lyrics", [
                "optimize_lrc", "optimize_embedded_lyrics", "lyrics_format",
                "lrc_timestamp_precision", "lrc_strip_metadata",
                "lrc_collapse_blank_lines", "append_final_newline"]),
            ("CUE Sheets", [
                "keep_empty_cue_lines", "keep_other_cue_lines",
                "cue_file_type"]),
            ("Tags", [
                "normalize_media_source", "digital_media_source_value",
                "fix_instrumental_from_lyrics", "write_audit_tag",
                "write_log_grade", "write_replaygain_tags",
                "write_dynamic_range_tags"]),
            ("Grading", [
                "grade_verbose", "grade_include_music", "grade_include_cover",
                "grade_include_cue", "grade_include_log", "grade_include_lrc",
                "grade_include_other"]),
            ("Audio Audit", [
                "audit_thorough", "force_audit", "audit_cutoff_allow",
                "audit_verify_cd_checksums", "audit_clipping", "audit_mqa",
                "audit_ai", "audit_fake_stereo", "audit_silence",
                "audit_dynamic_range", "audit_true_peak", "audit_lufs",
                "audit_bpm"]),
            ("DR & ReplayGain", [
                "dr_replaygain_enabled", "replaygain_skip_existing",
                "force_dr_replaygain"]),
            ("Auto Tagging", [
                "auto_advisory", "auto_instrumental", "force_auto_tag"]),
            ("Interface", [
                "auto_advance", "worker_limit"]),
            ("Updates", [
                "check_updates_on_start", "auto_update_on_start",
                "update_check_interval_days", "update_close_other_instances",
                "confirm_before_update"]),
        ]
        for title, keys in groups:
            lay.addWidget(section_label(title))
            card = self._card()
            g = QGridLayout(card)
            g.setContentsMargins(12, 4, 12, 4)
            g.setHorizontalSpacing(18)
            g.setVerticalSpacing(8)
            for i, key in enumerate(keys):
                row, pair = divmod(i, 2)
                label, kind, extra = CONFIG_FIELDS[key]
                lbl = QLabel(label)
                tip = FIELD_DESCRIPTIONS.get(key)
                if tip:
                    lbl.setToolTip(tip)
                    lbl.setWordWrap(False)
                g.addWidget(lbl, row, pair * 2)
                default = DEFAULT_CONFIG.get(key)
                align_right = Qt.AlignmentFlag.AlignRight
                if kind == "bool":
                    var = ToggleSwitch(bool(config.get(key, default)))
                    g.addWidget(var, row, pair * 2 + 1, align_right)
                    self.vars[key] = ("bool", var)
                elif kind == "int":
                    var = QSpinBox()
                    var.setRange(extra[0], extra[1])
                    try:
                        val = int(config.get(key, default))
                    except (TypeError, ValueError):
                        val = extra[0]
                    var.setValue(val)
                    g.addWidget(var, row, pair * 2 + 1, align_right)
                    self.vars[key] = ("int", var)
                elif kind == "choice":
                    var = QComboBox()
                    for v in extra:
                        var.addItem(v)
                    cur = str(config.get(key, extra[0])).upper()
                    var.setCurrentIndex(
                        list(extra).index(cur) if cur in extra else 0)
                    g.addWidget(var, row, pair * 2 + 1, align_right)
                    self.vars[key] = ("choice", var)
                else:
                    var = QLineEdit(str(config.get(key, "")))
                    g.addWidget(var, row, pair * 2 + 1)
                    self.vars[key] = ("str", var)
                g.setColumnStretch(pair * 2 + 1, 1)
            lay.addWidget(card)
            lay.addSpacing(4)

        # --- Run All order ---------------------------------------------------
        lay.addWidget(section_label("Run All Order"))
        card = self._card()
        g = QGridLayout(card)
        g.setContentsMargins(12, 10, 12, 10)
        g.setHorizontalSpacing(10)
        current = [s for s in
                   (config.get("run_all_order") or BASE_RUN_ALL)
                   if isinstance(s, int) and s in SCRIPT_NAMES]
        # Only the base scripts (1-6) auto-fill empty slots. 7/8 run in
        # Run All only when explicitly picked in a slot below.
        for sid in (1, 2, 3, 4, 5, 6):
            if sid not in current:
                current.append(sid)
        self.order_combos = []
        for i, sid in enumerate(current[:len(SCRIPT_NAMES)]):
            row, col = divmod(i, 4)
            g.addWidget(QLabel(f"{i + 1}."), row, col * 2)
            combo = QComboBox()
            for n in sorted(SCRIPT_NAMES):
                combo.addItem(SCRIPT_NAMES[n])
            combo.setCurrentText(SCRIPT_NAMES[sid])
            g.addWidget(combo, row, col * 2 + 1)
            self.order_combos.append(combo)
        lay.addWidget(card)
        lay.addSpacing(4)

        # --- Encoder tags -----------------------------------------------------
        lay.addWidget(section_label("Encoder Tags"))
        card = self._card()
        g = QGridLayout(card)
        g.setContentsMargins(12, 10, 12, 10)
        g.setHorizontalSpacing(14)
        heads = ("", "Program", "Quality", "Version")
        for c, h in enumerate(heads):
            lbl = QLabel(h)
            lbl.setProperty("role", "section")
            g.addWidget(lbl, 0, c + 1, Qt.AlignmentFlag.AlignCenter
                        if c else Qt.AlignmentFlag.AlignLeft)
        self.encoder_vars = {}
        tag_types = [
            ("flac", "FLAC (.flac)"), ("jpeg", "JPEG (.jpg/.jpeg)"),
            ("png", "PNG (.png)"), ("jxl", "JPEG XL (.jxl)"),
        ]
        for r, (ftype, label) in enumerate(tag_types, start=1):
            g.addWidget(QLabel(label), r, 0)
            self.encoder_vars[ftype] = {}
            for c, key in enumerate(("ENCODER_PROGRAM", "ENCODER_QUALITY",
                                     "ENCODER_VERSION"), start=1):
                var = ToggleSwitch(bool(
                    (config.get("encoder_tags") or {})
                    .get(ftype, {}).get(key, True)))
                g.addWidget(var, r, c, Qt.AlignmentFlag.AlignCenter)
                self.encoder_vars[ftype][key] = var
        lay.addWidget(card)
        lay.addSpacing(4)

        # --- Detected tools ----------------------------------------------------
        lay.addWidget(section_label("Detected Tools"))
        card = self._card()
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        tools = tools_mod.detect_all_tools()
        found = {
            "flac": tools.get("flac", {}).get("version"),
            "libjxl": tools.get("libjxl", {}).get("version"),
            "libjpeg-turbo": tools.get("libjpeg_turbo", {}).get("version"),
            "oxipng": tools.get("oxipng", {}).get("version"),
            "auditor": tools.get("audioauditor", {}).get("version"),
        }
        line = "   ".join(
            f"{name} {'v' + ver if ver else '—'}" for name, ver in found.items())
        verlbl = QLabel(line)
        mono = pick_monospace()
        f = QFont(mono)
        f.setPointSize(9)
        verlbl.setFont(f)
        v.addWidget(verlbl)
        if not any(found.values()):
            warn = QLabel(
                "No tools found. Use Dependencies to download flac / libjxl /\n"
                "libjpeg-turbo / oxipng / AudioAuditor.")
            warn.setProperty("role", "muted")
            v.addWidget(warn)
        lay.addWidget(card)
        lay.addSpacing(4)

        lay.addWidget(QLabel(
            "Digital SOURCE Value: written to SOURCE when MEDIA is "
            '"Digital Media" and SOURCE is missing.\nExisting values are '
            "preserved."))

        lay.addStretch(1)

        # --- Buttons -----------------------------------------------------------
        btns = QHBoxLayout()
        reset = QPushButton("Reset to Defaults")
        reset.clicked.connect(self._reset_defaults)
        btns.addWidget(reset)
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton("Save")
        save.setProperty("variant", "accent")
        save.clicked.connect(self._save)
        btns.addWidget(save)
        outer.addLayout(btns)

    # ------------------------------------------------------------------
    @staticmethod
    def _card():
        card = QFrame()
        card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)
        return card

    def _browse(self):
        path = QFileDialog.getExistingDirectory(
            self, "Choose Library Folder",
            self.vars["music_folder"].text() or "")
        if path:
            self.vars["music_folder"].setText(path)

    def _on_theme_changed(self):
        mode = self.theme_combo.currentData()
        self.config["theme"] = mode
        save_config(self.config)
        apply_app_theme(self.config)

    def _pick_accent(self, hexval):
        self.config["accent_color"] = hexval
        save_config(self.config)
        apply_app_theme(self.config)

    def _pick_custom_accent(self):
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(
            parent=self, title="Custom accent color")
        if color.isValid():
            self._pick_accent(color.name())

    def _reset_defaults(self):
        ret = QMessageBox.question(
            self, "Reset settings",
            "Restore every setting to its default value?\n"
            "Nothing is written to disk until you press Save.")
        if ret != QMessageBox.StandardButton.Yes:
            return
        defaults = DEFAULT_CONFIG.copy()
        self.vars["music_folder"].setText(defaults.get("music_folder", ""))
        for key, entry in self.vars.items():
            if key == "music_folder":
                continue
            kind, widget = entry
            d = defaults.get(key)
            try:
                if kind == "bool":
                    widget.setChecked(bool(d))
                elif kind == "int":
                    widget.setValue(int(d))
                elif kind == "choice":
                    widget.setCurrentText(str(d).upper())
                else:
                    widget.setText(str(d))
            except (ValueError, TypeError):
                pass
        order = [s for s in (defaults.get("run_all_order")
                             or BASE_RUN_ALL)
                 if s in SCRIPT_NAMES]
        for combo, sid in zip(self.order_combos, order):
            combo.setCurrentText(SCRIPT_NAMES[sid])
        for ftype, fields in self.encoder_vars.items():
            for key, var in fields.items():
                var.setChecked(bool(
                    (defaults.get("encoder_tags") or {})
                    .get(ftype, {}).get(key, True)))

    def _save(self):
        self.config["music_folder"] = \
            self.vars["music_folder"].text().strip()
        for key, entry in self.vars.items():
            if key == "music_folder":
                continue
            kind, widget = entry
            try:
                if kind == "bool":
                    self.config[key] = widget.isChecked()
                elif kind == "int":
                    self.config[key] = widget.value()
                elif kind == "choice":
                    self.config[key] = widget.currentText().upper()
                else:
                    self.config[key] = widget.text().strip()
            except (ValueError, TypeError):
                QMessageBox.warning(self, "Invalid value",
                                    f"'{CONFIG_FIELDS[key][0]}' has an "
                                    f"invalid value.")
                return

        name_to_id = {v: k for k, v in SCRIPT_NAMES.items()}
        order = []
        for combo in self.order_combos:
            sid = name_to_id.get(combo.currentText())
            if sid and sid not in order:
                order.append(sid)
        self.config["run_all_order"] = order or list(BASE_RUN_ALL)

        encoder_tags = self.config.get("encoder_tags") or {}
        for ftype, fields in self.encoder_vars.items():
            encoder_tags[ftype] = {
                key: var.isChecked() for key, var in fields.items()}
        self.config["encoder_tags"] = encoder_tags

        if not str(self.config.get("digital_media_source_value", "")).strip():
            self.config["digital_media_source_value"] = DEFAULT_DIGITAL_SOURCE

        # Validate / coerce everything (ints, numeric choice strings like
        # the LRC timestamp decimals) the same way the load path does.
        try:
            self.config = normalize_config(self.config)
        except Exception:
            pass

        if not save_config(self.config):
            QMessageBox.critical(self, "Save failed",
                                 "Could not write config.json.")
            return
        self.accept()
        self.on_saved(self.config)


# ==========================================================================
# Custom run order
# ==========================================================================
class CustomRunDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.result_order = []
        self.setWindowTitle("Custom Run")
        self.setModal(True)
        THEME.register_window(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(8)

        lay.addWidget(section_label("Run Order"))
        hint = QLabel("Script numbers, comma-separated — e.g.  3,1,2,5")
        hint.setProperty("role", "muted")
        lay.addWidget(hint)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText("3,1,2,5")
        lay.addWidget(self.entry)
        self.entry.returnPressed.connect(self._ok)
        self.entry.setFocus()

        legend = QLabel(
            "1 Format Lyrics      2 Format CUEs      3 Optimize FLACs\n"
            "4 Grade Library      5 Process Images   6 Audit Library\n"
            "7 DR & ReplayGain    8 Auto Tagging")
        legend.setProperty("role", "muted")
        lay.addWidget(legend)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        run = QPushButton("Run")
        run.setProperty("variant", "accent")
        run.clicked.connect(self._ok)
        btns.addWidget(run)
        lay.addLayout(btns)

    def _ok(self):
        order = []
        valid = tuple(str(n) for n in SCRIPT_NAMES)
        for part in self.entry.text().replace(" ", "").split(","):
            if part in valid and int(part) not in order:
                order.append(int(part))
        if not order:
            QMessageBox.information(
                self, "Invalid order", "Enter at least one script number "
                f"(1-{len(SCRIPT_NAMES)}).")
            return
        self.result_order = order
        self.accept()


# ==========================================================================
# Grade details
# ==========================================================================
class GradeDetailsDialog(QDialog):
    def __init__(self, parent, album_dir, res, lyrics_format, track_file=None):
        super().__init__(parent)
        name = track_file or album_dir
        self.setWindowTitle("Grade Details — " + os.path.basename(name))
        self.setModal(True)
        self.resize(700, 540)
        THEME.register_window(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        f = QFont(pick_monospace())
        f.setPointSize(9)
        self.text.setFont(f)
        lay.addWidget(self.text, 1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

        from mlo.grader import format_grade_report
        from .theme import THEME as T
        p = T.palette()
        styles = {
            None: p["text"], "bold": p["bright"], "red": p["danger"],
            "green": p["success"], "muted": p["muted"],
        }
        import html as html_mod
        parts = []
        for text, style in format_grade_report(
                res, lyrics_format, track_file=track_file):
            esc = html_mod.escape(text)
            color = styles.get(style, p["text"])
            weight = "600" if style == "bold" else "400"
            parts.append(
                f"<div style='color:{color}; font-weight:{weight}; "
                f"white-space:pre'>{esc}</div>")
        self.text.setHtml("".join(parts).replace("\n", "<br>"))


# ==========================================================================
# Tag editor
# ==========================================================================
class TagEditorDialog(QDialog):
    def __init__(self, parent, album_dir, track_path=None):
        super().__init__(parent)
        self.album_dir = album_dir
        self.track_path = track_path

        if track_path:
            files = [track_path]
        else:
            from mlo.stats import is_audio_file
            files = sorted(
                os.path.join(album_dir, f)
                for f in os.listdir(album_dir) if is_audio_file(f))
        self.files = files

        title = ("Tag Editor — " + os.path.basename(track_path)
                 if track_path else
                 f"Tag Editor — {os.path.basename(album_dir)} "
                 f"({len(files)} files)")
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(620, 560)
        THEME.register_window(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_host = QWidget()
        self.rows_lay = QVBoxLayout(self.rows_host)
        self.rows_lay.setContentsMargins(0, 4, 0, 4)
        self.rows_lay.setSpacing(2)
        scroll.setWidget(self.rows_host)
        outer.addWidget(scroll, 1)

        self.row_vars = {}

        from mlo.audio import AudioFile
        first = AudioFile(files[0]) if files else None
        if first is None or first.audio is None:
            QMessageBox.critical(
                self, "Edit Tags",
                "Cannot read " + (os.path.basename(files[0]) if files
                                  else album_dir))
            self.reject()
            return

        existing = first.all_tags()
        seen = {}
        for key in list(existing) + [k for _l, k in COMMON_TAGS]:
            folded = key.lower()
            if folded not in seen:
                seen[folded] = key
        for key in sorted(seen.values(), key=str.lower):
            self.add_row(key, existing.get(key, ""))

        footer = QHBoxLayout()
        add_btn = QPushButton("Add tag…")
        add_btn.clicked.connect(lambda: self._add_tag_menu(add_btn))
        footer.addWidget(add_btn)
        note = QLabel("Empty value removes the tag. Applies to all files.")
        note.setProperty("role", "muted")
        footer.addWidget(note, 1)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setProperty("variant", "accent")
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        outer.addLayout(footer)

    def add_row(self, key, value=""):
        row = QFrame()
        row.setObjectName("Card")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 3, 10, 3)
        h.setSpacing(10)
        remove = QToolButton()
        remove.setText("×")
        remove.clicked.connect(lambda _c=False, k=key: self.remove_row(k))
        key_lbl = QLabel(key)
        key_lbl.setMinimumWidth(140)
        entry = QLineEdit(str(value))
        h.addWidget(remove)
        h.addWidget(key_lbl)
        h.addWidget(entry, 1)
        self.rows_lay.addWidget(row)
        self.row_vars[key] = (entry, row)

    def remove_row(self, key):
        var = self.row_vars.pop(key, None)
        if var:
            var[1].deleteLater()

    def _add_tag_menu(self, btn):
        menu = QMenu(self)
        for label, key in COMMON_TAGS:
            if key not in self.row_vars:
                menu.addAction(label, lambda k=key: self.add_row(k))
        menu.addSeparator()
        for label, key in RAW_TAGS:
            if key not in self.row_vars:
                menu.addAction(label, lambda k=key: self.add_row(k))
        menu.addSeparator()
        menu.addAction("Custom tag…", self._custom_tag)
        menu.exec(btn.mapToGlobal(QPoint(0, btn.height())))

    def _custom_tag(self):
        key, ok = QInputDialog.getText(self, "Add tag", "Tag key:")
        if ok and key.strip() and key.strip() not in self.row_vars:
            self.add_row(key.strip())

    def _save(self):
        changes = {key: var[0].text().strip()
                   for key, var in self.row_vars.items()}
        album_dir = self.album_dir
        files = self.files

        def work():
            from mlo.audio import AudioFile
            modified = 0
            errors = []
            for path in files:
                af = AudioFile(path)
                if af.audio is None:
                    errors.append(
                        f"{os.path.basename(path)}: {af.error}")
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
                    modified += 1
            SAVER_BRIDGE.status.emit(
                "Tags updated — re-grading album…"
                if modified else "No tag changes saved.")
            SAVER_BRIDGE.saved.emit(album_dir, modified, errors)

        self.accept()
        threading.Thread(target=work, daemon=True).start()
