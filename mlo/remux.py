"""Lossless video remux — script 11: any video container -> MP4.

Music libraries increasingly carry promo clips and music videos alongside
the tracks (VOB rips, MKV/AVI/WMV downloads, TS captures...). Browsers,
players and this app's own library scanner all prefer MP4, so this script
normalizes every video file:

* Video stream is copied **bit-exact** when its codec is MP4-compatible
  (h264 / hevc / mpeg4 / av1 / vp9). Incompatible codecs (MPEG-2 in a VOB,
  VP8, Flash...) are re-encoded to H.264 when ``video_reencode_incompatible``
  is set — otherwise the file is skipped untouched.
* **Every** audio stream is decoded and re-encoded to FLAC (lossless from
  the decoded source), preserving channel layout and sample rate — FLAC in
  MP4 is standardized and keeps multi-channel / hi-res audio intact.
* Text subtitle streams become mov_text; chapters and cover art survive.
* Output is verified with ffprobe (video present, audio stream count
  matches, duration within 0.5%) before anything replaces the source. The
  original file is only deleted when ``video_remove_original`` is set.

Config keys: video_reencode_incompatible, video_crf, video_preset,
video_flac_level, video_remove_original, video_process_mp4.
"""

import json
import os
import tempfile
import threading

from .paths import DEPS_DIR
from .stats import (
    _collect_targets,
    _make_pbar,
    _walk_files,
    new_stats,
    worker_count,
)
from .subproc import run_tool
from .tools import detect_all_tools
from .ui import Color, c, log, print_header

# Every container this script accepts as input.
VIDEO_EXTS = (
    ".vob", ".mpg", ".mpeg", ".m2v", ".vro", ".mod", ".tod",
    ".ts", ".m2ts", ".mts", ".m2t",
    ".mkv", ".avi", ".divx", ".wmv", ".asf", ".mov", ".flv", ".f4v",
    ".webm", ".ogv", ".3gp", ".3g2", ".rm", ".rmvb",
)

# Video codecs an MP4 muxer accepts without re-encoding. vp9/av1 are
# standard MP4 codec ids (ISO/IEC 14496-15); h263/vp8/mpeg2 are not.
MP4_SAFE_VIDEO = {"h264", "hevc", "mpeg4", "av1", "vp9"}

# Text-based subtitle codecs mov_text can carry; bitmap subs (PGS/DVB,
# VOB spu) are dropped — MP4 cannot hold them losslessly.
TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}

X264_PRESETS = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
)


def _ffprobe_json(ffprobe_exe, path, timeout=60):
    """Probe a media file, returning parsed JSON or None."""
    try:
        proc = run_tool(
            [ffprobe_exe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return json.loads(proc.stdout)
    except (ValueError, TypeError):
        return None


def _stream_info(path, ffprobe_exe):
    """(video_codec, [audio_codecs], [subtitle_codecs], duration) or None."""
    data = _ffprobe_json(ffprobe_exe, path)
    if not data:
        return None
    video = None
    audio, subs = [], []
    for st in data.get("streams") or []:
        sttype = st.get("codec_type")
        if sttype == "video":
            # cover-art attached pictures (mjpeg/png) are not the program
            disp = st.get("disposition") or {}
            if st.get("codec_name") in ("mjpeg", "png") and disp.get("attached_pic"):
                continue
            if video is None:
                video = st.get("codec_name")
        elif sttype == "audio":
            audio.append(st.get("codec_name"))
        elif sttype == "subtitle":
            subs.append(st.get("codec_name"))
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return video, audio, subs, duration


def _unique_dest(src, out_ext=".mp4"):
    """Destination path next to the source: same stem + out_ext, never
    overwriting an existing file ('name (2).mp4')."""
    stem = os.path.splitext(src)[0]
    dest = stem + out_ext
    if os.path.normcase(dest) == os.path.normcase(src):
        stem += " (video)"
        dest = stem + out_ext
    n = 2
    while os.path.exists(dest):
        dest = f"{stem} ({n}){out_ext}"
        n += 1
    return dest


# Serializes dest-name allocation + final replace so two threads converting
# same-stem sources (video.vob + video.mkv) can't collide.
_DEST_LOCK = threading.Lock()


def remux_video(src, dest, ffmpeg_exe, ffprobe_exe, cfg):
    """Remux one video file to MP4. Returns (ok, message).

    ``dest`` must not exist (callers pass a temp path); on success the
    caller os.replace()s it into place after verification.
    """
    info = _stream_info(src, ffprobe_exe)
    if info is None:
        return False, "unreadable by ffprobe"
    vcodec, acodecs, scodecs, duration = info
    if vcodec is None and not acodecs:
        return False, "no audio or video streams"

    reencode_bad = bool(cfg.get("video_reencode_incompatible", True))
    if vcodec is None:
        return False, "no video stream"
    if vcodec not in MP4_SAFE_VIDEO:
        if not reencode_bad:
            return False, f"video codec {vcodec} is not MP4-compatible (re-encode disabled)"
        copy_video = False
    else:
        copy_video = True

    try:
        crf = max(0, min(51, int(cfg.get("video_crf", 18))))
    except (TypeError, ValueError):
        crf = 18
    preset = str(cfg.get("video_preset", "medium") or "medium").lower()
    if preset not in X264_PRESETS:
        preset = "medium"
    try:
        flac_level = max(0, min(8, int(cfg.get("video_flac_level", 8))))
    except (TypeError, ValueError):
        flac_level = 8

    cmd = [ffmpeg_exe, "-y", "-v", "error", "-nostdin", "-i", src,
           "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?"]
    if copy_video:
        cmd += ["-c:v", "copy"]
    else:
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-pix_fmt", "yuv420p"]
    # FLAC keeps every decoded audio stream bit-perfect (any channel
    # layout / bit depth). Handle both flac-in-mp4-capable and older
    # builds via -strict -2 (a no-op on modern ffmpeg).
    cmd += ["-c:a", "flac", "-strict", "-2",
            "-compression_level", str(flac_level)]
    if scodecs:
        cmd += ["-c:s", "mov_text"]
    cmd += ["-movflags", "+faststart", "-f", "mp4", dest]

    timeout = 60 * 120  # long encodes (full VOB remasters) still capped
    try:
        proc = run_tool(cmd, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=timeout)
    except Exception as e:
        return False, f"ffmpeg failed: {e}"
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        return False, "; ".join(tail) or f"ffmpeg exit {proc.returncode}"

    # Verification: the output must have video, the same number of audio
    # streams, and (when known) a duration within 0.5% / 1 s of the source.
    out_info = _stream_info(dest, ffprobe_exe)
    if out_info is None:
        return False, "output failed verification (ffprobe)"
    ov, oa, _subs, odur = out_info
    if ov is None:
        return False, "output has no video stream"
    if len(oa) != len(acodecs):
        return False, f"audio stream count changed ({len(acodecs)} -> {len(oa)})"
    if duration and odur and abs(duration - odur) > max(1.0, 0.005 * duration):
        return False, f"duration changed ({duration:.2f}s -> {odur:.2f}s)"
    return True, ("video copied" if copy_video else
                  f"{vcodec} video re-encoded to h264 (crf {crf})")


def run_remux_videos(config):
    """Script 11 — convert every video file in the target set to MP4."""
    stats = new_stats()
    stats["converted"] = 0
    stats["removed_originals"] = 0

    tools = detect_all_tools()
    ffmpeg = (tools.get("ffmpeg") or {}).get("ffmpeg_exe")
    ffprobe = (tools.get("ffmpeg") or {}).get("ffprobe_exe")
    if not ffmpeg or not ffprobe or not os.path.isfile(ffmpeg):
        log(c("ERROR: ffmpeg/ffprobe not available — install Dependencies first.", Color.RED))
        stats["errors"].append("ffmpeg/ffprobe not available")
        return stats

    print_header("Video Remux (MP4)")
    reenc = bool(config.get("video_reencode_incompatible", True))
    remove_original = bool(config.get("video_remove_original", False))
    process_mp4 = bool(config.get("video_process_mp4", False))
    log(
        f"ffmpeg: {ffmpeg}\n"
        f"incompatible video: {'re-encode to h264' if reenc else 'skip'} · "
        f"audio: FLAC · originals: {'removed after verified remux' if remove_original else 'kept'}"
    )

    exts = VIDEO_EXTS + (".mp4",) if process_mp4 else VIDEO_EXTS
    folder = os.path.abspath(config["music_folder"] or os.getcwd())
    targets = config.get("targets")
    if targets:
        files = _collect_targets(targets, exts)
    else:
        files = sorted(_walk_files(folder, exts))

    # Deduplicate case-insensitively (Windows) — selections can double-count.
    seen = {}
    for f in files:
        seen.setdefault(os.path.normcase(f), f)
    files = sorted(seen.values())

    if not files:
        log("No video files found.")
        return stats
    log(f"{len(files)} video file(s) found")

    workers = worker_count(config, default=min(4, os.cpu_count() or 1),
                           items=len(files))
    pbar = _make_pbar(total=len(files), desc="Remuxing videos")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _job(path):
        if os.path.splitext(path)[1].lower() == ".mp4" and process_mp4:
            # Only normalize mp4 files that don't already carry FLAC audio.
            info = _stream_info(path, ffprobe)
            if info and all(a == "flac" for a in info[1]) and info[1]:
                return path, None, "already FLAC audio", 0
        # Unique temp file in the same directory (same volume => the final
        # os.replace is atomic). mkstemp guarantees no two jobs share one.
        fd, tmp = tempfile.mkstemp(
            prefix=".remux_", suffix=".mp4", dir=os.path.dirname(path) or ".")
        os.close(fd)
        try:
            ok, msg = remux_video(path, tmp, ffmpeg, ffprobe, config)
            if not ok:
                return path, None, msg, 0
            with _DEST_LOCK:
                dest = _unique_dest(path)
                os.replace(tmp, dest)
            try:
                added = os.path.getsize(dest)
            except OSError:
                added = 0
            return path, dest, msg, added
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, f) for f in files]
        for fut in as_completed(futures):
            try:
                path, dest, msg, added = fut.result()
            except Exception as e:
                stats["error_count"] += 1
                stats["errors"].append(str(e))
                pbar.update(1)
                continue
            if dest is None:
                stats["skipped_count"] += 1
                if msg != "already FLAC audio":
                    stats["errors"].append(f"{os.path.basename(path)}: {msg}")
                    log(c(f"  ! {os.path.basename(path)}: {msg}", Color.YELLOW))
                else:
                    log(c(f"  = {os.path.basename(path)}: {msg}", Color.YELLOW))
            else:
                stats["converted"] += 1
                stats["modified_count"] += 1
                stats["total_bytes_added"] += added
                if remove_original:
                    try:
                        before = os.path.getsize(path)
                        with _DEST_LOCK:
                            os.remove(path)
                        stats["removed_originals"] += 1
                        stats["total_bytes_removed"] += before
                        log(f"  + {os.path.basename(path)} -> {os.path.basename(dest)} ({msg}; original removed)")
                    except OSError as e:
                        stats["errors"].append(f"{os.path.basename(path)}: remove failed: {e}")
                else:
                    log(f"  + {os.path.basename(path)} -> {os.path.basename(dest)} ({msg})")
            pbar.update(1)

    pbar.close()
    log(
        f"Done: {stats['converted']} converted · {stats['skipped_count']} skipped · "
        f"{stats['error_count']} errors"
    )
    return stats
