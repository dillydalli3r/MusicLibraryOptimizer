"""Configuration persisted to config.json next to the application."""
import copy
import json
import os
import tempfile

from .paths import CONFIG_FILE, DEFAULT_DIGITAL_SOURCE
from .ui import c, Color

# Run All order — systematic pipeline: 1) textual metadata, 2) media, 3) analysis, 4) report.
# 1 Format Lyrics + 2 Format CUEs normalize sidecars first so autotag can derive
# INSTRUMENTAL correctly; 8 Auto Tagging then fixes INSTRUMENTAL/ADVISORY/GENRE;
# 3 Optimize FLACs + 5 Process Images handle media (FLAC preserves the fixed tags);
# 7 DR/ReplayGain + 6 Audit Library analyze the final audio; 4 Grade Library last
# reports 100/0. User can reorder via Settings → Run All Order.
DEFAULT_RUN_ALL_ORDER = [1, 2, 8, 3, 5, 7, 6, 4]

# Audio tag families that can be toggled per filetype.
# Each family groups related TAG_MAP keys that are written together.
AUDIO_TAG_FAMILIES = [
    "AUDIT",          # AUDIT (Audit Library)
    "LOG_GRADE",      # LOG_GRADE (disc rip log scores)
    "REPLAYGAIN",     # REPLAYGAIN_TRACK/ALBUM_GAIN/PEAK (4 tags via rsgain)
    "DYNAMIC_RANGE",  # DYNAMIC RANGE + ALBUM DYNAMIC RANGE (simple-dr-meter)
    "MEDIA_SOURCE",   # MEDIA + SOURCE (Digital Media normalization)
    "INSTRUMENTAL",   # INSTRUMENTAL (lyrics presence)
    "ADVISORY",       # ITUNESADVISORY + ALBUMITUNESADVISORY
    "LYRICS",         # embedded LYRICS tag (and .lrc sidecar)
]
AUDIO_TAG_TYPES = ["flac", "mp3", "mp4", "ogg", "opus", "aac"]

# Map individual tag names to their family for per-type checks.
_TAG_TO_FAMILY = {
    "AUDIT": "AUDIT",
    "LOG_GRADE": "LOG_GRADE",
    "REPLAYGAIN_TRACK_GAIN": "REPLAYGAIN",
    "REPLAYGAIN_TRACK_PEAK": "REPLAYGAIN",
    "REPLAYGAIN_ALBUM_GAIN": "REPLAYGAIN",
    "REPLAYGAIN_ALBUM_PEAK": "REPLAYGAIN",
    "DYNAMIC RANGE": "DYNAMIC_RANGE",
    "ALBUM DYNAMIC RANGE": "DYNAMIC_RANGE",
    "MEDIA": "MEDIA_SOURCE",
    "SOURCE": "MEDIA_SOURCE",
    "INSTRUMENTAL": "INSTRUMENTAL",
    "ITUNESADVISORY": "ADVISORY",
    "ALBUMITUNESADVISORY": "ADVISORY",
    "LYRICS": "LYRICS",
    "UNSYNCEDLYRICS": "LYRICS",
    # integrity tags follow AUDIT family (written alongside audit when present)
    "AUDIO_MD5": "AUDIT",
    "INTEGRITY": "AUDIT",
    "LOG_CRC": "LOG_GRADE",
}

def _audio_tag_family(tag_name):
    return _TAG_TO_FAMILY.get(str(tag_name).upper())

def _ext_to_audio_type(ext):
    ext = (ext or "").lower().lstrip(".")
    if ext == "flac":
        return "flac"
    if ext == "mp3":
        return "mp3"
    if ext in ("m4a", "mp4", "aac"):
        # aac files use mp4 container in mutagen; keep separate for aac
        return "aac" if ext == "aac" else "mp4"
    if ext == "ogg":
        return "ogg"
    if ext == "opus":
        return "opus"
    return None

def should_write_audio_tag(config, tag_name, filepath=None, filetype=None):
    """Whether an audio tag may be written for the given file.

    Checks the global master switch for the tag's family (e.g. write_audit_tag)
    AND the per-filetype `audio_tag_writes` override. If no per-type entry
    exists the default is True (backward compatible).
    Unknown tags or filetypes always return True.
    """
    if config is None:
        return True
    family = _audio_tag_family(tag_name)
    if not family:
        return True
    # Global master switches (map family -> config key).
    family_global = {
        "AUDIT": "write_audit_tag",
        "LOG_GRADE": "write_log_grade",
        "REPLAYGAIN": "write_replaygain_tags",
        "DYNAMIC_RANGE": "write_dynamic_range_tags",
        "MEDIA_SOURCE": "normalize_media_source",
        "INSTRUMENTAL": None,  # gated by two keys; handle below
        "ADVISORY": "auto_advisory",
        "LYRICS": None,  # lyrics_format gates this separately
    }
    gkey = family_global.get(family)
    if gkey is not None and not config.get(gkey, True):
        return False
    # INSTRUMENTAL has two globals; require at least one path to be enabled.
    # For per-type we still respect the individual caller: fix_instrumental
    # vs auto_instrumental are checked at call sites, so here just check
    # that at least one is enabled when family is INSTRUMENTAL.
    if family == "INSTRUMENTAL":
        if not config.get("fix_instrumental_from_lyrics", True) and not config.get("auto_instrumental", True):
            return False
    # Resolve filetype
    if not filetype:
        if filepath:
            ext = os.path.splitext(filepath)[1]
            filetype = _ext_to_audio_type(ext)
        else:
            return True
    if not filetype:
        return True
    # Per-filetype override
    per = config.get("audio_tag_writes") or {}
    # Normalize filetype alias: aac -> aac, mp4 stays mp4
    ft = per.get(filetype)
    if not isinstance(ft, dict):
        # Also try ext-based fallback for mp4/m4a
        if filetype == "mp4":
            ft = per.get("mp4") or per.get("m4a")
        if not isinstance(ft, dict):
            return True
    # If family not in ft, default True
    if family not in ft:
        return True
    return bool(ft.get(family, True))

DEFAULT_CONFIG = {
    # The first-run wizard supplies this; never ship a developer-specific
    # library path in the application defaults.
    "music_folder": "",

    # FLAC
    "flac_level": 8,
    "add_seektables": False,
    "force_reencode_flac": False,
    "flac_preserve_picture": False,
    "flac_no_padding": True,

    # Images — global
    "jpegxl_effort": 10,
    "jpegxl_distance": 0.0,
    "images_jpeg_quality": 95,
    "reencode_images": True,
    "reencode_to_jxl": True,
    "convert_jxl_back": False,
    "rename_to_cover": True,
    "remove_alpha": True,
    "jpeg_progressive": True,
    "png_optimization_level": 6,
    "force_reencode_images": False,
    # Cover art — resize / crop (new in v1.2.0) — defaults now enforce exactly 1000x1000
    "cover_resize_enabled": True,
    "cover_target_size": 1000,
    "cover_crop_enabled": True,
    "cover_crop_threshold": 0.05,
    "cover_force_exact_size": True,
    "cover_enforce_size": True,
    "cover_enforce_square": True,
    "cover_jpeg_enabled": True,
    "cover_png_enabled": True,
    "cover_jxl_enabled": True,
    "cover_jpeg_target_size": 0,
    "cover_png_target_size": 0,
    "cover_jxl_target_size": 0,

    # Lyrics / CUE — including Enhanced/Extended LRC (new in v1.2.0)
    "optimize_lrc": True,
    "optimize_embedded_lyrics": True,
    "lyrics_format": "EMBEDDED",
    "lrc_timestamp_precision": 2,
    "lrc_strip_metadata": True,
    "lrc_collapse_blank_lines": True,
    "lrc_enhanced_enabled": True,
    "lrc_enhanced_word_sync": True,
    "lrc_extended_enabled": True,
    "lrc_add_zero_timestamp": True,
    "lrc_zero_timestamp_blank": False,
    # Where the zero timestamp is added when enabled: EMBEDDED, LRC, or BOTH.
    # Now works for both standard and enhanced LRCs (per request).
    # When enabled, it always adds a blank "[00:00.00]" as the first line.
    "lrc_zero_timestamp_target": "BOTH",
    # Disabled by default to preserve the byte-exact no-final-newline mode.
    "append_final_newline": False,
    "keep_empty_cue_lines": False,
    "keep_other_cue_lines": False,
    "cue_file_type": "WAVE",

    # MEDIA / SOURCE normalization
    "normalize_media_source": True,
    "digital_media_source_value": DEFAULT_DIGITAL_SOURCE,
    # When True, empty SOURCE on Digital Media is filled with the value above;
    # when False (default, per request), empty stays empty.
    "fill_empty_source": False,

    # CD rips (MEDIA=CD): deterministic CD-N renaming of .log/.cue and
    # conservative CUE FILE-name correction. Both are content-derived —
    # nothing is renamed when the evidence is ambiguous. The single-fallback
    # ensures a lone .cue/.log in a single-disc album still becomes CD-1.
    "discs_rename_enabled": True,
    "discs_rename_pattern": "CD-{n}",
    "discs_rename_single_fallback": True,
    "discs_toc_tolerance_s": 4.0,
    "discs_toc_unique_margin_s": 4.0,
    "cue_fix_filenames": True,

    # Music-file tag writes
    "fix_instrumental_from_lyrics": True,
    "write_audit_tag": True,
    "write_log_grade": True,
    "write_replaygain_tags": True,
    "write_dynamic_range_tags": True,

    # Grading
    "grade_verbose": True,
    # What file categories are allowed when grading an album folder. A
    # folder with files of a disallowed category fails grading. 'other' is
    # opt-in: by default any file that is not music/cover/cue/log/lrc fails.
    "grade_include_music": True,
    "grade_include_cover": True,
    "grade_include_cue": True,
    "grade_include_log": True,
    "grade_include_lrc": True,
    "grade_include_other": False,
    # Configurable strict checks for grading (all on by default, per request)
    # These make trailing/leading spaces, blank lines, cropping and zero timestamp
    # count as failures for the relevant file types.
    "grade_check_tag_spaces": True,
    "grade_check_lyrics_spaces": True,
    "grade_check_cue_spaces": True,
    "grade_check_cover_crop": True,
    "grade_check_lyrics_zero": True,
    "grade_check_tag_blank_lines": True,
    "grade_check_lyrics_blank_lines": True,
    "grade_check_cue_blank_lines": True,
    "grader_cover_size_tolerance_px": 1,
    "grader_strict_square_threshold": 0.005,
    "grade_log_score_threshold": 0,

    # Audio audit (AudioAuditor CLI): full-track detectors (silence, DR,
    # true peak, LUFS, BPM) instead of the fast scan; force re-audits files
    # that already carry an AUDIT verdict. Detector toggles map to the CLI's
    # --no-* flags (default on) and --cutoff-allow sets the frequency-cutoff
    # threshold for fake detection (0 = CLI default).
    "audit_thorough": True,
    "force_audit": False,
    "audit_cutoff_allow": 0,
    # For MEDIA=CD rips, verify tracks against the CRC-32 checksums printed
    # in the .log and write AUDIT=REAL/FAKE from that (authoritative over
    # AudioAuditor for those files). When audit_cd_require_both is True
    # (now the default), BOTH the .log CRC and AudioAuditor must be REAL
    # for the final AUDIT to be REAL; if either is FAKE, the result is FAKE.
    "audit_verify_cd_checksums": True,
    "audit_cd_require_both": True,
    "audit_integrity": True,
    "audit_fail_on_unscorable_log": True,
    "audit_batch_size": 250,
    "audit_batch_timeout_s": 30,
    "audit_per_file_timeout_s": 30,
    "audit_clipping": True,
    "audit_scaled_clipping": True,
    "audit_mqa": True,
    "audit_ai": True,
    "audit_fake_stereo": True,
    "audit_silence": True,
    "audit_dynamic_range": True,
    "audit_true_peak": True,
    "audit_lufs": True,
    "audit_bpm": True,

    # Encoder marker tags written per file type (ENCODER_PROGRAM /
    # ENCODER_QUALITY / ENCODER_VERSION) — ENCODER_PROGRAM off by default
    # (legacy, not needed for optimization gating), but can be re-enabled per
    # format via Settings → Encoder Tags. QUALITY/VERSION remain on (they gate
    # re-optimization: higher effort or newer version).
    "encoder_tags": {
        "flac": {"ENCODER_PROGRAM": False, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "jpeg": {"ENCODER_PROGRAM": False, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "png": {"ENCODER_PROGRAM": False, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "jxl": {"ENCODER_PROGRAM": False, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
    },
    # Per-filetype audio tag writes — which semantic tag families each audio
    # container receives. All True by default; ANDed with the global master
    # switches above (write_audit_tag etc.). Organized by filetype for
    # predictable, fine-grained control without crowding the UI.
    "audio_tag_writes": {
        "flac": {k: True for k in AUDIO_TAG_FAMILIES},
        "mp3": {k: True for k in AUDIO_TAG_FAMILIES},
        "mp4": {k: True for k in AUDIO_TAG_FAMILIES},
        "ogg": {k: True for k in AUDIO_TAG_FAMILIES},
        "opus": {k: True for k in AUDIO_TAG_FAMILIES},
        "aac": {k: True for k in AUDIO_TAG_FAMILIES},
    },

    # DR / ReplayGain (script 7): rsgain + simple-dr-meter.
    "dr_replaygain_enabled": True,
    "replaygain_skip_existing": True,
    "force_dr_replaygain": False,
    "force_dr_ui": False,

    # Auto Tagging (script 8)
    "auto_advisory": True,
    "auto_instrumental": True,
    "auto_zero_advisory_for_instrumental": True,
    "force_auto_tag": False,
    "force_auto_tag_ui": False,

    # Misc
    "auto_advance": True,
    # 0 means automatic. A positive value caps every module's worker pool,
    # which is useful on slower disks or shared machines.
    "worker_limit": 0,
    "run_all_order": list(DEFAULT_RUN_ALL_ORDER),

    # External taggers (Mp3tag / MusicBrainz Picard): explicit exe paths.
    # Empty means auto-detect (registry / install dirs / PATH).
    "mp3tag_path": "",
    "picard_path": "",
    "foobar2000_path": "",

    # UI
    "compact_ui": False,
    "sidebar_visible": True,
    "force_ui": False,
    "force_flac_ui": False,
    "force_images_ui": False,
    "force_audit_ui": False,
    "force_lyrics_ui": False,
    "force_cue_ui": False,
    "library_sort": "name",
    "library_columns": {},

    # GUI: theme ("dark" | "light" | "system"), accent color ("" = theme
    # default, else #rrggbb), and whether the library tree also lists
    # non-audio files inside each album. Tkinter is now the GUI (PySide6
    # removed as obsolete).
    "theme": "dark",
    "accent_color": "",
    "library_show_all_files": False,

    # First run / updates
    "first_run_done": False,
    "last_update_check": 0,
    "check_updates_on_start": True,
    "auto_update_on_start": False,
    "update_check_interval_days": 7,
    "update_close_other_instances": True,
    "confirm_before_update": True,
    "show_sidecar_files": False,
}


_BOOL_KEYS = {
    key for key, value in DEFAULT_CONFIG.items() if isinstance(value, bool)
}
_INT_RANGES = {
    "flac_level": (0, 8),
    "jpegxl_effort": (1, 10),
    "lrc_timestamp_precision": (2, 3),
    "png_optimization_level": (0, 6),
    "audit_cutoff_allow": (0, 24000),
    "audit_batch_size": (50, 500),
    "audit_batch_timeout_s": (10, 120),
    "audit_per_file_timeout_s": (10, 60),
    "images_jpeg_quality": (70, 100),
    "grader_cover_size_tolerance_px": (0, 5),
    "grade_log_score_threshold": (0, 100),
    "worker_limit": (0, 64),
    "update_check_interval_days": (1, 30),
    "cover_target_size": (0, 4000),
    "cover_jpeg_target_size": (0, 4000),
    "cover_png_target_size": (0, 4000),
    "cover_jxl_target_size": (0, 4000),
}
_CHOICES = {
    "lyrics_format": {"EMBEDDED", "LRC", "BOTH"},
    "lrc_zero_timestamp_target": {"EMBEDDED", "LRC", "BOTH"},
    "cue_file_type": {"WAVE", "MP3"},
}


def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
    return default


def normalize_config(user=None) -> dict:
    """Return a validated, deep-copied configuration.

    Configuration files are user-editable, so malformed values must not leak
    into the GUI as truthy strings or invalid encoder arguments.
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if isinstance(user, dict):
        # Never persist transient 'targets' (GUI selection) to disk
        user = {k: v for k, v in user.items() if k != "targets"}
        # Deep-merge nested dicts instead of shallow overwrite
        for k in ("encoder_tags", "audio_tag_writes"):
            if k in user and isinstance(user[k], dict) and isinstance(cfg[k], dict):
                merged = copy.deepcopy(cfg[k])
                merged.update(user[k])
                user[k] = merged
        cfg.update(user)

    for key in _BOOL_KEYS:
        cfg[key] = _as_bool(cfg.get(key), DEFAULT_CONFIG.get(key, False))

    for key, (low, high) in _INT_RANGES.items():
        try:
            value = int(cfg.get(key, DEFAULT_CONFIG[key]))
        except (TypeError, ValueError):
            value = DEFAULT_CONFIG[key]
        cfg[key] = max(low, min(high, value))

    for key, choices in _CHOICES.items():
        value = str(cfg.get(key, DEFAULT_CONFIG[key])).upper()
        cfg[key] = value if value in choices else DEFAULT_CONFIG[key]

    folder = cfg.get("music_folder", "")
    cfg["music_folder"] = folder.strip() if isinstance(folder, str) else ""

    source = cfg.get("digital_media_source_value", DEFAULT_DIGITAL_SOURCE)
    cfg["digital_media_source_value"] = (
        str(source).strip() or DEFAULT_DIGITAL_SOURCE
    )

    try:
        last_check = float(cfg.get("last_update_check", 0) or 0)
        cfg["last_update_check"] = max(0.0, last_check)
    except (TypeError, ValueError):
        cfg["last_update_check"] = 0.0

    try:
        thr = float(cfg.get("cover_crop_threshold", 0.05))
        cfg["cover_crop_threshold"] = max(0.0, min(0.5, thr))
    except (TypeError, ValueError):
        cfg["cover_crop_threshold"] = 0.05
    for k, default, lo, hi in (
        ("discs_toc_tolerance_s", 4.0, 0.5, 10.0),
        ("discs_toc_unique_margin_s", 4.0, 0.5, 10.0),
        ("jpegxl_distance", 0.0, 0.0, 2.0),
        ("grader_strict_square_threshold", 0.005, 0.0, 0.05),
    ):
        try:
            v = float(cfg.get(k, default))
            cfg[k] = max(lo, min(hi, v))
        except (TypeError, ValueError):
            cfg[k] = default

    for k in ("cover_target_size", "cover_jpeg_target_size",
              "cover_png_target_size", "cover_jxl_target_size"):
        try:
            cfg[k] = int(cfg.get(k, DEFAULT_CONFIG[k]) or 0)
        except (TypeError, ValueError):
            cfg[k] = DEFAULT_CONFIG[k]
        cfg[k] = max(0, min(4000, cfg[k]))

    # Discs rename pattern: must contain {n}, reasonable length, no path sep
    pat = cfg.get("discs_rename_pattern", "CD-{n}")
    if not isinstance(pat, str) or "{n}" not in pat:
        pat = "CD-{n}"
    # Sanitize: no directory separators, no null, limit length
    pat = pat.replace("/", "").replace("\\", "").strip()[:32] or "CD-{n}"
    if "{n}" not in pat:
        pat = "CD-{n}"
    cfg["discs_rename_pattern"] = pat

    default_tags = DEFAULT_CONFIG["encoder_tags"]
    user_tags = cfg.get("encoder_tags") if isinstance(cfg.get("encoder_tags"), dict) else {}
    merged_tags = {}
    for file_type, fields in default_tags.items():
        merged_tags[file_type] = dict(fields)
        values = user_tags.get(file_type)
        if isinstance(values, dict):
            for field in fields:
                merged_tags[file_type][field] = _as_bool(
                    values.get(field), fields[field]
                )
    cfg["encoder_tags"] = merged_tags

    # Audio tag writes per filetype
    default_audio = DEFAULT_CONFIG.get("audio_tag_writes", {})
    user_audio = cfg.get("audio_tag_writes") if isinstance(cfg.get("audio_tag_writes"), dict) else {}
    merged_audio = {}
    for ftype in AUDIO_TAG_TYPES:
        base = default_audio.get(ftype, {k: True for k in AUDIO_TAG_FAMILIES})
        merged_audio[ftype] = dict(base)
        vals = user_audio.get(ftype)
        if isinstance(vals, dict):
            for fam in AUDIO_TAG_FAMILIES:
                if fam in vals:
                    merged_audio[ftype][fam] = _as_bool(vals.get(fam), base.get(fam, True))
    # alias: if user used "m4a" key, fold into mp4
    if isinstance(user_audio.get("m4a"), dict):
        for fam in AUDIO_TAG_FAMILIES:
            if fam in user_audio["m4a"]:
                merged_audio["mp4"][fam] = _as_bool(user_audio["m4a"].get(fam), merged_audio["mp4"].get(fam, True))
    cfg["audio_tag_writes"] = merged_audio

    columns = cfg.get("library_columns")
    cfg["library_columns"] = dict(columns) if isinstance(columns, dict) else {}

    order = cfg.get("run_all_order", DEFAULT_RUN_ALL_ORDER)
    clean_order = []
    if isinstance(order, (list, tuple)):
        for value in order:
            try:
                script_id = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= script_id <= 8 and script_id not in clean_order:
                clean_order.append(script_id)
    # Migrate legacy sequential default [1..8] to systematic pipeline
    if clean_order == [1, 2, 3, 4, 5, 6, 7, 8] and clean_order != list(DEFAULT_RUN_ALL_ORDER):
        clean_order = list(DEFAULT_RUN_ALL_ORDER)
    cfg["run_all_order"] = clean_order or list(DEFAULT_RUN_ALL_ORDER)
    return cfg


def load_config() -> dict:
    user = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user = json.load(f)
        except Exception:
            user = None
    return normalize_config(user)


def save_config(cfg: dict) -> bool:
    """Validate and atomically replace the persisted configuration."""
    try:
        normalized = normalize_config(cfg)
        directory = os.path.dirname(CONFIG_FILE) or "."
        fd, temp_path = tempfile.mkstemp(
            prefix=".mlo_config_", suffix=".json", dir=directory
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(normalized, f, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, CONFIG_FILE)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return True
    except Exception as e:
        print(c(f"ERROR: Could not save config: {e}", Color.RED))
        return False
