"""Library grader: per-album tag/lyrics/cover compliance reports."""
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .audio import AudioFile
from .lyrics import _lrc_for, _canonical_lyrics, format_lyrics_text
from .cue import canonical_cue_text
from .paths import AUDIO_EXTS
from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, is_audio_file,
    _find_albums, _clean_set, _summarize_values, _collect_targets,
    worker_count,
)
from .ui import print_header, log, c, Color, print_separator, _short_val

PER_TRACK_TAGS = [
    "GENRE",
    "ITUNESADVISORY",
    "REPLAYGAIN_TRACK_GAIN",
    "REPLAYGAIN_TRACK_PEAK",
    "REPLAYGAIN_ALBUM_GAIN",
    "REPLAYGAIN_ALBUM_PEAK",
    "DYNAMIC RANGE",
    "INSTRUMENTAL",
]


ALBUM_TAGS = [
    "ALBUMITUNESADVISORY",
    "ALBUM DYNAMIC RANGE",
]


COVER_NAMES = {"cover.jpg", "cover.jpeg", "cover.png", "cover.jxl"}


def summarize_audits(values):
    """Collapse per-track AUDIT values into one album-level verdict.

    FAKE wins, a uniform REAL passes through, anything else is 'Mix'.
    None when empty. Case-insensitive (legacy mixed-case tags).
    """
    vals = {str(v).strip().upper() for v in values if v and str(v).strip()}
    if not vals:
        return None
    if "FAKE" in vals:
        return "FAKE"
    if vals == {"REAL"}:
        return "REAL"
    return "Mix"


def _grade_lyrics_present(embedded, lrc, lyrics_format):
    fmt = str(lyrics_format).upper()

    if fmt == "LRC":
        return lrc
    if fmt == "BOTH":
        return embedded and lrc

    return embedded


def _lyrics_formatted(text, cfg):
    """True when the lyrics already match the configured formatting
    (timestamps, metadata stripping, blank collapse, no trailing blanks).

    Idempotency check against the raw text: running the Lyrics formatter
    must not change it (so a stray trailing newline, CRLF, or timestamp
    precision drift is caught too).
    """
    if not text or not str(text).strip():
        return True
    raw = str(text)
    try:
        expected = _canonical_lyrics(format_lyrics_text(
            raw,
            precision=int(cfg.get("lrc_timestamp_precision", 2) or 2),
            strip_metadata=cfg.get("lrc_strip_metadata", True),
            collapse_blank_lines=cfg.get("lrc_collapse_blank_lines", True),
        ))
    except Exception:
        return True
    return raw == expected


# Two timestamps on the SAME line ("[00:00.00][00:45.53]text") break
# ESLyrics on foobar2000. Must not span a newline (that is the legitimate
# "[00:00.00]" empty marker line followed by the next line), so use a
# space/tab-only separator.
_MERGED_TS_RE = re.compile(
    r"\[\d{1,2}:\d{2}(?:\.\d+)?\][ \t]*\[\d{1,2}:\d{2}"
)


def _lyrics_merged_timestamps(text):
    """True when a line carries two adjacent timestamps."""
    return bool(_MERGED_TS_RE.search(str(text or "")))


def _cue_formatted(path, cfg):
    """True when a cue sheet is already in canonical form (LF, no BOM,
    quoted FILE lines with the configured type, no trailing whitespace,
    normalized DISCID/track/index)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(4096)
    except OSError:
        return False
    if b"\x00" in raw:
        return True  # not really a cue; do not penalize
    if raw.startswith(b"\xef\xbb\xbf"):
        return False  # UTF-8 BOM would be stripped
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="latin-1", newline="") as f:
                content = f.read()
        except OSError:
            return False
    except OSError:
        return False
    canonical = canonical_cue_text(
        content,
        keep_empty_lines=cfg.get("keep_empty_cue_lines", False),
        keep_other_lines=cfg.get("keep_other_cue_lines", False),
        file_type=cfg.get("cue_file_type", "WAVE"),
        append_final_newline=cfg.get("append_final_newline", False),
    )
    return canonical == content


def _grade_album(album_dir, lyrics_format, cfg=None):
    if cfg is None:
        cfg = {}
    all_files = os.listdir(album_dir)
    files = sorted(f for f in all_files if is_audio_file(f))
    audio_paths = [os.path.join(album_dir, f) for f in files]

    if not audio_paths:
        return None

    total_checks = 0
    failed_checks = 0

    tracks = []
    issues = {}

    album_tag_values = {}
    media_values = []
    source_values = []
    album_artist = None

    lyrics_present_count = 0
    lyrics_expected_count = 0
    instrumental_count = 0

    def add_issue(field, where="album"):
        issues.setdefault(field, set()).add(where)

    cover_file = None
    for f in all_files:
        if f.lower() in COVER_NAMES:
            cover_file = f
            break

    has_log = any(f.lower().endswith(".log") for f in all_files)
    has_cue = any(f.lower().endswith(".cue") for f in all_files)

    for ap in audio_paths:
        af = AudioFile(ap)
        basename = os.path.basename(ap)

        track = {
            "file": basename,
            "issues": [],
            "values": {},
            "lyrics_embedded": False,
            "lyrics_lrc": False,
            "unreadable": False,
            "audit": None,
            "log_grade": None,
        }

        if af.audio is None:
            track["unreadable"] = True
            add_issue("Unreadable audio file", basename)
            track["issues"].append("UNREADABLE")

            for t in PER_TRACK_TAGS:
                total_checks += 1
                failed_checks += 1

            tracks.append(track)
            continue

        # Required per-track tags.
        for t in PER_TRACK_TAGS:
            total_checks += 1
            val = af.get_tag(t)
            track["values"][t] = val

            if val is None or str(val).strip() == "":
                failed_checks += 1
                add_issue(f"Missing {t}", basename)
                track["issues"].append(t)

        # Artist for the library view (first track that has one). Keys are
        # matched case-insensitively: Picard writes lowercase Vorbis
        # comments while other taggers use uppercase.
        if album_artist is None:
            try:
                raw = {str(k).lower(): v for k, v in af.all_tags().items()}
                for k in ("albumartist", "tpe2", "aart",
                          "artist", "tpe1", "\xa9art"):
                    v = str(raw.get(k) or "").strip()
                    if v:
                        album_artist = v
                        break
            except Exception:
                album_artist = None

        # Album-wide tag values.
        for t in ALBUM_TAGS:
            v = af.get_tag(t)
            album_tag_values.setdefault(t, set()).add(
                str(v).strip() if v is not None else ""
            )

        # MEDIA / SOURCE values.
        media_val = af.get_tag("MEDIA")
        source_val = af.get_tag("SOURCE")

        media_clean = str(media_val).strip() if media_val is not None else ""
        source_clean = str(source_val).strip() if source_val is not None else ""

        track["values"]["MEDIA"] = media_clean or None
        track["values"]["SOURCE"] = source_clean or None

        # AudioAuditor verdict persisted by the Audit Library script:
        # required on every track of every media type, REAL to pass.
        audit_val = af.get_tag("AUDIT")
        audit_clean = str(audit_val).strip() if audit_val is not None else ""
        track["audit"] = audit_clean or None
        total_checks += 1
        if not audit_clean:
            failed_checks += 1
            add_issue("Missing AUDIT tag (run Audit Library)", basename)
            track["issues"].append("AUDIT")
        elif audit_clean.upper() != "REAL":
            failed_checks += 1
            add_issue(f"AUDIT tag is {audit_clean.upper()} (not REAL)",
                      basename)
            track["issues"].append("AUDIT")

        # Rip-log score (MEDIA=CD releases only, checked once MEDIA is
        # known - read here, graded in the CD section below).
        lg_val = af.get_tag("LOG_GRADE")
        track["log_grade"] = (
            str(lg_val).strip() if lg_val is not None
            and str(lg_val).strip() else None)

        if media_clean:
            media_values.append(media_clean)

        if source_clean:
            source_values.append(source_clean)

        # Lyrics status.
        lyr = af.get_lyrics()
        embedded = bool(lyr and str(lyr).strip())
        lrc = os.path.exists(_lrc_for(ap))

        track["lyrics_embedded"] = embedded
        track["lyrics_lrc"] = lrc

        inst = af.get_tag("INSTRUMENTAL")
        inst_val = str(inst).strip() if inst is not None else None
        track["values"]["INSTRUMENTAL"] = inst_val

        if inst_val == "1":
            instrumental_count += 1
            total_checks += 1

            if embedded or lrc:
                failed_checks += 1
                add_issue("INSTRUMENTAL=1 but lyrics present", basename)
                track["issues"].append("LYRICS")

        elif inst_val == "0":
            lyrics_expected_count += 1
            total_checks += 1

            if _grade_lyrics_present(embedded, lrc, lyrics_format):
                lyrics_present_count += 1
            else:
                failed_checks += 1
                add_issue(f"Missing lyrics ({lyrics_format.upper()})", basename)
                track["issues"].append("LYRICS")

        # Lyrics FORMATTING compliance (only when lyrics are present):
        # the stored text must already be in the canonical form the Lyrics
        # script would produce, and never carry merged timestamps.
        if embedded or lrc:
            total_checks += 1
            lyr_text = str(lyr) if embedded else None
            lrc_text = None
            if lrc:
                try:
                    with open(_lrc_for(ap), "r", encoding="utf-8",
                              errors="replace") as _f:
                        lrc_text = _f.read()
                except OSError:
                    lrc_text = None
            fmt_ok = True
            if lyr_text and not _lyrics_formatted(lyr_text, cfg):
                fmt_ok = False
            if lrc_text and not _lyrics_formatted(lrc_text, cfg):
                fmt_ok = False
            if (lyr_text and _lyrics_merged_timestamps(lyr_text)) or \
               (lrc_text and _lyrics_merged_timestamps(lrc_text)):
                fmt_ok = False
            if not fmt_ok:
                failed_checks += 1
                add_issue("Lyrics not optimally formatted "
                          "(run Lyrics script)", basename)
                track["issues"].append("LYRICS")

        tracks.append(track)

    # MEDIA consistency.
    total_checks += 1
    media_summary = _summarize_values(media_values)

    if media_summary is None:
        failed_checks += 1
        add_issue("Missing MEDIA", "album-wide")
    elif media_summary == "INCONSISTENT":
        failed_checks += 1
        add_issue("MEDIA inconsistent across tracks", "album-wide")

    digital = media_summary == "Digital Media"

    # SOURCE policy per track.
    for tr in tracks:
        if tr.get("unreadable"):
            continue

        total_checks += 1
        src = tr["values"].get("SOURCE")

        if digital:
            if not src:
                failed_checks += 1
                add_issue("Missing SOURCE (required for Digital Media)", tr["file"])
                tr["issues"].append("SOURCE")
        else:
            if src:
                failed_checks += 1
                add_issue("SOURCE present but MEDIA is not Digital Media", tr["file"])
                tr["issues"].append("SOURCE")

    # SOURCE consistency for Digital Media.
    if digital:
        total_checks += 1
        clean_sources = _clean_set(source_values)

        if len(clean_sources) > 1:
            failed_checks += 1
            add_issue("SOURCE inconsistent across album", "album-wide")

    # Album-wide tag consistency.
    for t in ALBUM_TAGS:
        total_checks += 1
        vals = album_tag_values.get(t, set())
        clean = {x for x in vals if x}

        if not clean:
            failed_checks += 1
            add_issue(f"Missing album tag {t}", "album-wide")
        elif "" in vals:
            failed_checks += 1
            add_issue(f"Album tag {t} missing on some tracks", "album-wide")
        elif len(clean) > 1:
            failed_checks += 1
            add_issue(f"Album tag {t} inconsistent", "album-wide")

    # Media-specific file requirements.
    if media_summary == "CD":
        total_checks += 1
        if not has_log:
            failed_checks += 1
            add_issue("Missing .log file", "album")

        total_checks += 1
        if not has_cue:
            failed_checks += 1
            add_issue("Missing .cue file", "album")

        # CD releases must carry the rip-log score on every track.
        for tr in tracks:
            if tr.get("unreadable"):
                continue
            total_checks += 1
            lg = tr.get("log_grade")
            if lg is None:
                failed_checks += 1
                add_issue("Missing LOG_GRADE tag (run Audit Library)",
                          tr["file"])
                tr["issues"].append("LOG_GRADE")
            elif not lg.isdigit() or not (0 <= int(lg) <= 100):
                failed_checks += 1
                add_issue(f"LOG_GRADE not 0-100: {lg}", tr["file"])
                tr["issues"].append("LOG_GRADE")

    elif media_summary == "Digital Media":
        # SOURCE requirements already checked per-track.
        pass

    else:
        total_checks += 1
        if media_summary is not None and media_summary != "INCONSISTENT":
            failed_checks += 1
            add_issue("Unrecognized MEDIA value", "album-wide")

    # Cover check.
    total_checks += 1
    if not cover_file:
        failed_checks += 1
        add_issue("Missing cover image", "album")

    # CUE sheet FORMATTING compliance (when a cue exists): every cue must
    # already be in the canonical form the CUE formatter would produce.
    if has_cue:
        cue_files = sorted(
            os.path.join(album_dir, f) for f in all_files
            if f.lower().endswith(".cue")
        )
        total_checks += 1
        cue_ok = True
        for cue_path in cue_files:
            if not _cue_formatted(cue_path, cfg):
                cue_ok = False
                break
        if not cue_ok:
            failed_checks += 1
            add_issue("CUE sheet not optimally formatted "
                      "(run CUE Sheets script)", "album")

    pass_count = max(0, total_checks - failed_checks)

    # Album-level audit summary from the per-track AUDIT tags.
    audit_summary = summarize_audits(tr["audit"] for tr in tracks)

    return {
        "path": album_dir,
        "album_artist": album_artist,
        "audit_summary": audit_summary,
        "media": media_summary or "(unknown)",
        "source_summary": _summarize_values(source_values),
        "track_count": len(audio_paths),
        "pass_count": pass_count,
        "total_checks": total_checks,
        "cover_file": cover_file,
        "has_log": has_log,
        "has_cue": has_cue,
        "lyrics_present": lyrics_present_count,
        "lyrics_expected": lyrics_expected_count,
        "instrumental_count": instrumental_count,
        "tracks": tracks,
        "album_values": {
            t: _summarize_values(album_tag_values.get(t, set()))
            for t in ALBUM_TAGS
        },
        "issues": {k: sorted(v, key=str.lower) for k, v in issues.items()},
    }


def format_grade_report(res, lyrics_format, track_file=None):
    """
    Build [(text, style), ...] lines for a grade result, for the GUI
    grade-details dialog. Styles: None, "bold", "red", "green", "muted".
    Pass track_file to limit the report to a single track.
    """
    lines = []

    if "error" in res:
        lines.append((f"Error grading: {res.get('path')}", "red"))
        return lines

    ok = res["pass_count"] == res["total_checks"]
    failed = res["total_checks"] - res["pass_count"]

    lines.append((
        f"Grade: {'PASS' if ok else 'FAIL'} ({100.0 if ok else 0.0:.0f}%) | "
        f"Checks: {res['pass_count']}/{res['total_checks']} | "
        f"Failed: {failed} | Tracks: {res['track_count']}",
        "green" if ok else "red",
    ))
    lines.append((
        f"Media: {res['media']} | "
        f"Source: {res['source_summary'] or 'MISSING'} | "
        f"Cover: {res['cover_file'] or 'MISSING'} | "
        f"Log: {'yes' if res['has_log'] else 'no'} | "
        f"Cue: {'yes' if res['has_cue'] else 'no'}",
        None,
    ))

    if res.get("audit_summary"):
        audit = res["audit_summary"]
        lines.append((
            f"Audio audit: {audit}",
            "green" if audit == "REAL"
            else ("red" if audit in ("FAKE", "Mix") else None),
        ))
    if res.get("media") == "CD":
        grades = sorted({
            tr.get("log_grade") for tr in res["tracks"]
            if tr.get("log_grade")})
        lines.append((
            "Rip-log grades (LOG_GRADE): "
            + (" ".join(f"{g}/100" for g in grades) if grades
               else "MISSING"),
            "green" if grades else "red",
        ))

    album_tag_parts = []
    for t in ALBUM_TAGS:
        val = res["album_values"].get(t)
        album_tag_parts.append(f"{t}={val if val else 'MISSING'}")
    lines.append(("Album tags: " + " | ".join(album_tag_parts), None))

    lines.append((
        f"Lyrics: required {str(lyrics_format).upper()}; "
        f"present {res['lyrics_present']}/{res['lyrics_expected']}; "
        f"instrumental {res['instrumental_count']}",
        None,
    ))

    if res["issues"]:
        for field, where in sorted(res["issues"].items()):
            if len(where) == 1 and where[0] in ("album", "album-wide"):
                lines.append((f"  - {field}", "red"))
            elif len(where) <= 5:
                lines.append((f"  - {field}: {', '.join(where)}", "red"))
            else:
                preview = ", ".join(where[:5])
                lines.append((f"  - {field}: {preview}, +{len(where) - 5} more", "red"))
    else:
        lines.append(("  - no problems", "green"))

    lines.append(("Tracks:", "bold"))

    for i, tr in enumerate(res["tracks"], 1):
        if track_file and os.path.join(res["path"], tr["file"]) != track_file:
            continue

        v = tr["values"]
        lyr = []
        if tr["lyrics_embedded"]:
            lyr.append("EMB")
        if tr["lyrics_lrc"]:
            lyr.append("LRC")
        lyr_state = "+".join(lyr) if lyr else "NONE"

        lines.append((f"  {i:02d}. {tr['file']}", "bold"))
        lines.append((
            f"      GENRE={_short_val(v.get('GENRE'), 18)} | "
            f"ADVISORY={_short_val(v.get('ITUNESADVISORY'), 8)} | "
            f"DR={_short_val(v.get('DYNAMIC RANGE'), 6)} | "
            f"INST={_short_val(v.get('INSTRUMENTAL'), 4)}",
            None,
        ))
        lines.append((
            f"      RG_TRACK={_short_val(v.get('REPLAYGAIN_TRACK_GAIN'), 10)} / "
            f"{_short_val(v.get('REPLAYGAIN_TRACK_PEAK'), 8)} | "
            f"RG_ALBUM={_short_val(v.get('REPLAYGAIN_ALBUM_GAIN'), 10)} / "
            f"{_short_val(v.get('REPLAYGAIN_ALBUM_PEAK'), 8)}",
            None,
        ))
        lines.append((
            f"      MEDIA={_short_val(v.get('MEDIA'), 14)} | "
            f"SOURCE={_short_val(v.get('SOURCE'), 14)} | "
            f"LYRICS={lyr_state} | "
            f"AUDIT={tr.get('audit') or '—'} | "
            f"LOG_GRADE={tr.get('log_grade') or '—'}",
            None,
        ))

        if tr["issues"]:
            lines.append((f"      Issues: {', '.join(tr['issues'])}", "red"))
        elif track_file:
            lines.append(("      No issues", "green"))

        if track_file:
            break

    return lines


def _relpath_guard(path, base):
    """os.path.relpath that never raises on cross-drive paths (Windows)."""
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return os.path.basename(path)


def run_grade_library(config):
    folder = config["music_folder"]
    lyrics_format = config.get("lyrics_format", "EMBEDDED").upper()
    verbose = config.get("grade_verbose", True)

    stats = new_stats()
    stats["is_grader"] = True
    stats["grade_dist"] = {"PASS": 0, "FAIL": 0}

    print_header("Library Grader")
    log(f"music folder: {folder} · lyrics format: {lyrics_format}")
    log(
        f"criteria: per-track {', '.join(PER_TRACK_TAGS)} | "
        f"album {', '.join(ALBUM_TAGS)} | media/source rule | "
        f"CD log+cue | cover jpg/jpeg/png/jxl | "
        f"INST=1 no lyrics | INST=0 lyrics required"
    )

    if not os.path.isdir(folder):
        log(c(f"ERROR: folder does not exist: {folder}", Color.RED))
        return stats

    if config.get("targets") is not None:
        # Targeted run: derive albums from the explicit targets only — do
        # NOT walk the whole library first (costly on large trees).
        target_files = _collect_targets(config["targets"], AUDIO_EXTS)
        albums = sorted({os.path.dirname(f) for f in target_files})
    else:
        albums = _find_albums(folder)

    if not albums:
        log("No albums found.")
        return stats

    results = []
    counts = {"ok": 0, "skip": 0, "fail": 0}
    workers = worker_count(config, default=16, maximum=16, items=len(albums))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_grade_album, a, lyrics_format, config): a
                   for a in albums}
        pbar = _make_pbar(len(futures), "Grading", unit="album")

        for fut in as_completed(futures):
            album = futures[fut]

            try:
                result = fut.result()
            except Exception as e:
                stats["total_scanned"] += 1
                stats["error_count"] += 1
                stats["errors"].append((album, str(e)))
                _pbar_update(pbar, counts, kind="fail")
                continue

            if result is None:
                stats["skipped_count"] += 1
                _pbar_skip(pbar, counts)
                continue

            stats["total_scanned"] += 1
            results.append(result)
            _pbar_update(pbar, counts, kind="ok")

        if pbar:
            pbar.close()

    results.sort(key=lambda r: _relpath_guard(r["path"], folder).lower())

    summary_pass = 0
    summary_total = 0
    issue_counts = {}

    for result in results:
        failed_checks = result["total_checks"] - result["pass_count"]
        passed = failed_checks == 0
        # Binary grading: an album is 100% only when every check passes.
        pct = 100.0 if passed else 0.0
        grade = "PASS" if passed else "FAIL"

        stats["grade_dist"][grade] += 1
        summary_pass += result["pass_count"]
        summary_total += result["total_checks"]

        for field in result["issues"]:
            issue_counts[field] = issue_counts.get(field, 0) + 1

        rel = _relpath_guard(result["path"], folder)

        grade_color = Color.GREEN if passed else Color.RED

        log(
            f"{c('✓' if passed else '✕', grade_color)} {rel}  "
            f"{c(grade, grade_color)} {result['pass_count']}/{result['total_checks']} · "
            f"{result['track_count']} tr · {result['media'] or 'no media'} · "
            f"src {result['source_summary'] or '—'} · "
            f"{result['cover_file'] or 'no cover'} · "
            f"log {'✓' if result['has_log'] else '–'} "
            f"cue {'✓' if result['has_cue'] else '–'} · "
            f"lyrics {result['lyrics_present']}/{result['lyrics_expected']}"
        )

        missing_tags = [
            t for t in ALBUM_TAGS if not result["album_values"].get(t)
        ]
        if missing_tags:
            log(c(f"    missing album tags: {', '.join(missing_tags)}",
                  Color.YELLOW))

        if result["issues"]:
            log(c(f"    issues: {', '.join(result['issues'])}", Color.RED))

        if verbose:
            log("Tracks:")

            for i, tr in enumerate(result["tracks"], 1):
                v = tr["values"]

                lyr = []
                if tr["lyrics_embedded"]:
                    lyr.append("EMB")
                if tr["lyrics_lrc"]:
                    lyr.append("LRC")
                lyr_state = "+".join(lyr) if lyr else "NONE"

                log(f"  {i:02d}. {tr['file']}")
                log(
                    f"      GENRE={_short_val(v.get('GENRE'), 18)} | "
                    f"ADVISORY={_short_val(v.get('ITUNESADVISORY'), 8)} | "
                    f"DR={_short_val(v.get('DYNAMIC RANGE'), 6)} | "
                    f"INST={_short_val(v.get('INSTRUMENTAL'), 4)}"
                )
                log(
                    f"      RG_TRACK={_short_val(v.get('REPLAYGAIN_TRACK_GAIN'), 10)} / "
                    f"{_short_val(v.get('REPLAYGAIN_TRACK_PEAK'), 8)} | "
                    f"RG_ALBUM={_short_val(v.get('REPLAYGAIN_ALBUM_GAIN'), 10)} / "
                    f"{_short_val(v.get('REPLAYGAIN_ALBUM_PEAK'), 8)}"
                )
                log(
                    f"      MEDIA={_short_val(v.get('MEDIA'), 14)} | "
                    f"SOURCE={_short_val(v.get('SOURCE'), 14)} | "
                    f"LYRICS={lyr_state}"
                )

                if tr["issues"]:
                    log(
                        c(
                            f"      Issues: {', '.join(tr['issues'])}",
                            Color.RED,
                        )
                    )

    stats["summary_pass"] = summary_pass
    stats["summary_total"] = summary_total
    stats["albums_passed"] = stats["grade_dist"].get("PASS", 0)
    stats["albums_failed"] = stats["grade_dist"].get("FAIL", 0)
    stats["issue_counts"] = issue_counts

    return stats

