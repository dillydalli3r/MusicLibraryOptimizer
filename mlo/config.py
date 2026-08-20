"""Configuration persisted to config.json next to the application."""
import copy
import json
import os
import tempfile

from .paths import CONFIG_FILE, DEFAULT_DIGITAL_SOURCE
from .ui import c, Color

# Run All order. By default EVERY script runs (1-8); the user can change the
# order / remove scripts via Settings -> Run All Order (or the console menu).
DEFAULT_RUN_ALL_ORDER = [1, 2, 3, 4, 5, 6, 7, 8]

DEFAULT_CONFIG = {
    # The first-run wizard supplies this; never ship a developer-specific
    # library path in the application defaults.
    "music_folder": "",

    # FLAC
    "flac_level": 8,
    "add_seektables": False,
    "force_reencode_flac": False,

    # Images
    "jpegxl_effort": 10,
    "reencode_images": True,
    "reencode_to_jxl": True,
    "convert_jxl_back": False,
    "rename_to_cover": True,
    "remove_alpha": True,
    "jpeg_progressive": True,
    "png_optimization_level": 2,
    "force_reencode_images": False,

    # Lyrics / CUE
    "optimize_lrc": True,
    "optimize_embedded_lyrics": True,
    "lyrics_format": "EMBEDDED",
    "lrc_timestamp_precision": 2,
    "lrc_strip_metadata": True,
    "lrc_collapse_blank_lines": True,
    # Disabled by default to preserve the byte-exact no-final-newline mode.
    "append_final_newline": False,
    "keep_empty_cue_lines": False,
    "keep_other_cue_lines": False,
    "cue_file_type": "WAVE",

    # MEDIA / SOURCE normalization
    "normalize_media_source": True,
    "digital_media_source_value": DEFAULT_DIGITAL_SOURCE,

    # Music-file tag writes
    "fix_instrumental_from_lyrics": True,
    "write_audit_tag": True,
    "write_log_grade": True,
    "write_replaygain_tags": True,
    "write_dynamic_range_tags": True,

    # Grading
    "grade_verbose": True,

    # Audio audit (AudioAuditor CLI): full-track detectors (silence, DR,
    # true peak, LUFS, BPM) instead of the fast scan; force re-audits files
    # that already carry an AUDIT verdict. Detector toggles map to the CLI's
    # --no-* flags (default on) and --cutoff-allow sets the frequency-cutoff
    # threshold for fake detection (0 = CLI default).
    "audit_thorough": False,
    "force_audit": False,
    "audit_cutoff_allow": 0,
    "audit_clipping": True,
    "audit_mqa": True,
    "audit_ai": True,
    "audit_fake_stereo": True,
    "audit_silence": True,
    "audit_dynamic_range": True,
    "audit_true_peak": True,
    "audit_lufs": True,
    "audit_bpm": True,

    # Encoder marker tags written per file type (ENCODER_PROGRAM /
    # ENCODER_QUALITY / ENCODER_VERSION)
    "encoder_tags": {
        "flac": {"ENCODER_PROGRAM": True, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "jpeg": {"ENCODER_PROGRAM": True, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "png": {"ENCODER_PROGRAM": True, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "jxl": {"ENCODER_PROGRAM": True, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
    },

    # DR / ReplayGain (script 7): rsgain + simple-dr-meter.
    "dr_replaygain_enabled": True,
    "replaygain_skip_existing": True,
    "force_dr_replaygain": False,
    "force_dr_ui": False,

    # Auto Tagging (script 8)
    "auto_advisory": True,
    "auto_instrumental": True,
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
    "library_sort": "name",
    "library_columns": {},

    # First run / updates
    "first_run_done": False,
    "last_update_check": 0,
    "check_updates_on_start": True,
    "auto_update_on_start": False,
    "update_check_interval_days": 7,
    "update_close_other_instances": True,
    "confirm_before_update": True,
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
    "worker_limit": (0, 64),
    "update_check_interval_days": (1, 30),
}
_CHOICES = {
    "lyrics_format": {"EMBEDDED", "LRC", "BOTH"},
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
                json.dump(normalized, f, indent=2)
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
