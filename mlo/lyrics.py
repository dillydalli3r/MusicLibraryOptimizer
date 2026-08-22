"""Lyrics formatting, LRC/embedded conversion and MEDIA/SOURCE normalization."""
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .audio import AudioFile
from .config import should_write_audio_tag
from .paths import AUDIO_EXTS, DEFAULT_DIGITAL_SOURCE
from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _diff_bytes,
    _walk_files, is_audio_file, _find_albums, _clean_set, _summarize_values,
    _collect_targets, worker_count,
)
from .ui import print_header, log, c, Color, log_file_result

TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:\.(\d+))?\]")
WORD_TS_RE = re.compile(r"<(\d{1,2}):(\d{1,2})(?:\.(\d+))?>")


# Remove a SPACE (not a newline) directly after a timestamp. Using \s+ here
# would also consume the newline of a timestamp-only line, gluing
# "[00:00.00]" onto the following line as "[00:00.00][00:45.53]..." which
# ESLyrics on foobar2000 cannot parse.
SPACE_AFTER_TS_RE = re.compile(r"(\[\d{2}:\d{2}\.\d{2,3}\])[ \t]+")
# Enhanced LRC: space after word-level <mm:ss.xx> timestamps.
WORD_SPACE_AFTER_TS_RE = re.compile(r"(<\d{2}:\d{2}\.\d{2,3}>)[ \t]+")



LRC_META_RE = re.compile(
    r"^\s*\[(?:ar|ti|al|by|au|la|offset|length|re|ve):.*\]\s*$",
    re.IGNORECASE,
)


# A line carrying two or more timestamps. ESLyrics on foobar2000 cannot
# parse "[a]text[b]more" on one line (it shows a duplicated line), and the
# old space-after-timestamp bug glued whole lines together exactly like
# this. Split every timestamp boundary onto its own line.
_TS_TOKEN_RE = re.compile(r"\[\d{1,2}:\d{2}(?:\.\d+)?\]")


def _split_merged_ts(line):
    """Split a timestamp-run line into one line per timestamp.

    '[00:00.00][00:45.53]Stretching, filing[00:46.86]Against her skin'
      -> ['[00:00.00]', '[00:45.53]Stretching, filing',
          '[00:46.86]Against her skin']
    Only lines that START with a timestamp are considered.
    """
    if not line.startswith("["):
        return [line]
    matches = list(_TS_TOKEN_RE.finditer(line))
    if len(matches) < 2:
        return [line]
    out = []
    for i, m in enumerate(matches):
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(line)
        out.append(line[m.start():m.end()] + line[m.end():next_start])
    return out


def _part_stamp(part):
    """The leading timestamp of a _split_merged_ts part, if any."""
    m = _TS_TOKEN_RE.match(part)
    return m.group(0) if m else None


def _stamp_only(part):
    """True when a _split_merged_ts part is a bare timestamp that labels
    no text of its own."""
    m = _TS_TOKEN_RE.match(part)
    return m is not None and not part[m.end():].strip()


def _reformat_ts(m, precision=2):
    """Reformat a [mm:ss.xxx] timestamp to the requested precision,
    carrying correctly: [01:59.999] at precision 2 becomes [02:00.00]."""
    mins = int(m.group(1))
    secs = int(m.group(2))
    ms = m.group(3)

    if ms is None:
        ms_ms = 0
    else:
        try:
            ms_ms = int(ms[:3].ljust(3, "0")[:3])
        except ValueError:
            ms_ms = 0

    total_ms = (mins * 60 + secs) * 1000 + ms_ms
    unit_ms = 10 ** (3 - precision)
    # Round-half-up in integer milliseconds (Decimal quantize is a no-op
    # for positive exponents when built from an int).
    total_ms = ((total_ms + unit_ms // 2) // unit_ms) * unit_ms

    mm, rem = divmod(total_ms, 60000)
    ss, cc = divmod(rem, 1000)
    return f"[{mm:02d}:{ss:02d}.{cc // unit_ms:0{precision}d}]"


def _reformat_word_ts(m, precision=2):
    """Reformat a <mm:ss.xxx> word timestamp (Enhanced LRC)."""
    mins = int(m.group(1))
    secs = int(m.group(2))
    ms = m.group(3)
    if ms is None:
        ms_ms = 0
    else:
        try:
            ms_ms = int(ms[:3].ljust(3, "0")[:3])
        except ValueError:
            ms_ms = 0
    total_ms = (mins * 60 + secs) * 1000 + ms_ms
    unit_ms = 10 ** (3 - precision)
    total_ms = ((total_ms + unit_ms // 2) // unit_ms) * unit_ms
    mm, rem = divmod(total_ms, 60000)
    ss, cc = divmod(rem, 1000)
    return f"<{mm:02d}:{ss:02d}.{cc // unit_ms:0{precision}d}>"


def format_lyrics_text(text, precision=2, strip_metadata=True,
                       collapse_blank_lines=True,
                       lrc_enhanced_enabled=True,
                       lrc_enhanced_word_sync=True,
                       lrc_extended_enabled=True,
                       lrc_add_zero_timestamp=False,
                       lrc_zero_timestamp_blank=False,
                       cfg=None):
    """
    Cleans lyrics:
    - POSIX newlines
    - normalized timestamps ([mm:ss.xx] and Enhanced <mm:ss.xx>)
    - no space directly after timestamps
    - one line per timestamp: stacked timestamps are split up (unless Extended)
    - a [00:00.00] stacked in front of other stamps is dropped
    - timestamp-only lines lend their stamps to the next untimed line
    - no LRC metadata lines (unless Enhanced word-sync lines)
    - no duplicate blank lines

    The result is idempotent: cleaning already-clean lyrics is a no-op.
    lrc_enhanced_* and lrc_extended_enabled gate Enhanced/Extended features;
    cfg dict overrides when supplied.
    """
    if not text:
        return text
    # cfg overrides when supplied (used by grader + _format_for_storage)
    if cfg is not None:
        lrc_enhanced_enabled = cfg.get("lrc_enhanced_enabled", lrc_enhanced_enabled)
        lrc_enhanced_word_sync = cfg.get("lrc_enhanced_word_sync", lrc_enhanced_word_sync)
        lrc_extended_enabled = cfg.get("lrc_extended_enabled", lrc_extended_enabled)
        lrc_add_zero_timestamp = cfg.get("lrc_add_zero_timestamp", lrc_add_zero_timestamp)
        lrc_zero_timestamp_blank = cfg.get("lrc_zero_timestamp_blank", lrc_zero_timestamp_blank)
        # precision/strip/collapse may also be in cfg when called via grader
        try:
            precision = int(cfg.get("lrc_timestamp_precision", precision))
        except Exception:
            pass
        strip_metadata = cfg.get("lrc_strip_metadata", strip_metadata)
        collapse_blank_lines = cfg.get("lrc_collapse_blank_lines", collapse_blank_lines)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    precision = 3 if int(precision) == 3 else 2
    text = TIMESTAMP_RE.sub(
        lambda match: _reformat_ts(match, precision), text
    )
    if lrc_enhanced_enabled and lrc_enhanced_word_sync:
        text = WORD_TS_RE.sub(
            lambda m: _reformat_word_ts(m, precision), text
        )
        text = WORD_SPACE_AFTER_TS_RE.sub(r"\1", text)
    text = SPACE_AFTER_TS_RE.sub(r"\1", text)

    zero_ts = f"[00:00.{'0' * precision}]"
    lines = []
    pending_stamps = []

    for ln in text.split("\n"):
        s = ln.strip()

        if not s:
            lines.append("")
            pending_stamps = []
            continue

        if strip_metadata and LRC_META_RE.match(s):
            # Enhanced lines with word timestamps are not metadata
            if not (lrc_enhanced_enabled and WORD_TS_RE.search(s)):
                continue

        # Split merged "[a][b]text" lines — respect Extended flag
        if lrc_extended_enabled:
            parts = [s]
        else:
            parts = _split_merged_ts(s)

        # A [00:00.00] stacked directly in front of other timestamps is
        # a start-of-file marker that labels no text of its own — unless the
        # compatibility zero-timestamp option is enabled (then it is intentional).
        if not lrc_add_zero_timestamp:
            while (len(parts) > 1 and _stamp_only(parts[0])
                   and _part_stamp(parts[0]) == zero_ts):
                parts = parts[1:]

        # Timestamp-only line: hold the stamps for the next untimed
        # text line (dropped for good at a blank line, at EOF, or when
        # the next line carries timestamps of its own).
        if parts and all(_stamp_only(p) for p in parts):
            pending_stamps.extend(_part_stamp(p) for p in parts)
            continue

        if pending_stamps and not _TS_TOKEN_RE.search(s):
            # Untimed text right after stray stamps: each stamp labels
            # that text as a line of its own.
            for ts in pending_stamps:
                lines.append(f"{ts}{s}")
            pending_stamps = []
            continue

        # Whatever this line is, it is timed: stray stamps die here.
        pending_stamps = []

        # Stamps stacked in front of a text part each label that text
        # as a line of their own; a trailing run labels nothing and is
        # dropped.
        stacked = []
        for part in parts:
            if _stamp_only(part):
                stacked.append(_part_stamp(part))
                continue
            if stacked:
                m = _TS_TOKEN_RE.match(part)
                body = part[m.end():].rstrip() if m else part.rstrip()
                for ts in stacked:
                    lines.append(f"{ts}{body}")
                stacked = []
            lines.append(part.rstrip())

    cleaned = lines
    if collapse_blank_lines:
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

    # Compatibility: ensure first lyric line carries [00:00.00] when enabled.
    # When lrc_add_zero_timestamp is True, the very first non-blank lyric line
    # must start with the zero timestamp. Two modes:
    #  - blank=False (default, duplicate): insert "[00:00.00]<first text>" duplicating
    #    the first lyric's text at 0 and at its original time (idempotent).
    #  - blank=True: insert a bare "[00:00.00]" blank line at the very start
    #    (no text), leaving the original first line untouched.
    # Detection respects the current precision and is idempotent. Target filtering
    # (LRC/EMBEDDED/BOTH) is handled by the caller via cfg overrides.
    if lrc_add_zero_timestamp and cleaned:
        # Find first non-blank, non-metadata lyric line
        first_idx = None
        for idx, ln in enumerate(cleaned):
            s = ln.strip()
            if not s:
                continue
            if strip_metadata and LRC_META_RE.match(s):
                if lrc_enhanced_enabled and WORD_TS_RE.search(s):
                    pass
                else:
                    continue
            first_idx = idx
            break
        if first_idx is not None:
            first_line = cleaned[first_idx]
            if lrc_zero_timestamp_blank:
                # Blank mode: ensure a bare zero line exists at first_idx
                if first_line.strip() != zero_ts:
                    cleaned.insert(first_idx, zero_ts)
            else:
                if not first_line.startswith(zero_ts):
                    # Extract display text without leading line timestamps
                    text_part = first_line
                    # Strip all leading [mm:ss.xx] blocks
                    while True:
                        m = TIMESTAMP_RE.match(text_part)
                        if m:
                            text_part = text_part[m.end():].lstrip()
                        else:
                            break
                    # If the first line was timestamp-only or text extraction left
                    # it empty, look ahead for the next lyric text
                    if not text_part:
                        for nxt in range(first_idx + 1, len(cleaned)):
                            nxt_s = cleaned[nxt].strip()
                            if not nxt_s:
                                continue
                            if strip_metadata and LRC_META_RE.match(nxt_s):
                                if lrc_enhanced_enabled and WORD_TS_RE.search(nxt_s):
                                    pass
                                else:
                                    continue
                            nxt_text = cleaned[nxt]
                            while True:
                                m2 = TIMESTAMP_RE.match(nxt_text)
                                if m2:
                                    nxt_text = nxt_text[m2.end():].lstrip()
                                else:
                                    break
                            if nxt_text:
                                text_part = nxt_text
                                break
                        # Still empty? Use empty (will produce bare zero line)
                    # Build zero line
                    zero_line = f"{zero_ts}{text_part}" if text_part else zero_ts
                    # If first line already has a line timestamp, insert new zero line
                    # before it (keeping original). If it was untimed, replace it
                    # to avoid duplicating plain text.
                    if TIMESTAMP_RE.match(first_line):
                        cleaned.insert(first_idx, zero_line)
                    else:
                        cleaned[first_idx] = zero_line

    return "\n".join(cleaned)


def _lrc_for(audio_path):
    return os.path.splitext(audio_path)[0] + ".lrc"


def _canonical_lyrics(text, append_final_newline=False):
    """Canonicalize lyrics for storage.

    - CRLF -> LF.
    - Leading and trailing blank / whitespace-only lines are removed.
    - Every line is right-trimmed (no trailing spaces).
    - The result has NO trailing newline at all - no byte is wasted on a
      trailing newline, and there is never a blank last line.

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
    result = "\n".join(lines)
    if result and append_final_newline:
        result += "\n"
    return result


def _zero_target_allows(cfg, is_for_lrc: bool) -> bool:
    """Whether the zero-timestamp feature should apply for LRC file vs embedded tag.

    cfg lrc_zero_timestamp_target: EMBEDDED, LRC, or BOTH (default BOTH).
    is_for_lrc True = .lrc sidecar, False = embedded tag.
    """
    try:
        target = str(cfg.get("lrc_zero_timestamp_target", "BOTH")).upper()
    except Exception:
        target = "BOTH"
    if target == "LRC":
        return is_for_lrc
    if target == "EMBEDDED":
        return not is_for_lrc
    return True  # BOTH or unknown


def _format_for_storage(text, cfg, optimize=True, is_for_lrc=False):
    """Format lyrics using the persisted exact-output choices.

    is_for_lrc distinguishes .lrc sidecar vs embedded tag for the
    zero-timestamp target filter (lrc_zero_timestamp_target) and
    lrc_zero_timestamp_blank mode.
    """
    source = text
    if optimize:
        # Gate zero timestamp by target
        eff_zero = bool(cfg.get("lrc_add_zero_timestamp", False)) and _zero_target_allows(cfg, is_for_lrc)
        # Build a cfg view with effective zero flag so format_lyrics_text sees the filtered value
        cfg_view = dict(cfg)
        cfg_view["lrc_add_zero_timestamp"] = eff_zero
        source = format_lyrics_text(
            text,
            precision=cfg.get("lrc_timestamp_precision", 2),
            strip_metadata=cfg.get("lrc_strip_metadata", True),
            collapse_blank_lines=cfg.get("lrc_collapse_blank_lines", True),
            lrc_enhanced_enabled=cfg.get("lrc_enhanced_enabled", True),
            lrc_enhanced_word_sync=cfg.get("lrc_enhanced_word_sync", True),
            lrc_extended_enabled=cfg.get("lrc_extended_enabled", True),
            lrc_add_zero_timestamp=eff_zero,
            lrc_zero_timestamp_blank=cfg.get("lrc_zero_timestamp_blank", False),
            cfg=cfg_view,
        )
    return _canonical_lyrics(
        source,
        append_final_newline=cfg.get("append_final_newline", False),
    )


def _process_lyrics_for_audio(audio_path, cfg):
    af = AudioFile(audio_path)

    if af.audio is None:
        return ("fail", 0, 0, f"load: {af.error}")

    modified = False
    original_size = os.path.getsize(audio_path)

    lrc_path = _lrc_for(audio_path)
    lrc_exists = os.path.exists(lrc_path)
    lyrics_format = cfg.get("lyrics_format", "EMBEDDED").upper()
    force = cfg.get("force_lyrics", False)

    # set_lyrics / delete_lyrics mutate the in-memory tag even when the
    # save fails; remember to re-open the file from disk before the
    # INSTRUMENTAL decision below reflects anything but persisted state.
    lyrics_touched = False

    # Clean embedded lyrics (no trailing newline / blank lines).
    can_write_lyrics = should_write_audio_tag(cfg, "LYRICS", filepath=audio_path)
    can_write_instr = should_write_audio_tag(cfg, "INSTRUMENTAL", filepath=audio_path)
    if (force or cfg.get("optimize_embedded_lyrics", True)) and can_write_lyrics:
        cur = af.get_lyrics()
        if cur:
            cleaned = _format_for_storage(cur, cfg, optimize=True, is_for_lrc=False)
            if cleaned != cur:
                lyrics_touched = True
                if af.set_lyrics(cleaned):
                    modified = True

    # Clean existing LRC file (no trailing newline / blank lines).
    if lrc_exists and (force or cfg.get("optimize_lrc", True)):
        try:
            with open(lrc_path, "r", encoding="utf-8", errors="replace") as f:
                lrc_content = f.read()

            final = _format_for_storage(
                lrc_content, cfg, optimize=cfg.get("optimize_lrc", True), is_for_lrc=True
            )

            if final != lrc_content:
                with open(lrc_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(final)
                modified = True

        except Exception as e:
            return ("fail", 0, 0, f"lrc clean: {e}")

    # Post-cleaning state used by the conversion step below. The
    # optimize_* flags gate in-place cleaning only; whatever a
    # conversion writes is always canonical, so the graded format
    # check passes afterwards.
    embedded_raw = af.get_lyrics()
    embedded_canonical = (
        _format_for_storage(embedded_raw, cfg, optimize=True, is_for_lrc=False)
        if embedded_raw and str(embedded_raw).strip() else None
    )

    lrc_raw = None
    if lrc_exists:
        try:
            with open(lrc_path, "r", encoding="utf-8", errors="replace") as f:
                lrc_raw = f.read()
        except Exception as e:
            return ("fail", 0, 0, f"lrc read: {e}")

        if not lrc_raw.strip() and lyrics_format == "EMBEDDED":
            # Empty sidecar with lyrics living in the tag: remove the
            # stray file instead of embedding nothing.
            try:
                os.remove(lrc_path)
                lrc_exists = False
                modified = True
            except OSError:
                pass

    lrc_canonical = (
        _format_for_storage(lrc_raw, cfg, optimize=True, is_for_lrc=True)
        if lrc_raw and lrc_raw.strip() else None
    )

    # Conversion between LRC and embedded lyrics.
    # Respect per-filetype LYRICS toggle for any embedded tag writes and
    # lrc_zero_timestamp_target (EMBEDDED/LRC/BOTH) for zero insertion.
    if lyrics_format == "EMBEDDED" and lrc_canonical:
        if can_write_lyrics:
            # Destination is embedded tag — format lrc_raw for embedded target
            dest_for_embedded = _format_for_storage(lrc_raw, cfg, optimize=True, is_for_lrc=False)
            if embedded_canonical != dest_for_embedded:
                # Embed first; only delete the sidecar once the lyrics are
                # safely inside the tag (a failed write must never destroy
                # the only copy).
                lyrics_touched = True
                if not af.set_lyrics(dest_for_embedded):
                    return ("fail", 0, 0, f"embed lyrics: {af.error}")
            try:
                os.remove(lrc_path)
                lrc_exists = False
                modified = True
            except OSError as e:
                return ("fail", 0, 0, f"lrc delete: {e}")
        else:
            # LYRICS disabled for this filetype — leave both as is
            pass

    elif lyrics_format == "LRC" and embedded_canonical:
        # Destination is .lrc sidecar — format embedded_raw for LRC target
        dest_for_lrc = _format_for_storage(embedded_raw, cfg, optimize=True, is_for_lrc=True)
        # .lrc file write is always allowed (sidecar), but embedded delete is gated
        try:
            with open(lrc_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(dest_for_lrc)
        except Exception as e:
            return ("fail", 0, 0, f"lrc write: {e}")
        if can_write_lyrics:
            lyrics_touched = True
            if not af.delete_lyrics():
                return ("fail", 0, 0, f"delete embedded lyrics: {af.error}")
        lrc_exists = True
        modified = True

    elif lyrics_format == "BOTH":
        # Keep lyrics in both places, reconciled to one canonical text
        # (the embedded tag wins a disagreement - players read it).
        # Respect target: format for each destination separately.
        try:
            if lrc_canonical and not embedded_canonical:
                if can_write_lyrics:
                    dest_for_embedded = _format_for_storage(lrc_raw, cfg, optimize=True, is_for_lrc=False)
                    lyrics_touched = True
                    if not af.set_lyrics(dest_for_embedded):
                        return ("fail", 0, 0, f"embed lyrics: {af.error}")
                    modified = True

            elif embedded_canonical and lrc_canonical != embedded_canonical:
                # Write embedded's text formatted for LRC target
                dest_for_lrc = _format_for_storage(embedded_raw, cfg, optimize=True, is_for_lrc=True)
                with open(lrc_path, "w", encoding="utf-8",
                          newline="\n") as f:
                    f.write(dest_for_lrc)
                lrc_exists = True
                modified = True

            elif embedded_canonical and not lrc_canonical:
                dest_for_lrc = _format_for_storage(embedded_raw, cfg, optimize=True, is_for_lrc=True)
                with open(lrc_path, "w", encoding="utf-8",
                          newline="\n") as f:
                    f.write(dest_for_lrc)
                lrc_exists = True
                modified = True

        except Exception as e:
            return ("fail", 0, 0, f"both sync: {e}")

    notes = []

    # set_lyrics / delete_lyrics mutate the in-memory tag even when the
    # save fails, so re-read from disk before deciding on INSTRUMENTAL.
    if lyrics_touched:
        af = AudioFile(audio_path)
        if af.audio is None:
            return ("fail", 0, 0, f"reload: {af.error}")

    # INSTRUMENTAL=1 with lyrics present is contradictory: flip it to 0.
    inst = af.get_tag("INSTRUMENTAL")
    if (cfg.get("fix_instrumental_from_lyrics", True)
            and can_write_instr
            and inst is not None and str(inst).strip() == "1"):
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
    # args is (album_dir, default_source) or (album_dir, default_source, config)
    if len(args) == 3:
        album_dir, default_source, cfg = args
    else:
        album_dir, default_source = args
        cfg = None

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
            # Respect the new fill_empty_source toggle (default False = keep empty)
            if cfg is not None and not cfg.get("fill_empty_source", False):
                # Do not auto-fill empty SOURCE; keep it empty (per user request)
                # Still need to handle the case where SOURCE is present but inconsistent?
                # For now, just don't fill.
                pass
            else:
                clean_sources = _clean_set(source_values)

                if len(clean_sources) == 1:
                    fill_source = next(iter(clean_sources))
                elif clean_sources:
                    fill_source = sorted(clean_sources)[0]
                else:
                    fill_source = default_source or DEFAULT_DIGITAL_SOURCE

                for path, af, source_clean in entries:
                    if not source_clean:
                        # Respect per-filetype MEDIA_SOURCE toggle
                        if cfg is not None and not should_write_audio_tag(cfg, "SOURCE", filepath=path):
                            continue
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
                    if cfg is not None and not should_write_audio_tag(cfg, "SOURCE", filepath=path):
                        continue
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

    if config.get("targets") is not None:
        target_files = _collect_targets(config["targets"], AUDIO_EXTS)
        albums = sorted({os.path.dirname(f) for f in target_files})

    if not albums:
        return stats

    counts = {"ok": 0, "skip": 0, "fail": 0}
    workers = worker_count(config, default=16, maximum=16, items=len(albums))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_normalize_album_media_source, (a, default_source, config)): a
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

    targets = config.get("targets")
    files = _collect_targets(targets, AUDIO_EXTS)
    if targets is None:
        files = sorted(_walk_files(folder, AUDIO_EXTS))

    if files:
        threads = worker_count(
            config, default=(os.cpu_count() or 1) * 3,
            maximum=64, items=len(files)
        )
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

