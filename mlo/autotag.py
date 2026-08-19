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
from .paths import AUDIO_EXTS
from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _collect_targets,
    _find_albums, is_audio_file,
)
from .ui import print_header, log, c, Color


# ----------------------------------------------------------------------
# ALBUMITUNESADVISORY
# ----------------------------------------------------------------------
def album_advisory_from_tracks(files):
    """Derive the album advisory (0/1/2) from per-track ITUNESADVISORY."""
    has_safe = False
    for path in files:
        try:
            af = AudioFile(path)
            v = str(af.get_tag("ITUNESADVISORY") or "").strip()
        except Exception:
            continue
        if v == "1":
            return 1
        if v == "2":
            has_safe = True
    return 2 if has_safe else 0


# ----------------------------------------------------------------------
# INSTRUMENTAL
# ----------------------------------------------------------------------
def _has_lyrics(path):
    """True when the track has lyrics (embedded LYRICS or an .lrc sidecar)."""
    try:
        af = AudioFile(path)
        if af.get_lyrics() and str(af.get_lyrics()).strip():
            return True
    except Exception:
        pass
    return os.path.exists(os.path.splitext(path)[0] + ".lrc")


# ----------------------------------------------------------------------
# Album helpers
# ----------------------------------------------------------------------
def _album_files(album_dir):
    return sorted(
        os.path.join(album_dir, f)
        for f in os.listdir(album_dir) if is_audio_file(f))


def _advisory_ok(album_dir, value):
    for path in _album_files(album_dir):
        try:
            af = AudioFile(path)
            if str(af.get_tag("ALBUMITUNESADVISORY") or "").strip() != str(value):
                return False
        except Exception:
            return False
    return True


def _write_advisory(album_dir, value):
    modified = 0
    for path in _album_files(album_dir):
        try:
            af = AudioFile(path)
            if str(af.get_tag("ALBUMITUNESADVISORY") or "").strip() != str(value):
                if af.set_tag("ALBUMITUNESADVISORY", str(value)):
                    modified += 1
        except Exception:
            continue
    return modified


def _instrumental_ok(album_dir):
    """True when every track WITH lyrics already has INSTRUMENTAL=0.

    Tracks without lyrics are left alone (they may be non-instrumental but
    simply lack downloaded lyric files), so they never block a skip.
    """
    for path in _album_files(album_dir):
        if not _has_lyrics(path):
            continue
        try:
            af = AudioFile(path)
            have = str(af.get_tag("INSTRUMENTAL") or "").strip()
        except Exception:
            return False
        if have != "0":
            return False
    return True


def _write_instrumental(album_dir):
    """Set INSTRUMENTAL=0 on every track that HAS lyrics.

    Tracks without lyrics are NOT touched - they could still be
    non-instrumental, just missing lyric files.
    """
    modified = 0
    for path in _album_files(album_dir):
        if not _has_lyrics(path):
            continue
        try:
            af = AudioFile(path)
            have = str(af.get_tag("INSTRUMENTAL") or "").strip()
        except Exception:
            continue
        if have != "0":
            if af.set_tag("INSTRUMENTAL", "0"):
                modified += 1
    return modified


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

    if config.get("targets"):
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
        advisory_value = (album_advisory_from_tracks(files)
                          if do_advisory else None)
        modified = 0
        if do_advisory and (force or not _advisory_ok(album, advisory_value)):
            modified += _write_advisory(album, advisory_value)
        if do_instrumental and (force or not _instrumental_ok(album)):
            modified += _write_instrumental(album)
        notes = []
        if advisory_value is not None and modified:
            notes.append(f"advisory={advisory_value}")
        if do_instrumental and modified:
            notes.append("instrumental")
        return album, modified, notes, advisory_value

    counts = {"ok": 0, "skip": 0, "fail": 0}
    pbar = _make_pbar(len(album_dirs), "AutoTag", unit="album")
    workers = max(2, min(8, os.cpu_count() or 2, len(album_dirs)))
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