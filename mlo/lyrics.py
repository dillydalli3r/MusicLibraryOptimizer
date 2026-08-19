"""Lyrics formatting, LRC/embedded conversion and MEDIA/SOURCE normalization."""
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from .audio import AudioFile
from .paths import AUDIO_EXTS, DEFAULT_DIGITAL_SOURCE
from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _diff_bytes,
    _walk_files, is_audio_file, _find_albums, _clean_set, _summarize_values,
    _collect_targets,
)
from .ui import print_header, log, c, Color, log_file_result

TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:\.(\d+))?\]")


SPACE_AFTER_TS_RE = re.compile(r"(\[\d{2}:\d{2}\.\d{2}\])\s+")


LRC_META_RE = re.compile(
    r"^\s*\[(?:ar|ti|al|by|offset|length|re|ve):.*\]\s*$",
    re.IGNORECASE,
)


def _round_ms_to_2(ms_str):
    try:
        d = Decimal("0." + ms_str).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        s = format(d, "f")
        digits = s.split(".", 1)[1] if "." in s else "00"
        return digits[:2].ljust(2, "0")
    except (InvalidOperation, ValueError):
        return ms_str[:2].ljust(2, "0")


def _reformat_ts(m):
    mins = m.group(1).zfill(2)
    secs = m.group(2).zfill(2)
    ms = m.group(3)

    if ms is None:
        ms = "00"
    elif len(ms) > 2:
        ms = _round_ms_to_2(ms)
    else:
        ms = ms.ljust(2, "0")[:2]

    return f"[{mins}:{secs}.{ms}]"


def format_lyrics_text(text):
    """
    Cleans lyrics:
    - POSIX newlines
    - normalized timestamps
    - no space directly after timestamps
    - no LRC metadata lines
    - no duplicate blank lines
    """
    if not text:
        return text

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = TIMESTAMP_RE.sub(_reformat_ts, text)
    text = SPACE_AFTER_TS_RE.sub(r"\1", text)

    lines = []

    for ln in text.split("\n"):
        s = ln.strip()

        if not s:
            lines.append("")
        elif LRC_META_RE.match(s):
            continue
        else:
            lines.append(s)

    cleaned = []
    prev_blank = False

    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    return "\n".join(cleaned)


def _lrc_for(audio_path):
    return os.path.splitext(audio_path)[0] + ".lrc"


def _canonical_lyrics(text, file_mode=False):
    """Guarantee lyrics end with NO blank / whitespace-only lines.

    - Leading blank lines are removed.
    - Every line is right-trimmed (no trailing spaces).
    - Trailing blank / whitespace-only lines are removed.
    - file_mode=True  (.lrc files): the text ends with exactly one POSIX
      newline and nothing after it.
    - file_mode=False (embedded LYRICS tag): the value ends with the last
      lyric line and has no trailing newline at all.

    Returns "" when the input is empty or only blank lines.
    """
    if not text:
        return ""
    lines = [
        ln.rstrip()
        for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    body = "\n".join(lines)
    return (body + "\n") if file_mode else body


def _process_lyrics_for_audio(audio_path, cfg):
    af = AudioFile(audio_path)

    if af.audio is None:
        return ("fail", 0, 0, f"load: {af.error}")

    modified = False
    original_size = os.path.getsize(audio_path)

    lrc_path = _lrc_for(audio_path)
    lrc_exists = os.path.exists(lrc_path)
    lyrics_format = cfg.get("lyrics_format", "EMBEDDED").upper()

    # Clean embedded lyrics.
    if cfg.get("optimize_embedded_lyrics", True):
        cur = af.get_lyrics()
        if cur:
            cleaned = _canonical_lyrics(format_lyrics_text(cur))
            if cleaned != cur:
                if af.set_lyrics(cleaned):
                    modified = True

    # Clean existing LRC file.
    if cfg.get("optimize_lrc", True) and lrc_exists:
        try:
            with open(lrc_path, "r", encoding="utf-8", errors="replace") as f:
                lrc_content = f.read()

            # Exactly one trailing POSIX newline; no trailing blank lines.
            final = _canonical_lyrics(format_lyrics_text(lrc_content),
                                      file_mode=True)

            if final != lrc_content:
                with open(lrc_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(final)
                modified = True

        except Exception as e:
            return ("fail", 0, 0, f"lrc clean: {e}")

    # Conversion between LRC and embedded lyrics.
    if lyrics_format == "EMBEDDED" and lrc_exists:
        try:
            with open(lrc_path, "r", encoding="utf-8", errors="replace") as f:
                lrc_content = f.read()
        except Exception as e:
            return ("fail", 0, 0, f"lrc read: {e}")

        # Canonicalized even when optimize_lrc is off, so embedded lyrics
        # never carry trailing blank lines.
        cleaned = _canonical_lyrics(
            format_lyrics_text(lrc_content)
            if cfg.get("optimize_lrc", True)
            else lrc_content)

        if af.set_lyrics(cleaned):
            try:
                os.remove(lrc_path)
                modified = True
            except OSError as e:
                return ("fail", 0, 0, f"lrc delete: {e}")
        else:
            return ("fail", 0, 0, f"embed lyrics: {af.error}")

    elif lyrics_format == "LRC":
        cur = af.get_lyrics()
        if cur:
            # Exactly one trailing POSIX newline; no blank tail - even when
            # optimize_lrc is off.
            final = _canonical_lyrics(
                format_lyrics_text(cur)
                if cfg.get("optimize_lrc", True)
                else cur,
                file_mode=True)

            try:
                with open(lrc_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(final)

                af.delete_lyrics()
                modified = True

            except Exception as e:
                return ("fail", 0, 0, f"lrc write: {e}")

    notes = []

    # INSTRUMENTAL=1 with lyrics present is contradictory: flip it to 0.
    inst = af.get_tag("INSTRUMENTAL")
    if inst is not None and str(inst).strip() == "1":
        embedded_now = bool(af.get_lyrics() and str(af.get_lyrics()).strip())
        lrc_now = os.path.exists(lrc_path)

        if embedded_now or lrc_now:
            if af.set_tag("INSTRUMENTAL", "0"):
                modified = True
                notes.append("instrumental cleared")

    final_size = os.path.getsize(audio_path)
    b_rem, b_add = _diff_bytes(original_size, final_size)

    if modified:
        notes.append("lyrics processed")
        return ("modified", b_rem, b_add, "; ".join(notes))

    return ("unchanged", 0, 0, "no changes")


def _normalize_album_media_source(args):
    album_dir, default_source = args

    try:
        files = sorted(f for f in os.listdir(album_dir) if is_audio_file(f))

        if not files:
            return (album_dir, "skipped", 0, 0, "no audio files")

        entries = []
        media_values = []
        source_values = []

        for fn in files:
            path = os.path.join(album_dir, fn)
            af = AudioFile(path)

            if af.audio is None:
                return (
                    album_dir,
                    "failed",
                    0,
                    0,
                    f"cannot read {fn}: {af.error}",
                )

            media_val = af.get_tag("MEDIA")
            source_val = af.get_tag("SOURCE")

            media_clean = str(media_val).strip() if media_val is not None else ""
            source_clean = str(source_val).strip() if source_val is not None else ""

            if media_clean:
                media_values.append(media_clean)

            if source_clean:
                source_values.append(source_clean)

            entries.append((path, af, source_clean))

        media_summary = _summarize_values(media_values)
        digital = media_summary == "Digital Media"

        modified_files = 0
        bytes_removed = 0
        bytes_added = 0

        if digital:
            clean_sources = _clean_set(source_values)

            if len(clean_sources) == 1:
                fill_source = next(iter(clean_sources))
            elif clean_sources:
                fill_source = sorted(clean_sources)[0]
            else:
                fill_source = default_source or DEFAULT_DIGITAL_SOURCE

            for path, af, source_clean in entries:
                if not source_clean:
                    original_size = os.path.getsize(path)

                    if not af.set_tag("SOURCE", fill_source):
                        return (
                            album_dir,
                            "failed",
                            0,
                            0,
                            f"failed writing SOURCE in {os.path.basename(path)}: {af.error}",
                        )

                    final_size = os.path.getsize(path)
                    b_rem, b_add = _diff_bytes(original_size, final_size)

                    modified_files += 1
                    bytes_removed += b_rem
                    bytes_added += b_add

        else:
            for path, af, source_clean in entries:
                if source_clean:
                    original_size = os.path.getsize(path)

                    if not af.delete_tag("SOURCE"):
                        return (
                            album_dir,
                            "failed",
                            0,
                            0,
                            f"failed removing SOURCE in {os.path.basename(path)}: {af.error}",
                        )

                    final_size = os.path.getsize(path)
                    b_rem, b_add = _diff_bytes(original_size, final_size)

                    modified_files += 1
                    bytes_removed += b_rem
                    bytes_added += b_add

        if modified_files:
            return (
                album_dir,
                "modified",
                bytes_removed,
                bytes_added,
                f"{modified_files} file(s) normalized",
            )

        return (album_dir, "unchanged", 0, 0, "already correct")

    except Exception as e:
        return (album_dir, "failed", 0, 0, str(e))


def _normalize_media_source_library(config, stats):
    """
    Album-level MEDIA/SOURCE enforcement:
    - Digital Media albums must have SOURCE populated.
    - Non-Digital Media albums must not have SOURCE.
    """
    if not config.get("normalize_media_source", True):
        return stats

    folder = config["music_folder"]
    default_source = config.get("digital_media_source_value", DEFAULT_DIGITAL_SOURCE)

    if not os.path.isdir(folder):
        return stats

    albums = _find_albums(folder)

    if config.get("targets"):
        target_files = _collect_targets(config["targets"], AUDIO_EXTS)
        albums = sorted({os.path.dirname(f) for f in target_files})

    if not albums:
        return stats

    counts = {"ok": 0, "skip": 0, "fail": 0}
    workers = min(16, os.cpu_count() or 1, len(albums))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_normalize_album_media_source, (a, default_source)): a
            for a in albums
        }

        pbar = _make_pbar(len(futures), "MEDIA/SOURCE", unit="album")

        for fut in as_completed(futures):
            album = futures[fut]

            try:
                path, status, b_rem, b_add, info = fut.result()
            except Exception as e:
                stats["total_scanned"] += 1
                stats["error_count"] += 1
                stats["errors"].append((album, str(e)))
                _pbar_update(pbar, counts, kind="fail")
                continue

            if status in ("unchanged", "skipped"):
                stats["skipped_count"] += 1
                log_file_result(album, "skip", info=info or "unchanged")
                _pbar_skip(pbar, counts)
                continue

            stats["total_scanned"] += 1

            if status == "modified":
                stats["modified_count"] += 1
                stats["total_bytes_removed"] += b_rem
                stats["total_bytes_added"] += b_add
                log_file_result(album, "ok", b_rem, b_add)
                _pbar_update(pbar, counts, kind="ok")
            else:
                stats["error_count"] += 1
                stats["errors"].append((path, info))
                log_file_result(album, "fail", info=info)
                _pbar_update(pbar, counts, kind="fail")

        if pbar:
            pbar.close()

    return stats


def run_format_lyrics(config):
    folder = config["music_folder"]
    stats = new_stats()

    print_header("Lyrics Formatter + MEDIA/SOURCE Normalizer")
    log(f"folder: {folder}")
    log(
        f"LRC={config.get('optimize_lrc', True)} · "
        f"embedded={config.get('optimize_embedded_lyrics', True)} · "
        f"format={config.get('lyrics_format', 'EMBEDDED').upper()} · "
        f"media/source={config.get('normalize_media_source', True)} · "
        f"src fallback={config.get('digital_media_source_value', DEFAULT_DIGITAL_SOURCE)} · "
        f"INST auto-fix=on"
    )

    if not os.path.isdir(folder):
        log(c(f"ERROR: folder does not exist: {folder}", Color.RED))
        return stats

    files = _collect_targets(config.get("targets"), AUDIO_EXTS)
    if not files:
        files = sorted(_walk_files(folder, AUDIO_EXTS))

    if files:
        threads = min(64, (os.cpu_count() or 1) * 3)
        counts = {"ok": 0, "skip": 0, "fail": 0}

        with ThreadPoolExecutor(max_workers=threads) as ex:
            futures = {ex.submit(_process_lyrics_for_audio, p, config): p for p in files}
            pbar = _make_pbar(len(futures), "Lyrics")

            for fut in as_completed(futures):
                p = futures[fut]

                try:
                    status, b_rem, b_add, info = fut.result()
                except Exception as e:
                    stats["total_scanned"] += 1
                    stats["error_count"] += 1
                    stats["errors"].append((p, str(e)))
                    _pbar_update(pbar, counts, kind="fail")
                    continue

                if status == "unchanged":
                    stats["skipped_count"] += 1
                    log_file_result(p, "skip", info="unchanged")
                    _pbar_skip(pbar, counts)
                    continue

                stats["total_scanned"] += 1

                if status == "modified":
                    stats["modified_count"] += 1
                    stats["total_bytes_removed"] += b_rem
                    stats["total_bytes_added"] += b_add
                    log_file_result(p, "ok", b_rem, b_add)
                    _pbar_update(pbar, counts, kind="ok")
                else:
                    stats["error_count"] += 1
                    stats["errors"].append((p, info))
                    log_file_result(p, "fail", info=info)
                    _pbar_update(pbar, counts, kind="fail")

            if pbar:
                pbar.close()
    else:
        log("No audio files found for lyrics processing.")

    # Album-level MEDIA/SOURCE enforcement.
    _normalize_media_source_library(config, stats)

    return stats

