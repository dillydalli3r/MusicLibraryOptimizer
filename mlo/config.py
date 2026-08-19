"""Configuration persisted to config.json next to the application."""
import json
import os

from .paths import CONFIG_FILE, DEFAULT_DIGITAL_SOURCE
from .ui import c, Color

# Run All order. By default EVERY script runs (1-8); the user can change the
# order / remove scripts via Settings -> Run All Order (or the console menu).
DEFAULT_RUN_ALL_ORDER = [1, 2, 3, 4, 5, 6, 7, 8]

DEFAULT_CONFIG = {
    "music_folder": r"F:\Media\Music\Artists",

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
    "force_reencode_images": False,

    # Lyrics / CUE
    "optimize_lrc": True,
    "optimize_embedded_lyrics": True,
    "lyrics_format": "EMBEDDED",
    "keep_empty_cue_lines": False,
    "keep_other_cue_lines": False,

    # MEDIA / SOURCE normalization
    "normalize_media_source": True,
    "digital_media_source_value": DEFAULT_DIGITAL_SOURCE,

    # Grading
    "grade_verbose": True,

    # Audio audit (AudioAuditor CLI): full-track detectors (silence, DR,
    # true peak, LUFS, BPM) instead of the fast scan; force re-audits
    # files that already carry an AUDIT verdict. Detector toggles map to
    # the CLI's --no-* flags (default on) and --cutoff-allow sets the
    # frequency-cutoff threshold for fake detection (0 = CLI default).
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

    # Auto Tagging (script 8): derive ALBUMITUNESADVISORY from manual
    # per-track ITUNESADVISORY (0 unrated / 1 explicit / 2 edited-safe) and
    # derive INSTRUMENTAL from lyrics presence (0 with lyrics, 1 without).
    "auto_advisory": True,
    "auto_instrumental": True,
    "force_auto_tag": False,
    "force_auto_tag_ui": False,

    # Misc
    "auto_advance": True,
    "run_all_order": list(DEFAULT_RUN_ALL_ORDER),

    # External taggers (Mp3tag / MusicBrainz Picard): explicit exe paths.
    # Empty means auto-detect (registry / install dirs / PATH).
    "mp3tag_path": "",
    "picard_path": "",

    # UI
    "compact_ui": False,
    "sidebar_visible": True,
    "force_ui": False,
    "force_flac_ui": False,
    "force_images_ui": False,
    "force_audit_ui": False,
    "library_sort": "name",
    # Library tree column visibility (id -> bool); keys merge with the
    # app's column table so partial maps are fine.
    "library_columns": {},
    # First run / updates
    "first_run_done": False,
    "last_update_check": 0,
    # Check for a new release when the app starts (once per interval).
    "check_updates_on_start": True,
}


def load_config() -> dict:
    cfg = DEFAULT_CONFIG.copy()

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user = json.load(f)
            cfg.update(user)
        except Exception:
            pass

    if str(cfg.get("lyrics_format", "EMBEDDED")).upper() not in ("EMBEDDED", "LRC", "BOTH"):
        cfg["lyrics_format"] = "EMBEDDED"

    if not str(cfg.get("digital_media_source_value", DEFAULT_DIGITAL_SOURCE)).strip():
        cfg["digital_media_source_value"] = DEFAULT_DIGITAL_SOURCE

    # Ensure encoder_tags exists for every supported file type with
    # per-field defaults (user config may predate the section).
    default_tags = DEFAULT_CONFIG["encoder_tags"]
    user_tags = cfg.get("encoder_tags") or {}
    merged = {}
    for ftype, fields in default_tags.items():
        merged[ftype] = dict(fields)
        merged[ftype].update(user_tags.get(ftype) or {})
    cfg["encoder_tags"] = merged

    order = cfg.get("run_all_order", DEFAULT_RUN_ALL_ORDER)
    clean_order = []
    try:
        for x in order:
            xi = int(x)
            if 1 <= xi <= 8 and xi not in clean_order:
                clean_order.append(xi)
    except Exception:
        clean_order = list(DEFAULT_RUN_ALL_ORDER)

    cfg["run_all_order"] = clean_order or list(DEFAULT_RUN_ALL_ORDER)
    return cfg


def save_config(cfg: dict) -> bool:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(c(f"ERROR: Could not save config: {e}", Color.RED))
        return False

