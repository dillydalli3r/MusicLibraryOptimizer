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
import pathlib
import tempfile
from contextlib import asynccontextmanager
from typing import List, Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
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


class TagsRequest(BaseModel):
    path: str
    tags: dict


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
    """Move staged files into the library. target_dir = album folder name."""
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
    """Path-containment guard shared by every path-taking endpoint."""
    return os.path.abspath(p).lower().startswith(os.path.abspath(folder).lower())


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
    albums_data = []
    for alb in sorted(albums):
        if os.path.dirname(alb).lower() != p.lower():
            continue
        try:
            a = lib_mod.build_album(alb, cfg)
            if a is not None:
                albums_data.append(a)
        except Exception as e:
            albums_data.append({"path": alb.replace("\\", "/"), "error": str(e), "tracks": []})
    return {
        "path": p.replace("\\", "/"),
        "name": os.path.basename(p),
        "albums": albums_data,
        "aggregate": lib_mod._aggregate_albums(albums_data),
    }


# --------------------------------------------------------------------------- #
# Streaming / tags
# --------------------------------------------------------------------------- #
_CTYPES = {
    ".flac": "audio/flac", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".mp4": "audio/mp4", ".ogg": "audio/ogg", ".opus": "audio/ogg",
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


@app.post("/api/tags")
def set_tags(req: TagsRequest):
    from mlo.audio import AudioFile
    p = os.path.normpath(req.path)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "file outside music folder")
    af = AudioFile(p)
    if af.audio is None:
        raise HTTPException(500, af.error or "unreadable")
    errors = []
    for k, v in req.tags.items():
        if k.upper() in ("LYRICS", "UNSYNCEDLYRICS"):
            if not af.set_lyrics(str(v)):
                errors.append(f"{k}: {af.error}")
        else:
            if v is None or str(v) == "":
                if not af.delete_tag(k):
                    errors.append(f"{k}: {af.error or 'delete failed'}")
            else:
                if not af.set_tag(k, str(v)):
                    errors.append(f"{k}: {af.error or 'write failed'}")
    if errors:
        raise HTTPException(500, "; ".join(errors))
    tagcache.invalidate_path(p)
    return {"ok": True}


@app.post("/api/tags/batch")
def set_tags_batch(req: TagsRequest):
    """Apply a tag map to multiple files: {path: {tag: value}}."""
    from mlo.audio import AudioFile
    errors = []
    changed = 0
    for p, tag_map in req.tags.items():
        fp = os.path.normpath(p)
        if not os.path.isfile(fp):
            errors.append(f"{p}: not found")
            continue
        if not _in_music_folder(fp, _music_folder()):
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
async def upload_cover(album: str = Query(...), file: UploadFile = File(...)):
    alb = os.path.normpath(album)
    if not os.path.isdir(alb):
        raise HTTPException(404, "album not found")
    if not _in_music_folder(alb, _music_folder()):
        raise HTTPException(400, "album outside music folder")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".jxl", ".webp", ".bmp"):
        ext = ".jpg"
    dest = os.path.join(alb, f"cover{ext}")
    data = await file.read()
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

    RUNNERS = {
        1: run_format_lyrics, 2: run_format_cues, 3: run_optimize_flacs,
        4: run_grade_library, 5: run_process_images, 6: run_audit_library,
        7: run_calc_dr_replaygain, 8: run_auto_tagging, 9: run_generate_accurip,
        10: run_format_all,
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
    base = os.path.dirname(load_config().get("music_folder", "") or ".")
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
    if not os.path.abspath(p).lower().startswith(os.path.abspath(folder).lower()):
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
        if not os.path.abspath(p).lower().startswith(os.path.abspath(folder).lower()):
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
            if not os.path.abspath(dst).lower().startswith(os.path.abspath(folder).lower()):
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

        # companion sidecars: same stem as an audio file, different extension
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
                    if fstem.lower() == sstem and fext.lower() not in (".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".wav", ".aac"):
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

        results.append({
            "path": album_dir,
            "ok": True,
            "moved": moved,
            "leftovers": leftovers,
            "album_root": new_root.replace("\\", "/"),
            "pruned": pruned,
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
    if not os.path.abspath(target).lower().startswith(os.path.abspath(folder).lower()):
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
    """Recursively list a folder's files with relative paths (native picks)."""
    p = os.path.normpath(path)
    if not os.path.isdir(p):
        raise HTTPException(404, "folder not found")
    if not _in_music_folder(p, _music_folder()):
        raise HTTPException(400, "folder outside music folder")
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
    if not os.path.abspath(dest).lower().startswith(os.path.abspath(folder).lower()):
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
    target = os.path.normpath(os.path.join(folder, req.target_dir))
    if not os.path.isdir(target):
        raise HTTPException(404, "album not found")
    from mlo.audio import AudioFile
    changes = {}
    for f in os.listdir(target):
        if not is_audio_file(f):
            continue
        changes[os.path.join(target, f).replace("\\", "/")] = {}
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
            await asyncio.sleep(30)
            await ws.ping()
    except WebSocketDisconnect:
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