"""Playlists for MusicLibraryOptimizer v2.

Dual storage:
  * SQLite (server/data/playlists.db) — fast UI, smart playlists, ordering.
  * .m3u8 export/import — portable standard format for other players.

Playlist kinds:
  * manual — explicit ordered list of track paths.
  * smart  — saved filter (JSON) re-evaluated against the library payload.
"""
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "playlists.db"

_lock = threading.Lock()


def _conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _init():
    with _lock:
        with _conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'manual',
                    filter_json TEXT,
                    created REAL NOT NULL,
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (playlist_id, path)
                );
                CREATE TABLE IF NOT EXISTS likes (
                    path TEXT PRIMARY KEY,
                    liked_at REAL NOT NULL
                );
                """
            )


_init()


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def list_playlists():
    with _conn() as c:
        rows = c.execute("SELECT * FROM playlists ORDER BY name COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["filter"] = json.loads(item.pop("filter_json")) if item.get("filter_json") else None
            n = c.execute("SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id=?", (item["id"],)).fetchone()[0]
            item["track_count"] = n
            out.append(item)
        return out


def get_playlist(pid):
    with _conn() as c:
        r = c.execute("SELECT * FROM playlists WHERE id=?", (pid,)).fetchone()
        if r is None:
            return None
        item = dict(r)
        item["filter"] = json.loads(item.pop("filter_json")) if item.get("filter_json") else None
        rows = c.execute(
            "SELECT path FROM playlist_tracks WHERE playlist_id=? ORDER BY position", (pid,)
        ).fetchall()
        item["tracks"] = [x["path"] for x in rows]
        return item


def create_playlist(name, kind="manual", filter_spec=None):
    with _lock:
        with _conn() as c:
            now = time.time()
            cur = c.execute(
                "INSERT INTO playlists (name, kind, filter_json, created, updated) VALUES (?,?,?,?,?)",
                (name, kind, json.dumps(filter_spec) if filter_spec else None, now, now),
            )
            return cur.lastrowid


def rename_playlist(pid, name):
    with _conn() as c:
        c.execute("UPDATE playlists SET name=?, updated=? WHERE id=?", (name, time.time(), pid))
        return c.rowcount > 0


def delete_playlist(pid):
    with _lock:
        with _conn() as c:
            c.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (pid,))
            c.execute("DELETE FROM playlists WHERE id=?", (pid,))
            return c.rowcount > 0


# --------------------------------------------------------------------------- #
# Manual playlist tracks
# --------------------------------------------------------------------------- #
def add_tracks(pid, paths, position=None):
    """Append (or insert at position) track paths, deduplicating."""
    with _lock:
        with _conn() as c:
            existing = {r["path"] for r in c.execute(
                "SELECT path FROM playlist_tracks WHERE playlist_id=?", (pid,))}
            new = [p for p in paths if p not in existing]
            if not new:
                return 0
            if position is None:
                base = c.execute("SELECT COALESCE(MAX(position),0) FROM playlist_tracks WHERE playlist_id=?",
                                 (pid,)).fetchone()[0]
                start = base + 1
                for i, p in enumerate(new):
                    c.execute("INSERT INTO playlist_tracks (playlist_id, path, position) VALUES (?,?,?)",
                              (pid, p, start + i))
            else:
                c.execute("UPDATE playlist_tracks SET position = position + ? WHERE playlist_id=? AND position >= ?",
                          (len(new), pid, position))
                for i, p in enumerate(new):
                    c.execute("INSERT INTO playlist_tracks (playlist_id, path, position) VALUES (?,?,?)",
                              (pid, p, position + i))
            c.execute("UPDATE playlists SET updated=? WHERE id=?", (time.time(), pid))
            return len(new)


def set_order(pid, paths):
    """Replace the entire ordering with `paths` (reorder / full replace)."""
    with _lock:
        with _conn() as c:
            c.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (pid,))
            for i, p in enumerate(paths):
                c.execute("INSERT INTO playlist_tracks (playlist_id, path, position) VALUES (?,?,?)",
                          (pid, p, i))
            c.execute("UPDATE playlists SET updated=? WHERE id=?", (time.time(), pid))


def remove_tracks(pid, paths):
    with _lock:
        with _conn() as c:
            for p in paths:
                c.execute("DELETE FROM playlist_tracks WHERE playlist_id=? AND path=?", (pid, p))
            c.execute("UPDATE playlists SET updated=? WHERE id=?", (time.time(), pid))


# --------------------------------------------------------------------------- #
# Smart playlists
# --------------------------------------------------------------------------- #
_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a is not None and b is not None and a < b,
    "gt": lambda a, b: a is not None and b is not None and a > b,
    "lte": lambda a, b: a is not None and b is not None and a <= b,
    "gte": lambda a, b: a is not None and b is not None and a >= b,
    "contains": lambda a, b: a is not None and str(b).lower() in str(a).lower(),
    "missing": lambda a, b: a is None or str(a).strip() == "",
    "present": lambda a, b: a is not None and str(a).strip() != "",
}


def _track_value(track, field):
    """Extract a sortable value from an enriched track payload."""
    tags = track.get("tags") or {}
    if field in tags:
        return tags[field]
    if field in track:
        return track.get(field)
    tech = track.get("tech") or {}
    if field in tech:
        return tech[field]
    if field == "grade_pass":
        return track.get("grade_pass")
    if field == "lyrics_present":
        return track.get("lyrics_present")
    return None


def evaluate_smart(pid, library, base_paths=None):
    """Evaluate a smart playlist against the library payload.

    filter spec: {"conditions": [{field, op, value}], "match": "all"|"any"}
    Returns ordered list of matching track paths (respecting optional base_paths).
    """
    pl = get_playlist(pid)
    if pl is None or pl["kind"] != "smart":
        return None
    spec = pl.get("filter") or {}
    conditions = spec.get("conditions", [])
    match_all = spec.get("match", "all") == "all"

    hits = []
    for artist in library.get("artists", []):
        for alb in artist.get("albums", []):
            for tr in alb.get("tracks", []):
                if base_paths is not None and tr.get("path") not in base_paths:
                    continue
                results = []
                for cond in conditions:
                    op = cond.get("op", "eq")
                    field = cond.get("field")
                    value = cond.get("value")
                    fn = _OPS.get(op)
                    if fn is None:
                        results.append(False)
                        continue
                    results.append(fn(_track_value(tr, field), value))
                ok = all(results) if match_all else any(results)
                if ok:
                    hits.append(tr.get("path"))
    return hits


def set_smart_filter(pid, filter_spec):
    with _lock:
        with _conn() as c:
            c.execute("UPDATE playlists SET filter_json=?, updated=? WHERE id=?",
                      (json.dumps(filter_spec), time.time(), pid))
            return c.rowcount > 0


# --------------------------------------------------------------------------- #
# .m3u8 export / import
# --------------------------------------------------------------------------- #
def export_m3u8(pid):
    """Render a playlist as an .m3u8 string (EXTM3U + EXTINF lines)."""
    pl = get_playlist(pid)
    if pl is None:
        return None
    lines = ["#EXTM3U"]
    for path in pl["tracks"]:
        dur = _duration_of(path)
        title = os.path.splitext(os.path.basename(path))[0]
        lines.append(f"#EXTINF:{dur:.0f},{title}")
        lines.append(path.replace("\\", "/"))
    return "\n".join(lines) + "\n"


def import_m3u8(name, content, base_dir=None):
    """Parse .m3u8 content into a new manual playlist. Returns playlist id."""
    paths = []
    base_dir = base_dir or ""
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line
        if not os.path.isabs(p):
            p = os.path.join(base_dir, p)
        if os.path.isfile(p):
            paths.append(os.path.normpath(p))
    pid = create_playlist(name, kind="manual")
    add_tracks(pid, paths)
    return pid


def _duration_of(path):
    try:
        from mlo.audio import AudioFile
        af = AudioFile(path)
        if af.audio is not None and af.audio.info is not None:
            return float(af.audio.info.length)
    except Exception:
        pass
    return 0.0

# --------------------------------------------------------------------------- #
# Liked tracks (heart)
# --------------------------------------------------------------------------- #
def list_likes():
    with _conn() as c:
        rows = c.execute("SELECT path FROM likes ORDER BY liked_at DESC").fetchall()
        return [r["path"] for r in rows]


def is_liked(path):
    with _conn() as c:
        return c.execute("SELECT 1 FROM likes WHERE path=?", (path,)).fetchone() is not None


def toggle_like(path):
    path = str(path or "").strip()
    if not path:
        raise ValueError("path required")
    with _lock:
        with _conn() as c:
            if c.execute("SELECT 1 FROM likes WHERE path=?", (path,)).fetchone():
                c.execute("DELETE FROM likes WHERE path=?", (path,))
                return False
            c.execute("INSERT INTO likes (path, liked_at) VALUES (?, ?)", (path, time.time()))
            return True
