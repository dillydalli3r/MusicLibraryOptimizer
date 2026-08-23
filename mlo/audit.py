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
from .config import should_write_audio_tag
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
# audit_scaled_clipping is filtered in Python (no CLI flag) so loud masters
# can hide just scaled clipping without losing normal clipping detection.
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


def verify_integrity(filepath, ffmpeg_exe=None, flac_exe=None):
    """Verify audio file integrity like foobar2000's Verify Integrity.

    For FLAC: runs `flac -t` (test) which checks frame CRCs and stream integrity.
    For all types: runs `ffmpeg -v error -i file -f null -` to catch decoding errors,
    truncated files, and sync errors (similar to foobar2000's decoder check).

    Returns (ok: bool, error: str | None). True when no errors detected.
    """
    ext = os.path.splitext(filepath)[1].lower()
    # Try flac -t for FLAC files (most thorough for FLAC)
    if ext == ".flac" and flac_exe and os.path.isfile(flac_exe):
        try:
            proc = run_tool([flac_exe, "-t", filepath],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", timeout=60)
            # flac -t returns 0 on success, non-zero on error; stderr contains details
            if proc.returncode == 0:
                # Also check ffmpeg as second opinion for FLAC (catches more)
                pass
            else:
                err = (proc.stderr or proc.stdout or "").strip().splitlines()
                err = err[-1] if err else f"flac -t rc={proc.returncode}"
                return False, err[:200]
        except subprocess.TimeoutExpired:
            return False, "flac -t timeout"
        except Exception as e:
            return False, str(e)[:200]

    # ffmpeg check for all audio types (including FLAC as second check)
    if ffmpeg_exe and os.path.isfile(ffmpeg_exe):
        try:
            proc = run_tool([ffmpeg_exe, "-v", "error", "-i", filepath, "-f", "null", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", timeout=60)
            err = (proc.stderr or "").strip()
            if proc.returncode != 0:
                return False, (err.splitlines()[0] if err else f"ffmpeg rc={proc.returncode}")[:200]
            if err:
                # Filter false positives like "error correction" / "error concealment" which are not decode errors
                low = err.lower()
                if "error" in low and "error correction" not in low and "error concealment" not in low and "error resilience" not in low:
                    return False, err.splitlines()[0][:200]
                # Also catch "invalid", "corrupt", "truncated" etc.
                if any(k in low for k in ("invalid", "corrupt", "truncated", "sync error", "crc mismatch")):
                    return False, err.splitlines()[0][:200]
            return True, None
        except subprocess.TimeoutExpired:
            return False, "ffmpeg timeout"
        except Exception as e:
            return False, str(e)[:200]

    # Fallback: try mutagen load to at least verify the file can be parsed
    try:
        af = AudioFile(filepath)
        if af.audio is None:
            return False, af.error or "unreadable"
        return True, None
    except Exception as e:
        return False, str(e)[:200]


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

    # AudioAuditorCLI 2.0.0 scan/analyze currently hangs for many files
    # (even a single 1-sec test flac times out after 60s with --json --fast).
    # Fall back to per-file `info` (which still works) when the batch times out.
    batch_timeout = int(config.get("audit_batch_timeout_s", 30) or 30)
    per_file_timeout = int(config.get("audit_per_file_timeout_s", 30) or 30)
    try:
        proc = run_tool(
            cmd,
            input="\n".join(paths) + "\n",
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=batch_timeout,
        )
    except subprocess.TimeoutExpired:
        # Fallback: use `info` per file (slow but reliable, and `info` still works for 2.0.0)
        log(c(f"AudioAuditor batch timed out after {batch_timeout}s, falling back to per-file info (2.0.0 scan hang)", Color.YELLOW))
        items = []
        for p in paths:
            try:
                proc2 = run_tool([cli, "info", p], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=per_file_timeout)
                if proc2.returncode == 0 and proc2.stdout:
                    # Parse the text output of `info` into a minimal JSON-like item
                    # info always succeeds and shows `Status: REAL/FAKE` — map to Valid/Fake
                    out = proc2.stdout
                    # Robust status parse: look for Status line
                    import re as _re
                    m = _re.search(r"Status:\s*(REAL|FAKE)", out, _re.IGNORECASE)
                    if m:
                        status = "Valid" if m.group(1).upper() == "REAL" else "Fake"
                    else:
                        status = "Unknown"
                    # Extract filePath from the info output or use the input path
                    items.append({"filePath": p, "fileName": os.path.basename(p), "status": status, "errorMessage": ""})
                else:
                    items.append({"filePath": p, "fileName": os.path.basename(p), "status": "Unknown", "errorMessage": (proc2.stderr or "")[:200]})
            except Exception as e:
                items.append({"filePath": p, "fileName": os.path.basename(p), "status": "Unknown", "errorMessage": str(e)[:200]})
        return items

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


def _read_and_normalize_audit(path, write_tags=True, config=None):
    """Read the AUDIT verdict and fix legacy mixed-case values (Real -> REAL)
    in a single file open. Returns (verdict, changed)."""
    try:
        af = AudioFile(path)
        raw = str(af.get_tag("AUDIT") or "").strip()
        v = raw.upper()
        changed = False
        if write_tags and raw and v in ("REAL", "FAKE") and raw != v:
            # Respect per-filetype AUDIT toggle
            if config is None or should_write_audio_tag(config, "AUDIT", filepath=path):
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

    # ------------------------------------------------------------------
    # CD rip verification — by default the .log CRC is the ONLY integrity
    # source for MEDIA=CD. When audit_cd_require_both is True, BOTH the
    # .log CRC and AudioAuditor must be REAL for the final AUDIT to be REAL;
    # if either is FAKE the result is FAKE (conservative). Files that cannot
    # be verified get NO verdict at all (grading fails them). AudioAuditor
    # is otherwise never run on CD rips; it is reserved for every other
    # release type.
    # ------------------------------------------------------------------
    require_both = bool(config.get("audit_cd_require_both", False))
    cd_files = set()
    unverified_cd = {}
    checksum_verified = {}
    if config.get("audit_verify_cd_checksums", True):
        # Reuse already-detected tools to avoid redundant GitHub cache lookup
        ffmpeg_exe_for_cd = (tools.get("ffmpeg") or {}).get("ffmpeg_exe")
        if not ffmpeg_exe_for_cd:
            log(c("WARNING: ffmpeg not found - CD checksum verification "
                  "unavailable.", Color.YELLOW))
            stats["errors"].append(("CD checksum", "ffmpeg not found"))
        else:
            from .discs import verify_album_checksums
            from concurrent.futures import as_completed

            def _is_cd(album_dir, paths_):
                # Check all paths, not just first file order (mixed-media albums)
                try:
                    for pp in paths_:
                        af = AudioFile(pp)
                        if af.audio is not None and str(af.get_tag("MEDIA") or "").strip() == "CD":
                            return True
                    return False
                except Exception:
                    return False

            by_album = {}
            for p in files:
                by_album.setdefault(os.path.dirname(p), []).append(p)
            cd_albums = {a: ps for a, ps in by_album.items()
                         if _is_cd(a, ps)}
            cd_files = {p for ps in cd_albums.values() for p in ps}
            cw = worker_count(config, default=4, maximum=8,
                              items=len(cd_albums))
            with ThreadPoolExecutor(max_workers=cw) as ex:
                futures = {
                    ex.submit(verify_album_checksums, ffmpeg_exe_for_cd,
                              album, paths, config): album
                    for album, paths in cd_albums.items()
                }
                for fut in as_completed(futures):
                    album = futures[fut]
                    try:
                        res, unver = fut.result()
                    except Exception as e:
                        stats["errors"].append((os.path.basename(album), f"checksum verify: {e}"))
                        continue
                    for path, verdict in res.items():
                        # When bothrequired, defer tag write until after AA
                        if not require_both and config.get("write_audit_tag", True) and should_write_audio_tag(config, "AUDIT", filepath=path):
                            changed, b_rem, b_add, err = _write_audit_tag(path, verdict)
                            if err:
                                stats["errors"].append((os.path.basename(path), err))
                            elif changed:
                                stats["modified_count"] += 1
                                stats["total_bytes_removed"] += b_rem
                                stats["total_bytes_added"] += b_add
                        checksum_verified[path] = verdict
                    unverified_cd.update(unver)

            if cd_files:
                n_real = sum(1 for v in checksum_verified.values()
                             if v == "REAL")
                n_fake = len(checksum_verified) - n_real
                if require_both:
                    log(f"CD checksums: {n_real} REAL, {n_fake} FAKE "
                        f"({len(unverified_cd)} unverified of "
                        f"{len(cd_files)} CD track(s) — will be combined with AudioAuditor)")
                else:
                    log(f"CD checksums: {n_real} REAL, {n_fake} FAKE "
                        f"({len(unverified_cd)} unverified of "
                        f"{len(cd_files)} CD track(s) - .log CRC is the only "
                        f"audit source for MEDIA=CD)")
                if n_fake:
                    for p in sorted(checksum_verified):
                        if checksum_verified[p] == "FAKE":
                            try:
                                rel = os.path.relpath(p, folder)
                            except ValueError:
                                rel = os.path.join(os.path.basename(os.path.dirname(p)), os.path.basename(p))
                            log(f"  {c('✕', Color.RED)} "
                                 f"{rel} "
                                 f"{c('FAKE (CRC mismatch vs .log)', Color.RED)}")
                if unverified_cd and verbose:
                    for p in sorted(unverified_cd)[:20]:
                        log(f"  {c('–', Color.GREY)} {os.path.basename(p)} "
                            f"{c(unverified_cd[p], Color.GREY)}")

    # ------------------------------------------------------------------
    # Integrity check (foobar2000 Verify Integrity style) — optional but on
    # by default. Uses `flac -t` for FLAC and `ffmpeg -v error` for all
    # types to catch truncated files, frame CRC mismatches, and sync errors.
    # Failures here make the final AUDIT FAKE, just like a fake lossless
    # detection, and are all configurable via Settings → Audit.
    # ------------------------------------------------------------------
    integrity_failed = {}
    integrity_ok = set()
    if config.get("audit_integrity", True):
        ffmpeg_exe = (tools.get("ffmpeg") or {}).get("ffmpeg_exe")
        flac_exe = (tools.get("flac") or {}).get("flac_exe")
        # Only verify files that would be audited anyway (respect force/skip later)
        # But run it now so we can fail fast and avoid an expensive AudioAuditor run
        # on a file that is already corrupt.
        def _check_one(p):
            ok, err = verify_integrity(p, ffmpeg_exe, flac_exe)
            return p, ok, err

        cw = worker_count(config, default=8, maximum=16, items=len(files))
        with ThreadPoolExecutor(max_workers=cw) as ex:
            futs = {ex.submit(_check_one, p): p for p in files}
            from concurrent.futures import as_completed as _as_comp
            for fut in _as_comp(futs):
                p, ok, err = fut.result()
                if not ok:
                    integrity_failed[p] = err or "integrity check failed"
                else:
                    integrity_ok.add(p)

        if integrity_failed:
            n_fail = len(integrity_failed)
            log(c(f"Integrity: {n_fail} file(s) failed verification (foobar2000 style) — will be AUDIT=FAKE", Color.RED))
            for p in sorted(integrity_failed)[:10]:
                try:
                    rel = os.path.relpath(p, folder)
                except ValueError:
                    rel = os.path.basename(p)
                log(f"  {c('✕', Color.RED)} {rel} {c(integrity_failed[p][:80], Color.RED)}")
            if n_fail > 10:
                log(f"  … and {n_fail - 10} more")
        else:
            log("Integrity: all files passed verification")

    # When require_both is False, CD rips are excluded from AudioAuditor;
    # when True, they are included and the final verdict is the AND of both
    # sources (both must be REAL, otherwise FAKE). Checksum tags were already
    # written above when not require_both; when require_both we deferred and
    # will write the combined result per-file below.

    # Skip files that already carry a REAL/FAKE verdict (normalizing
    # legacy mixed-case values) unless the audit is forced.
    # When require_both, CD files are NOT skipped — they need the second source.
    todo = files
    skipped = 0
    if not force:
        workers = worker_count(config, default=8, maximum=8, items=len(files))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(
                lambda path: _read_and_normalize_audit(
                    path, config.get("write_audit_tag", True), config
                ),
                files,
            ))
        todo = []
        for path, (verdict, changed) in zip(files, results):
            if verdict is not None:
                # When bothrequired, CD files must be re-checked even if they
                # already have a tag, because we need to AND the two sources.
                if require_both and path in cd_files:
                    todo.append(path)
                    continue
                skipped += 1
                if changed:
                    stats["modified_count"] += 1
            else:
                todo.append(path)
        if skipped:
            log(f"skipping {skipped} file(s) already carrying an AUDIT "
                f"verdict (force audit overrides)")

    if not require_both:
        # Only skip CD files that were successfully verified via log CRC.
        # Unverified CD files (no .log, no CRC, or log missing) still need
        # AudioAuditor — otherwise they'd never be audited and grading would
        # always fail them for missing AUDIT.
        todo = [p for p in todo if p not in checksum_verified]
        if cd_files:
            n_unverified = len(unverified_cd)
            n_verified = len(checksum_verified)
            log(f"CD rips ({len(cd_files)} track(s)) are verified via .log "
                f"checksums only - AudioAuditor not applied to MEDIA=CD "
                f"({n_verified} verified, {n_unverified} unverified will be audited).")
    else:
        # require_both: keep CD files in todo even if they were checksum-verified
        # (we need to AND). Unverified CD files stay in todo as well — they'll
        # be audited and then marked FAKE because the log side is not REAL.
        if cd_files:
            log(f"CD rips ({len(cd_files)} track(s)) will be verified via BOTH "
                f".log checksums AND AudioAuditor (both must be REAL).")

    # Integrity failures that were skipped due to already having an AUDIT tag
    # still need to be handled — if a file is corrupt, its AUDIT must be FAKE
    # even if it already says REAL. Respect per-filetype toggle.
    if config.get("audit_integrity", True) and integrity_failed:
        for p, err in list(integrity_failed.items()):
            if p not in todo and p in files and should_write_audio_tag(config, "AUDIT", filepath=p):
                todo.append(p)

    log(f"auditing {len(todo)} file(s) · fast scan "
        f"{'off (--thorough)' if thorough else 'on'}")

    counts = {"ok": 0, "skip": 0, "fail": 0}
    status_counts = {"Real": 0, "Fake": 0, "Unknown": 0,
                     "Corrupt": 0, "Optimized": 0}
    issue_counts = {}
    flagged = []
    warned = 0
    pbar = _make_pbar(len(todo), "Auditing", unit="file")
    batch_size = int(config.get("audit_batch_size", BATCH_SIZE) or BATCH_SIZE)
    batch_size = max(50, min(500, batch_size))
    # Track per-file severity/status for later unscorable-log handling
    file_severity_map = {}
    file_status_map = {}

    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        try:
            items = _audit_batch(cli, batch, config)
        except Exception as e:
            stats["total_scanned"] += len(batch)
            stats["error_count"] += len(batch)
            stats["errors"].append((f"batch {start // batch_size + 1} "
                                     f"({len(batch)} files)", str(e)))
            log(c(f"Audit batch failed: {e}", Color.RED))
            counts["fail"] += len(batch)
            if pbar is not None:
                try:
                    pbar.update(len(batch))
                    pbar.set_postfix(ok=counts["ok"], skip=counts["skip"], fail=counts["fail"])
                except Exception:
                    pass
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
        canon_failed = {canon(k): v for k, v in integrity_failed.items()} if config.get("audit_integrity", True) else {}
        for item in items:
            path = item.get("filePath") or ""
            missing.discard(canon(path))
            severity, reason = _classify(item)
            # Scaled clipping is very common on loud masters; allow silencing just this warning
            if reason == "scaled clipping" and not config.get("audit_scaled_clipping", True):
                severity, reason = "ok", ""
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
            # Track for unscorable-log FAIL handling later
            file_severity_map[canon(path)] = severity
            file_status_map[canon(path)] = skey

            # Base AA tag value before CD combination.
            tag_value = _audit_tag_value(severity, cli_status)

            # When bothrequired, the final AUDIT is the AND of the two sources.
            # checksum must be REAL and AA must be Valid/REAL; otherwise FAKE.
            # .log CRC is authoritative, so an unverified log also means FAKE.
            # Preserve warning flags (Valid+clipping etc.) when both are REAL.
            if require_both and path in cd_files:
                chk = checksum_verified.get(path)
                aa_real = (tag_value == "REAL" and severity != "fail")
                orig_severity = severity
                orig_reason = reason
                # Normalize AA verdict: _audit_tag_value returns REAL only for Valid
                if chk != "REAL":
                    tag_value = "FAKE"
                    severity = "fail"
                    reason = f"CD log not REAL ({unverified_cd.get(path, chk or 'no CRC')})"
                elif not aa_real:
                    tag_value = "FAKE"
                    severity = "fail"
                    # keep AA reason but note log was REAL
                    reason = f"{orig_reason} (log REAL but AA {cli_status})" if orig_reason else f"AA {cli_status} (log REAL)"
                else:
                    tag_value = "REAL"
                    # Both REAL: keep original warn if AA had flags, else ok
                    if orig_severity == "warn":
                        severity = "warn"
                        reason = orig_reason
                    else:
                        severity = "ok"
                        reason = ""
                # Ensure status counts reflect the AA side already counted;
                # the final tag is what grading will use.

            # Integrity check — use canon for Windows 8.3 / case variant safety
            if canon(path) in canon_failed and should_write_audio_tag(config, "AUDIT", filepath=path):
                tag_value = "FAKE"
                severity = "fail"
                reason = f"integrity check failed: {canon_failed[canon(path)]}"

            # Persist the verdict into the file's AUDIT tag (respects per-filetype).
            if config.get("write_audit_tag", True) and should_write_audio_tag(config, "AUDIT", filepath=path):
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
    # Pre-filter to albums that could be CD rips (contain .log and MEDIA==CD) to avoid
    # spawning thousands of no-op threads for non-CD libraries (5k albums = 5k futures).
    cd_candidate_dirs = []
    for d in album_dirs:
        try:
            if not any(f.lower().endswith(".log") for f in os.listdir(d)):
                continue
            # Check any track's MEDIA is CD, not just first by unsorted listdir
            found_cd = False
            for f in os.listdir(d):
                if f.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac")):
                    try:
                        af0 = AudioFile(os.path.join(d, f))
                        if str(af0.get_tag("MEDIA") or "").strip() == "CD":
                            found_cd = True
                            break
                    except Exception:
                        continue
            if not found_cd:
                continue
            cd_candidate_dirs.append(d)
        except OSError:
            continue
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
            config=config,
            log_fn=(lambda m: log(f"  {m}")) if verbose else None)
        return album_dir, scores, notes

    if not cd_candidate_dirs:
        # No CD candidates — skip thread pool entirely
        pass
    else:
        workers = worker_count(config, default=8, maximum=8, items=len(cd_candidate_dirs))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_grade_one, d) for d in cd_candidate_dirs]
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

    # Audit FAIL on unscorable logs — user request: every CD .log must be gradeable
    def _canon2(p):
        try:
            return os.path.normcase(os.path.realpath(p))
        except OSError:
            return os.path.normcase(p)
    if config.get("audit_fail_on_unscorable_log", True) and cd_candidate_dirs:
        unscorable_albums = set()
        for d in cd_candidate_dirs:
            if d not in log_scores:
                unscorable_albums.add(d)
            else:
                try:
                    from .discs import album_discs as _ad2
                    discs_here = _ad2(d)
                    expected = len(discs_here) if discs_here else 1
                    if len(log_scores[d]) < expected:
                        unscorable_albums.add(d)
                except Exception:
                    pass
        # Also parse orphan log notes that contain "could not score" but album not in cd_candidate (fallback)
        for note in log_notes:
            if "could not score" in note.lower():
                base = note.split(":", 1)[0].strip()
                for d in cd_candidate_dirs:
                    if os.path.basename(d).lower() == base.lower():
                        unscorable_albums.add(d)
                        break
                # orphan filename case: try to find album by file location
                if base.lower().endswith(".log"):
                    for d in cd_candidate_dirs:
                        try:
                            if base.lower() in (f.lower() for f in os.listdir(d)):
                                unscorable_albums.add(d)
                                break
                        except OSError:
                            pass
        if unscorable_albums:
            log(c(f"Audit FAIL on unscorable logs: {len(unscorable_albums)} CD album(s) have .log that could not be graded — marking their tracks as failed (audit_fail_on_unscorable_log on)", Color.RED))
            for d in unscorable_albums:
                try:
                    album_files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                except OSError:
                    continue
                for fp in album_files:
                    if fp not in files:
                        continue
                    canon_fp = _canon2(fp)
                    prev_sev = file_severity_map.get(canon_fp)
                    prev_status = file_status_map.get(canon_fp)
                    try:
                        rel = os.path.relpath(fp, folder)
                    except ValueError:
                        rel = os.path.basename(fp)
                    # Adjust counts: move from previous status to Fake
                    if canon_fp in file_status_map:
                        if prev_status == "Real":
                            status_counts["Real"] = max(0, status_counts.get("Real", 0) - 1)
                            status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                            if prev_sev == "warn":
                                warned = max(0, warned - 1)
                        elif prev_status == "Unknown":
                            status_counts["Unknown"] = max(0, status_counts.get("Unknown", 0) - 1)
                            status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                        elif prev_status not in ("Fake", "Corrupt", "Optimized"):
                            status_counts[prev_status] = max(0, status_counts.get(prev_status, 0) - 1)
                            status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                        # total_scanned already counted
                    else:
                        # Was skipped (already had AUDIT tag) — move from skipped to failed
                        if stats.get("skipped_count", 0) > 0:
                            stats["skipped_count"] = max(0, stats["skipped_count"] - 1)
                        stats["total_scanned"] = stats.get("total_scanned", 0) + 1
                        # If it was previously counted as Real in skipped, adjust Real/Fake
                        # We don't have prior status, assume Real -> Fake
                        if status_counts.get("Real", 0) > 0:
                            # Only move if we have Real to move; otherwise just increment Fake
                            # For skipped, status_counts not yet includes it, so just increment Fake
                            pass
                        status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                    flagged.append((rel, "unscorable .log (LOG_GRADE missing)"))
                    issue_counts["unscorable .log"] = issue_counts.get("unscorable .log", 0) + 1
                    stats["grade_dist"]["FAIL"] = stats["grade_dist"].get("FAIL", 0) + 1
                    file_status_map[canon_fp] = "Fake"
                    file_severity_map[canon_fp] = "fail"
                    # Write AUDIT=FAKE if allowed (makes next run stay failed until log fixed)
                    if config.get("write_audit_tag", True) and should_write_audio_tag(config, "AUDIT", filepath=fp):
                        try:
                            _write_audit_tag(fp, "FAKE")
                        except Exception:
                            pass

    # --------------------------------------------------------------
    # Audit FAIL on invalid .log SHA256 checksum (EAC 1.0b1+ logs)
    # --------------------------------------------------------------
    if config.get("audit_verify_log_checksum", True) and cd_candidate_dirs:
        from .discs import check_log_checksum, album_discs as _ad_chk, _disc_pattern_for as _pat_chk, _disc_expected_name as _exp_chk
        checksum_failed = {}  # album_dir -> list of (log_path, detail)
        for d in cd_candidate_dirs:
            try:
                discs_here = _ad_chk(d)
            except Exception:
                discs_here = {}
            pat = _pat_chk(config)
            logs_to_check = []
            if discs_here:
                for disc_n in discs_here:
                    lp = os.path.join(d, _exp_chk(pat, disc_n, ".log"))
                    if os.path.isfile(lp):
                        logs_to_check.append((lp, discs_here[disc_n]))
                    else:
                        # Fallback orphan present but not at expected name
                        pass
                # Also include any extra .log not at expected pattern (orphan)
                try:
                    for f in os.listdir(d):
                        if f.lower().endswith(".log"):
                            full = os.path.join(d, f)
                            if full not in [x[0] for x in logs_to_check]:
                                # Orphan log -> applies to all tracks of album
                                all_tr = [os.path.join(d, xf) for xf in os.listdir(d) if xf.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                                logs_to_check.append((full, all_tr))
                except OSError:
                    pass
            else:
                try:
                    for f in os.listdir(d):
                        if f.lower().endswith(".log"):
                            full = os.path.join(d, f)
                            all_tr = [os.path.join(d, xf) for xf in os.listdir(d) if xf.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                            logs_to_check.append((full, all_tr))
                except OSError:
                    continue
            for lp, trs in logs_to_check:
                state, detail = check_log_checksum(lp)
                # 'unsupported' (XLD/no checksum) and 'missing' (no checksum line) are not fails — only 'invalid' is a hard fail.
                # Missing on an EAC log that declares a checksum but can't be parsed is treated as invalid for strictness,
                # but XLD/unsupported is passed to avoid false-failing non-EAC collections.
                if state == "invalid":
                    checksum_failed.setdefault(d, []).append((lp, detail))
                elif state == "missing":
                    # EAC log claims no checksum line but should have one — treat as fail only if log is EAC
                    # check_log_checksum already returns 'unsupported' for XLD; 'missing' here means EAC without checksum (old version)
                    # We still fail it when strict (user asked fail if checksum verification failed) — but allow turn off via toggle.
                    # To avoid failing ancient rips with no checksum ever, we only fail if the log text contains 'Exact Audio Copy V1.0' (version where checksum expected)
                    try:
                        from .discs import read_log_text as _rlt
                        txt_tmp = _rlt(lp)
                        if "Exact Audio Copy V1.0" in txt_tmp:
                            checksum_failed.setdefault(d, []).append((lp, detail))
                    except Exception:
                        pass
                # 'ok', 'unsupported', None are passes
        if checksum_failed:
            log(c(f"Audit FAIL on log checksum: {sum(len(v) for v in checksum_failed.values())} log(s) in {len(checksum_failed)} CD album(s) have invalid SHA256 checksum — marking their disc(s) as failed (audit_verify_log_checksum on)", Color.RED))
            for d, lst in checksum_failed.items():
                for lp, detail in lst:
                    # Determine affected tracks for this log
                    try:
                        discs_here = _ad_chk(d)
                        affected = None
                        if discs_here:
                            pat = _pat_chk(config)
                            for dn, trs in discs_here.items():
                                exp = os.path.join(d, _exp_chk(pat, dn, ".log"))
                                if os.path.normcase(exp) == os.path.normcase(lp):
                                    affected = trs
                                    break
                        if affected is None:
                            # Orphan or single-disc: all album files
                            affected = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                    except OSError:
                        continue
                    for fp in affected:
                        if fp not in files:
                            continue
                        canon_fp = _canon2(fp)
                        try:
                            rel = os.path.relpath(fp, folder)
                        except ValueError:
                            rel = os.path.basename(fp)
                        # Already Fake from earlier gates (unscorable / earlier checksum) — add secondary reason without double-moving counts/FAIL/flagged
                        if file_status_map.get(canon_fp) == "Fake" and file_severity_map.get(canon_fp) == "fail":
                            issue_counts["log checksum invalid"] = issue_counts.get("log checksum invalid", 0) + 1
                            continue
                        prev_status = file_status_map.get(canon_fp)
                        prev_sev = file_severity_map.get(canon_fp)
                        # Adjust status counts (move to Fake if not already)
                        if canon_fp in file_status_map:
                            if prev_status == "Real":
                                status_counts["Real"] = max(0, status_counts.get("Real", 0) - 1)
                                status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                                if prev_sev == "warn":
                                    warned = max(0, warned - 1)
                            elif prev_status == "Unknown":
                                status_counts["Unknown"] = max(0, status_counts.get("Unknown", 0) - 1)
                                status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                            elif prev_status not in ("Fake", "Corrupt", "Optimized"):
                                status_counts[prev_status] = max(0, status_counts.get(prev_status, 0) - 1)
                                status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                            else:
                                flagged.append((rel, f"log checksum invalid ({os.path.basename(lp)})"))
                                issue_counts["log checksum invalid"] = issue_counts.get("log checksum invalid", 0) + 1
                                file_status_map[canon_fp] = "Fake"
                                file_severity_map[canon_fp] = "fail"
                                continue
                        else:
                            if stats.get("skipped_count", 0) > 0:
                                stats["skipped_count"] = max(0, stats["skipped_count"] - 1)
                            stats["total_scanned"] = stats.get("total_scanned", 0) + 1
                            status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                        flagged.append((rel, f"log checksum invalid ({os.path.basename(lp)}: {detail or 'mismatch'})"))
                        issue_counts["log checksum invalid"] = issue_counts.get("log checksum invalid", 0) + 1
                        stats["grade_dist"]["FAIL"] = stats["grade_dist"].get("FAIL", 0) + 1
                        file_status_map[canon_fp] = "Fake"
                        file_severity_map[canon_fp] = "fail"
                        if config.get("write_audit_tag", True) and should_write_audio_tag(config, "AUDIT", filepath=fp):
                            try:
                                _write_audit_tag(fp, "FAKE")
                            except Exception:
                                pass

    # --------------------------------------------------------------
    # Audit FAIL on AccurateRip mismatch (any track not accurately ripped)
    # --------------------------------------------------------------
    if config.get("audit_require_accuraterip", True) and cd_candidate_dirs:
        from .discs import check_accuraterip as _chk_ar, album_discs as _ad_ar, _disc_pattern_for as _pat_ar, _disc_expected_name as _exp_ar
        ar_failed = {}  # album_dir -> list of (log_path, reason)
        for d in cd_candidate_dirs:
            try:
                discs_here = _ad_ar(d)
            except Exception:
                discs_here = {}
            pat = _pat_ar(config)
            logs_to_check_ar = []
            if discs_here:
                for disc_n in discs_here:
                    lp = os.path.join(d, _exp_ar(pat, disc_n, ".log"))
                    if os.path.isfile(lp):
                        logs_to_check_ar.append((lp, discs_here[disc_n]))
                try:
                    for f in os.listdir(d):
                        if f.lower().endswith(".log"):
                            full = os.path.join(d, f)
                            if full not in [x[0] for x in logs_to_check_ar]:
                                all_tr = [os.path.join(d, xf) for xf in os.listdir(d) if xf.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                                logs_to_check_ar.append((full, all_tr))
                except OSError:
                    pass
            else:
                try:
                    for f in os.listdir(d):
                        if f.lower().endswith(".log"):
                            full = os.path.join(d, f)
                            all_tr = [os.path.join(d, xf) for xf in os.listdir(d) if xf.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                            logs_to_check_ar.append((full, all_tr))
                except OSError:
                    continue
            for lp, trs in logs_to_check_ar:
                ok, reason, per = _chk_ar(lp)
                if ok is False:
                    ar_failed.setdefault(d, []).append((lp, reason))
                # ok True / None is pass (None = couldn't read, not strict)
        if ar_failed:
            log(c(f"Audit FAIL on AccurateRip: {sum(len(v) for v in ar_failed.values())} log(s) in {len(ar_failed)} CD album(s) not accurately ripped — marking their disc(s) as failed (audit_require_accuraterip on)", Color.RED))
            for d, lst in ar_failed.items():
                for lp, reason in lst:
                    try:
                        discs_here = _ad_ar(d)
                        affected = None
                        if discs_here:
                            pat = _pat_ar(config)
                            for dn, trs in discs_here.items():
                                exp = os.path.join(d, _exp_ar(pat, dn, ".log"))
                                if os.path.normcase(exp) == os.path.normcase(lp):
                                    affected = trs
                                    break
                        if affected is None:
                            affected = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                    except OSError:
                        continue
                    for fp in affected:
                        if fp not in files:
                            continue
                        canon_fp = _canon2(fp)
                        # If already Fake from earlier gates, add reason without double-moving counts
                        already_fake = file_status_map.get(canon_fp) == "Fake" and file_severity_map.get(canon_fp) == "fail"
                        prev_status = file_status_map.get(canon_fp)
                        prev_sev = file_severity_map.get(canon_fp)
                        try:
                            rel = os.path.relpath(fp, folder)
                        except ValueError:
                            rel = os.path.basename(fp)
                        if already_fake:
                            issue_counts["not accurately ripped"] = issue_counts.get("not accurately ripped", 0) + 1
                            continue
                        if canon_fp in file_status_map:
                            if prev_status == "Real":
                                status_counts["Real"] = max(0, status_counts.get("Real", 0) - 1)
                                status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                                if prev_sev == "warn":
                                    warned = max(0, warned - 1)
                            elif prev_status == "Unknown":
                                status_counts["Unknown"] = max(0, status_counts.get("Unknown", 0) - 1)
                                status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                            elif prev_status not in ("Fake", "Corrupt", "Optimized"):
                                status_counts[prev_status] = max(0, status_counts.get(prev_status, 0) - 1)
                                status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                            else:
                                flagged.append((rel, f"not accurately ripped ({os.path.basename(lp)})"))
                                issue_counts["not accurately ripped"] = issue_counts.get("not accurately ripped", 0) + 1
                                file_status_map[canon_fp] = "Fake"
                                file_severity_map[canon_fp] = "fail"
                                continue
                        else:
                            if stats.get("skipped_count", 0) > 0:
                                stats["skipped_count"] = max(0, stats["skipped_count"] - 1)
                            stats["total_scanned"] = stats.get("total_scanned", 0) + 1
                            status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                        flagged.append((rel, f"not accurately ripped ({os.path.basename(lp)}: {reason or 'AR mismatch'})"))
                        issue_counts["not accurately ripped"] = issue_counts.get("not accurately ripped", 0) + 1
                        stats["grade_dist"]["FAIL"] = stats["grade_dist"].get("FAIL", 0) + 1
                        file_status_map[canon_fp] = "Fake"
                        file_severity_map[canon_fp] = "fail"
                        if config.get("write_audit_tag", True) and should_write_audio_tag(config, "AUDIT", filepath=fp):
                            try:
                                _write_audit_tag(fp, "FAKE")
                            except Exception:
                                pass

    # --------------------------------------------------------------
    # Audit FAIL on Logchecker score below threshold
    # --------------------------------------------------------------
    if int(config.get("audit_log_score_threshold", 0) or 0) > 0 and cd_candidate_dirs and log_scores:
        try:
            thr_a = int(config.get("audit_log_score_threshold", 0) or 0)
            thr_a = max(0, min(100, thr_a))
        except Exception:
            thr_a = 0
        if thr_a > 0:
            from .discs import album_discs as _ad_thr, _disc_pattern_for as _pat_thr, _disc_expected_name as _exp_thr
            thr_failed = {}  # album_dir -> list disc nums
            for d, scores in list(log_scores.items()):
                for disc_n, sc in scores.items():
                    try:
                        if int(sc) < thr_a:
                            thr_failed.setdefault(d, []).append((disc_n, sc))
                    except Exception:
                        continue
            if thr_failed:
                log(c(f"Audit FAIL on log score threshold: {sum(len(v) for v in thr_failed.values())} disc(s) in {len(thr_failed)} CD album(s) below {thr_a}/100 — marking their disc(s) as failed (audit_log_score_threshold on)", Color.RED))
                for d, lst in thr_failed.items():
                    for disc_n, sc in lst:
                        try:
                            discs_here = _ad_thr(d)
                            affected = None
                            if discs_here and disc_n in discs_here:
                                affected = discs_here[disc_n]
                            else:
                                pat = _pat_thr(config)
                                exp = os.path.join(d, _exp_thr(pat, disc_n, ".log"))
                                if os.path.isfile(exp):
                                    # Find tracks belonging to this disc via filename D-TT or all if single
                                    if discs_here:
                                        affected = discs_here.get(disc_n)
                                    if not affected:
                                        affected = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                                else:
                                    affected = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".aac"))]
                            if not affected:
                                continue
                        except OSError:
                            continue
                        for fp in affected:
                            if fp not in files:
                                continue
                            canon_fp = _canon2(fp)
                            try:
                                rel = os.path.relpath(fp, folder)
                            except ValueError:
                                rel = os.path.basename(fp)
                            if file_status_map.get(canon_fp) == "Fake" and file_severity_map.get(canon_fp) == "fail":
                                issue_counts[f"log score < {thr_a}"] = issue_counts.get(f"log score < {thr_a}", 0) + 1
                                continue
                            prev_status = file_status_map.get(canon_fp)
                            prev_sev = file_severity_map.get(canon_fp)
                            if canon_fp in file_status_map:
                                if prev_status == "Real":
                                    status_counts["Real"] = max(0, status_counts.get("Real", 0) - 1)
                                    status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                                    if prev_sev == "warn":
                                        warned = max(0, warned - 1)
                                elif prev_status == "Unknown":
                                    status_counts["Unknown"] = max(0, status_counts.get("Unknown", 0) - 1)
                                    status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                                elif prev_status not in ("Fake", "Corrupt", "Optimized"):
                                    status_counts[prev_status] = max(0, status_counts.get(prev_status, 0) - 1)
                                    status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                                else:
                                    issue_counts[f"log score < {thr_a}"] = issue_counts.get(f"log score < {thr_a}", 0) + 1
                                    file_status_map[canon_fp] = "Fake"
                                    file_severity_map[canon_fp] = "fail"
                                    continue
                            else:
                                if stats.get("skipped_count", 0) > 0:
                                    stats["skipped_count"] = max(0, stats["skipped_count"] - 1)
                                stats["total_scanned"] = stats.get("total_scanned", 0) + 1
                                status_counts["Fake"] = status_counts.get("Fake", 0) + 1
                            flagged.append((rel, f"log score {sc} below threshold {thr_a}"))
                            issue_counts[f"log score < {thr_a}"] = issue_counts.get(f"log score < {thr_a}", 0) + 1
                            stats["grade_dist"]["FAIL"] = stats["grade_dist"].get("FAIL", 0) + 1
                            file_status_map[canon_fp] = "Fake"
                            file_severity_map[canon_fp] = "fail"
                            if config.get("write_audit_tag", True) and should_write_audio_tag(config, "AUDIT", filepath=fp):
                                try:
                                    _write_audit_tag(fp, "FAKE")
                                except Exception:
                                    pass

    stats["grade_dist"]["PASS"] = status_counts["Real"]
    stats["summary_pass"] = max(0, status_counts["Real"] - warned)
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
