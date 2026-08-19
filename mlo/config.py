"""Configuration persisted to config.json next to the application."""
import json
import os

from .paths import CONFIG_FILE, DEFAULT_DIGITAL_SOURCE
from .ui import c, Color

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
    # files that already carry an AUDIT verdict.
    "audit_thorough": False,
    "force_audit": False,

    # Encoder marker tags written per file type (ENCODER_PROGRAM /
    # ENCODER_QUALITY / ENCODER_VERSION)
    "encoder_tags": {
        "flac": {"ENCODER_PROGRAM": True, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "jpeg": {"ENCODER_PROGRAM": True, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "png": {"ENCODER_PROGRAM": True, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
        "jxl": {"ENCODER_PROGRAM": True, "ENCODER_QUALITY": True, "ENCODER_VERSION": True},
    },

    # Misc
    "auto_advance": True,
    "run_all_order": [1, 2, 3, 5, 4],

    # External taggers (Mp3tag / MusicBrainz Picard): explicit exe paths.
    # Empty means auto-detect (registry / install dirs / PATH).
    "mp3tag_path": "",
    "picard_path": "",

    # UI
    "compact_ui": False,
    "force_ui": False,
    "force_flac_ui": False,
    "force_images_ui": False,
    "force_audit_ui": False,
    "library_sort": "name",
    # Library tree column visibility (id -> bool); keys merge with the
    # app's column table so partial maps are fine.
    "library_columns": {},
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

    order = cfg.get("run_all_order", [1, 2, 3, 5, 4])
    clean_order = []
    try:
        for x in order:
            xi = int(x)
            if 1 <= xi <= 6 and xi not in clean_order:
                clean_order.append(xi)
    except Exception:
        clean_order = [1, 2, 3, 5, 4]

    cfg["run_all_order"] = clean_order or [1, 2, 3, 5, 4]
    return cfg


def save_config(cfg: dict) -> bool:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(c(f"ERROR: Could not save config: {e}", Color.RED))
        return False

