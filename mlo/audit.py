"""Audio integrity auditing via the AudioAuditor CLI.

Wraps AudioAuditorCLI (https://github.com/Angel2mp3/AudioAuditor), a .NET
tool that detects fake lossless files (frequency cutoffs / upsampled
lossy sources), clipping, MQA encoding, fake stereo, excessive silence
and AI-generated audio. The CLI ships as a single self-contained exe and
is auto-downloaded into .dependencies like the encoder toolchain.

Files are fed to the CLI in batches via stdin (one path per line, its
documented bulk mode) and results are read back as one JSON array per
batch with `analyze --json`.

Outputs written to tags:
  AUDIT      REAL / FAKE - on every audited file. Files that already
             carry a REAL or FAKE verdict are skipped (force audit
             overrides this), like the ENCODER markers for optimization.
  LOG_GRADE  0-100 rip-log score (AudioAuditor/cambia) - written to the
             tracks of MEDIA=CD releases only, one score per disc, with
             logs/cues deterministically named CD-N.log / CD-N.cue
             first (see discs.py).
"""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .audio import AudioFile
from .paths import AUDIO_EXTS, DEPS_DIR
from .stats import (
    new_stats, _make_pbar, _pbar_update, _collect_targets, _walk_files,
    _diff_bytes, worker_count,
)
from .subproc import run_tool
from .tools import detect_all_tools
from .ui import print_header, log, c, Color

# Statuses reported by the CLI: Valid (real lossless), Fake (frequency
# cutoff / transcoded), Unknown (could not classify / decode errors),
# Corrupt, Optimized (MQA). Anything unknown-but-decoded is treated as
# a warning rather than a failure.
STATUS_REAL = "Valid"

# How many paths to pipe per CLI invocation. The CLI accepts up to 50k
# paths per run; smaller batches give the GUI a usable progress bar.
BATCH_SIZE = 250

# Map per-file boolean flags to issue labels for the summary.
FLAG_KEYS = (
    ("hasClipping", "clipping"),
    ("isMqa", "MQA"),
    ("isAiGenerated", "AI-generated"),
    ("isFakeStereo", "fake stereo"),
    ("hasExcessiveSilence", "excessive silence"),
    ("hasScaledClipping", "scaled clipping"),
)


# Detector toggles: config key -> CLI --no-* flag. Default on; a False
# setting appends the flag, disabling that detector. Silenced detectors
# produce no warning flags, so a "warn" verdict from them disappears.
DETECTOR_NO_FLAGS = {
    "audit_clipping": "--no-clipping",
    "audit_mqa": "--no-mqa",
    "audit_ai": "--no-ai",
    "audit_fake_stereo": "--no-fake-stereo",
    "audit_silence": "--no-silence",
    "audit_dynamic_range": "--no-dynamic-range",
    "audit_true_peak": "--no-true-peak",
    "audit_lufs": "--no-lufs",
    "audit_bpm": "--no-bpm",
}


def _audit_batch(cli, paths, config):
    """Run one AudioAuditorCLI analyze batch; returns parsed items."""
    cmd = [
        cli, "analyze", "--json",
        "--no-fun", "--no-tips", "--no-update-check", "--no-config",
    ]
    if config.get("audit_thorough", False):
        cmd.append("--thorough")
    else:
        cmd.append("--fast")

    cutoff = config.get("audit_cutoff_allow", 0)
    if cutoff:
        try:
            cmd += ["--cutoff-allow", str(int(cutoff))]
        except (ValueError, TypeError):
            pass

    for key, flag in DETECTOR_NO_FLAGS.items():
        if not config.get(key, True):
            cmd.append(flag)

    proc = run_tool(
        cmd,
        input="\n".join(paths) + "\n",
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=3600,
    )

    if not (proc.stdout or "").strip():
        err = (proc.stderr or "").strip()
        if "No supported audio files" in err:
            return []
        raise RuntimeError(f"AudioAuditorCLI failed (rc={proc.returncode}): "
                           f"{err[:200] or 'no output'}")

    try:
        items = json.loads(proc.stdout)
    except ValueError as e:
        raise RuntimeError(f"unparseable AudioAuditorCLI JSON output: {e}")

    if not isinstance(items, list):
        raise RuntimeError("unexpected AudioAuditorCLI output shape")
    return items


def _classify(item):
    """Return (severity, label): 'fail' | 'warn' | 'ok' and a reason."""
    status = str(item.get("status", "")).strip()
    err = str(item.get("errorMessage") or "").strip()

    if status == STATUS_REAL:
        flags = [label for key, label in FLAG_KEYS if item.get(key)]
        if flags:
            return "warn", ", ".join(flags)
        return "ok", ""
    if status == "Fake":
        cutoff = item.get("effectiveFrequency")
        detail = f"cutoff {cutoff} Hz" if cutoff else "spectral cutoff"
        return "fail", f"fake lossless ({detail})"
    if status == "Corrupt":
        return "fail", f"corrupt: {err or 'unreadable'}"
    if status == "Optimized":
        return "fail", "MQA (lossy 'optimized')"
    if status == "Unknown":
        if err:
            return "fail", f"unknown: {err}"
        return "warn", "unclassified"

    return "warn", f"status {status or '?'}"


def _audit_file_line(item):
    """Compact per-file console line with the key metrics."""
    parts = [
        f"{item.get('sampleRate', '?')} Hz",
        f"{item.get('bitsPerSample', '?')}-bit",
        f"{item.get('channels', '?')}ch",
        f"{item.get('actualBitrate', '?')} kbps",
    ]
    cutoff = item.get("effectiveFrequency")
    if cutoff:
        parts.append(f"cutoff {cutoff} Hz")
    rg = item.get("replayGain") if item.get("hasReplayGain") else None
    if rg is not None:
        parts.append(f"RG {rg} dB")
    return "  ".join(str(p) for p in parts)


def _audit_tag_value(severity, cli_status):
    """The AUDIT tag value for a file. Binary by design: REAL when the
    CLI confirms genuine lossless (status Valid), FAKE for everything
    else (fake lossless, corrupt, MQA, unclassifiable)."""
    return "REAL" if cli_status == "Valid" else "FAKE"


def _read_and_normalize_audit(path, write_tags=True):
    """Read the AUDIT verdict and fix legacy mixed-case values (Real -> REAL)
    in a single file open. Returns (verdict, changed)."""
    try:
        af = AudioFile(path)
        raw = str(af.get_tag("AUDIT") or "").strip()
        v = raw.upper()
        changed = False
        if write_tags and raw and v in ("REAL", "FAKE") and raw != v:
            changed = bool(af.set_tag("AUDIT", v))
        return (v if v in ("REAL", "FAKE") else None), changed
    except Exception:
        return None, False


def _write_audit_tag(path, value):
    """Write the AUDIT tag when it differs. Returns
    (changed: bool, b_rem: int, b_add: int, error: str | None)."""
    try:
        before = os.path.getsize(path)
    except OSError as e:
        return False, 0, 0, f"stat: {e}"

    try:
        af = AudioFile(path)
        if af.audio is None:
            return False, 0, 0, f"load: {af.error}"

        cur = af.get_tag("AUDIT")
        cur_clean = str(cur).strip() if cur is not None else ""
        if cur_clean.lower() == value.lower():
            return False, 0, 0, None

        if not af.set_tag("AUDIT", value):
            return False, 0, 0, f"write: {af.error}"

        after = os.path.getsize(path)
        b_rem, b_add = _diff_bytes(before, after)
        return True, b_rem, b_add, None
    except Exception as e:
        return False, 0, 0, str(e)


def run_audit_library(config):
    folder = config["music_folder"]
    thorough = config.get("audit_thorough", False)

    stats = new_stats()
    stats["is_grader"] = True
    stats["grade_dist"] = {"PASS": 0, "FAIL": 0}

    print_header("Audio Auditor (AudioAuditorCLI)")
    log(f"music folder: {folder} · thorough={thorough} · writes AUDIT tags")

    tools = detect_all_tools()
    aa = tools.get("audioauditor")
    if not aa:
        log(c("ERROR: Could not auto-detect AudioAuditorCLI in the "
              ".dependencies folder.", Color.RED))
        log(f"Expected a folder like: {os.path.join(DEPS_DIR, 'AudioAuditor v2.0.0')}")
        log("Use Dependencies (GUI sidebar → MANAGE) to download it.")
        return stats

    cli = aa["cli_exe"]
    log(f"cli: {cli} · v{aa['version']}")

    if not os.path.isdir(folder):
        log(c(f"ERROR: folder does not exist: {folder}", Color.RED))
        return stats

    targets = config.get("targets")
    files = _collect_targets(targets, AUDIO_EXTS)
    if targets is None:
        files = sorted(_walk_files(folder, AUDIO_EXTS))
    if not files:
        log("No audio files found.")
        return stats

    force = config.get("force_audit", False)
    verbose = config.get("grade_verbose", True)

    # CD rip checksum verification first (MEDIA=CD albums with checksums in
    # their .log). Checksums are authoritative: matching = REAL, mismatch =
    # FAKE. Files verified this way are excluded from the AudioAuditor pass.
    checksum_verified = {}
    ffmpeg_exe_for_cd = None
    if config.get("audit_verify_cd_checksums", True) and not force:
        _tools_ff = detect_all_tools()
        _ff = (_tools_ff.get("ffmpeg") or {}).get("ffmpeg_exe")
        if _ff:
            ffmpeg_exe_for_cd = _ff
        else:
            log(c("WARNING: ffmpeg not found - CD checksum verification "
                  "skipped (AudioAuditor only).", Color.YELLOW))
    if ffmpeg_exe_for_cd:
        from .discs import verify_album_checksums
        from concurrent.futures import as_completed
        by_album = {}
        for p in files:
            by_album.setdefault(os.path.dirname(p), []).append(p)
        cw = worker_count(config, default=4, maximum=8, items=len(by_album))
        with ThreadPoolExecutor(max_workers=cw) as ex:
            futures = {
                ex.submit(verify_album_checksums, ffmpeg_exe_for_cd, album,
                          paths, config): album
                for album, paths in by_album.items()
            }
            for fut in as_completed(futures):
                album = futures[fut]
                try:
                    res = fut.result() or {}
                except Exception:
                    continue
                for path, verdict in res.items():
                    if config.get("write_audit_tag", True):
                        _write_audit_tag(path, verdict)
                    checksum_verified[path] = verdict
        if checksum_verified:
            n_real = sum(1 for v in checksum_verified.values() if v == "REAL")
            n_fake = len(checksum_verified) - n_real
            log(f"CD checksums: verified {len(checksum_verified)} track(s) "
                f"against .log CRCs ({n_real} REAL, {n_fake} FAKE)")
            if n_fake:
                for p, v in sorted(checksum_verified.items()):
                    if v == "FAKE":
                        log(f"  {c('✕', Color.RED)} {os.path.basename(p)} "
                            f"{c('FAKE (CRC mismatch)', Color.RED)}")

    # Skip files that already carry a REAL/FAKE verdict (normalizing
    # legacy mixed-case values) unless the audit is forced.
    todo = files
    skipped = 0
    if not force:
        workers = worker_count(config, default=8, maximum=8, items=len(files))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(
                lambda path: _read_and_normalize_audit(
                    path, config.get("write_audit_tag", True)
                ),
                files,
            ))
        todo = []
        for path, (verdict, changed) in zip(files, results):
            if verdict is not None:
                skipped += 1
                if changed:
                    stats["modified_count"] += 1
            else:
                todo.append(path)
        # CD-checksum-verified files already carry a verdict.
        todo = [p for p in todo if p not in checksum_verified]
        if skipped:
            log(f"skipping {skipped} file(s) already carrying an AUDIT "
                f"verdict (force audit overrides)")

    log(f"auditing {len(todo)} file(s) · fast scan "
        f"{'off (--thorough)' if thorough else 'on'}")

    counts = {"ok": 0, "skip": 0, "fail": 0}
    status_counts = {"Real": 0, "Fake": 0, "Unknown": 0,
                     "Corrupt": 0, "Optimized": 0}
    issue_counts = {}
    flagged = []
    warned = 0
    pbar = _make_pbar(len(todo), "Auditing", unit="file")

    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        try:
            items = _audit_batch(cli, batch, config)
        except Exception as e:
            stats["error_count"] += len(batch)
            stats["errors"].append((f"batch {start // BATCH_SIZE + 1} "
                                    f"({len(batch)} files)", str(e)))
            log(c(f"Audit batch failed: {e}", Color.RED))
            _pbar_update(pbar, counts, kind="fail")
            continue

        # Files the CLI silently dropped (unsupported/renamed). Paths
        # are compared via realpath so 8.3 short names don't cause
        # phantom misses when the CLI echoes back the long form (or
        # vice versa).
        def canon(p):
            if not p:
                return ""
            try:
                return os.path.normcase(os.path.realpath(p))
            except OSError:
                return os.path.normcase(p)

        missing = {canon(p) for p in batch}
        for item in items:
            path = item.get("filePath") or ""
            missing.discard(canon(path))
            severity, reason = _classify(item)
            cli_status = str(item.get("status", "")).strip()

            stats["total_scanned"] += 1
            try:
                rel = os.path.relpath(path, folder) if path else item.get(
                    "fileName", "?")
            except ValueError:
                rel = os.path.basename(path) if path else item.get(
                    "fileName", "?")

            # CLI verdict drives the status counts; warnings (clipping
            # flags etc. on an otherwise Valid file) are tracked apart.
            skey = {"Valid": "Real", "Fake": "Fake", "Corrupt": "Corrupt",
                    "Optimized": "Optimized"}.get(cli_status, "Unknown")
            status_counts[skey] += 1

            # Persist the verdict into the file's AUDIT tag.
            tag_value = _audit_tag_value(severity, cli_status)
            if config.get("write_audit_tag", True):
                changed, b_rem, b_add, tag_err = _write_audit_tag(
                    path, tag_value)
            else:
                changed, b_rem, b_add, tag_err = False, 0, 0, None
            if tag_err:
                log(c(f"    [tag warn] {os.path.basename(rel)}: {tag_err}",
                      Color.YELLOW))
            elif changed:
                stats["modified_count"] += 1
                stats["total_bytes_removed"] += b_rem
                stats["total_bytes_added"] += b_add

            if severity == "ok":
                if verbose:
                    log(f"{c('✓', Color.GREEN)} {rel}")
            elif severity == "warn":
                warned += 1
                stats["skipped_count"] += 1
                issue_counts[reason] = issue_counts.get(reason, 0) + 1
                log(f"{c('!', Color.YELLOW)} {rel}  "
                    f"{c(reason, Color.YELLOW)}")
                if verbose:
                    log(f"    {_audit_file_line(item)}")
            else:
                stats["grade_dist"]["FAIL"] += 1
                stats["errors"].append((rel, reason))
                base_reason = reason.split(" (")[0]
                issue_counts[base_reason] = issue_counts.get(base_reason, 0) + 1
                flagged.append((rel, reason))
                log(f"{c('✕', Color.RED)} {rel}  {c(reason, Color.RED)}")
                log(f"    {_audit_file_line(item)}")

        # Files the CLI silently dropped (unsupported/renamed).
        for gone in missing:
            stats["total_scanned"] += 1
            stats["skipped_count"] += 1
            status_counts["Unknown"] += 1
            try:
                rel_gone = os.path.relpath(gone, folder)
            except ValueError:
                rel_gone = os.path.basename(gone)
            log(f"{c('–', Color.GREY)} {rel_gone} "
                f"{c('(no audit result)', Color.GREY)}")

        if pbar is not None:
            try:
                pbar.update(len(batch))
            except Exception:
                pass

    if pbar:
        pbar.close()

    # Rip-log grading for MEDIA=CD albums: rename logs/cues to CD-N and
    # write each disc's 0-100 cambia score to its tracks' LOG_GRADE.
    # Parallelized across albums - each disc scores in its own CLI process,
    # so thread workers scale instead of running one album at a time.
    album_dirs = sorted({os.path.dirname(p) for p in files})
    log_scores = {}
    log_notes = []
    from .discs import grade_album_logs
    from concurrent.futures import as_completed

    def _grade_one(album_dir):
        if not os.path.isdir(album_dir):
            return album_dir, {}, []
        scores, notes = grade_album_logs(
            cli, album_dir, force=force,
            write_tags=config.get("write_log_grade", True),
            log_fn=(lambda m: log(f"  {m}")) if verbose else None)
        return album_dir, scores, notes

    workers = worker_count(config, default=8, maximum=8, items=len(album_dirs))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_grade_one, d) for d in album_dirs]
        for fut in as_completed(futures):
            album_dir, scores, notes = fut.result()
            if scores:
                log_scores[album_dir] = scores
            log_notes.extend(f"{os.path.basename(album_dir)}: {n}" for n in notes)

    if log_scores:
        log("")
        log("Rip-log grades (LOG_GRADE):")
        for album_dir, scores in log_scores.items():
            parts = " · ".join(f"CD-{d} = {s}/100"
                               for d, s in sorted(scores.items()))
            log(f"  {os.path.basename(album_dir)}: {parts}")
    if log_notes:
        for n in log_notes[:20]:
            log(c(f"  [log] {n}", Color.YELLOW))
        if len(log_notes) > 20:
            log(f"  … and {len(log_notes) - 20} more.")

    stats["grade_dist"]["PASS"] = status_counts["Real"]
    stats["summary_pass"] = status_counts["Real"] - warned
    stats["summary_total"] = stats["total_scanned"]
    stats["issue_counts"] = issue_counts
    stats["audit_status_counts"] = status_counts
    stats["audit_warned"] = warned
    stats["audit_flagged"] = len(flagged)
    stats["audit_log_scores"] = {
        os.path.basename(d): s for d, s in log_scores.items()}

    log("")
    log("Audit summary: "
        + " · ".join(f"{k} {v}" for k, v in status_counts.items()))
    if skipped:
        log(f"  {skipped} file(s) already audited were skipped.")
    if warned:
        log(f"  {warned} clean file(s) carry warning flags "
            f"(clipping / MQA / silence / AI markers) - still REAL.")

    return stats
