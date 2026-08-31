"""Tag-rich library payload builder for the v2 web UI.

Builds the artist -> album -> track tree from `mlo.grader` output and
enriches every track with sortable metadata (audio tech info + tags),
so the frontend can sort/filter by grade, audit, genre, year, advisory,
instrumental, MBIDs, RYM links, duration, bitrate, sample rate, etc.
"""
import os

from mlo.stats import _find_albums
from mlo.grader import _grade_album
from mlo.audio import AudioFile
from mlo.paths import get_sidecar_cover_path
from server import tagcache

# Tags surfaced per track for sorting/filtering on the frontend.
TRACK_TAGS = [
    "TITLE", "ARTIST", "ALBUM", "DATE", "GENRE",
    "ITUNESADVISORY", "INSTRUMENTAL", "MEDIA", "SOURCE",
    "TRACKNUMBER", "DISCNUMBER",
    "MUSICBRAINZ_ALBUMID", "MUSICBRAINZ_ALBUMARTISTID",
    "MUSICBRAINZ_ARTISTID", "MUSICBRAINZ_TRACKID",
    "MUSICBRAINZ_RELEASEGROUPID",
    "RATEYOURMUSIC_ALBUM", "RATEYOURMUSIC_TRACK", "RATEYOURMUSIC_ARTIST",
    "ALBUMARTISTSORT", "ORIGINALDATE", "RELEASETYPE", "RELEASECOUNTRY",
    "CATALOGNUMBER", "TRACKTOTAL", "DISCTOTAL",
]

# Tags read from the first track to represent album-level metadata.
ALBUM_LEVEL_TAGS = [
    "ALBUM", "ARTIST", "DATE", "MUSICBRAINZ_ALBUMID",
    "MUSICBRAINZ_ALBUMARTISTID", "MUSICBRAINZ_RELEASEGROUPID",
    "RATEYOURMUSIC_ALBUM",
]

TECH_ATTRS = ("length", "bitrate", "sample_rate", "bits_per_sample", "channels")


def _read_tags(path):
    """Read TRACK_TAGS for a file path as a flat dict (None when missing)."""
    tags, _ = tagcache.read_track(path, TRACK_TAGS)
    return tags


def _enrich_track(tr, album_dir):
    """Add path, tech info, tags and per-track sidecar cover (cached reads)."""
    p = os.path.join(album_dir, tr["file"])
    tr["path"] = p.replace("\\", "/")
    tags, tech = tagcache.read_track(p, TRACK_TAGS)
    tr["tags"] = tags
    tr["tech"] = tech
    # Per-track sidecar cover: "01 - Song.jpg" next to "01 - Song.flac"
    try:
        sc = get_sidecar_cover_path(album_dir, tr["file"])
        tr["cover_file"] = os.path.basename(sc) if sc else None
    except Exception:
        tr["cover_file"] = None
    # Per-track audit/grade convenience fields for sorting.
    tr["grade_pass"] = not tr.get("issues")
    tr["lyrics_present"] = bool(tr.get("lyrics_embedded") or tr.get("lyrics_lrc"))
    return tr


def _album_meta(album_dir, tracks):
    """Album-level metadata read from the first readable track."""
    meta = {}
    for tr in tracks:
        tags = tr.get("tags") or {}
        if tags:
            for t in ALBUM_LEVEL_TAGS:
                meta[t] = tags.get(t)
            break
    return meta


def _aggregate_albums(albums_data):
    """Artist-level aggregates from a list of album payloads."""
    total_checks = sum(a.get("total_checks", 0) for a in albums_data)
    pass_count = sum(a.get("pass_count", 0) for a in albums_data)
    track_count = sum(a.get("track_count", 0) for a in albums_data)
    audits = {a.get("audit_summary") for a in albums_data}
    audit = "FAKE" if "FAKE" in audits else ("REAL" if audits == {"REAL"} else
                                             ("Mix" if len(audits) > 1 else
                                              (next(iter(audits)) if audits else None)))
    return {
        "album_count": len(albums_data),
        "track_count": track_count,
        "pass_count": pass_count,
        "total_checks": total_checks,
        "grade_pct": round(100.0 * pass_count / total_checks, 1) if total_checks else None,
        "audit_summary": audit,
    }


def build_album(album_dir, cfg):
    """Grade + enrich a single album. Returns the enriched dict or None."""
    res = _grade_album(album_dir, str(cfg.get("lyrics_format", "EMBEDDED")).upper(), cfg)
    if res is None:
        return None
    if "error" in res:
        res["path"] = album_dir.replace("\\", "/")
        res["tracks"] = []
        return res
    res["path"] = res["path"].replace("\\", "/")
    for tr in res.get("tracks", []):
        _enrich_track(tr, album_dir)
    res["meta"] = _album_meta(album_dir, res.get("tracks", []))
    tc = res.get("total_checks", 0)
    res["grade_pct"] = round(100.0 * res.get("pass_count", 0) / tc, 1) if tc else None
    res["pass"] = res.get("pass_count", 0) == tc and tc > 0
    return res


def build_library(cfg, progress=None):
    """Full library tree with artist/album/track aggregates (TTL-cached)."""
    folder = cfg.get("music_folder") or ""
    if not folder or not os.path.isdir(folder):
        return {"folder": folder, "artists": [], "error": "music_folder not set or not found"}

    cfg_key = (
        folder,
        cfg.get("lyrics_format"),
        cfg.get("worker_limit"),
        cfg.get("short_folder_names"),
    )

    def _build():
        albums = _find_albums(folder)
        artists = {}
        for alb in albums:
            artists.setdefault(os.path.dirname(alb), []).append(alb)

        result = []
        total = len(artists)
        for i, (artist_dir, alb_list) in enumerate(sorted(artists.items())):
            if progress:
                progress(i + 1, total, "Scanning library")
            albums_data = []
            for alb in sorted(alb_list):
                try:
                    a = build_album(alb, cfg)
                    if a is not None:
                        albums_data.append(a)
                except Exception as e:
                    albums_data.append({"path": alb.replace("\\", "/"), "error": str(e), "tracks": []})
            agg = _aggregate_albums(albums_data)
            result.append({
                "path": artist_dir.replace("\\", "/"),
                "name": os.path.basename(artist_dir),
                "albums": albums_data,
                "aggregate": agg,
            })
        return {"folder": folder.replace("\\", "/"), "artists": result}

    return tagcache.get_library(cfg_key, _build)