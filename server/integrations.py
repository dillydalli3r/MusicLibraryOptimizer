"""MusicBrainz / LRCLIB / RateYourMusic integrations for the import wizard.

MusicBrainz is queried with proper rate limiting (1 req/s) and a UA string
per their API etiquette. RYM has no public API — links are user-supplied
URLs stored as tags, but we validate/parse them here.
"""
import asyncio
import re
import threading
import time

import httpx

MB_BASE = "https://musicbrainz.org/ws/2"
LRCLIB_BASE = "https://lrclib.net/api"
USER_AGENT = "MusicLibraryOptimizer/2.0 (https://github.com/dillydalli3r/MusicLibraryOptimizer)"

_last_request = 0.0
_mb_lock = threading.Lock()


def mb_get(endpoint, params=None, timeout=30.0, retries=3):
    """Rate-limited MusicBrainz WS/2 GET returning parsed JSON.

    Retries 429/5xx (MusicBrainz rate-limits and has occasional 503s) with
    Retry-After-aware backoff, while keeping the 1 request/second etiquette.
    """
    global _last_request
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(retries):
        with _mb_lock:
            elapsed = time.time() - _last_request
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
            try:
                r = httpx.get(
                    f"{MB_BASE}/{endpoint}",
                    params=params or {},
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.HTTPError:
                _last_request = time.time()
                if attempt < retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            _last_request = time.time()
        if r.status_code in (429, 500, 502, 503, 504):
            wait = 1.5 * (attempt + 1)
            retry_after = r.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = max(wait, float(retry_after))
                except ValueError:
                    pass
            if attempt < retries - 1:
                time.sleep(wait)
                continue
        r.raise_for_status()
        return r.json()


def _mbid(value):
    """Extract a MusicBrainz ID from an ID or a musicbrainz.org URL."""
    if not value:
        return None
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value, re.I)
    return m.group(0).lower() if m else None


def _genres(node):
    return [g["name"] for g in (node.get("genres") or [])]


# --------------------------------------------------------------------------- #
# Release lookups
# --------------------------------------------------------------------------- #
def release_lookup(mbid):
    """Full release: media/discs, recordings, artist credits, genres."""
    data = mb_get(
        f"release/{mbid}",
        {"inc": "artists+recordings+media+release-groups+artist-credits+genres", "fmt": "json"},
    )
    # Normalize media into a flat list of {disc, position, title, length, recording mbid, artist mbids}
    tracks = []
    for medium in data.get("media", []):
        disc = medium.get("position", 1)
        for trk in medium.get("tracks", []):
            rec = trk.get("recording", {})
            artists = []
            for ac in trk.get("artist-credit", []):
                if "artist" in ac:
                    artists.append({
                        "name": ac.get("name", ""),
                        "mbid": ac["artist"].get("id"),
                    })
            tracks.append({
                "position": trk.get("position"),
                "disc": disc,
                "title": trk.get("title"),
                "length": trk.get("length"),
                "recording_mbid": rec.get("id"),
                "artist_mbids": [a["mbid"] for a in artists],
                "artist_credit": "".join(
                    (ac.get("name", "") + (ac.get("joinphrase", "") or ""))
                    for ac in trk.get("artist-credit", [])
                ),
                "genres": _genres(rec),
            })
    release_artists = [
        {"name": ac.get("name", ""), "mbid": ac["artist"].get("id")}
        for ac in data.get("artist-credit", []) if "artist" in ac
    ]
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "date": (data.get("date") or ""),
        "release_group_id": (data.get("release-group") or {}).get("id"),
        "artists": release_artists,
        "genres": _genres(data),
        "media": tracks,
        "medium_count": len(data.get("media", [])),
    }


def release_group_genres(rg_mbid):
    try:
        data = mb_get(f"release-group/{rg_mbid}", {"inc": "genres", "fmt": "json"})
        return _genres(data)
    except Exception:
        return []


def artist_genres(artist_mbid):
    try:
        data = mb_get(f"artist/{artist_mbid}", {"inc": "genres", "fmt": "json"})
        return _genres(data)
    except Exception:
        return []


def genre_cascade(release, limit=None):
    """Cascading genre import: track -> release -> release-group -> artist.

    Genres are merged across levels (deduped, in popularity order) and capped
    at `limit` per track. limit=None imports everything. Returns per-track
    genres plus the fallback chain used for each track.
    """
    rg = release.get("release_group_id")
    rg_genres = release_group_genres(rg) if rg else []
    artist_genres_all = []
    for a in release.get("artists", []):
        if a.get("mbid"):
            artist_genres_all.extend(artist_genres(a["mbid"]))
    artist_genres_all = list(dict.fromkeys(artist_genres_all))
    release_genres = release.get("genres", [])

    per_track = []
    for trk in release.get("media", []):
        ordered = []
        sources = []
        for level, lst in (
            ("track", trk.get("genres") or []),
            ("release", release_genres),
            ("release-group", rg_genres),
            ("artist", artist_genres_all),
        ):
            if lst and not sources:
                sources.append(level)
            for g in lst:
                if g not in ordered:
                    ordered.append(g)
        merged = ordered[:limit] if limit else ordered
        per_track.append({
            "position": trk["position"],
            "disc": trk["disc"],
            "title": trk["title"],
            "genres": merged,
            "source": sources[0] if sources else None,
            "levels_used": sources,
        })
    return {
        "per_track": per_track,
        "levels": {
            "track": any(t.get("genres") for t in release.get("media", [])),
            "release": bool(release_genres),
            "release_group": bool(rg_genres),
            "artist": bool(artist_genres_all),
        },
    }


def search_releases(query, limit=10):
    """Release search by title/artist (for the wizard's album picker)."""
    try:
        data = mb_get("release", {"query": query, "limit": limit, "fmt": "json"})
        out = []
        for r in data.get("releases", []):
            credit = "".join(
                (ac.get("name", "") + (ac.get("joinphrase", "") or ""))
                for ac in r.get("artist-credit", [])
            )
            out.append({
                "id": r.get("id"),
                "title": r.get("title"),
                "date": r.get("date"),
                "artist": credit,
                "country": r.get("country"),
                "status": r.get("status"),
            })
        return out
    except Exception as e:
        return {"error": str(e)}


def search_artists(query, limit=5):
    try:
        data = mb_get("artist", {"query": query, "limit": limit, "fmt": "json"})
        return [{"id": a.get("id"), "name": a.get("name"), "type": a.get("type")}
                for a in data.get("artists", [])]
    except Exception as e:
        return {"error": str(e)}


# --------------------------------------------------------------------------- #
# Track matching (local files <-> release media)
# --------------------------------------------------------------------------- #
def match_tracks(local_tracks, release):
    """Suggest release track/disc for each local track.

    local_tracks: list of {path, file, tracknumber, discnumber, title, duration}
    Matching: exact (disc,position) hit first, then title-similarity fallback.
    """
    release_media = release.get("media", [])
    by_pos = {(m["disc"], m["position"]): m for m in release_media}
    suggestions = []
    for lt in local_tracks:
        tn = lt.get("tracknumber")
        dn = lt.get("discnumber") or 1
        match = None
        score = 0.0
        if tn is not None:
            m = by_pos.get((dn, tn)) or by_pos.get((1, tn))
            if m:
                match, score = m, 1.0
        if match is None and lt.get("title"):
            best, best_score = None, 0.0
            for m in release_media:
                s = _similarity(lt["title"], m.get("title", ""))
                if s > best_score:
                    best, best_score = m, s
            if best and best_score >= 0.6:
                match, score = best, best_score
        suggestions.append({
            "local": lt.get("path"),
            "file": lt.get("file"),
            "matched": match is not None,
            "confidence": score,
            "release_track": match,
        })
    return suggestions


def _similarity(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# --------------------------------------------------------------------------- #
# LRCLIB
# --------------------------------------------------------------------------- #
_LRCLIB_HEADERS = {"User-Agent": USER_AGENT}


def lrclib_search(artist, track, album=None, duration=None):
    params = {"track_name": track, "artist_name": artist}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = duration
    r = httpx.get(f"{LRCLIB_BASE}/search", params=params, headers=_LRCLIB_HEADERS, timeout=15)
    if r.status_code == 200:
        return r.json()
    raise httpx.HTTPStatusError(f"lrclib search {r.status_code}", request=r.request, response=r)


def lrclib_get(artist, track, album=None, duration=None):
    """Exact-match lyrics lookup with a search fallback.

    Falls back to /search (preferring synced lyrics, then closest duration)
    when the exact /get returns 404.
    """
    params = {"artist_name": artist, "track_name": track}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = duration
    r = httpx.get(f"{LRCLIB_BASE}/get", params=params, headers=_LRCLIB_HEADERS, timeout=15)
    if r.status_code == 200:
        return r.json()
    if r.status_code == 404:
        try:
            hits = lrclib_search(artist, track, album, duration)
        except Exception:
            hits = []
        if isinstance(hits, list) and hits:
            synced = [h for h in hits if h.get("syncedLyrics")]
            pool = synced or hits
            if duration:
                pool = sorted(pool, key=lambda h: abs(int(h.get("duration") or 0) - int(duration)))
            return pool[0]
        return None
    raise httpx.HTTPStatusError(f"lrclib get {r.status_code}", request=r.request, response=r)


# --------------------------------------------------------------------------- #
# RateYourMusic (no public API — link helpers only)
# --------------------------------------------------------------------------- #
# RYM slugs vary (artist/album, album/format, %-encoding, apostrophes…).
# Keep it lenient: any rateyourmusic.com URL is a valid link to store.
RYM_RE = re.compile(r"^https?://(?:www\.)?rateyourmusic\.com/.+$", re.I)


def parse_rym_album_url(url):
    """Validate a RYM URL, returning the canonical URL or None."""
    url = (url or "").strip()
    if RYM_RE.match(url):
        return url
    return None