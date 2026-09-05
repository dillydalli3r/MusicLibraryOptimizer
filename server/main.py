"""
FastAPI backend for MusicLibraryOptimizer v2 — localhost:8000.

Wraps the mlo/* engine as REST + WebSocket for the React frontend:
library (tag-rich, sortable), grading/auditing, tag editing, playback
streaming, playlists (manual + smart, .m3u8), MusicBrainz/LRCLIB/RYM
integrations, and album import.
"""
import os
import sys
import json
import asyncio
import threading
import time
import pathlib
import tempfile
from contextlib import asynccontextmanager
from typing import List, Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mlo import load_config, save_config
from mlo.config import DEFAULT_CONFIG
from mlo import stats as stats_mod

from server import library as lib_mod
from server import playlists as pl_mod
from server import integrations as intg
from server import tagcache
from mlo.paths import SKIP_DIRS

# Captured at startup — worker threads use run_coroutine_threadsafe against
# this loop to relay script progress over the WebSocket (get_event_loop()
# from a worker thread is unreliable and deprecated).
_MAIN_LOOP = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _MAIN_LOOP
    _MAIN_LOOP = asyncio.get_running_loop()
    # Optionally bring up the managed slskd process with the backend.
    if load_config().get("soulseek_autostart", False):
        def _autostart_slskd():
            try:
                from server import soulseek
                ok, msg = soulseek.start()
                if ok:
                    soulseek.wait_until_ready()
                else:
                    print(f"[mlo] slskd autostart skipped: {msg}")
            except Exception as e:
                print(f"[mlo] slskd autostart failed: {e}")
        threading.Thread(target=_autostart_slskd, daemon=True).start()
    yield


app = FastAPI(title="MusicLibraryOptimizer API", version="2.0.0", lifespan=_lifespan)

# Docker/bootstrap: MLO_MUSIC_FOLDER env seeds music_folder when unset.
_MLO_ENV_FOLDER = os.environ.get("MLO_MUSIC_FOLDER")
if _MLO_ENV_FOLDER:
    _cfg = load_config()
    if not _cfg.get("music_folder"):
        _cfg["music_folder"] = os.path.normpath(_MLO_ENV_FOLDER)
        save_config(_cfg)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://localhost:1420",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# The /api/library payload is large (every track's tags + grading details);
# gzip cuts it ~10x for a cheap first-paint win on big libraries.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# --------------------------------------------------------------------------- #
# Progress relay (WebSocket + original hook)
# --------------------------------------------------------------------------- #
progress_clients: set[WebSocket] = set()

orig_hook = stats_mod.progress_hook


def _relay(done, total, desc):
    try:
        if orig_hook:
            orig_hook(done, total, desc)
    except Exception:
        pass
    loop = _MAIN_LOOP
    if loop is None or loop.is_closed():
        return
    for ws in list(progress_clients):
        try:
            asyncio.run_coroutine_threadsafe(
                ws.send_json({"done": done, "total": total, "desc": desc}), loop
            )
        except Exception:
            pass


stats_mod.progress_hook = _relay
stats_mod.tqdm = None


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class RunRequest(BaseModel):
    ids: List[int]
    targets: Optional[List[str]] = None
    force: Optional[dict] = None


class LyricsEmbedRequest(BaseModel):
    path: str
    lyrics: str


class PlaylistCreate(BaseModel):
    name: str
    kind: str = "manual"
    filter: Optional[dict] = None


class PlaylistRename(BaseModel):
    name: str


class PlaylistTracks(BaseModel):
    paths: List[str]
    position: Optional[int] = None


class SmartFilter(BaseModel):
    filter: dict


class MatchRequest(BaseModel):
    album_path: str
    release_id: str


class AssignTagsRequest(BaseModel):
    """Write MB/RYM links to tags. `tracks` maps track path -> {tag: value}."""
    tracks: dict


class ImportCommit(BaseModel):
    """Store MB/RYM links on an imported album. target_dir = album folder
    name under music_folder, or an absolute path already inside it."""
    target_dir: str
    mb_link: Optional[str] = None
    rym_link: Optional[str] = None


class AlbumRemove(BaseModel):
    path: str


# --------------------------------------------------------------------------- #
# Health / config
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/config")
def get_config():
    return load_config()


@app.post("/api/config")
def set_config(cfg: dict):
    ok = save_config(cfg)
    if not ok:
        raise HTTPException(500, "Failed to save config")
    return load_config()


# --------------------------------------------------------------------------- #
# Library
# --------------------------------------------------------------------------- #
def _music_folder(cfg=None):
    cfg = cfg or load_config()
    folder = cfg.get("music_folder") or ""
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, "music_folder not set or not found")
    return folder


def _in_music_folder(p, folder):
    """Path-containment guard shared by every path-taking endpoint.

    Compares normalized absolute paths at directory boundaries so a
    sibling like C:\\Music2 is never treated as being inside C:\\Music.
    """
    try:
        ap = os.path.abspath(os.path.normpath(p))
        af = os.path.abspath(os.path.normpath(folder))
    except (OSError, ValueError, TypeError):
        return False
    if ap == af:
        return True
    common = os.path.commonpath([ap, af])
    return os.path.normcase(common) == os.path.normcase(af)


def _skip_names():
    return {d.lower() for d in SKIP_DIRS}


@app.get("/api/library")
def library():
    """Tag-rich library tree: artists -> albums -> tracks (grade/audit + tags)."""
    cfg = load_config()
    return lib_mod.build_library(cfg)


@app.post("/api/naming/preview")
def naming_preview(req: dict):
    """Evaluate a naming script against a sample track so Settings can show
    what the folder structure would look like before running Organize."""
    from server.naming import DEFAULT_NAMING_SCRIPT, eval_script, track_variables
    script = str(req.get("script") or "").strip() or DEFAULT_NAMING_SCRIPT
    shorter = bool(req.get("short_folder_names"))
    sample = req.get("sample") or {}
    tags = {
        "ALBUMARTIST": str(sample.get("albumartist") or "System of a Down"),
        "ARTIST": str(sample.get("artist") or "System of a Down"),
        "ALBUM": str(sample.get("album") or "Toxicity"),
        "DATE": str(sample.get("date") or "2001-09-04"),
        "ORIGINALDATE": str(sample.get("originaldate") or "2001-08-27"),
        "RELEASETYPE": str(sample.get("releasetype") or "album"),
        "RELEASECOUNTRY": str(sample.get("releasecountry") or "US"),
        "MEDIA": str(sample.get("media") or "CD"),
        "CATALOGNUMBER": str(sample.get("catalognumber") or "CK 62240"),
        "DISCNUMBER": "1", "TRACKNUMBER": "4", "TITLE": str(sample.get("title") or "Psycho"),
        "MUSICBRAINZ_ALBUMID": "f8a44d0f-8241-3bdd-9988-413f28606650",
        "MUSICBRAINZ_ALBUMARTISTID": "cc0b7089-5d5c-4c2e-a48f-7b9c3e5d1a2b",
    }
    try:
        path = eval_script(script, track_variables(tags, tags["RELEASETYPE"]), shorter_ids=shorter)
        return {"path": path, "ok": True}
    except Exception as e:
        return {"path": None, "ok": False, "error": str(e)}


@app.post("/api/open-folder")
def open_folder(req: AlbumRemove):
    """Reveal a folder in the OS file manager (Windows/macOS/Linux)."""
    import subprocess
    import sys as _sys
    p = os.path.normpath(req.path)
    if not os.path.isdir(p):
        raise HTTPException(404, "folder not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "folder outside music folder")
    try:
        if _sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as e:
        raise HTTPException(500, f"could not open folder: {e}")
    return {"ok": True}


@app.get("/api/dependencies")
def dependencies():
    """Installed external tools (.dependencies + PATH) vs. the pinned
    versions the scripts expect, with optional GitHub 'latest' check."""
    from mlo.tools import detect_all_tools, DEPS_DIR
    from mlo.fetchdeps import DISPLAY_NAMES, installed_versions, latest_versions
    tools = detect_all_tools()
    installed = installed_versions()
    latest = {}
    try:
        latest = latest_versions()
    except Exception:
        pass
    out = []
    for key, name in DISPLAY_NAMES.items():
        info = tools.get(key) or {}
        exe = next((v for k, v in info.items() if k.endswith("_exe") and v), None)
        ver = info.get("version")
        iv = installed.get(key)
        lv = latest.get(key)
        present = bool(iv or info)
        if not present:
            state = "missing"
        elif lv and (iv or ver) and lv != (iv or ver):
            state = "update"
        else:
            state = "ok"
        out.append({
            "key": key,
            "name": name,
            "installed_version": iv,
            "latest_version": lv,
            "detected_version": ver,
            "path": exe,
            "state": state,
        })
    return {"deps_dir": str(DEPS_DIR), "tools": out}


class DepsInstallRequest(BaseModel):
    keys: Optional[List[str]] = None


@app.post("/api/dependencies/install")
def dependencies_install(req: DepsInstallRequest):
    """Install/update external tools from their pinned GitHub releases."""
    from mlo import fetchdeps
    wanted = set(req.keys or [])
    results = []
    for key, name in fetchdeps.DISPLAY_NAMES.items():
        if wanted and key not in wanted:
            continue
        try:
            fetchdeps.install_dependency(key, log=lambda m: None)
            results.append({"key": key, "name": name, "ok": True})
        except Exception as e:
            results.append({"key": key, "name": name, "ok": False, "error": str(e)})
    try:
        fetchdeps.refresh_tool_cache()
    except Exception:
        pass
    return {"results": results}


@app.get("/api/album/mbdetect")
def album_mbdetect(path: str = Query(...)):
    """Live scan: find a MusicBrainz release ID in ANY track tag.

    Scans every audio file's raw tags case-insensitively for a key
    containing 'musicbrainz' + 'album' (catches MUSICBRAINZ_ALBUMID and
    variants written by other taggers), and also checks the mapped
    MUSICBRAINZ_ALBUMID / MUSICBRAINZ_RELEASEGROUPID tags directly.
    """
    import re
    from mlo.audio import AudioFile

    p = os.path.normpath(path)
    if not os.path.isdir(p):
        raise HTTPException(404, "album not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "album outside music folder")
    uuid_re = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
    # Recursive: some libraries nest the album folder inside a folder of the
    # same name, so scan subdirectories too. Album tags are uniform across
    # tracks, so checking a handful of audio files is enough — this keeps the
    # scan instant even on huge folders.
    scanned = 0
    MAX_SCAN = 12
    skip = _skip_names()
    for root, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d.lower() not in skip]
        for f in sorted(files):
            if not is_audio_file(f):
                continue
            scanned += 1
            if scanned > MAX_SCAN:
                return {"mbid": None, "truncated": True}
            af = AudioFile(os.path.join(root, f))
            if af.audio is None:
                continue
            for key in ("MUSICBRAINZ_ALBUMID", "MUSICBRAINZ_RELEASEGROUPID"):
                v = af.get_tag(key)
                m = uuid_re.search(str(v)) if v else None
                if m:
                    rel = os.path.relpath(os.path.join(root, f), p)
                    return {"mbid": m.group(0).lower(), "key": key, "track": rel}
            try:
                for k, v in (af.all_tags() or {}).items():
                    kl = str(k).lower()
                    if "musicbrainz" in kl and "album" in kl and "artist" not in kl:
                        m = uuid_re.search(str(v)) if v else None
                        if m:
                            rel = os.path.relpath(os.path.join(root, f), p)
                            return {"mbid": m.group(0).lower(), "key": k, "track": rel}
            except Exception:
                continue
    return {"mbid": None, "scanned": scanned}


@app.get("/api/album")
def get_album(path: str = Query(...)):
    p = os.path.normpath(path)
    if not os.path.isdir(p):
        raise HTTPException(404, "album not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "album outside music folder")
    res = lib_mod.build_album(p, load_config())
    if res is None:
        raise HTTPException(404, "no audio files")
    return res


@app.get("/api/artist")
def get_artist(path: str = Query(...)):
    p = os.path.normpath(path)
    if not os.path.isdir(p):
        raise HTTPException(404, "artist not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "artist outside music folder")
    cfg = load_config()
    albums = lib_mod._find_albums(p)
    direct = [alb for alb in sorted(albums)
              if os.path.dirname(alb).lower() == p.lower()]
    albums_data = lib_mod.build_albums_parallel(direct, cfg)
    # Display name: the tag-derived artist (folders carry an MBID suffix).
    display_name = next((a.get("album_artist") for a in albums_data
                         if a.get("album_artist")), None)
    return {
        "path": p.replace("\\", "/"),
        "name": os.path.basename(p),
        "display_name": display_name,
        "albums": albums_data,
        "aggregate": lib_mod._aggregate_albums(albums_data),
    }


# --------------------------------------------------------------------------- #
# Streaming / tags
# --------------------------------------------------------------------------- #
_CTYPES = {
    ".flac": "audio/flac", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    # Music videos live in .mp4 too — video/mp4 demuxes fine in <audio>
    # elements and is required for <video> playback.
    ".mp4": "video/mp4", ".ogg": "audio/ogg", ".opus": "audio/ogg",
    ".wav": "audio/wav", ".aac": "audio/aac",
}


@app.get("/api/stream")
def stream(path: str = Query(...)):
    p = os.path.normpath(path)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "file outside music folder")
    ctype = _CTYPES.get(os.path.splitext(p)[1].lower(), "application/octet-stream")
    return FileResponse(p, media_type=ctype, headers={"Accept-Ranges": "bytes"})


@app.get("/api/tags")
def get_tags(path: str = Query(...)):
    """Read-only tag/lyrics/cover view (tag *writing* was removed — the
    engine's grading/auditing scripts own all tag writes now)."""
    from mlo.audio import AudioFile
    p = os.path.normpath(path)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "file outside music folder")
    af = AudioFile(p)
    if af.audio is None:
        raise HTTPException(500, af.error or "unreadable")
    tags = af.all_tags()
    try:
        lyr = af.get_lyrics()
    except Exception:
        lyr = None
    cover = None
    try:
        alb = os.path.dirname(p)
        for cand in ("cover.jpg", "cover.jpeg", "cover.png", "cover.jxl", "cover.webp", "cover.bmp"):
            if os.path.isfile(os.path.join(alb, cand)):
                cover = os.path.join(alb, cand).replace("\\", "/")
                break
    except Exception:
        pass
    return {"path": p.replace("\\", "/"), "tags": tags, "lyrics": lyr, "cover": cover}


@app.get("/api/cover")
def get_cover(request: Request, album: str = Query(...), file: Optional[str] = Query(None),
              color: int = Query(0)):
    """Serve an album's cover art, cached with ETag; ?color=1 returns the
    dominant color instead of the image bytes (UI tinting)."""
    alb = os.path.normpath(album)
    if not os.path.isdir(alb):
        raise HTTPException(404, "album not found")
    if not _in_music_folder(alb, _music_folder()):
        raise HTTPException(400, "album outside music folder")
    if color:
        c = tagcache.cover_color(alb, file)
        if c is None:
            raise HTTPException(404, "no cover")
        return {"color": c, "album": alb.replace("\\", "/")}
    data, ctype, etag = tagcache.cover_bytes(alb, file)
    if data is None:
        raise HTTPException(404, "no cover")
    from fastapi.responses import Response
    headers = {"Cache-Control": "public, max-age=3600", "Accept-Ranges": "bytes"}
    if etag:
        headers["ETag"] = f'"{etag}"'
        inm = request.headers.get("if-none-match")
        if inm and inm.strip('"') == etag:
            return Response(content=b"", status_code=304, headers=headers)
    return Response(content=data, media_type=ctype, headers=headers)


@app.post("/api/cover")
async def upload_cover(album: str = Query(...), file: UploadFile = File(...),
                       track: Optional[str] = Query(None)):
    """Upload cover art. Without `track` this replaces the album's cover.*;
    with `track=<audio filename>` it writes a per-track sidecar cover named
    after the track stem (e.g. '01 - Song.jpg')."""
    alb = os.path.normpath(album)
    if not os.path.isdir(alb):
        raise HTTPException(404, "album not found")
    if not _in_music_folder(alb, _music_folder()):
        raise HTTPException(400, "album outside music folder")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".jxl", ".webp", ".bmp"):
        ext = ".jpg"
    stem = "cover"
    if track:
        tstem = os.path.splitext(os.path.basename(track))[0].strip()
        tstem = re_safe_filename(tstem).strip().rstrip(".") or "cover"
        stem = tstem
    data = await file.read()
    return _write_cover_bytes(alb, stem, ext, data)


def _write_cover_bytes(alb: str, stem: str, ext: str, data: bytes):
    """Atomically write cover bytes as <stem><ext> into the album folder
    and bust the cover cache. Shared by upload and download-from-URL."""
    dest = os.path.join(alb, f"{stem}{ext}")
    fd, tmp = tempfile.mkstemp(prefix=".cover_tmp_", suffix=ext, dir=alb)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, dest)
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise HTTPException(500, str(e))
    tagcache.invalidate_all()
    return {"ok": True, "path": dest.replace("\\", "/")}


def _sniff_image_ext(data: bytes, content_type: str) -> str:
    """File-extension for image bytes, from magic numbers, then the
    Content-Type, defaulting to .jpg (the common cover-art case)."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"\xff\x0a" or data[:12] == b"\x00\x00\x00\x0cJXL ":
        return ".jxl"
    if data[:2] == b"BM":
        return ".bmp"
    ct = (content_type or "").split("/")[1].strip().lower()
    if ct in ("jpeg", "jpg"):
        return ".jpg"
    if ct in ("png", "webp", "jxl", "bmp"):
        return f".{ct}"
    return ".jpg"


@app.get("/api/cover/search")
async def cover_search(artist: str = Query(""), album: str = Query(""),
                       limit: int = Query(40, ge=1, le=100)):
    """Search covers.musichoarders.xyz (aggregates Apple Music, Deezer,
    Qobuz, Tidal, Discogs, ...) for album covers matching artist/album."""
    if not artist.strip() and not album.strip():
        raise HTTPException(400, "artist or album is required")
    try:
        results = await asyncio.to_thread(
            intg.cover_search, artist.strip(), album.strip(), limit)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"cover search failed: {e}")
    return {"results": results}


@app.post("/api/cover/fromurl")
async def cover_from_url(album: str = Query(...), url: str = Query(...),
                         track: Optional[str] = Query(None)):
    """Download a cover image from a URL (e.g. a COV search result) and
    store it like an uploaded cover (album cover.* or per-track sidecar)."""
    alb = os.path.normpath(album)
    if not os.path.isdir(alb):
        raise HTTPException(404, "album not found")
    if not _in_music_folder(alb, _music_folder()):
        raise HTTPException(400, "album outside music folder")
    try:
        data, ctype = await asyncio.to_thread(intg.fetch_image_bytes, url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"cover download failed: {e}")
    if not data:
        raise HTTPException(502, "empty image response")
    stem = "cover"
    if track:
        tstem = os.path.splitext(os.path.basename(track))[0].strip()
        tstem = re_safe_filename(tstem).strip().rstrip(".") or "cover"
        stem = tstem
    return _write_cover_bytes(alb, stem, _sniff_image_ext(data, ctype), data)


@app.get("/api/videos/scan")
def videos_scan(path: str = Query(None)):
    """List video files (non-audio containers) under an album or the whole
    library, with codec/duration info from ffprobe, so the UI can offer
    one-click remuxing."""
    from mlo.remux import VIDEO_EXTS, _stream_info
    from mlo.tools import detect_all_tools

    folder = _music_folder()
    root = os.path.normpath(path) if path else folder
    if not os.path.isdir(root):
        raise HTTPException(404, "folder not found")
    if not _in_music_folder(root, folder):
        raise HTTPException(400, "folder outside music folder")
    ffprobe = (detect_all_tools().get("ffmpeg") or {}).get("ffprobe_exe")
    skip = _skip_names()
    out = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip]
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() not in VIDEO_EXTS:
                continue
            full = os.path.join(r, f)
            info = _stream_info(full, ffprobe) if ffprobe else None
            out.append({
                "path": full.replace("\\", "/"),
                "album": r.replace("\\", "/"),
                "file": f,
                "size": os.path.getsize(full),
                "video_codec": info[0] if info else None,
                "audio_codecs": info[1] if info else [],
                "duration": info[3] if info else None,
                "mp4_safe": (info[0] in ("h264", "hevc", "mpeg4", "av1", "vp9")) if info else None,
            })
    return {"videos": out}


@app.post("/api/lyrics/embed")
def lyrics_embed(req: LyricsEmbedRequest):
    """Write ONLY the embedded LYRICS tag (the last tag-write path the UI
    still needs; everything else is grading-script territory)."""
    from mlo.audio import AudioFile
    p = os.path.normpath(req.path)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "file outside music folder")
    af = AudioFile(p)
    if af.audio is None:
        raise HTTPException(500, af.error or "unreadable")
    if not af.set_lyrics(req.lyrics or ""):
        raise HTTPException(500, af.error or "lyrics write failed")
    tagcache.invalidate_path(p)
    return {"ok": True}


class LyricsAiRequest(BaseModel):
    mode: str  # "clean" | "repair" | "wordsync"
    text: str = ""
    artist: str = ""
    track: str = ""
    candidates: Optional[List[str]] = None


@app.post("/api/lyrics/ai")
async def lyrics_ai(req: LyricsAiRequest):
    """AI-assisted lyrics tooling.

    * wordsync - deterministic line→word sync (ELRC), no AI needed.
    * clean   - strip ads/watermarks/garbage from raw lyrics via LLM.
    * repair  - fill/fix lyric lines using LRCLIB candidate lines as
                evidence via LLM.
    """
    cfg = load_config()
    text = req.text or ""
    if req.mode == "wordsync":
        if not text.strip():
            raise HTTPException(400, "no lyrics text provided")
        from server.ai import wordsync_lrc
        return {"mode": "wordsync", "result": wordsync_lrc(text)}

    from server import ai as ai_mod
    if not ai_mod.ai_configured(cfg):
        raise HTTPException(400, "AI is not configured — set base URL and model in Settings → AI")
    if req.mode == "clean":
        if not text.strip():
            raise HTTPException(400, "no lyrics text provided")
        result = await asyncio.to_thread(ai_mod.lyrics_clean, cfg, text)
    elif req.mode == "repair":
        if not text.strip() and not req.candidates:
            raise HTTPException(400, "repair needs lyrics text and/or candidates")
        result = await asyncio.to_thread(ai_mod.lyrics_repair, cfg, text, req.candidates or [], req.artist, req.track)
    else:
        raise HTTPException(400, f"unknown mode: {req.mode}")
    return {"mode": req.mode, "result": result}


# --------------------------------------------------------------------------- #
# Run scripts
# --------------------------------------------------------------------------- #
@app.post("/api/run")
def run_scripts(req: RunRequest):
    from mlo import (
        run_format_lyrics, run_format_cues, run_optimize_flacs, run_grade_library,
        run_process_images, run_audit_library, run_auto_tagging,
    )
    from mlo.loudness import run_calc_dr_replaygain
    try:
        from mlo.accurip import run_generate_accurip
    except ImportError:
        run_generate_accurip = None
    try:
        from mlo.format_all import run_format_all
    except ImportError:
        run_format_all = None
    try:
        from mlo.remux import run_remux_videos
    except ImportError:
        run_remux_videos = None
    try:
        from mlo.audiometa import run_analyze_audiometa
    except ImportError:
        run_analyze_audiometa = None

    RUNNERS = {
        1: run_format_lyrics, 2: run_format_cues, 3: run_optimize_flacs,
        4: run_grade_library, 5: run_process_images, 6: run_audit_library,
        7: run_calc_dr_replaygain, 8: run_auto_tagging, 9: run_generate_accurip,
        10: run_format_all, 11: run_remux_videos, 12: run_analyze_audiometa,
    }
    cfg = load_config()
    if req.targets:
        cfg["targets"] = [os.path.normpath(t) for t in req.targets]
    # Per-script options default from saved config; the request can override.
    f = req.force or {}
    cfg["force_reencode_flac"] = bool(f.get("flac", cfg.get("force_reencode_flac")))
    cfg["force_reencode_images"] = bool(f.get("images", cfg.get("force_reencode_images")))
    cfg["force_audit"] = bool(f.get("audit", cfg.get("force_audit")))
    cfg["force_lyrics"] = bool(f.get("lyrics", cfg.get("force_lyrics")))
    cfg["force_cue"] = bool(f.get("cue", cfg.get("force_cue")))
    cfg["force_dr_replaygain"] = bool(f.get("dr", cfg.get("force_dr_replaygain")))
    cfg["force_auto_tag"] = bool(f.get("autotag", cfg.get("force_auto_tag")))
    cfg["force_accurip"] = bool(f.get("accurip", cfg.get("force_accurip")))
    cfg["force_audiometa"] = bool(f.get("audiometa", cfg.get("force_audiometa")))
    # image-option overrides (subset of run_process_images knobs)
    for key in ("rename_to_cover", "reencode_to_jxl", "images_convert_to_jpeg",
                "images_convert_lossless_to_png", "convert_jxl_back", "remove_alpha",
                "jpeg_progressive", "cover_resize_enabled", "cover_crop_enabled",
                "cover_target_size", "cover_jpeg_quality", "jpegxl_effort",
                "jpegxl_distance", "png_optimization_level"):
        if key in f:
            cfg[key] = f[key]

    for i in req.ids:
        if i not in RUNNERS or RUNNERS[i] is None:
            raise HTTPException(400, f"runner {i} not available")

    results = []
    for i in req.ids:
        runner = RUNNERS[i]
        try:
            s = runner(cfg)
            results.append({"id": i, "name": runner.__name__, "stats": s})
        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append({"id": i, "error": str(e)})
    tagcache.invalidate_all()
    return {"results": results}


# --------------------------------------------------------------------------- #
# Playlists
# --------------------------------------------------------------------------- #
@app.get("/api/playlists")
def playlists_list():
    return pl_mod.list_playlists()


@app.post("/api/playlists")
def playlists_create(req: PlaylistCreate):
    if not req.name.strip():
        raise HTTPException(400, "name required")
    pid = pl_mod.create_playlist(req.name.strip(), req.kind, req.filter)
    return pl_mod.get_playlist(pid)


@app.get("/api/playlists/{pid}")
def playlists_get(pid: int):
    pl = pl_mod.get_playlist(pid)
    if pl is None:
        raise HTTPException(404, "playlist not found")
    return pl


@app.patch("/api/playlists/{pid}")
def playlists_rename(pid: int, req: PlaylistRename):
    if not pl_mod.rename_playlist(pid, req.name.strip()):
        raise HTTPException(404, "playlist not found")
    return pl_mod.get_playlist(pid)


@app.delete("/api/playlists/{pid}")
def playlists_delete(pid: int):
    if not pl_mod.delete_playlist(pid):
        raise HTTPException(404, "playlist not found")
    return {"ok": True}


@app.post("/api/playlists/{pid}/tracks")
def playlists_add(pid: int, req: PlaylistTracks):
    if pl_mod.get_playlist(pid) is None:
        raise HTTPException(404, "playlist not found")
    n = pl_mod.add_tracks(pid, [os.path.normpath(p) for p in req.paths], req.position)
    return {"added": n}


@app.put("/api/playlists/{pid}/tracks")
def playlists_order(pid: int, req: PlaylistTracks):
    """Full reorder: body paths replace the playlist order entirely."""
    if pl_mod.get_playlist(pid) is None:
        raise HTTPException(404, "playlist not found")
    pl_mod.set_order(pid, [os.path.normpath(p) for p in req.paths])
    return {"ok": True}


@app.delete("/api/playlists/{pid}/tracks")
def playlists_remove(pid: int, req: PlaylistTracks):
    if pl_mod.get_playlist(pid) is None:
        raise HTTPException(404, "playlist not found")
    pl_mod.remove_tracks(pid, [os.path.normpath(p) for p in req.paths])
    return {"ok": True}


@app.post("/api/playlists/{pid}/filter")
def playlists_filter(pid: int, req: SmartFilter):
    pl = pl_mod.get_playlist(pid)
    if pl is None:
        raise HTTPException(404, "playlist not found")
    if pl["kind"] != "smart":
        raise HTTPException(400, "not a smart playlist")
    pl_mod.set_smart_filter(pid, req.filter)
    return pl_mod.get_playlist(pid)


@app.post("/api/playlists/{pid}/evaluate")
def playlists_evaluate(pid: int):
    pl = pl_mod.get_playlist(pid)
    if pl is None:
        raise HTTPException(404, "playlist not found")
    if pl["kind"] != "smart":
        raise HTTPException(400, "not a smart playlist")
    library = lib_mod.build_library(load_config())
    hits = pl_mod.evaluate_smart(pid, library)
    return {"paths": hits or []}


@app.get("/api/playlists/{pid}/export")
def playlists_export(pid: int):
    content = pl_mod.export_m3u8(pid)
    if content is None:
        raise HTTPException(404, "playlist not found")
    pl = pl_mod.get_playlist(pid)
    name = re_safe_filename(pl["name"]) or "playlist"
    return PlainTextResponse(
        content,
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{name}.m3u8"'},
    )


@app.post("/api/playlists/import")
async def playlists_import(name: str = Query(...), file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    base = load_config().get("music_folder") or os.getcwd()
    pid = pl_mod.import_m3u8(name.strip() or file.filename or "imported", content, base)
    return pl_mod.get_playlist(pid)


def re_safe_filename(name):
    import re
    return re.sub(r'[\\/*?:"<>|]', "_", name)


# --------------------------------------------------------------------------- #
# MusicBrainz / LRCLIB / RYM
# --------------------------------------------------------------------------- #
@app.get("/api/mb/release")
def mb_release_query(mbid: str = Query(...)):
    """Release lookup by ID or full URL (query param — URLs contain slashes
    and cannot travel inside the path segment)."""
    rid = intg._mbid(mbid)
    if not rid:
        raise HTTPException(400, "invalid MusicBrainz ID or URL")
    try:
        return intg.release_lookup(rid)
    except Exception as e:
        raise HTTPException(502, f"MusicBrainz lookup failed: {e}")


@app.get("/api/mb/release-genres")
def mb_release_genres_query(mbid: str = Query(...), limit: Optional[int] = Query(None)):
    rid = intg._mbid(mbid)
    if not rid:
        raise HTTPException(400, "invalid MusicBrainz ID or URL")
    try:
        release = intg.release_lookup(rid)
        return intg.genre_cascade(release, limit=max(0, int(limit)) if limit else None)
    except Exception as e:
        raise HTTPException(502, f"MusicBrainz genre lookup failed: {e}")


@app.get("/api/mb/release/{mbid}")
def mb_release(mbid: str):
    rid = intg._mbid(mbid)
    if not rid:
        raise HTTPException(400, "invalid MusicBrainz ID or URL")
    try:
        return intg.release_lookup(rid)
    except Exception as e:
        raise HTTPException(502, f"MusicBrainz lookup failed: {e}")


@app.get("/api/mb/release/{mbid}/genres")
def mb_release_genres(mbid: str):
    rid = intg._mbid(mbid)
    if not rid:
        raise HTTPException(400, "invalid MusicBrainz ID or URL")
    try:
        release = intg.release_lookup(rid)
        return intg.genre_cascade(release)
    except Exception as e:
        raise HTTPException(502, f"MusicBrainz genre lookup failed: {e}")


@app.get("/api/mb/search/releases")
def mb_search_releases(q: str = Query(..., min_length=1), limit: int = 10,
                        mode: str = Query("release")):
    """Search MusicBrainz releases: mode = release | track | catno | barcode."""
    if mode not in ("release", "track", "catno", "barcode"):
        raise HTTPException(400, "mode must be release, track, catno or barcode")
    try:
        return intg.search_releases(q, limit, mode)
    except Exception as e:
        raise HTTPException(502, f"MusicBrainz search failed: {e}")


@app.get("/api/mb/search/artists")
def mb_search_artists(q: str = Query(..., min_length=1), limit: int = 5):
    try:
        return intg.search_artists(q, limit)
    except Exception as e:
        raise HTTPException(502, f"MusicBrainz search failed: {e}")


def _scan_album_tracks(album_dir):
    """Recursively list audio files in an album folder with tags + tech info."""
    tracks = []
    skip = _skip_names()
    for root, dirs, files in os.walk(album_dir):
        dirs[:] = [d for d in dirs if d.lower() not in skip]
        for f in sorted(files):
            if not is_audio_file(f):
                continue
            path = os.path.join(root, f)
            tags, tech = tagcache.read_track(path, None)
            duration = float(tech.get("length") or 0) or None
            tn = tags.get("TRACKNUMBER")
            dn = tags.get("DISCNUMBER")
            try:
                tn = int(str(tn).split("/")[0])
            except (TypeError, ValueError):
                tn = None
            try:
                dn = int(str(dn).split("/")[0])
            except (TypeError, ValueError):
                dn = None
            tracks.append({
                "path": path.replace("\\", "/"),
                "file": os.path.relpath(path, album_dir).replace("\\", "/"),
                "tracknumber": tn,
                "discnumber": dn,
                "title": tags.get("TITLE"),
                "artist": tags.get("ARTIST"),
                "duration": duration,
                "tags": tags,
                "tech": tech,
            })
    return tracks


@app.post("/api/mb/match")
def mb_match(req: MatchRequest):
    """Suggest release track/disc matches for local files in an album."""
    album_dir = os.path.normpath(req.album_path)
    if not os.path.isdir(album_dir):
        raise HTTPException(404, "album not found")
    rid = intg._mbid(req.release_id)
    if not rid:
        raise HTTPException(400, "invalid release ID")
    try:
        release = intg.release_lookup(rid)
    except Exception as e:
        raise HTTPException(502, f"MusicBrainz lookup failed: {e}")

    from mlo.audio import AudioFile
    local_tracks = _scan_album_tracks(album_dir)
    for lt in local_tracks:
        lt.pop("tags", None)
        lt.pop("tech", None)
    return {"release": release, "suggestions": intg.match_tracks(local_tracks, release)}


@app.post("/api/mb/assign")
def mb_assign(req: AssignTagsRequest):
    """Write per-track MB/RYM link tags. tracks: {path: {TAG: value}}."""
    from mlo.audio import AudioFile
    errors = []
    changed = 0
    folder = _music_folder()
    for p, tag_map in req.tracks.items():
        fp = os.path.normpath(p)
        if not os.path.isfile(fp):
            errors.append(f"{p}: not found")
            continue
        if not _in_music_folder(fp, folder):
            errors.append(f"{p}: outside music folder")
            continue
        af = AudioFile(fp)
        if af.audio is None:
            errors.append(f"{p}: {af.error or 'unreadable'}")
            continue
        for k, v in tag_map.items():
            try:
                if v is None or str(v) == "":
                    if not af.delete_tag(k):
                        errors.append(f"{p} {k}: {af.error or 'delete failed'}")
                elif not af.set_tag(k, str(v)):
                    errors.append(f"{p} {k}: {af.error or 'write failed'}")
            except Exception as e:
                errors.append(f"{p} {k}: {e}")
        changed += 1
        tagcache.invalidate_path(fp)
    if errors:
        raise HTTPException(500, "; ".join(errors))
    return {"ok": True, "changed": changed}


@app.get("/api/lyrics/search")
async def lyrics_search(
    artist: str = Query(...), track: str = Query(...),
    album: str = Query(None), duration: int = Query(None),
):
    try:
        return await asyncio.to_thread(
            intg.lrclib_search, artist, track, album, duration
        )
    except Exception as e:
        raise HTTPException(502, f"lrclib search failed: {e}")


@app.get("/api/lyrics/get")
async def lyrics_get(
    artist: str = Query(""), track: str = Query(...),
    album: str = Query(None), duration: int = Query(None),
):
    try:
        res = await asyncio.to_thread(intg.lrclib_get, artist, track, album, duration)
        if res is None:
            return JSONResponse({"found": False}, status_code=404)
        return res
    except Exception as e:
        raise HTTPException(502, str(e))


class LyricsWriteRequest(BaseModel):
    path: str
    lrc: str = ""
    source: str = "lrclib"


@app.post("/api/lyrics/write")
def lyrics_write(req: LyricsWriteRequest):
    """Write .lrc sidecar atomically, canonicalized via mlo.lyrics."""
    from mlo.lyrics import _format_for_storage
    p = os.path.normpath(req.path)
    if not os.path.isfile(p):
        raise HTTPException(404, "audio file not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "file outside music folder")
    lrc_path = os.path.splitext(p)[0] + ".lrc"
    cfg = load_config()
    try:
        final = _format_for_storage(req.lrc, cfg, optimize=True, is_for_lrc=True)
    except Exception:
        final = req.lrc
    fd, tmp = tempfile.mkstemp(prefix=".lrc_tmp_", suffix=".lrc", dir=os.path.dirname(p) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(final)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, lrc_path)
    except Exception as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise HTTPException(500, str(e))
    tagcache.invalidate_path(lrc_path)
    return {"ok": True, "lrc": lrc_path.replace("\\", "/")}


@app.get("/api/rym/validate")
def rym_validate(url: str = Query(...)):
    return {"valid": intg.parse_rym_album_url(url) is not None}


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
def is_audio_file(name):
    return os.path.splitext(name)[1].lower() in {
        ".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".wav", ".aac",
    }


@app.post("/api/album/remove")
def album_remove(req: AlbumRemove):
    """Remove an album from the library by moving it into
    <music_folder>/.mlo_trash/ (recoverable, nothing is deleted)."""
    import shutil
    cfg = load_config()
    folder = cfg.get("music_folder") or ""
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, "music_folder not set or not found")
    p = os.path.normpath(req.path)
    if not os.path.isdir(p):
        raise HTTPException(404, "album not found")
    if not _in_music_folder(p, folder):
        raise HTTPException(400, "album outside music folder")
    trash = os.path.normpath(os.path.join(folder, ".mlo_trash"))
    os.makedirs(trash, exist_ok=True)
    name = os.path.basename(p) or "album"
    dest = os.path.normpath(os.path.join(trash, name))
    n = 2
    while os.path.exists(dest):
        dest = os.path.normpath(os.path.join(trash, f"{name} ({n})"))
        n += 1
    shutil.move(p, dest)
    tagcache.invalidate_all()
    return {"ok": True, "trash": dest.replace("\\", "/")}


@app.get("/api/album/scan-tracks")
def album_scan_tracks(path: str = Query(...)):
    """Direct folder scan: audio files with tags (independent of the library)."""
    p = os.path.normpath(path)
    if not os.path.isdir(p):
        raise HTTPException(404, "folder not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "folder outside music folder")
    return {"path": p.replace("\\", "/"), "tracks": _scan_album_tracks(p)}


class OrganizeRequest(BaseModel):
    paths: List[str]
    dry_run: bool = False


class BeetsImportRequest(BaseModel):
    paths: List[str]


@app.get("/api/beets/status")
def beets_status():
    """Vendored-beets availability and the config that would be generated."""
    from server import beetscfg
    version = beetscfg.beets_available()
    cfg = load_config()
    return {
        "installed": bool(version),
        "version": version,
        "db": beetscfg.db_path(),
        "config": beetscfg.generate_config(cfg),
    }


@app.post("/api/beets/install")
def beets_install():
    """Vendor beets into .dependencies (pip-managed, like other tools)."""
    from mlo import fetchdeps
    fetchdeps.install_dependency("beets", log=lambda m: None)
    return {"ok": True, "version": fetchdeps.PINNED["beets"]["version"]}


@app.post("/api/beets/import")
def beets_import(req: BeetsImportRequest):
    """Tag albums with managed beets (MusicBrainz match + Picard-parity
    plugin: locale aliases, work/movement, release-type caps), then
    optionally re-organize file placement with the naming script."""
    from server import beetscfg
    folder = _music_folder()
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, "music_folder not set or not found")
    valid = []
    for p in req.paths:
        np = os.path.normpath(p)
        if not os.path.isdir(np):
            raise HTTPException(404, f"album not found: {p}")
        if not _in_music_folder(np, folder):
            raise HTTPException(400, f"album outside music folder: {p}")
        valid.append(np)
    cutoff = time.time()
    ok, output = beetscfg.run_beets_import(valid)
    if not ok:
        raise HTTPException(500, output[-2000:])
    tagcache.invalidate_all()
    organized = None
    if load_config().get("beets_organize_after", False):
        # beets already placed files per the naming script; organize only the
        # album folders this import touched (fresh mtimes under music folder)
        # so stale-file failures on the pre-import paths are impossible.
        from mlo.stats import _find_albums
        fresh = [d for d in _find_albums(folder)
                 if os.path.getmtime(d) >= cutoff - 1]
        if fresh:
            res = organize(OrganizeRequest(paths=fresh, dry_run=False))
            organized = res.get("results")
    return {"ok": True, "output": output[-4000:], "organized": organized}


class SoulseekSearchRequest(BaseModel):
    query: str


class SoulseekDownloadRequest(BaseModel):
    username: str
    files: List[dict]  # [{filename, size}]


@app.get("/api/soulseek/status")
def soulseek_status():
    """Managed slskd availability, running state, login and download dir."""
    from server import soulseek
    cfg = load_config()
    running = soulseek.is_running() or soulseek.web_up(cfg)
    logged_in = None
    server = None
    if running:
        try:
            server = soulseek.server_state()
            logged_in = bool(server and server.get("isLoggedIn"))
        except Exception:
            logged_in = False
    return {
        "installed": soulseek.slskd_installed(),
        "running": running,
        "logged_in": logged_in,
        "server": server,
        "download_dir": soulseek.download_dir(cfg),
        "web_port": int(cfg.get("soulseek_web_port") or 5030),
    }


@app.post("/api/soulseek/start")
def soulseek_start():
    """Start the managed slskd process and wait for its web API."""
    from server import soulseek
    ok, msg = soulseek.start()
    if not ok:
        raise HTTPException(400, msg)
    if not soulseek.wait_until_ready():
        raise HTTPException(504, "slskd did not become ready in time")
    return {"ok": True, "message": msg}


@app.post("/api/soulseek/stop")
def soulseek_stop():
    from server import soulseek
    stopped = soulseek.stop()
    if not stopped:
        return {"ok": True, "message": "not running"}
    return {"ok": True, "message": "stopped"}


@app.post("/api/soulseek/search")
def soulseek_search(req: SoulseekSearchRequest):
    """Start a Soulseek search; returns an id to poll for results."""
    from server import soulseek
    if not (soulseek.is_running() or soulseek.web_up(load_config())):
        raise HTTPException(400, "slskd is not running — start it first")
    if not req.query.strip():
        raise HTTPException(400, "empty query")
    return {"id": soulseek.search(req.query.strip())}


@app.get("/api/soulseek/search/{search_id}")
def soulseek_search_results(search_id: str):
    from server import soulseek
    if not soulseek.is_running():
        raise HTTPException(400, "slskd is not running")
    return soulseek.search_results(search_id)


@app.post("/api/soulseek/download")
def soulseek_download(req: SoulseekDownloadRequest):
    """Queue files from a user for download into the download dir."""
    from server import soulseek
    if not (soulseek.is_running() or soulseek.web_up()):
        raise HTTPException(400, "slskd is not running — start it first")
    if not req.username or not req.files:
        raise HTTPException(400, "username and files required")
    soulseek.enqueue_download(req.username, req.files)
    return {"ok": True, "queued": len(req.files)}


@app.get("/api/soulseek/downloads")
def soulseek_downloads():
    """Download transfer tree (per user / directory / file with state)."""
    from server import soulseek
    if not soulseek.is_running():
        return {"downloads": []}
    return {"downloads": soulseek.downloads_state()}


@app.post("/api/soulseek/import")
def soulseek_import():
    """Move completed downloads from the download dir into the library,
    one album folder per shared folder."""
    from server import soulseek
    try:
        moved = soulseek.import_completed()
    except ValueError as e:
        raise HTTPException(400, str(e))
    tagcache.invalidate_all()
    return {"ok": True, "moved": moved}


@app.get("/api/soulseek/user/{username}")
def soulseek_user(username: str):
    """Remote user profile info (speed, slots, shared file count)."""
    from server import soulseek
    if not soulseek.is_running():
        raise HTTPException(400, "slskd is not running")
    try:
        return soulseek.user_info(username)
    except Exception as e:
        raise HTTPException(502, f"user info failed: {e}")


@app.post("/api/organize")
def organize(req: OrganizeRequest):
    """Rename/move albums according to the configured naming script.

    For each album: evaluate the script per track, move the audio files,
    move same-stem sidecars (.lrc/.cue/...) next to their track, move
    leftover album files (cover art etc.) to the new album root, and prune
    emptied folders. Nothing leaves the music folder.
    """
    import shutil
    from server.naming import DEFAULT_NAMING_SCRIPT, eval_script, track_variables

    cfg = load_config()
    folder = cfg.get("music_folder") or ""
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, "music_folder not set or not found")
    script = (cfg.get("naming_script") or "").strip() or DEFAULT_NAMING_SCRIPT
    shorter = bool(cfg.get("short_folder_names", False))

    results = []
    for album_dir in req.paths:
        p = os.path.normpath(album_dir)
        if not os.path.isdir(p):
            results.append({"path": album_dir, "error": "album not found"})
            continue
        if not _in_music_folder(p, folder):
            results.append({"path": album_dir, "error": "album outside music folder"})
            continue
        tracks = _scan_album_tracks(p)
        if not tracks:
            results.append({"path": album_dir, "error": "no audio files found"})
            continue

        # album-level tags from the first tagged track
        meta_tags = next((t["tags"] for t in tracks if t["tags"].get("TITLE") or t["tags"].get("ALBUM")), tracks[0]["tags"])
        release_type = meta_tags.get("RELEASETYPE")
        if not release_type and meta_tags.get("MUSICBRAINZ_ALBUMID"):
            try:
                rel = intg.release_lookup(meta_tags["MUSICBRAINZ_ALBUMID"])
                release_type = rel.get("release_type")
            except Exception:
                release_type = None

        moves = []  # (src, dst)
        new_root = None
        errors = []
        for t in tracks:
            vars_ = track_variables(t["tags"], release_type=release_type)
            rel = eval_script(script, vars_, shorter_ids=shorter)
            if not rel:
                errors.append(f"{t['file']}: script evaluated to empty path")
                continue
            dst = os.path.normpath(os.path.join(folder, rel))
            if not _in_music_folder(dst, folder):
                errors.append(f"{t['file']}: destination outside music folder")
                continue
            src = os.path.normpath(t["path"])
            if os.path.normcase(src) == os.path.normcase(dst):
                continue
            stem, ext = os.path.splitext(dst)
            n = 2
            while os.path.exists(dst) and os.path.normcase(dst) != os.path.normcase(src):
                dst = f"{stem} ({n}){ext}"
                n += 1
            moves.append((src, dst))
            if new_root is None:
                new_root = os.path.dirname(dst)

        if new_root is None:
            results.append({"path": album_dir, "error": "nothing to move (already organized?)", "errors": errors})
            continue

        # companion sidecars: same stem as an audio file, different extension.
        # Matches exact stems ("04 - Psycho.jpg") AND extended stems
        # ("04 - Psycho.cover.jpg" / "04 - Psycho - front.jpg").
        sidecar_moves = []
        for src, dst in moves:
            sdir, sname = os.path.split(src)
            sstem = os.path.splitext(sname)[0].lower()
            ddir, dname = os.path.split(dst)
            dstem = os.path.splitext(dname)[0]
            try:
                for f in os.listdir(sdir):
                    fpath = os.path.join(sdir, f)
                    fstem, fext = os.path.splitext(f)
                    if f.lower() == sname.lower() or os.path.isdir(fpath):
                        continue
                    if fext.lower() not in (".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".wav", ".aac"):
                        fstem_l = fstem.lower()
                        if fstem_l == sstem or fstem_l.startswith(sstem + "."):
                            sidecar_moves.append((fpath, os.path.join(ddir, dstem + fext)))
            except OSError:
                pass

        if req.dry_run:
            results.append({
                "path": album_dir,
                "dry_run": True,
                "album_root": new_root.replace("\\", "/"),
                "moves": [{"from": s.replace("\\", "/"), "to": d.replace("\\", "/")} for s, d in moves],
                "sidecars": [{"from": s.replace("\\", "/"), "to": d.replace("\\", "/")} for s, d in sidecar_moves],
                "errors": errors,
            })
            continue

        moved = 0
        for src, dst in moves + sidecar_moves:
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1
            except Exception as e:
                errors.append(f"{os.path.basename(src)}: {e}")

        # leftovers (cover art, logs, anything else) -> new album root
        leftovers = 0
        for root, dirs, files in os.walk(p):
            for f in list(files):
                fpath = os.path.join(root, f)
                if not os.path.exists(fpath):
                    continue
                dst = os.path.join(new_root, f)
                n = 2
                while os.path.exists(dst):
                    base, ext = os.path.splitext(f)
                    dst = os.path.join(new_root, f"{base} ({n}){ext}")
                    n += 1
                try:
                    os.makedirs(new_root, exist_ok=True)
                    shutil.move(fpath, dst)
                    leftovers += 1
                except Exception as e:
                    errors.append(f"{f}: {e}")

        # prune emptied folders (up to music_folder)
        pruned = 0
        cursor = p
        while os.path.abspath(cursor).lower() != os.path.abspath(folder).lower():
            try:
                if os.listdir(cursor):
                    break
                os.rmdir(cursor)
                pruned += 1
                cursor = os.path.dirname(cursor)
            except OSError:
                break

        # Post-organize cue maintenance: renaming audio underneath cue
        # sheets leaves stale FILE references, and album-named cues moved
        # by the leftovers pass keep names the CD-N grader rejects. Re-run
        # the same evidence-based engine the cue script uses.
        notes = []
        try:
            from mlo.discs import fix_cue_filenames, rename_cues_for_discs
            for old, new in rename_cues_for_discs(new_root, config=cfg):
                notes.append(f"cue renamed: {old} -> {new}")
            notes.extend(fix_cue_filenames(new_root, config=cfg))
        except Exception as e:
            errors.append(f"cue maintenance: {e}")

        results.append({
            "path": album_dir,
            "ok": True,
            "moved": moved,
            "leftovers": leftovers,
            "album_root": new_root.replace("\\", "/"),
            "pruned": pruned,
            "notes": notes,
            "errors": errors,
        })
    tagcache.invalidate_all()
    return {"results": results}


@app.post("/api/import/upload")
async def import_upload(
    target_dir: str = Query(...),
    files: List[UploadFile] = File(...),
):
    """Upload files into a new album directory under the music folder.

    Filenames may contain relative subpaths (e.g. "CD1/01 - Intro.flac")
    so whole album folders keep their internal structure. Path traversal
    and absolute paths are rejected.
    """
    cfg = load_config()
    folder = cfg.get("music_folder") or ""
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, "music_folder not set or not found")
    target = os.path.normpath(os.path.join(folder, target_dir))
    if not _in_music_folder(target, folder):
        raise HTTPException(400, "target outside music folder")
    os.makedirs(target, exist_ok=True)
    saved = []
    for f in files:
        name = (f.filename or "file").replace("\\", "/")
        parts = [p for p in name.split("/") if p and p not in (".", "..")]
        if not parts:
            continue
        # reject absolute/escaping paths
        if os.path.isabs(name) or ".." in name.split("/"):
            raise HTTPException(400, f"unsafe filename: {name!r}")
        dest = os.path.join(target, *parts)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        data = await f.read()
        with open(dest, "wb") as out:
            out.write(data)
        saved.append(dest.replace("\\", "/"))
    return {"ok": True, "saved": saved, "album_path": target.replace("\\", "/")}


@app.post("/api/import/scan")
def import_scan(path: str = Query(...)):
    """Recursively list a folder's files with relative paths (native picks).

    The picked folder may live anywhere — the follow-up ingest step moves
    it into the library.
    """
    p = os.path.normpath(path)
    if not os.path.isdir(p):
        raise HTTPException(404, "folder not found")
    out = []
    for root, dirs, files in os.walk(p):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, p).replace("\\", "/")
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            out.append({"relPath": rel, "size": size})
    out.sort(key=lambda x: x["relPath"].lower())
    return {"root": p.replace("\\", "/"), "files": out}


@app.post("/api/import/ingest")
def import_ingest(source: str = Query(...), target: str = Query(...)):
    """Move (or copy across devices) an album folder into the library."""
    import shutil
    cfg = load_config()
    folder = cfg.get("music_folder") or ""
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, "music_folder not set or not found")
    src = os.path.normpath(source)
    if not os.path.isdir(src):
        raise HTTPException(404, "source folder not found")
    name = re_safe_filename(os.path.basename(target or os.path.basename(src)))
    if not name:
        raise HTTPException(400, "invalid target name")
    dest = os.path.normpath(os.path.join(folder, name))
    if not _in_music_folder(dest, folder):
        raise HTTPException(400, "target outside music folder")
    if os.path.normcase(os.path.abspath(dest)) == os.path.normcase(os.path.abspath(src)):
        return {"ok": True, "path": dest.replace("\\", "/")}
    n = 2
    base = dest
    while os.path.exists(dest):
        dest = os.path.normpath(os.path.join(folder, f"{name} ({n})"))
        n += 1
    try:
        shutil.move(src, dest)
    except OSError:
        # cross-device: copy then remove the source so the import is a move
        shutil.copytree(src, dest)
        shutil.rmtree(src, ignore_errors=True)
    tagcache.invalidate_all()
    return {"ok": True, "path": dest.replace("\\", "/")}


@app.post("/api/import/commit")
def import_commit(req: ImportCommit):
    """Store MB/RYM links on every track of a freshly imported album.

    target_dir: album folder name under music_folder.
    """
    cfg = load_config()
    folder = cfg.get("music_folder") or ""
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, "music_folder not set or not found")
    target = os.path.normpath(req.target_dir)
    if not os.path.isabs(target):
        target = os.path.normpath(os.path.join(folder, req.target_dir))
    if not _in_music_folder(target, folder):
        raise HTTPException(400, "target outside music folder")
    if not os.path.isdir(target):
        raise HTTPException(404, "album not found")
    from mlo.audio import AudioFile
    changes = {}
    for root, _dirs, files in os.walk(target):
        for f in files:
            if not is_audio_file(f):
                continue
            changes[os.path.join(root, f).replace("\\", "/")] = {}
    mb = intg._mbid(req.mb_link)
    if mb:
        for p in changes:
            changes[p]["MUSICBRAINZ_ALBUMID"] = mb
    rym = intg.parse_rym_album_url(req.rym_link)
    if rym:
        for p in changes:
            changes[p]["RATEYOURMUSIC_ALBUM"] = rym
    errors = []
    for p, tag_map in changes.items():
        if not tag_map:
            continue
        af = AudioFile(os.path.normpath(p))
        if af.audio is None:
            errors.append(f"{p}: {af.error or 'unreadable'}")
            continue
        for k, v in tag_map.items():
            if not af.set_tag(k, v):
                errors.append(f"{p} {k}: {af.error}")
        tagcache.invalidate_path(os.path.normpath(p))
    if errors:
        raise HTTPException(500, "; ".join(errors))
    return {"ok": True, "changed": len(changes)}


# --------------------------------------------------------------------------- #
# WebSocket + static
# --------------------------------------------------------------------------- #
@app.websocket("/ws/progress")
async def ws_progress(ws: WebSocket):
    await ws.accept()
    progress_clients.add(ws)
    try:
        while True:
            try:
                # receive() detects dead peers (ping does not), so stale
                # sockets get pruned instead of accumulating forever.
                await asyncio.wait_for(ws.receive(), timeout=30)
            except asyncio.TimeoutError:
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        progress_clients.discard(ws)


WEB_DIST = ROOT / "web" / "dist"
if WEB_DIST.is_dir():
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve the built SPA: real files as-is, everything else falls back
        to index.html so client-side routes (/settings, /album/...) work."""
        if full_path.startswith(("api/", "ws")):
            raise HTTPException(404)
        file = WEB_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(WEB_DIST / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=True)