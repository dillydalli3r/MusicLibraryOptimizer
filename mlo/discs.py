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

# Per-track CRC-32 checksums in rip logs (hex, 8 digits):
#   EAC: "Test CRC 3F2A51A2" / "Copy CRC 3F2A51A2" / "Accurately ripped
#        (confidence 10)  [3F2A51A2]"
#   XLD: "CRC32 hash (test run) : 3F2A51A2" / "CRC32 hash : 3F2A51A2"
COPY_CRC_RE = re.compile(r"^Copy CRC\s+([0-9A-Fa-f]{8})")
TEST_CRC_RE = re.compile(r"^Test CRC\s+([0-9A-Fa-f]{8})")
XLD_CRC_RE = re.compile(r"^CRC32 hash(?:\s+\(test run\))?\s*:\s*([0-9A-Fa-f]{8})")
ACCURATE_CRC_RE = re.compile(r"\[([0-9A-Fa-f]{8})\]")


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


def parse_log_checksums(text):
    """Map track number -> CRC-32 hex (8 chars, uppercase) from a rip log.

    Walks the "Track  N" sections; prefers Copy CRC over Test CRC over the
    AccurateRip bracket value.
    """
    per_track = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^Track\s+(\d{1,3})\b", line, re.IGNORECASE)
        if m:
            current = int(m.group(1))
            continue
        if current is None:
            continue
        m = COPY_CRC_RE.match(line)
        if m:
            per_track[current] = m.group(1).upper()
            continue
        m = TEST_CRC_RE.match(line)
        if m:
            per_track.setdefault(current, m.group(1).upper())
            continue
        m = XLD_CRC_RE.match(line)
        if m:
            per_track.setdefault(current, m.group(1).upper())
            continue
        if "accurately" in line.lower():
            m = ACCURATE_CRC_RE.search(line)
            if m:
                per_track.setdefault(current, m.group(1).upper())
    return per_track


def _file_track_number(path):
    """Track number from the TRACKNUMBER tag, else the 'NN' filename prefix."""
    try:
        af = AudioFile(path)
        raw = str(af.get_tag("TRACKNUMBER") or "").strip()
        if raw.isdigit():
            return int(raw)
    except Exception:
        pass
    m = re.match(r"^(\d{1,3})(?:\s*[-._\s])", os.path.basename(path))
    if m:
        return int(m.group(1))
    return None


def _audio_crc32(ffmpeg_exe, path):
    """CRC-32 of the file's decoded 16-bit PCM (the value EAC/XLD print in
    their logs), as 8 uppercase hex digits, or None on failure."""
    try:
        proc = run_tool(
            [ffmpeg_exe, "-v", "error", "-i", path,
             "-f", "s16le", "-acodec", "pcm_s16le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=600,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        import zlib
        return format(zlib.crc32(proc.stdout) & 0xFFFFFFFF, "08X")
    except Exception:
        return None


def verify_album_checksums(ffmpeg_exe, album_dir, paths, config=None):
    """Verify MEDIA=CD tracks against the CRC-32 checksums in the rip logs.

    This is the ONLY integrity source for CD rips — AudioAuditor is never
    consulted for MEDIA=CD (see audit.py). A file whose log checksum
    matches its actual decoded-PCM CRC is REAL, a mismatch is FAKE, and
    files whose log carries no usable checksum are reported as unverified
    (they get no AUDIT value, so grading fails the album instead of
    guessing).

    Returns ({path: 'REAL'|'FAKE'}, {path: reason}) — verified verdicts
    first, then unverified files with the reason (no log / no checksum /
    undecodable).
    """
    unverified = {}
    if not config or not config.get("audit_verify_cd_checksums", True):
        return {}, {}
    if not paths:
        return {}, {}
    af = AudioFile(paths[0])
    if af.audio is None:
        return {}, {p: "unreadable audio" for p in paths}
    if str(af.get_tag("MEDIA") or "").strip() != "CD":
        return {}, {}

    logs = [os.path.join(album_dir, f) for f in sorted(os.listdir(album_dir))
            if f.lower().endswith(".log")]
    if not logs:
        return {}, {p: "no .log file" for p in paths}
    discs = album_discs(album_dir)
    multi = bool(discs)

    verdicts = {}
    pattern = _disc_pattern_for(config)
    for p in paths:
        d = disc_of_filename(os.path.basename(p))
        if d is None or d < 1:
            d = 1
        if multi:
            log_path = os.path.join(album_dir, _disc_expected_name(pattern, d, ".log"))
            if not os.path.isfile(log_path):
                unverified[p] = f"missing {_disc_expected_name(pattern, d, '.log')}"
                continue
            per_track = parse_log_checksums(read_log_text(log_path))
            if not per_track:
                unverified[p] = f"{_disc_expected_name(pattern, d, '.log')} has no per-track CRCs"
                continue
        else:
            per_track = {}
            for log_path in logs:
                per_track.update(parse_log_checksums(read_log_text(log_path)))
            if not per_track:
                unverified[p] = "log has no per-track CRCs"
                continue
        tn = _file_track_number(p)
        crc = per_track.get(tn)
        if not crc:
            unverified[p] = f"log has no CRC for track {tn if tn else '?'}"
            continue
        actual = _audio_crc32(ffmpeg_exe, p)
        if actual is None:
            unverified[p] = "could not decode audio for CRC"
            continue
        verdicts[p] = "REAL" if actual == crc else "FAKE"
    return verdicts, unverified


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


def _disc_pattern_for(config):
    """Return the discs rename pattern (e.g. 'CD-{n}') with {n} placeholder."""
    if config is None:
        return "CD-{n}"
    pat = str(config.get("discs_rename_pattern", "CD-{n}")).strip()
    if "{n}" not in pat:
        return "CD-{n}"
    return pat[:32]


def _disc_expected_name(pattern, disc, ext):
    """Render pattern for a disc number, with extension."""
    base = pattern.replace("{n}", str(disc))
    # Ensure extension matches expected (lowercase comparison, keep ext as passed)
    if not base.lower().endswith(ext.lower()):
        base += ext
    return base


def _is_expected_disc_file(name, pattern, ext):
    """True if filename matches the pattern for any disc 1..99."""
    for n in range(1, 100):
        if name.lower() == _disc_expected_name(pattern, n, ext).lower():
            return True
    return False


def rename_cues_for_discs(album_dir, discs=None, log_fn=None, config=None):
    """Rename cues to <pattern>.cue based on their FILE entries.

    Pattern is configurable via discs_rename_pattern (default 'CD-{n}').
    Uses only content-derived evidence (FILE entries), never order.
    Single-disc albums without D-TT naming are treated as disc 1 so
    their single cue still becomes CD-1.cue (trivial, no guessing).
    """
    if config is not None and not config.get("discs_rename_enabled", True):
        return []
    pattern = _disc_pattern_for(config)
    discs = discs if discs is not None else album_discs(album_dir)
    # Single-disc fallback: no D-TT but audio files exist → treat as disc 1
    if not discs:
        # Use is_audio_file to count actual music (skip sidecars)
        aud = [f for f in os.listdir(album_dir) if is_audio_file(f)]
        if len(aud) > 0:
            # Only trivial single-cue case qualifies; multi-cue without
            # disc evidence remains untouched to avoid guessing.
            cues = [f for f in os.listdir(album_dir) if f.lower().endswith(".cue")]
            if len(cues) == 1 and len(aud) >= 1:
                discs = {1: [os.path.join(album_dir, f) for f in aud]}
            else:
                return []
    # Build lookup maps: exact, stem-insensitive, and normalized (handles
    # Unicode dashes, disc prefix, and .wav vs .flac)
    known_exact = {}
    known_stem = {}
    known_norm = {}
    for d, paths in discs.items():
        for p in paths:
            base = os.path.basename(p)
            known_exact[base.lower()] = d
            # stem without extension, ascii dashes, lower
            stem = os.path.splitext(_ascii_dashes(base))[0].lower()
            known_stem[stem] = d
            norm = _norm_name(base)
            known_norm[norm] = d

    notes = []
    # Trivial single-disc single-cue: rename directly to CD-1.cue (no FILE check)
    # This covers cases like a.cue → CD-1.cue where FILE entries are .wav vs .flac
    cues_all = [f for f in sorted(os.listdir(album_dir)) if f.lower().endswith(".cue") and not _is_expected_disc_file(f, pattern, ".cue")]
    if len(discs) == 1 and len(cues_all) == 1:
        sole_disc = next(iter(discs))
        sole_cue = cues_all[0]
        dst = os.path.join(album_dir, _disc_expected_name(pattern, sole_disc, ".cue"))
        if not os.path.exists(dst):
            _rename(os.path.join(album_dir, sole_cue), dst, notes)
            if log_fn and notes:
                for old, new in notes:
                    log_fn(f"cue: {old} -> {new}")
            return notes
    for f in sorted(os.listdir(album_dir)):
        if not f.lower().endswith(".cue"):
            continue
        if _is_expected_disc_file(f, pattern, ".cue"):
            continue
        path = os.path.join(album_dir, f)
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        file_discs = set()
        for m in CUE_FILE_RE.finditer(text):
            raw = m.group(1).replace("/", "\\").split("\\")[-1]
            # Try exact, then stem, then normalized (most lenient)
            d = known_exact.get(raw.lower())
            if d is None:
                stem = os.path.splitext(_ascii_dashes(raw))[0].lower()
                d = known_stem.get(stem)
            if d is None:
                d = known_norm.get(_norm_name(raw))
            if d is not None:
                file_discs.add(d)
        if len(file_discs) == 1:
            d = file_discs.pop()
            dst = os.path.join(album_dir, _disc_expected_name(pattern, d, ".cue"))
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


def rename_logs_for_discs(album_dir, discs=None, log_fn=None, config=None):
    """Rename logs to <pattern>.log using content-derived evidence only."""
    if config is not None and not config.get("discs_rename_enabled", True):
        return []
    pattern = _disc_pattern_for(config)
    discs = discs if discs is not None else album_discs(album_dir)
    # Single-disc fallback without D-TT: one log → CD-1.log
    if not discs:
        aud = [f for f in os.listdir(album_dir) if is_audio_file(f)]
        if len(aud) > 0:
            logs_tmp = [f for f in os.listdir(album_dir) if f.lower().endswith(".log")]
            if len(logs_tmp) == 1 and len(aud) >= 1:
                discs = {1: [os.path.join(album_dir, f) for f in aud]}
            else:
                return []
    logs = [f for f in sorted(os.listdir(album_dir))
            if f.lower().endswith(".log")]
    notes = []

    # 1) explicit disc numbers already present in filenames
    remaining = []
    claimed = {}
    for f in logs:
        if _is_expected_disc_file(f, pattern, ".log"):
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
        dst = os.path.join(album_dir, _disc_expected_name(pattern, d, ".log"))
        if os.path.normcase(dst) == os.path.normcase(os.path.join(album_dir, f)):
            continue
        if not os.path.exists(dst):
            _rename(os.path.join(album_dir, f), dst, notes)
    if log_fn and notes:
        for old, new in notes:
            log_fn(f"log: {old} -> {new}")
    return notes


# ----------------------------------------------------------------------
# CUE FILE-name correction (conservative, evidence-based)
# ----------------------------------------------------------------------
# Unicode dashes that appear in filenames (especially "Suite‐Pee" U+2010)
_UNICODE_DASHES = ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212", "\uFE58", "\uFE63", "\uFF0D")

def _ascii_dashes(s):
    for ch in _UNICODE_DASHES:
        s = s.replace(ch, "-")
    return s

def _strip_disc_prefix(name):
    """Strip leading disc prefix 'D-' from D-TT filenames, leaving 'TT Title'."""
    base = os.path.basename(name)
    # D-TT like "1-01 Title" or "1 - 01 Title" -> strip the "1-"
    m = re.match(r"^\d{1,2}\s*-\s*", _ascii_dashes(base))
    if m:
        # Only strip if what remains starts with a track number (TT)
        rest = base[m.end():]
        if re.match(r"^\d{1,3}(?:\s*[-._\s]|\b)", rest):
            return rest
    return base

def _norm_name(s):
    """Normalize a filename for comparison: lowercase, strip extension
    separators/underscores/double spaces. Never removes digits.
    Handles Unicode dashes and strips disc prefix so '1-01 Title' matches '01 Title'."""
    # Normalize dashes first, then strip disc prefix for comparison
    s = _ascii_dashes(s)
    s = _strip_disc_prefix(s)
    s = os.path.splitext(os.path.basename(s))[0].lower()
    s = re.sub(r"[\s_\-\.]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


def _track_num_of(name):
    """Track number from filename.
    For D-TT like '1-01 Title.flac' returns 1 (the TT, not the disc).
    For '01 - Title.flac' returns 1. Handles Unicode dashes."""
    base = _ascii_dashes(os.path.basename(name))
    # D-TT: disc-track
    m = re.match(r"^\d{1,2}\s*-\s*(\d{1,3})(?:\s*[-._\s]|\b)", base)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    m = re.match(r"^(\d{1,3})(?:\s*[-._\s])", base)
    return int(m.group(1)) if m else None


def fix_cue_filenames(album_dir, log_fn=None, config=None):
    """Correct FILE entries inside .cue sheets to match the actual audio
    filenames in *album_dir* — with minimal assumptions.

    A FILE entry is only rewritten when ALL of these hold:
      1. the referenced file does not exist on disk (any letter-case), and
      2. exactly ONE candidate audio file matches by normalized name
         (punctuation/space-insensitive), OR exactly one candidate shares
         the same leading track number AND the cue references exactly the
         tracks of one album folder (single-cue sanity).
    Ambiguous or missing matches are left untouched and reported.

    Returns a list of note strings describing every change.
    """
    if config is not None and not config.get("cue_fix_filenames", True):
        return []
    notes = []
    cues = [f for f in sorted(os.listdir(album_dir))
            if f.lower().endswith(".cue")]
    if not cues:
        return notes

    audio = [f for f in sorted(os.listdir(album_dir)) if is_audio_file(f)]
    if not audio:
        return notes

    # Lookup tables over real files.
    exact = {f.lower(): f for f in audio}
    norm = {}
    for f in audio:
        norm.setdefault(_norm_name(f), []).append(f)
    nums = {}
    for f in audio:
        n = _track_num_of(f)
        if n is not None:
            nums.setdefault(n, []).append(f)

    for cue in cues:
        path = os.path.join(album_dir, cue)
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue

        changed = False
        out_lines = []
        for line in lines:
            m = CUE_FILE_RE.match(line.rstrip("\n"))
            if not m:
                out_lines.append(line)
                continue
            ref = m.group(1)
            ref_base = ref.replace("/", "\\").split("\\")[-1]
            new_line = line

            exists = (
                os.path.isfile(os.path.join(album_dir, ref_base))
                or ref_base.lower() in exact
                or any(f.lower() == ref_base.lower() for f in audio)
            )
            if not exists:
                candidates = None
                # 1) unique normalized-name match
                c = norm.get(_norm_name(ref_base), [])
                if len(c) == 1:
                    candidates = c
                else:
                    # 2) unique leading-track-number match
                    tn = _track_num_of(ref_base)
                    if tn is not None:
                        c2 = nums.get(tn, [])
                        if len(c2) == 1:
                            candidates = c2
                if candidates:
                    actual = candidates[0]
                    # Keep any directory part of the original reference.
                    head = ref[: len(ref) - len(ref_base)] if ref_base else ""
                    new_ref = head + actual
                    if new_ref != ref:
                        new_line = line.replace(
                            f'"{ref}"', f'"{new_ref}"', 1)
                        if new_line != line:
                            notes.append(
                                f"{cue}: FILE \"{ref}\" -> \"{new_ref}\"")
                            changed = True
                else:
                    notes.append(
                        f"{cue}: unresolved FILE \"{ref}\" left as-is")
            out_lines.append(new_line)

        if changed:
            try:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.writelines(out_lines)
            except OSError as e:
                notes.append(f"{cue}: write failed ({e})")
    if log_fn and notes:
        for n in notes:
            log_fn(n)
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
                     write_tags=True, config=None):
    """Rename logs/cues to CD-N (config-gated), fix CUE FILE names and
    write LOG_GRADE (0-100) to every track of MEDIA=CD albums, one score
    per disc.

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

    # Fix FILE entries first (conservative) so the subsequent
    # FILE->disc mapping for renaming has correct references; .log
    # files are never modified — only renamed.
    fix_cue_filenames(album_dir, log_fn=log_fn, config=config)
    rename_logs_for_discs(album_dir, discs, log_fn=log_fn, config=config)
    rename_cues_for_discs(album_dir, discs, log_fn=log_fn, config=config)

    scores = {}
    pattern = _disc_pattern_for(config)
    for d, paths in sorted(discs.items()):
        log_path = os.path.join(album_dir, _disc_expected_name(pattern, d, ".log"))
        if not os.path.isfile(log_path):
            notes.append(f"disc {d}: no {_disc_expected_name(pattern, d, '.log')}")
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
            notes.append(f"disc {d}: could not score {_disc_expected_name(pattern, d, '.log')}")
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
