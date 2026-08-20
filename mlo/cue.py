"""CUE sheet formatter."""
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _walk_files, _diff_bytes,
    _collect_targets, worker_count,
)
from .ui import print_header, log, log_file_result

def canonical_cue_text(content, keep_empty_lines, keep_other_lines,
                       file_type, append_final_newline):
    """Return the canonical (normalized) form of a cue sheet's text.

    Pure function with no side effects: LF line endings, DISCID hex
    normalization, quoted FILE lines with the configured type, TRACK/INDEX
    normalization, structural directives preserved, REM comments stripped
    (unless keep_other_lines), blank-line collapsing, and no trailing blank
    lines. ``append_final_newline`` optionally adds a single trailing LF.
    """
    file_type = str(file_type).upper()
    if file_type not in ("WAVE", "MP3"):
        file_type = "WAVE"

    original = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = original.split("\n")

    discid_line = None
    formatted = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if keep_empty_lines:
                formatted.append("")
            continue

        upper = stripped.upper()

        if upper.startswith("REM DISCID"):
            if discid_line is None:
                parts = stripped.split(None, 2)
                if len(parts) >= 3:
                    raw = parts[2].strip()
                    hex_code = re.sub(r"[^0-9A-Fa-f]", "", raw).upper()[:8]
                    discid_line = (
                        f"REM DISCID {hex_code}"
                        if hex_code
                        else f"REM DISCID {raw.upper()}"
                    )
                else:
                    discid_line = "REM DISCID"

        elif upper == "FILE" or upper.startswith("FILE "):
            m = re.search(r'"([^"]*)"', stripped)
            if m:
                name = m.group(1)
            else:
                parts = stripped.split(None, 2)
                if len(parts) >= 2:
                    name = parts[1].strip().strip("'\"")
                else:
                    formatted.append(stripped)
                    continue
            formatted.append(f'FILE "{name}" {file_type}')

        elif upper.startswith("TRACK"):
            parts = stripped.split(None, 2)
            if len(parts) >= 3:
                formatted.append(f"  TRACK {parts[1].zfill(2)} {parts[2].upper()}")
            else:
                formatted.append(f"  {stripped}")

        elif upper.startswith("INDEX"):
            parts = stripped.split(None, 2)
            if len(parts) >= 3:
                tp = parts[2].split(":")
                if len(tp) == 3:
                    try:
                        formatted.append(
                            f"    INDEX {parts[1].zfill(2)} "
                            f"{int(tp[0]):02d}:{int(tp[1]):02d}:{int(tp[2]):02d}"
                        )
                    except ValueError:
                        formatted.append(f"    {stripped}")
                else:
                    formatted.append(f"    {stripped}")
            else:
                formatted.append(f"    {stripped}")

        else:
            # Keep structural directives (PREGAP, POSTGAP, FLAGS,
            # PERFORMER, TITLE, CATALOG, ISRC, SONGWRITER, ...)
            # unconditionally — dropping them corrupts the sheet.
            # Only REM comment lines are stripped when keep_other_lines
            # is off.
            if not (upper.startswith("REM ") and not keep_other_lines):
                formatted.append(stripped)

    if discid_line:
        formatted.insert(0, discid_line)

    new_content = "\n".join(formatted)

    while "\n\n\n" in new_content:
        new_content = new_content.replace("\n\n\n", "\n\n")

    # No trailing blank / whitespace-only lines AND no trailing newline
    # byte at all (empty cue -> empty string).
    new_content = new_content.rstrip()
    if new_content and append_final_newline:
        new_content += "\n"

    return new_content


def _process_cue_file(args):
    filename, keep_empty_lines, keep_other_lines, file_type, append_final_newline = args
    tmp_path = None

    try:
        original_size = os.path.getsize(filename)

        # Safety: a real .cue is plain text. If the file contains NUL bytes
        # it is binary (e.g. an audio file that reached here by mistake) and
        # must never be rewritten/overwritten.
        with open(filename, "rb") as raw:
            head = raw.read(4096)
        if b"\x00" in head:
            return (filename, False, "binary file skipped (not a cue)", 0, 0)

        try:
            with open(filename, "r", encoding="utf-8-sig") as f:
                original_content = f.read()
        except UnicodeDecodeError:
            with open(filename, "r", encoding="latin-1") as f:
                original_content = f.read()

        # Keep the raw text for the "unchanged" comparison so CRLF-only
        # files still get normalized to LF.
        raw_content = original_content

        new_content = canonical_cue_text(
            original_content, keep_empty_lines, keep_other_lines,
            file_type, append_final_newline,
        )

        if new_content == raw_content:
            return (filename, False, None, 0, 0)

        fd, tmp_path = tempfile.mkstemp(
            prefix=".cue_tmp_",
            suffix=".cue",
            dir=os.path.dirname(filename),
        )

        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)

        os.replace(tmp_path, filename)
        tmp_path = None

        final_size = os.path.getsize(filename)
        b_rem, b_add = _diff_bytes(original_size, final_size)

        return (filename, True, None, b_rem, b_add)

    except Exception as e:
        return (filename, False, f"{type(e).__name__}: {e}", 0, 0)

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def run_format_cues(config):
    target = config["music_folder"]
    keep_empty = config.get("keep_empty_cue_lines", False)
    keep_other = config.get("keep_other_cue_lines", False)
    file_type = config.get("cue_file_type", "WAVE").upper()
    if file_type not in ("WAVE", "MP3"):
        file_type = "WAVE"
    append_final_newline = config.get("append_final_newline", False)
    stats = new_stats()

    print_header("CUE Formatter")
    log(
        f"keep empty={'on' if keep_empty else 'off'} · "
        f"keep other={'on' if keep_other else 'off'}"
    )
    log(f"target: {target}")

    # First pass: deterministically rename multi-CD cues to CD-N.cue
    # (based on their FILE entries), then re-collect.
    targets = config.get("targets")
    cues = _collect_targets(targets, (".cue",))
    if targets is None:
        cues = sorted(_walk_files(target, (".cue",)))

    from .discs import rename_cues_for_discs
    renamed_any = False
    for album_dir in sorted({os.path.dirname(c) for c in cues}):
        for old, new in rename_cues_for_discs(album_dir):
            renamed_any = True
            log(f"cue renamed: {old} -> {new}")
    if renamed_any:
        # Re-collect by walking each original album folder: explicit
        # targets may have pointed at a now-renamed .cue file.
        cues = []
        for album_dir in sorted({os.path.dirname(c) for c in cues}):
            if os.path.isdir(album_dir):
                cues.extend(
                    os.path.join(album_dir, f)
                    for f in sorted(os.listdir(album_dir))
                    if f.lower().endswith(".cue")
                )
        cues = sorted(set(cues))

    if not cues:
        log("No .cue files found.")
        return stats

    threads = worker_count(
        config, default=(os.cpu_count() or 4) * 4,
        maximum=64, items=len(cues)
    )
    counts = {"ok": 0, "skip": 0, "fail": 0}

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = {
            ex.submit(
                _process_cue_file,
                (f, keep_empty, keep_other, file_type, append_final_newline),
            ): f
            for f in cues
        }

        pbar = _make_pbar(len(futures), "CUEs")

        for fut in as_completed(futures):
            fn, ok, err, br, ba = fut.result()

            if err:
                stats["total_scanned"] += 1
                stats["error_count"] += 1
                stats["errors"].append((fn, err))
                log_file_result(fn, "fail", info=err)
                _pbar_update(pbar, counts, kind="fail")
                continue

            if not ok:
                stats["skipped_count"] += 1
                log_file_result(fn, "skip", info=err or "unchanged")
                _pbar_skip(pbar, counts)
                continue

            stats["total_scanned"] += 1
            stats["modified_count"] += 1
            stats["total_bytes_removed"] += br
            stats["total_bytes_added"] += ba
            log_file_result(fn, "ok", br, ba)
            _pbar_update(pbar, counts, kind="ok")

        if pbar:
            pbar.close()

    return stats

