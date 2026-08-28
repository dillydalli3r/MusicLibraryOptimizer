"""
FastAPI backend for MusicLibraryOptimizer — localhost:8000

Wraps mlo/* as REST + WebSocket for the React frontend.
Serves Tracks/Albums/Artists/All grading/auditing/tagging via the same
mlo logic the Tkinter app used, so GRADE/AUDIT columns stay 100% parity.
"""
import os
import sys
import json
import asyncio
import pathlib
from typing import List, Optional

# Ensure project root on path so `import mlo` works when running from server/
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mlo import load_config, save_config
from mlo.config import DEFAULT_CONFIG, DEFAULT_RUN_ALL_ORDER
from mlo.stats import _find_albums
from mlo import stats as stats_mod

app = FastAPI(title="MusicLibraryOptimizer API", version="1.7.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- progress relay ---
progress_clients: set[WebSocket] = set()

orig_hook = stats_mod.progress_hook

def _relay(done, total, desc):
    # forward to all WS clients + keep original hook
    try:
        if orig_hook:
            orig_hook(done, total, desc)
    except Exception:
        pass
    for ws in list(progress_clients):
        try:
            asyncio.run_coroutine_threadsafe(ws.send_json({"done": done, "total": total, "desc": desc}), asyncio.get_event_loop())
        except Exception:
            pass

# Use hook relay for all mlo progress
stats_mod.progress_hook = _relay
# Also disable tqdm so _HookPbar always fires
stats_mod.tqdm = None

class RunRequest(BaseModel):
    ids: List[int]
    targets: Optional[List[str]] = None
    force: Optional[dict] = None  # {flac, images, audit, lyrics, cue, dr, autotag, accurip}

class TagsRequest(BaseModel):
    path: str
    tags: dict

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.7.1"}

@app.get("/api/config")
def get_config():
    cfg = load_config()
    return cfg

@app.post("/api/config")
def set_config(cfg: dict):
    # save_config validates + atomic replaces config.json
    ok = save_config(cfg)
    if not ok:
        raise HTTPException(500, "Failed to save config")
    return load_config()

@app.get("/api/library")
def library():
    """Full library tree for React: artists -> albums -> tracks with grade/audit per mlo/grader."""
    from mlo.grader import _grade_album
    from mlo.config import DEFAULT_CONFIG as DC
    cfg = load_config()
    folder = cfg.get("music_folder", "")
    if not folder or not os.path.isdir(folder):
        return {"artists": [], "folder": folder, "error": "music_folder not set or not found"}
    # Find albums and grade each
    albums = _find_albums(folder)
    # Group by artist parent dir
    artists = {}
    for alb in albums:
        artist_dir = os.path.dirname(alb)
        artists.setdefault(artist_dir, []).append(alb)
    result_artists = []
    for artist_dir, alb_list in sorted(artists.items()):
        artist_name = os.path.basename(artist_dir)
        albums_data = []
        for alb in sorted(alb_list):
            try:
                res = _grade_album(alb, cfg.get("lyrics_format", "EMBEDDED").upper(), cfg)
                if res is None or "error" in res:
                    continue
                # Normalize paths to forward slashes for frontend
                res["path"] = res["path"].replace("\\", "/")
                for tr in res.get("tracks", []):
                    tr["_full"] = os.path.join(alb, tr["file"]).replace("\\", "/")
                albums_data.append(res)
            except Exception as e:
                albums_data.append({"path": alb.replace("\\","/"), "error": str(e), "tracks": []})
        result_artists.append({
            "path": artist_dir.replace("\\", "/"),
            "name": artist_name,
            "albums": albums_data,
        })
    return {"folder": folder.replace("\\","/"), "artists": result_artists}

@app.get("/api/album")
def get_album(path: str = Query(...)):
    from mlo.grader import _grade_album
    cfg = load_config()
    p = os.path.normpath(path)
    if not os.path.isdir(p):
        raise HTTPException(404, "album not found")
    res = _grade_album(p, cfg.get("lyrics_format","EMBEDDED").upper(), cfg)
    if res is None:
        raise HTTPException(404, "no audio files")
    if "error" in res:
        raise HTTPException(500, res.get("error_detail","error"))
    res["path"] = res["path"].replace("\\","/")
    for tr in res.get("tracks",[]):
        tr["_full"] = os.path.join(p, tr["file"]).replace("\\","/")
    return res

@app.get("/api/stream")
def stream(path: str = Query(...)):
    p = os.path.normpath(path)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not found")
    # Basic content-type sniff
    ext = os.path.splitext(p)[1].lower()
    ctype = "audio/flac" if ext==".flac" else "audio/mpeg" if ext==".mp3" else "audio/mp4" if ext in (".m4a",".mp4") else "audio/ogg" if ext==".ogg" else "application/octet-stream"
    return FileResponse(p, media_type=ctype, headers={"Accept-Ranges": "bytes"})

@app.get("/api/tags")
def get_tags(path: str = Query(...)):
    from mlo.audio import AudioFile
    p = os.path.normpath(path)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not found")
    af = AudioFile(p)
    if af.audio is None:
        raise HTTPException(500, af.error or "unreadable")
    tags = af.all_tags()
    # include lyrics separate
    try:
        lyr = af.get_lyrics()
    except Exception:
        lyr = None
    # cover preview
    cover = None
    try:
        from mlo.paths import get_sidecar_cover_path
        # check album cover
        alb = os.path.dirname(p)
        for cand in ["cover.jpg","cover.jpeg","cover.png","cover.jxl"]:
            if os.path.isfile(os.path.join(alb, cand)):
                cover = os.path.join(alb, cand).replace("\\","/")
                break
    except Exception:
        pass
    return {"path": p.replace("\\","/"), "tags": tags, "lyrics": lyr, "cover": cover}

@app.post("/api/tags")
def set_tags(req: TagsRequest):
    from mlo.audio import AudioFile
    p = os.path.normpath(req.path)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not found")
    af = AudioFile(p)
    if af.audio is None:
        raise HTTPException(500, af.error or "unreadable")
    errors = []
    for k,v in req.tags.items():
        if k.upper() in ("LYRICS","UNSYNCEDLYRICS"):
            if not af.set_lyrics(str(v)):
                errors.append(f"{k}: {af.error}")
        else:
            if v is None or str(v)=="":
                if not af.delete_tag(k):
                    # ignore if tag didn't exist
                    pass
            else:
                if not af.set_tag(k, str(v)):
                    errors.append(f"{k}: {af.error}")
    if errors:
        raise HTTPException(500, "; ".join(errors))
    return {"ok": True}

@app.post("/api/cover")
async def upload_cover(album: str = Query(...), file: UploadFile = File(...)):
    alb = os.path.normpath(album)
    if not os.path.isdir(alb):
        raise HTTPException(404, "album not found")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".jpg",".jpeg",".png",".jxl",".webp",".bmp"):
        ext = ".jpg"
    dest = os.path.join(alb, f"cover{ext}")
    data = await file.read()
    # atomic with fsync
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=".cover_tmp_", suffix=ext, dir=alb)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            try:
                f.flush(); os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, dest)
        try:
            d = os.open(alb, os.O_DIRECTORY)
            try: os.fsync(d)
            finally: os.close(d)
        except Exception:
            pass
    except Exception as e:
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception:
            pass
        raise HTTPException(500, str(e))
    return {"ok": True, "path": dest.replace("\\","/")}

@app.post("/api/run")
def run_scripts(req: RunRequest):
    from mlo import run_format_lyrics, run_format_cues, run_optimize_flacs, run_grade_library, run_process_images, run_audit_library
    from mlo.loudness import run_calc_dr_replaygain
    from mlo.autotag import run_auto_tagging
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
        7: run_calc_dr_replaygain, 8: run_auto_tagging, 9: run_generate_accurip, 10: run_format_all,
    }
    cfg = load_config()
    if req.targets:
        cfg["targets"] = [os.path.normpath(t) for t in req.targets]
    # force mapping
    f = req.force or {}
    # master force is implicit if any force key set; mimic app.py force_master gate
    if f.get("flac"): cfg["force_reencode_flac"] = True
    if f.get("images"): cfg["force_reencode_images"] = True
    if f.get("audit"): cfg["force_audit"] = True
    if f.get("lyrics"): cfg["force_lyrics"] = True
    if f.get("cue"): cfg["force_cue"] = True
    if f.get("dr"): cfg["force_dr_replaygain"] = True
    if f.get("autotag"): cfg["force_auto_tag"] = True
    if f.get("accurip"): cfg["force_accurip"] = True

    # Validate ids
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
    return {"results": results}

# --- LRClib lyrics: uses lrclib.net per user ---
import httpx as _httpx

@app.get("/api/lyrics/search")
async def lyrics_search(artist: str = Query(...), track: str = Query(...), album: str = Query(None), duration: int = Query(None)):
    """Proxy to lrclib.net /api/search"""
    params = {"track_name": track, "artist_name": artist}
    if album: params["album_name"] = album
    # lrclib primary search
    try:
        async with _httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://lrclib.net/api/search", params=params)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        raise HTTPException(502, f"lrclib search failed: {e}")
    return []

@app.get("/api/lyrics/get")
async def lyrics_get(artist: str = Query(...), track: str = Query(...), album: str = Query(None), duration: int = Query(None)):
    """Proxy to lrclib.net /api/get - exact match, returns synced lyrics"""
    params = {"artist_name": artist, "track_name": track}
    if album: params["album_name"] = album
    if duration: params["duration"] = duration
    try:
        async with _httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://lrclib.net/api/get", params=params)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 404:
                return JSONResponse({"found": False}, status_code=404)
            else:
                raise HTTPException(r.status_code, r.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))

@app.post("/api/lyrics/write")
def lyrics_write(path: str = Query(...), lrc: str = "", source: str = "lrclib"):
    """Write .lrc sidecar atomically; never writes to tag per ask (translation sidecar only for helper)."""
    import tempfile
    from mlo.lyrics import _canonical_lyrics, format_lyrics_text
    p = os.path.normpath(path)
    if not os.path.isfile(p):
        raise HTTPException(404, "audio file not found")
    lrc_path = os.path.splitext(p)[0] + ".lrc"
    cfg = load_config()
    # canonicalize via mlo.lyrics
    try:
        # reuse format for storage
        from mlo.lyrics import _format_for_storage
        final = _format_for_storage(lrc, cfg, optimize=True, is_for_lrc=True)
    except Exception:
        final = lrc
    fd, tmp = tempfile.mkstemp(prefix=".lrc_tmp_", suffix=".lrc", dir=os.path.dirname(p) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(final)
            try: f.flush(); os.fsync(f.fileno())
            except Exception: pass
        os.replace(tmp, lrc_path)
        try:
            d = os.open(os.path.dirname(p) or ".", os.O_DIRECTORY)
            try: os.fsync(d)
            finally: os.close(d)
        except Exception: pass
    except Exception as e:
        try: os.remove(tmp)
        except Exception: pass
        raise HTTPException(500, str(e))
    return {"ok": True, "lrc": lrc_path.replace("\\","/")}

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

# Serve React build if present (after `npm run build` in web/)
WEB_DIST = ROOT / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=True)
