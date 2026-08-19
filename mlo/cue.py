"""CUE sheet formatter."""
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _walk_files, _diff_bytes,
    _collect_targets,
)
from .ui import print_header, log, log_file_result

def _process_cue_file(args):
    filename, keep_empty_lines, keep_other_lines = args
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
            with open(filename, "r", encoding="utf-8") as f:
                original_content = f.read()
        except UnicodeDecodeError:
            with open(filename, "r", encoding="latin-1") as f:
                original_content = f.read()

        original_content = original_content.replace("\r\n", "\n").replace("\r", "\n")
        lines = original_content.split("\n")

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

            elif upper.startswith("FILE"):
                m = re.search(r'"([^"]*)"', stripped)
                name = m.group(1) if m else stripped
                formatted.append(f'FILE "{name}" WAVE')

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
                if keep_other_lines:
                    formatted.append(stripped)

        if discid_line:
            formatted.insert(0, discid_line)

        new_content = "\n".join(formatted)

        while "\n\n\n" in new_content:
            new_content = new_content.replace("\n\n\n", "\n\n")

        # Guarantee no trailing blank / whitespace-only lines: strip all
        # trailing whitespace and newlines, then end with exactly one POSIX
        # newline (empty cue -> empty file).
        body = new_content.rstrip()
        new_content = (body + "\n") if body else ""

        if new_content == original_content:
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
    stats = new_stats()

    print_header("CUE Formatter")
    log(
        f"keep empty={'on' if keep_empty else 'off'} · "
        f"keep other={'on' if keep_other else 'off'}"
    )
    log(f"target: {target}")

    # First pass: deterministically rename multi-CD cues to CD-N.cue
    # (based on their FILE entries), then re-collect.
    cues = _collect_targets(config.get("targets"), (".cue",))
    if not cues:
        cues = sorted(_walk_files(target, (".cue",)))

    from .discs import rename_cues_for_discs
    renamed_any = False
    for album_dir in sorted({os.path.dirname(c) for c in cues}):
        for old, new in rename_cues_for_discs(album_dir):
            renamed_any = True
            log(f"cue renamed: {old} -> {new}")
    if renamed_any:
        cues = _collect_targets(config.get("targets"), (".cue",))
        if not cues:
            cues = sorted(_walk_files(target, (".cue",)))

    if not cues:
        log("No .cue files found.")
        return stats

    threads = min(64, (os.cpu_count() or 4) * 4)
    counts = {"ok": 0, "skip": 0, "fail": 0}

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = {
            ex.submit(_process_cue_file, (f, keep_empty, keep_other)): f
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

