"""Lossless FLAC re-encoding via the reference flac.exe toolchain."""
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from .containers import (
    _read_flac_tags, _write_flac_tags, _identity_missing,
)
from .subproc import run_tool
from .paths import DEPS_DIR
from .tools import detect_all_tools, _version_is_older
from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _diff_bytes, _walk_files,
    _collect_targets, worker_count,
)
from .ui import print_header, log, c, Color, log_file_result

def _should_reencode_flac(filepath, target_quality, target_version, force,
                          enabled=None):
    """Return (should_reencode, reason, written_by_us).

    written_by_us is True when the ENCODER identity tags match this
    pipeline's own marker, meaning the file was encoded with
    --no-seektable and had foreign metadata blocks stripped already.
    """
    if force:
        return True, "force re-encode", False

    q, v, program = _read_flac_tags(filepath)

    if _identity_missing(enabled, q, v, program):
        return True, "missing ENCODER tags", False

    try:
        if int(q) < int(target_quality):
            return True, f"quality {q} < {target_quality}", False
    except (ValueError, TypeError):
        return True, f"quality not numeric: {q}", False

    if _version_is_older(v, target_version):
        return True, f"encoder {v} older than {target_version}", False

    ours = str(program or "").strip() == "FLAC reference encoder"
    return False, f"already at quality={q}, version={v}", ours


def _optimize_flac(args):
    # Backwards compatible: older callers pass 8 args, new pass 9 with config
    if len(args) == 9:
        (
            flac_exe,
            metaflac_exe,
            filepath,
            flac_level,
            add_seektables,
            target_version,
            force,
            enabled,
            config,
        ) = args
    else:
        (
            flac_exe,
            metaflac_exe,
            filepath,
            flac_level,
            add_seektables,
            target_version,
            force,
            enabled,
        ) = args
        config = None

    filename = os.path.basename(filepath)
    temp_path = filepath + ".opttmp.flac"

    # Conservative clean: only remove UNSYNCEDLYRICS (always) and LYRICS when
    # the user wants LRC sidecars only (lyrics_format == LRC), plus
    # ENCODER_PROGRAM when that marker is disabled. No other tags are touched
    # so Picard/MusicBrainz IDs etc. are never deleted.
    try:
        from .containers import _clean_flac_tags
        _clean_flac_tags(filepath, config=config, enabled=enabled)
    except Exception:
        pass

    should_reencode, reason, ours = _should_reencode_flac(
        filepath,
        flac_level,
        target_version,
        force,
        enabled,
    )

    if not should_reencode:
        # Even when skipping re-encode, actively remove seektables if
        # required - but only for files this pipeline did not write
        # itself: our own output is encoded --no-seektable and already
        # stripped, so the metaflac pass would be pure process-spawn
        # overhead (one exe launch per file on every re-run).
        try:
            original_size = os.path.getsize(filepath)
        except OSError as e:
            return (filename, False, f"cannot stat file: {e}", 0, 0)

        if not add_seektables and metaflac_exe and not ours:
            try:
                result = run_tool(
                    [
                        metaflac_exe,
                        "--remove",
                        "--block-type=SEEKTABLE",
                        filepath,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                if result.returncode != 0:
                    err = (result.stderr or "").strip()
                    log(c(f"[strip warn] {filename}: metaflac failed: {err}",
                          Color.YELLOW))
                else:
                    final_size = os.path.getsize(filepath)

                    if final_size != original_size:
                        b_rem, b_add = _diff_bytes(original_size, final_size)
                        return (
                            filename,
                            True,
                            "removed seektable (skipped re-encode)",
                            b_rem,
                            b_add,
                        )
            except Exception:
                pass

        return (filename, False, f"skipped ({reason})", 0, 0)

    try:
        original_size = os.path.getsize(filepath)
    except OSError as e:
        return (filename, False, f"cannot stat file: {e}", 0, 0)

    flac_args = [f"-{flac_level}", "--no-padding", "-f"]

    if not add_seektables:
        flac_args.append("--no-seektable")

    cmd = [flac_exe] + flac_args + ["-o", temp_path, filepath]

    try:
        result = run_tool(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            err = (result.stderr or "").strip()
            return (filename, False, f"flac.exe failed: {err}", 0, 0)

        if not os.path.exists(temp_path):
            return (filename, False, "flac.exe produced no output", 0, 0)

        # Strip unwanted metadata from the temporary output before replacing
        # the original file. This keeps failure handling safe and accurate.
        if metaflac_exe:
            blocks = "PICTURE,PADDING,CUESHEET,APPLICATION"
            if not add_seektables:
                blocks = "PICTURE,SEEKTABLE,PADDING,CUESHEET,APPLICATION"

            try:
                result = run_tool(
                    [
                        metaflac_exe,
                        "--dont-use-padding",
                        "--remove",
                        "--block-type=" + blocks,
                        temp_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if result.returncode != 0:
                    err = (result.stderr or "").strip()
                    log(c(f"[strip warn] {filename}: metaflac failed: {err}",
                          Color.YELLOW))
            except Exception:
                pass

        try:
            _write_flac_tags(temp_path, flac_level, target_version, enabled)
        except Exception as e:
            log(c(f"[tag warn] {filename}: {e}", Color.YELLOW))

        final_size = os.path.getsize(temp_path)
        os.replace(temp_path, filepath)
        temp_path = None

        b_rem, b_add = _diff_bytes(original_size, final_size)
        info = f"{original_size // 1024} KB -> {final_size // 1024} KB"

        return (filename, True, info, b_rem, b_add)

    except Exception as e:
        return (filename, False, f"exception: {e}", 0, 0)

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def run_optimize_flacs(config):
    flac_level = config["flac_level"]
    add_seektables = config["add_seektables"]
    force = config.get("force_reencode_flac", False)
    stats = new_stats()

    tools = detect_all_tools()
    flac_tool = tools.get("flac")

    if not flac_tool:
        log(c("ERROR: Could not auto-detect flac.exe in .dependencies folder.", Color.RED))
        log(f"Expected a folder like: {os.path.join(DEPS_DIR, 'flac v1.5.0')}")
        return stats

    flac_exe = flac_tool["flac_exe"]
    metaflac_exe = flac_tool["metaflac_exe"]
    target_version = flac_tool["version"]

    print_header("FLAC Optimizer")
    strip_msg = "PICTURE, PADDING, CUESHEET, APPLICATION"
    if not add_seektables:
        strip_msg += ", SEEKTABLE"
    log(
        f"level=-{flac_level} · seektables={'on' if add_seektables else 'off'} · "
        f"encoder={target_version} · force={'on' if force else 'off'} · "
        f"padding=removed · strip={strip_msg}"
    )

    target = os.path.abspath(config["music_folder"] or os.getcwd())

    if not os.path.isdir(target):
        log(c(f"ERROR: TARGET_DIR does not exist: {target}", Color.RED))
        return stats

    log(f"target: {target}")
    log(f"flac.exe: {flac_exe} · metaflac.exe: {metaflac_exe or '(not found)'}")

    targets = config.get("targets")
    flac_files = _collect_targets(targets, (".flac",))
    if targets is None:
        flac_files = sorted(
            [
                f
                for f in _walk_files(target, (".flac",))
                if not f.endswith(".opttmp.flac")
            ]
        )

    if not flac_files:
        log("No FLAC files found.")
        return stats

    workers = worker_count(config, default=os.cpu_count() or 1,
                          items=len(flac_files))
    counts = {"ok": 0, "skip": 0, "fail": 0}

    args_list = [
        (
            flac_exe,
            metaflac_exe,
            fp,
            flac_level,
            add_seektables,
            target_version,
            force,
            (config.get("encoder_tags") or {}).get("flac") or {},
            config,
        )
        for fp in flac_files
    ]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_optimize_flac, a) for a in args_list]
        pbar = _make_pbar(len(futures), "FLAC")

        for future in as_completed(futures):
            try:
                filename, ok, info, b_rem, b_add = future.result()
            except Exception as e:
                stats["total_scanned"] += 1
                stats["error_count"] += 1
                stats["errors"].append(("<unknown FLAC>", str(e)))
                _pbar_update(pbar, counts, kind="fail")
                continue

            if ok:
                # A seektable-only change with zero byte difference is not
                # useful for byte metrics, so treat it as skipped.
                if info.startswith("removed seektable") and b_rem == 0 and b_add == 0:
                    stats["skipped_count"] += 1
                    log_file_result(filename, "skip", info="seektable removed")
                    _pbar_skip(pbar, counts)
                    continue

                stats["total_scanned"] += 1
                stats["modified_count"] += 1
                stats["total_bytes_removed"] += b_rem
                stats["total_bytes_added"] += b_add
                log_file_result(filename, "ok", b_rem, b_add)
                _pbar_update(pbar, counts, kind="ok")
            else:
                if info.startswith("skipped"):
                    stats["skipped_count"] += 1
                    log_file_result(filename, "skip",
                                    info=info[len("skipped"):].strip(" ()"))
                    _pbar_skip(pbar, counts)
                else:
                    stats["total_scanned"] += 1
                    stats["error_count"] += 1
                    stats["errors"].append((filename, info))
                    log_file_result(filename, "fail", info=info)
                    _pbar_update(pbar, counts, kind="fail")

        if pbar:
            pbar.close()

    return stats

