"""Automatic tagging: ALBUMITUNESADVISORY + INSTRUMENTAL.

Script 8 ("Auto Tagging") derives values that would otherwise have to be
filled in by hand:

1) ALBUMITUNESADVISORY from the per-track ITUNESADVISORY (set manually):
       0 = unrated / not explicit, 1 = explicit, 2 = edited / safe.
   Across ALL of the album's tracks (every disc in a multi-disc folder):
       any explicit track (1)      -> 1
       else any edited/safe (2)    -> 2
       else                        -> 0

2) INSTRUMENTAL from lyrics presence per track:
       has lyrics (embedded LYRICS or an .lrc sidecar) -> 0 (not instrumental)
       no lyrics -> LEFT UNTOUCHED. A track without downloaded lyric files
       may still be non-instrumental, so it is never auto-marked as
       instrumental.

Albums / tracks that already carry the correct values are skipped unless
the run is forced.
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from .audio import AudioFile
from .config import should_write_audio_tag
from .paths import AUDIO_EXTS
from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _collect_targets,
    _find_albums, is_audio_file, worker_count,
)
from .ui import print_header, log, c, Color


# ----------------------------------------------------------------------
# ALBUMITUNESADVISORY / INSTRUMENTAL (single-pass per album)
# ----------------------------------------------------------------------
def _has_lyrics(path):
    """True when the track has lyrics (embedded LYRICS or an .lrc sidecar)."""
    try:
        af = AudioFile(path)
        lyr = af.get_lyrics()
        if lyr and str(lyr).strip():
            return True
    except Exception:
        pass
    return os.path.exists(os.path.splitext(path)[0] + ".lrc")


def _album_files(album_dir):
    return sorted(
        os.path.join(album_dir, f)
        for f in os.listdir(album_dir) if is_audio_file(f))


def _derive_advisory(advisories):
    """1 if any explicit advisory, else 2 if any safe, else 0."""
    if any(v == "1" for v in advisories):
        return 1
    if any(v == "2" for v in advisories):
        return 2
    return 0


# ----------------------------------------------------------------------
# Script 8 runner
# ----------------------------------------------------------------------
def run_auto_tagging(config):
    folder = config["music_folder"]
    stats = new_stats()

    print_header("Auto Tagging")
    log(f"music folder: {folder}")
    if config.get("auto_advisory", True):
        log("  ALBUMITUNESADVISORY: from per-track ITUNESADVISORY "
            "(any explicit -> 1, else any safe -> 2, else 0)")
    if config.get("auto_instrumental", True):
        log("  INSTRUMENTAL: 0 when lyrics present (no-lyrics tracks left "
            "untouched)")

    force = config.get("force_auto_tag", False)
    do_advisory = config.get("auto_advisory", True)
    do_instrumental = config.get("auto_instrumental", True)

    if config.get("targets") is not None:
        target_files = _collect_targets(config["targets"], AUDIO_EXTS)
        album_dirs = sorted({os.path.dirname(f) for f in target_files})
    else:
        if not os.path.isdir(folder):
            log(c(f"ERROR: folder does not exist: {folder}", Color.RED))
            return stats
        album_dirs = _find_albums(folder)

    if not album_dirs:
        log("No albums found.")
        return stats

    def process_album(album):
        files = _album_files(album)
        if not files:
            return album, 0, None, None

        # Single pass: load every file once and cache the values needed,
        # instead of re-parsing each file for advisory + instrumental.
        info = []
        for path in files:
            try:
                af = AudioFile(path)
                lyr = af.get_lyrics()
                info.append({
                    "af": af,
                    "advisory": str(af.get_tag("ITUNESADVISORY") or "").strip(),
                    "album_advisory": str(
                        af.get_tag("ALBUMITUNESADVISORY") or "").strip(),
                    "instrumental": str(af.get_tag("INSTRUMENTAL") or "").strip(),
                    "has_lyrics": bool(lyr and str(lyr).strip()) or
                        os.path.exists(os.path.splitext(path)[0] + ".lrc"),
                })
            except Exception:
                continue
        if not info:
            return album, 0, None, None

        modified = 0
        notes = []
        advisory_value = None

        # Formatting: ensure GENRE has no leading/trailing spaces and
        # ITUNESADVISORY is exactly 0/1/2 without spaces. This is the
        # optimization step for those tags.
        for d in info:
            # GENRE (standard tag, not gated by per-type ADVISORY — but still trim)
            try:
                raw_genre = d["af"].get_tag("GENRE")
                if raw_genre is not None:
                    stripped = str(raw_genre).strip()
                    if str(raw_genre) != stripped:
                        if d["af"].set_tag("GENRE", stripped):
                            modified += 1
                            d["af"] = AudioFile(d["af"].path)  # refresh
            except Exception:
                pass
            # ITUNESADVISORY: trim spaces; keep 0/1/2 only (grading will flag others)
            # Gated by per-filetype ADVISORY
            try:
                raw_adv = d["af"].get_tag("ITUNESADVISORY")
                if raw_adv is not None:
                    stripped = str(raw_adv).strip()
                    if str(raw_adv) != stripped:
                        if not should_write_audio_tag(config, "ITUNESADVISORY", filepath=d["af"].path):
                            continue
                        # Only write trimmed if the trimmed value is valid 0/1/2 or empty
                        # If it's invalid like " 3 ", we still trim to "3" so grading can flag the value, not the spaces
                        if d["af"].set_tag("ITUNESADVISORY", stripped):
                            modified += 1
                            d["advisory"] = stripped
            except Exception:
                pass

        if do_advisory:
            advisory_value = _derive_advisory(
                d["advisory"] for d in info)
            if force or any(d["album_advisory"] != str(advisory_value)
                            for d in info):
                for d in info:
                    if d["album_advisory"] != str(advisory_value):
                        if not should_write_audio_tag(config, "ALBUMITUNESADVISORY", filepath=d["af"].path):
                            continue
                        if d["af"].set_tag("ALBUMITUNESADVISORY",
                                           str(advisory_value)):
                            modified += 1
            if modified:
                notes.append(f"advisory={advisory_value}")

        if do_instrumental:
            if force or any(d["has_lyrics"] and d["instrumental"] != "0" and should_write_audio_tag(config, "INSTRUMENTAL", filepath=d["af"].path)
                            for d in info):
                for d in info:
                    if d["has_lyrics"] and d["instrumental"] != "0":
                        if not should_write_audio_tag(config, "INSTRUMENTAL", filepath=d["af"].path):
                            continue
                        if d["af"].set_tag("INSTRUMENTAL", "0"):
                            modified += 1
            if modified:
                notes.append("instrumental")

        return album, modified, notes, advisory_value

    counts = {"ok": 0, "skip": 0, "fail": 0}
    pbar = _make_pbar(len(album_dirs), "AutoTag", unit="album")
    workers = worker_count(config, default=8, maximum=8, items=len(album_dirs))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_album, a): a for a in sorted(album_dirs)}
        for fut in as_completed(futures):
            album = futures[fut]
            try:
                _album, modified, notes, advisory_value = fut.result()
            except Exception as e:
                stats["total_scanned"] += 1
                stats["error_count"] += 1
                stats["errors"].append((os.path.basename(album), str(e)))
                _pbar_update(pbar, counts, kind="fail")
                continue
            if modified:
                stats["total_scanned"] += 1
                stats["modified_count"] += 1
                log(f"  {os.path.basename(_album)} ({', '.join(notes)})")
                _pbar_update(pbar, counts, kind="ok")
            else:
                stats["skipped_count"] += 1
                _pbar_skip(pbar, counts)

    if pbar:
        pbar.close()
    stats["is_grader"] = False
    return stats
