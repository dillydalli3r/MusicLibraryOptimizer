"""Key & BPM detection (script 12).

For every track it decodes audio with librosa (vendored into
.dependencies via pip, see fetchdeps.PIP_PACKAGES) and writes:

  * BPM        - from librosa's beat tracking (rounded to a whole number),
  * INITIALKEY - from the average chroma vector correlated against the
                 Krumhansl-Schmuckler major/minor profiles, rendered in
                 musical ('A min'), Camelot ('8A') or Open Key ('1m').

Skips tracks that already carry both tags unless overwrite/force is set,
and respects the per-filetype audio_tag_writes gates (BPM / INITIALKEY).
"""
import math
import os
import sys

from .audio import AudioFile
from .config import should_write_audio_tag
from .paths import AUDIO_EXTS
from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _walk_files,
    _collect_targets, is_audio_file, worker_count,
)
from .tools import python_pkg_path
from .ui import print_header, log, c, Color
from concurrent.futures import ThreadPoolExecutor, as_completed

# Krumhansl-Schmuckler key profiles (major, minor), indexed from C.
_KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Camelot wheel: each position n covers nB (major) + its relative nA (minor).
# C major = 8B, A minor = 8A, stepping by fifths. Indexed by tonic from C.
_CAMELOT_MAJOR = ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"]
_CAMELOT_MINOR = ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"]
# Open Key: 1d = C major, 1m = A minor, same circle of fifths ordering.
_OPENKEY_MAJOR = ["1d", "8d", "3d", "10d", "5d", "12d", "7d", "2d", "9d", "4d", "11d", "6d"]
_OPENKEY_MINOR = ["10m", "5m", "12m", "7m", "2m", "9m", "4m", "11m", "6m", "1m", "8m", "3m"]


# ----------------------------------------------------------------------
# Vendored librosa
# ----------------------------------------------------------------------
def _ensure_librosa():
    """Prepend the vendored librosa folder to sys.path; returns the version
    string or None when the dependency is not installed."""
    path = python_pkg_path("librosa")
    if path and path not in sys.path:
        sys.path.insert(0, path)
    try:
        import librosa
        return getattr(librosa, "__version__", "?")
    except Exception:
        return None


def _key_notation(tonic_idx, minor, notation):
    """Render a detected key in the configured notation."""
    tonic = _PITCHES[tonic_idx % 12]
    if notation == "camelot":
        return _CAMELOT_MINOR[tonic_idx] if minor else _CAMELOT_MAJOR[tonic_idx]
    if notation == "openkey":
        return _OPENKEY_MINOR[tonic_idx] if minor else _OPENKEY_MAJOR[tonic_idx]
    return f"{tonic} {'min' if minor else 'maj'}"


def detect_key_bpm(path, min_seconds=10):
    """Analyze one audio file. Returns (bpm:int|None, key:(tonic,minor)|None).

    BPM from librosa beat tracking (folded into the 70-180 range DJs
    expect); key from the mean chroma correlated against
    Krumhansl-Schmuckler profiles. Returns (None, None) for tracks shorter
    than *min_seconds* (too short for stable estimates).
    """
    import numpy as np
    import librosa

    sr = 22050
    y, _ = librosa.load(path, sr=sr, mono=True)
    if y.size < sr * max(1, min_seconds):
        return None, None

    bpm = None
    try:
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(np.atleast_1d(tempo)[0])
        if np.isfinite(tempo) and tempo > 0:
            bpm = tempo
            # Fold octave errors (half/double time) into a musical range.
            while bpm < 70:
                bpm *= 2
            while bpm > 180:
                bpm /= 2
            bpm = int(round(bpm))
    except Exception:
        bpm = None

    key = None
    try:
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=4096)
        mean_chroma = np.asarray(chroma).mean(axis=1)
        if np.isfinite(mean_chroma).all() and mean_chroma.sum() > 0:
            best = (-2.0, 0, False)
            for idx in range(12):
                rotated = np.roll(mean_chroma, -idx)
                for minor, profile in ((False, _KS_MAJOR), (True, _KS_MINOR)):
                    r = float(np.corrcoef(rotated, profile)[0, 1])
                    if math.isfinite(r) and r > best[0]:
                        best = (r, idx, minor)
            _, tonic, minor = best
            key = (tonic, minor)
    except Exception:
        key = None

    return bpm, key


# ----------------------------------------------------------------------
# Track selection / tag writing
# ----------------------------------------------------------------------
def _track_paths(config):
    folder = config["music_folder"]
    if config.get("targets") is not None:
        return sorted(_collect_targets(config["targets"], AUDIO_EXTS))
    if not os.path.isdir(folder):
        return []
    return sorted(_walk_files(folder, AUDIO_EXTS))


def _needs_analysis(path, force, overwrite):
    """True when at least one of BPM/INITIALKEY is missing (or forced)."""
    if force:
        return True
    try:
        af = AudioFile(path)
        has_bpm = bool(str(af.get_tag("BPM") or "").strip())
        has_key = bool(str(af.get_tag("INITIALKEY") or "").strip())
    except Exception:
        return True
    return overwrite or not (has_bpm and has_key)


def _write_tags(path, bpm, key_str, config):
    """Write BPM/INITIALKEY respecting per-filetype gates. Returns True when
    the file changed."""
    changed = False
    try:
        af = AudioFile(path)
        if bpm is not None and should_write_audio_tag(config, "BPM", filepath=path):
            if str(af.get_tag("BPM") or "").strip() != str(bpm):
                if af.set_tag("BPM", str(bpm)):
                    changed = True
        if key_str and should_write_audio_tag(config, "INITIALKEY", filepath=path):
            if str(af.get_tag("INITIALKEY") or "").strip() != key_str:
                if af.set_tag("INITIALKEY", key_str):
                    changed = True
    except Exception:
        return False
    return changed


# ----------------------------------------------------------------------
# Script entry point
# ----------------------------------------------------------------------
def run_analyze_audiometa(config):
    folder = config["music_folder"]
    stats = new_stats()

    if not config.get("audiometa_enabled", True):
        print_header("Key & BPM (skipped - disabled in settings)")
        return stats

    print_header("Key & BPM Detection")
    log(f"music folder: {folder}")

    version = _ensure_librosa()
    if not version:
        log(c("ERROR: librosa is not installed. Use Dependencies to install it.",
              Color.RED))
        stats["error_count"] += 1
        stats["errors"].append(("librosa", "not installed"))
        return stats
    log(f"librosa v{version} · notation={config.get('audiometa_key_notation', 'musical')}")

    force = config.get("force_audiometa", False)
    overwrite = config.get("audiometa_overwrite", False)
    min_seconds = int(config.get("audiometa_min_seconds", 10) or 10)

    paths = [p for p in _track_paths(config) if _needs_analysis(p, force, overwrite)]
    if not paths:
        log("Nothing to analyze (all tracks already tagged).")
        return stats

    notation = config.get("audiometa_key_notation", "musical")
    workers = worker_count(config, default=4, maximum=8, items=len(paths))
    counts = {"ok": 0, "skip": 0, "fail": 0}
    pbar = _make_pbar(len(paths), "Key & BPM", unit="file")

    def _task(path):
        try:
            bpm, key = detect_key_bpm(path, min_seconds)
        except Exception as e:
            return path, None, None, str(e)
        return path, bpm, key, None

    def _finish(path, bpm, key, err):
        if err is not None:
            stats["total_scanned"] += 1
            stats["error_count"] += 1
            stats["errors"].append((os.path.basename(path), err))
            _pbar_update(pbar, counts, kind="fail")
            return
        if bpm is None and key is None:
            stats["skipped_count"] += 1
            _pbar_skip(pbar, counts)
            return
        key_str = ""
        if key:
            tonic, minor = key
            key_str = _key_notation(tonic, minor, notation)
        if _write_tags(path, bpm, key_str, config):
            stats["total_scanned"] += 1
            stats["modified_count"] += 1
            _pbar_update(pbar, counts, kind="ok")
        else:
            stats["skipped_count"] += 1
            _pbar_skip(pbar, counts)

    if len(paths) == 1 or workers == 1:
        try:
            for path in paths:
                _finish(*_task(path))
        except KeyboardInterrupt:
            raise
        finally:
            if pbar:
                pbar.close()
    else:
        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(_task, p): p for p in paths}
                for fut in as_completed(futures):
                    _finish(*fut.result())
        finally:
            if pbar:
                pbar.close()

    stats["is_grader"] = False
    return stats
