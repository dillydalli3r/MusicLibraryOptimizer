"""MusicBrainz / LRCLIB / RateYourMusic integrations for the import wizard.

MusicBrainz is queried with proper rate limiting (1 req/s) and a UA string
per their API etiquette. RYM has no public API — links are user-supplied
URLs stored as tags, but we validate/parse them here.
"""
import asyncio
import json
import re
import threading
import time
import uuid

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


def _title_genres(node):
    """Genres in Title Case ('nu metal' -> 'Nu Metal') for tag import."""
    seen, out = set(), []
    for g in _genres(node):
        key = g.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(g.strip().title())
    return out


# --------------------------------------------------------------------------- #
# Release lookups
# --------------------------------------------------------------------------- #
def release_lookup(mbid):
    """Full release: media/discs, recordings, artist credits, genres and
    labels (catalog numbers). Country comes from the release entity."""
    data = mb_get(
        f"release/{mbid}",
        {"inc": "artists+recordings+media+release-groups+artist-credits+genres+labels", "fmt": "json"},
    )
    # Normalize media into a flat list of {disc, position, title, length, recording mbid, artist mbids}
    tracks = []
    for medium in data.get("media", []):
        disc = medium.get("position", 1)
        medium_format = medium.get("format") or ""
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
                "genres": _title_genres(rec),
            })
    release_artists = [
        {"name": ac.get("name", ""), "mbid": ac["artist"].get("id")}
        for ac in data.get("artist-credit", []) if "artist" in ac
    ]
    rg_obj = data.get("release-group") or {}
    primary = (rg_obj.get("primary-type") or "").lower()
    secondary = [s.lower() for s in (rg_obj.get("secondary-types") or [])]
    release_type = "+".join([primary] + secondary) if primary else ""

    # labels -> first catalog number
    catalog_number = ""
    for lab in data.get("label-info", []) or []:
        cn = (lab.get("catalog-number") or "").strip()
        if cn:
            catalog_number = cn
            break
    country = data.get("country") or ""

    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "date": (data.get("date") or ""),
        "barcode": (data.get("barcode") or ""),
        "country": country,
        "catalog_number": catalog_number,
        "release_group_id": (data.get("release-group") or {}).get("id"),
        "release_type": release_type,
        "artists": release_artists,
        "genres": _title_genres(data),
        "media": tracks,
        "medium_count": len(data.get("media", [])),
        "medium_formats": [m.get("format") or "" for m in data.get("media", [])],
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

    Genres are merged across levels (deduped, in popularity order, Title
    Case) and capped at `limit` per track. limit=None imports everything.
    Returns per-track genres plus the fallback chain used for each track.
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


def search_releases(query, limit=10, mode="release"):
    """Release search with multiple strategies.

    mode:
      * release  — free-text title/artist search
      * track    — search by track title
      * catno    — search by catalog number  (catno:"CK 62240")
      * barcode  — search by barcode         (barcode:074643924526)
    """
    q = (query or "").strip()
    if not q:
        return []
    if mode == "catno":
        q = f'catno:"{q}"'
    elif mode == "barcode":
        q = f"barcode:{q}"
    elif mode == "track":
        q = f'track:"{q}"'
    try:
        data = mb_get("release", {"query": q, "limit": limit, "fmt": "json"})
        out = []
        for r in data.get("releases", []):
            credit = "".join(
                (ac.get("name", "") + (ac.get("joinphrase", "") or ""))
                for ac in r.get("artist-credit", [])
            )
            label = ""
            for li in r.get("label-info", []) or []:
                if li.get("catalog-number"):
                    label = li["catalog-number"]
                    break
            out.append({
                "id": r.get("id"),
                "title": r.get("title"),
                "date": r.get("date"),
                "artist": credit,
                "country": r.get("country"),
                "status": r.get("status"),
                "catalog_number": label,
                "barcode": r.get("barcode") or "",
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
_lrclib_last = 0.0
_lrclib_lock = threading.Lock()


def _lrclib_get(endpoint, params, timeout=15, retries=3):
    """Rate-throttled LRCLIB GET with retry on 429/5xx (they throttle IPs)."""
    global _lrclib_last
    for attempt in range(retries):
        with _lrclib_lock:
            elapsed = time.time() - _lrclib_last
            if elapsed < 0.4:
                time.sleep(0.4 - elapsed)
            r = httpx.get(f"{LRCLIB_BASE}/{endpoint}", params=params,
                          headers=_LRCLIB_HEADERS, timeout=timeout)
            _lrclib_last = time.time()
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            time.sleep(2.0 * (attempt + 1))
            continue
        return r
    return r


def lrclib_search(artist, track, album=None, duration=None):
    params = {"track_name": track, "artist_name": artist}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = duration
    r = _lrclib_get("search", params)
    if r.status_code == 200:
        return r.json()
    if r.status_code in (400, 404):
        return []
    raise httpx.HTTPStatusError(f"lrclib search {r.status_code}", request=r.request, response=r)


def lrclib_get(artist, track, album=None, duration=None):
    """Exact-match lyrics lookup with a search fallback.

    Falls back to /search (preferring synced lyrics, then closest duration)
    when the exact /get comes back empty; 400/404 are treated as not-found.
    """
    params = {"artist_name": artist, "track_name": track}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = duration
    r = _lrclib_get("get", params)
    if r.status_code == 200:
        return r.json()
    if r.status_code in (400, 404):
        # retry the search without the album filter — it can hurt matches
        for album_filter in (None, album):
            try:
                hits = lrclib_search(artist, track, album_filter, duration)
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

# --------------------------------------------------------------------------- #
# covers.musichoarders.xyz (COV) — album cover meta-search
# --------------------------------------------------------------------------- #
# COV aggregates cover art from streaming services and databases. Its search
# endpoint is the same one the website's frontend calls: a POST that streams
# newline-delimited JSON events (source/cover/count/done/error).
COV_BASE = "https://covers.musichoarders.xyz"
# The site's API gate rejects non-browser User-Agents (401), so COV
# requests use a plain browser UA while MB/LRCLIB keep the app UA.
COV_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
# The API allows at most 9 active sources per search; prefer high-quality
# art sources first and fill up with whatever else is enabled.
COV_SOURCE_PRIORITY = [
    "qobuz", "applemusic", "tidal", "bandcamp", "deezer", "spotify",
    "itunes", "discogs", "musicbrainz",
]
COV_MAX_SOURCES = 9
COV_FALLBACK_SOURCES = [
    "qobuz", "applemusic", "tidal", "bandcamp", "deezer", "spotify",
    "itunes", "discogs", "musicbrainz",
]

_cov_sources_cache = {"at": 0.0, "ids": []}


def _cov_sources(timeout=15.0):
    """Enabled source ids from /api/info, cached for an hour."""
    import time as _time
    now = _time.time()
    if _cov_sources_cache["ids"] and now - _cov_sources_cache["at"] < 3600:
        return _cov_sources_cache["ids"]
    try:
        info = httpx.get(f"{COV_BASE}/api/info",
                         headers={"User-Agent": COV_UA},
                         timeout=timeout).json()
        enabled = [s["id"] for s in info.get("sources", []) if s.get("enabled", True)]
    except Exception:
        enabled = list(COV_FALLBACK_SOURCES)
    ordered = [s for s in COV_SOURCE_PRIORITY if s in enabled]
    ordered += [s for s in enabled if s not in ordered]
    ids = ordered[:COV_MAX_SOURCES]
    if not ids:
        ids = list(COV_FALLBACK_SOURCES)
    _cov_sources_cache.update(at=now, ids=ids)
    return ids


def cover_search(artist, album, limit=40, timeout=60.0):
    """Search COV for album covers. Returns a list of
    {source, small, big, title, artist, tracks, url} dicts sorted by the
    site's relevance order, capped at *limit*."""
    if not artist and not album:
        raise ValueError("artist or album is required")
    body = {"country": "us", "sources": _cov_sources()}
    if artist:
        body["artist"] = artist
    if album:
        body["album"] = album
    headers = {
        "User-Agent": COV_UA,
        "Referer": f"{COV_BASE}/",
        "Origin": COV_BASE,
        "X-Session": uuid.uuid4().hex,
    }
    results = []
    with httpx.Client(timeout=httpx.Timeout(timeout, read=timeout)) as client:
        with client.stream("POST", f"{COV_BASE}/api/search", json=body,
                           headers=headers) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                line = (line or "").strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") != "cover":
                    continue
                rel = ev.get("releaseInfo") or {}
                results.append({
                    "source": ev.get("source"),
                    "small": ev.get("smallCoverUrl"),
                    "big": ev.get("bigCoverUrl"),
                    "title": rel.get("title"),
                    "artist": rel.get("artist"),
                    "tracks": rel.get("tracks"),
                    "url": rel.get("url"),
                })
                if len(results) >= limit:
                    break
    return results


def fetch_image_bytes(url, timeout=60.0):
    """Download an image URL (cover art hosts serve public CDN files) and
    return (data, content_type). Only http(s) is allowed."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("invalid image url")
    with httpx.Client(timeout=httpx.Timeout(timeout, read=timeout),
                      follow_redirects=True) as client:
        r = client.get(url, headers={"User-Agent": COV_UA,
                                     "Referer": f"{COV_BASE}/"})
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        return r.content, ctype
