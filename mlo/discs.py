"""Multi-CD support: disc mapping, deterministic CD-N naming and
per-disc rip-log scoring.

Discs are identified from the track filename convention "D-TT Title"
(e.g. "2-03 Track.flac" -> disc 2) which this library uses throughout.
Logs and cues are renamed to CD-1.log / CD-2.cue ... using only
content-derived evidence, never order or fuzzy matching:

  cues   - the FILE entries inside a cue reference exact track
           filenames, so the referenced disc is exact.
  logs   - in order of preference:
             1. an explicit disc number in the current filename
                (CD-2.log, "Disc 2.log", "2 - Album.log"),
             2. the trivial single-disc case (one disc, one log),
             3. a unique total-duration match between the log's TOC
                (EAC prints per-track lengths in CD sectors) and the
                actual audio durations of exactly one disc.
           Anything ambiguous is left untouched - grading will flag the
           missing LOG_GRADE instead of guessing.

Per-disc rip-log scoring: AudioAuditorCLI scores only one log per
folder, so each disc is scored in isolation - a temporary folder is
filled with stub files named after that disc's tracks plus only that
disc's log; the stub run needs no audio decoding (cambia scores the log
text) and returns the 0-100 score via `analyze --rip-log --json`.
"""
import os
import re
import subprocess
import tempfile
import shutil

from .audio import AudioFile
from .paths import AUDIO_EXTS
from .stats import is_audio_file
from .subproc import run_tool
from .ui import log, c, Color

# "1-01 Title.flac" / "12-03 Title.flac" -> disc number
DISC_PREFIX_RE = re.compile(r"^(\d{1,2})\s*-\s*\d{2}(?:\s|\.|$)")

# Explicit disc numbers in log filenames: CD-2.log, CD2.log, Disc 02.log,
# "2 - Album.log", "(2).log" ...
LOG_NAME_DISC_RE = re.compile(
    r"(?:^|[\s_(-])(?:cd|disc)[\s_-]?(\d{1,2})(?=$|[\s._)\]-])"
    r"|^(\d{1,2})\s*[-._\s]",
    re.IGNORECASE,
)

CUE_FILE_RE = re.compile(r'^\s*FILE\s+"([^"]+)"', re.IGNORECASE)

# EAC TOC rows: "     1  |  0:00.00  |  3:13.27  | ..." (length column)
TOC_ROW_RE = re.compile(
    r"^\s*\d+\s*\|\s*\d+:\d{2}\.\d{2}\s*\|\s*(\d+):(\d{2})\.(\d{2})\s*\|",
    re.MULTILINE,
)

# Duration-match window in seconds and the uniqueness margin required
# before a TOC match is trusted.
TOC_TOLERANCE_S = 4.0
TOC_UNIQUE_MARGIN_S = 4.0


def disc_of_filename(name):
    """Disc number from the 'D-TT Title' filename convention, else None."""
    m = DISC_PREFIX_RE.match(os.path.basename(name))
    return int(m.group(1)) if m else None


def album_discs(album_dir):
    """Map {disc number: [audio file paths]} for an album folder.

    Only folders where every audio file carries the D-TT convention are
    returned; anything else has no reliable disc structure ({}).
    """
    discs = {}
    for f in sorted(os.listdir(album_dir)):
        if not is_audio_file(f):
            continue
        d = disc_of_filename(f)
        if d is None or d < 1:
            return {}
        discs.setdefault(d, []).append(os.path.join(album_dir, f))
    return discs


def read_log_text(path):
    """Decode an EAC/XLD log (UTF-16LE with BOM, or UTF-8)."""
    try:
        raw = open(path, "rb").read()
    except OSError:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if b"\x00" in raw[:512]:
        # NUL-byte Heuristic: UTF-16 without BOM.
        try:
            return raw.decode("utf-16-le", errors="replace")
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def parse_log_toc_seconds(text):
    """Total playtime of the log's 'TOC of the extracted CD' table, in
    seconds (CD sectors are 1/75 s)."""
    total = 0.0
    for m in TOC_ROW_RE.finditer(text):
        mins, secs, frames = int(m.group(1)), int(m.group(2)), int(m.group(3))
        total += mins * 60 + secs + frames / 75.0
    return total


def _audio_seconds(paths):
    total = 0.0
    for p in paths:
        try:
            af = AudioFile(p)
            if af.audio is not None and af.audio.info is not None:
                total += float(af.audio.info.length)
        except Exception:
            return None
    return total


# ----------------------------------------------------------------------
# Renaming
# ----------------------------------------------------------------------
def _rename(src, dst, notes):
    try:
        os.rename(src, dst)
        notes.append((os.path.basename(src), os.path.basename(dst)))
        return True
    except OSError as e:
        notes.append((os.path.basename(src), f"rename failed: {e}"))
        return False


def rename_cues_for_discs(album_dir, discs=None, log_fn=None):
    """Rename cues to CD-N.cue based on their FILE entries."""
    discs = discs if discs is not None else album_discs(album_dir)
    if not discs:
        return []
    known = {}
    for d, paths in discs.items():
        for p in paths:
            known[os.path.basename(p).lower()] = d

    notes = []
    for f in sorted(os.listdir(album_dir)):
        if not f.lower().endswith(".cue"):
            continue
        if re.match(r"^CD-\d{1,2}\.cue$", f, re.IGNORECASE):
            continue
        path = os.path.join(album_dir, f)
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        file_discs = set()
        for m in CUE_FILE_RE.finditer(text):
            base = m.group(1).replace("/", "\\").split("\\")[-1].lower()
            d = known.get(base)
            if d is not None:
                file_discs.add(d)
        if len(file_discs) == 1:
            d = file_discs.pop()
            dst = os.path.join(album_dir, f"CD-{d}.cue")
            if not os.path.exists(dst):
                _rename(path, dst, notes)
    if log_fn and notes:
        for old, new in notes:
            log_fn(f"cue: {old} -> {new}")
    return notes


def _log_name_disc(name):
    base = os.path.splitext(name)[0]
    m = LOG_NAME_DISC_RE.search(base)
    if not m:
        return None
    d = int(m.group(1) or m.group(2))
    return d if 1 <= d <= 99 else None


def rename_logs_for_discs(album_dir, discs=None, log_fn=None):
    """Rename logs to CD-N.log using content-derived evidence only."""
    discs = discs if discs is not None else album_discs(album_dir)
    if not discs:
        return []
    logs = [f for f in sorted(os.listdir(album_dir))
            if f.lower().endswith(".log")]
    notes = []

    # 1) explicit disc numbers already present in filenames
    remaining = []
    claimed = {}
    for f in logs:
        if re.match(r"^CD-\d{1,2}\.log$", f, re.IGNORECASE):
            d = _log_name_disc(f)
            if d:
                claimed.setdefault(d, f)
            continue
        d = _log_name_disc(f)
        if d and d in discs and d not in claimed:
            claimed[d] = f
        else:
            remaining.append(f)

    # 2) trivial single-disc case
    if len(discs) == 1 and len(remaining) == 1 and 1 not in claimed:
        claimed[1] = remaining.pop(0)

    # 3) unique TOC total-duration match against real audio durations
    if remaining and len(claimed) < len(discs):
        durations = {}
        for d, paths in discs.items():
            if d in claimed:
                continue
            secs = _audio_seconds(paths)
            if secs:
                durations[d] = secs
        for f in remaining:
            toc = parse_log_toc_seconds(read_log_text(os.path.join(album_dir, f)))
            if toc <= 0:
                continue
            candidates = [d for d, s in durations.items()
                          if abs(s - toc) <= TOC_TOLERANCE_S]
            if len(candidates) == 1:
                d = candidates[0]
                margins = sorted(abs(s - toc) for s in durations.values())
                unique = (len(margins) < 2 or
                          margins[1] - margins[0] >= TOC_UNIQUE_MARGIN_S)
                if unique and d not in claimed:
                    claimed[d] = f
                    durations.pop(d, None)

    for d, f in sorted(claimed.items()):
        dst = os.path.join(album_dir, f"CD-{d}.log")
        if os.path.normcase(dst) == os.path.normcase(os.path.join(album_dir, f)):
            continue
        if not os.path.exists(dst):
            _rename(os.path.join(album_dir, f), dst, notes)
    if log_fn and notes:
        for old, new in notes:
            log_fn(f"log: {old} -> {new}")
    return notes


# ----------------------------------------------------------------------
# Per-disc rip-log scoring
# ----------------------------------------------------------------------
def score_disc_log(cli_exe, log_path, disc_files, timeout=300):
    """Score one disc's log with AudioAuditorCLI in an isolated stub
    folder. Returns the 0-100 score (int) or None."""
    workdir = tempfile.mkdtemp(prefix="mlo_riplog_")
    try:
        for p in disc_files:
            stub = os.path.join(workdir, os.path.basename(p))
            try:
                open(stub, "wb").write(b"\x00" * 1024)
            except OSError:
                return None
        # Keep the original log basename - the CLI picks up any .log in
        # the folder, but some verifiers match it against the cue.
        shutil.copy2(log_path,
                     os.path.join(workdir, os.path.basename(log_path)))

        proc = run_tool(
            [cli_exe, "analyze", workdir, "--rip-log", "--json",
             "--no-fun", "--no-tips", "--no-update-check", "--no-config"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            return None
        try:
            import json
            items = json.loads(proc.stdout)
        except ValueError:
            return None
        for item in items:
            score = item.get("ripLogScore")
            if score is not None and item.get("hasRipLog"):
                try:
                    return int(score)
                except (ValueError, TypeError):
                    return None
        return None
    except Exception:
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def grade_album_logs(cli_exe, album_dir, force=False, log_fn=None,
                     write_tags=True):
    """Rename logs/cues to CD-N and write LOG_GRADE (0-100) to every
    track of MEDIA=CD albums, one score per disc.

    Returns ({disc: score}, notes list).
    """
    notes = []
    discs = album_discs(album_dir)
    if not discs:
        return {}, notes

    # MEDIA=CD only - read the first track's MEDIA tag.
    first = next(iter(discs.values()))[0]
    af = AudioFile(first)
    if af.audio is None:
        return {}, notes
    media = str(af.get_tag("MEDIA") or "").strip()
    if media != "CD":
        return {}, notes

    rename_logs_for_discs(album_dir, discs, log_fn=log_fn)
    rename_cues_for_discs(album_dir, discs, log_fn=log_fn)

    scores = {}
    for d, paths in sorted(discs.items()):
        log_path = os.path.join(album_dir, f"CD-{d}.log")
        if not os.path.isfile(log_path):
            notes.append(f"disc {d}: no CD-{d}.log")
            continue
        if not force:
            have = []
            for p in paths:
                t = AudioFile(p)
                v = str(t.get_tag("LOG_GRADE") or "").strip()
                have.append(v)
            if have and all(v.isdigit() and 0 <= int(v) <= 100 for v in have):
                continue  # already graded
        score = score_disc_log(cli_exe, log_path, paths)
        if score is None:
            notes.append(f"disc {d}: could not score CD-{d}.log")
            continue
        scores[d] = score
        for p in paths:
            if not write_tags:
                continue
            t = AudioFile(p)
            if str(t.get_tag("LOG_GRADE") or "").strip() != str(score):
                if t.set_tag("LOG_GRADE", str(score)):
                    if log_fn:
                        log_fn(f"disc {d}: LOG_GRADE={score} -> "
                               f"{os.path.basename(p)}")
                else:
                    notes.append(f"disc {d}: failed writing LOG_GRADE to "
                                 f"{os.path.basename(p)}")
    return scores, notes
