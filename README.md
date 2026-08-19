# Music Library Optimizer

A Windows program for optimizing music libraries. It targets FLAC files,
image files (mainly by converting to JPEG XL), cue sheets, and lyrics —
optimizing both storage space and formatting. It also grades the library
for tag/lyrics/cover compliance and audits audio integrity (fake-lossless
detection via AudioAuditor). Mostly written in Python.

Desktop GUI (dark theme) + optional console menu.

## Usage

**Desktop app:** double-click `Music Library Optimizer.exe`
(the compiled release — no Python required).

**From source:** `Music Library Optimizer.bat` or `python app.py`
(requires `pip install mutagen`, optionally `Pillow` and `tqdm`).

**Console menu:** `python -m mlo`

## Dependencies (automatic)

The GUI's **Dependencies…** dialog (sidebar → MANAGE) downloads the latest
official Windows builds straight from GitHub releases and installs them into
`.dependencies/`:

| Tool           | Source                        | Installed files             |
|----------------|-------------------------------|-----------------------------|
| FLAC           | xiph/flac                     | flac.exe, metaflac.exe      |
| libjxl         | libjxl/libjxl                 | cjxl.exe, djxl.exe          |
| libjpeg-turbo  | libjpeg-turbo/libjpeg-turbo   | jpegtran.exe                |
| oxipng         | oxipng/oxipng                 | oxipng.exe                  |
| AudioAuditor   | Angel2mp3/AudioAuditor        | AudioAuditorCLI.exe         |

Each tool shows its installed and latest version with a Download / Update /
Reinstall button, plus Install/Update All. The console menu offers the same
via option 10. libjpeg-turbo only ships NSIS installers for Windows, so that
one is unpacked with 7-Zip when available (also used for libjxl's
non-standard zip compression); without 7-Zip it falls back to a silent
install into a temporary folder. AudioAuditor ships a single self-contained
exe that is copied as-is — no extraction needed.

## Scripts

| # | Script            | What it does                                              |
|---|-------------------|-----------------------------------------------------------|
| 1 | Format Lyrics     | Cleans embedded/LRC lyrics, converts format, normalizes MEDIA/SOURCE |
| 2 | Format CUEs       | Normalizes .cue sheets (TRACK/INDEX padding, FILE lines, DISCID) |
| 3 | Optimize FLACs    | Lossless re-encode via flac.exe, strips PADDING/PICTURE etc. |
| 4 | Grade Library     | Per-album compliance report; albums grade 100% (all checks pass) or 0% |
| 5 | Process Images    | JPEG XL conversion / lossless JPEG/PNG optimize / reverse  |
| 6 | Audit Library     | Audio integrity audit via the AudioAuditor CLI            |

Only FLAC is losslessly re-encoded; other audio formats receive safe tag
operations only. Every processed artifact carries ENCODER marker tags so
re-runs skip already-optimized files (and FLACs carrying current markers
skip the seektable-strip pass entirely, avoiding one metaflac.exe launch
per file on re-runs).

The lyrics formatter also auto-fixes contradictory tags: when a track has
`INSTRUMENTAL=1` but lyrics are present (embedded or LRC), it sets
`INSTRUMENTAL=0`.

### Audit Library (script 6)

Runs [AudioAuditor](https://github.com/Angel2mp3/AudioAuditor)'s CLI
(`analyze --json`) over every audio file (or just the checked items —
paths are piped to the CLI in batches) and reports:

- **Real** — genuine lossless (JSON status `Valid`)
- **Fake** — spectral cutoff / transcoded-to-lossless sources
- **Corrupt / Unknown** — undecodable or unclassifiable files
- **Optimized** — MQA-encoded audio
- Warning flags on otherwise clean files: clipping, scaled clipping,
  MQA markers, fake stereo, excessive silence, AI-generated markers

Every file's verdict is written to its **`AUDIT` tag** — `REAL` or `FAKE`
only (binary by design: the CLI's `Valid` status maps to `REAL`, everything
else to `FAKE`) — Vorbis comment on FLAC/OGG/Opus, `TXXX:AUDIT` on MP3,
freeform atom on MP4 — so the verdict travels with the file and other tools
can read it. Files that already carry a `REAL`/`FAKE` verdict are skipped on
re-runs (like the ENCODER markers for optimization); the Force ▾ menu (or
the `Force Audit` setting) re-audits them. The fast scan runs by default;
enable **Thorough Audit** in Settings → Audio Auditor to add silence,
dynamic-range, true-peak, LUFS and BPM detectors (much slower).
**Optimize Selected** always finishes with an audit so verdicts stay
current, and the library view re-grades affected albums automatically after
every run.

### CD rip-log grading (Media = CD only)

For releases tagged `MEDIA=CD` the audit run also grades the EAC/XLD rip
logs. Multi-disc albums are supported:

- Audio files use the `D-TT Title` naming convention (`2-03 Song.flac`),
  which identifies each disc with no guesswork.
- `.log` and `.cue` files are renamed to a shared, deterministic
  `CD-N.log` / `CD-N.cue` scheme (`CD-1`, `CD-2`, … `CD-11`). Cues are
  mapped from their `FILE` entries (exact filenames); logs from an
  explicit disc number in the filename (`CD-2.log`, `Disc 2.log`,
  `2 - Album.log`) or a unique total-duration match against the audio.
  Ambiguous cases are left untouched rather than guessed — grading then
  flags the missing `LOG_GRADE`.
- Each disc's log is scored with AudioAuditorCLI's `--rip-log` mode in an
  isolated folder (no audio decoding needed) and the cambia 0-100 score is
  written to the **`LOG_GRADE`** tag of that disc's tracks.

Grading requires the `LOG_GRADE` tag (0-100) on every track of `MEDIA=CD`
albums — a missing score fails the album — while the `AUDIT` tag must be
`REAL` on every track of every media type.

### Audio Auditor settings

**Settings → Audio Auditor** configures the Audit Library run. Detector
toggles map directly to the CLI's `--no-*` flags; disabling a detector
removes the corresponding warning flag from the report (the `AUDIT` tag
stays `REAL` for genuine lossless either way).

| Setting | Effect |
|---|---|
| **Thorough Audit** | Enables silence/DR/true-peak/LUFS/BPM detectors (much slower). |
| **Force Audit** | Re-audits files that already carry an `AUDIT` tag and re-scores rip logs even when `LOG_GRADE` is present. |
| **Cutoff Allowance (Hz)** | `AudioAuditor --cutoff-allow` threshold. Files with a spectral cutoff at or above this value are NOT flagged as fake. `0` = CLI default (19600 Hz). Raise it (e.g. 20000) if genuine HD masters are misread as transcoded lossy. |
| **Clipping Detection** | Toggle `--no-clipping`. Loud modern masters often clip at the true-peak ceiling but are still genuine lossless. |
| **MQA Detection** | Toggle `--no-mqa`. |
| **AI Detection** | Toggle `--no-ai`. The standard watermark detector can false-positive on well-mastered digital sources. |
| **Fake Stereo Detection** | Toggle `--no-fake-stereo`. |
| **Silence Detection** | Toggle `--no-silence`. Quiet passages in classical/ambient music can trigger false warnings. |
| **Dynamic Range** | Toggle `--no-dynamic-range` (only used in Thorough mode). |
| **True Peak** | Toggle `--no-true-peak` (only used in Thorough mode). |
| **LUFS** | Toggle `--no-lufs` (only used in Thorough mode). |
| **BPM** | Toggle `--no-bpm` (only used in Thorough mode). |

The console config menu (option 9) exposes the same controls as options
22-33.

### Force options

The Library toolbar has a **Force** pill next to a **▾** menu that toggles
each force option individually (the master pill sets all of them):

- **Re-encode FLACs** — re-encode every FLAC regardless of ENCODER markers.
- **Re-encode images** — reprocess images regardless of ENCODER markers.
- **Audit** — re-audit files that already carry an `AUDIT` verdict and
  re-score rip logs even when `LOG_GRADE` is present.

Applies to **Optimize Selected**, **Run All** and **Run Custom**.

## Library view

The Library tab scans and grades the library in the background and shows
a tree of artists → albums → tracks. Checkboxes select items for
**Optimize Selected** (which runs the pipeline and finishes with an
audit); the filter row narrows by album-artist tag or folder name, can
show only failing albums, and sorts by grade.

Columns: **GRADE** (pass/fail), **AUDIT** (the album's `AUDIT` tag
summary), TRACKS, MEDIA, COVER and **TAGS** — whose heading is the key
to its layout: `G` Genre · `A` Advisory · `I` Instrumental · `L` Lyrics
· `AA` Album Advisory (`—` = missing/inconsistent). The CHECKS column is
hidden by default; **right-click any column heading** to toggle columns
on or off — the choice persists across launches.

Row colors combine grading and audit state:

| Color  | Meaning                                            |
|--------|----------------------------------------------------|
| green  | graded pass                                        |
| purple | audited only (audit clean, grade failing/pending)  |
| blue   | graded pass **and** audited Real                   |
| yellow | warnings / mixed (audit Warn/Mix, partial passes)  |
| red    | failing (grade fail, Fake/Corrupt/Optimized audit) |

### Right-click menu (rows)

- **Grade details…** — lists exactly which checks failed for an album or
  track (missing tags, cover, .log/.cue, lyrics, media/source policy),
  plus the album's audio-audit summary.
- **Edit album tags… / Edit track tags…** — built-in tagger for the graded
  metadata fields (GENRE, advisories, ReplayGain, Dynamic Range,
  INSTRUMENTAL, MEDIA, SOURCE, album-wide variants). Empty fields remove
  the tag; albums apply values to every track; the album is re-graded
  automatically after saving.
- **Enqueue in foobar2000** — sends the folder to foobar2000 via `/add`.
- **Open in Mp3tag / Open in Picard** — launch the external tagger with
  that folder loaded.

The toolbar also has **Enqueue in foobar2000**, **Mp3tag** and
**Picard** buttons that act on every checked folder in the tree. All
three apps are auto-detected via the registry (App Paths), common
install locations, or PATH; the first manual locate is remembered in
`config.json` (`foobar2000_path` / `mp3tag_path` / `picard_path`).

## Project layout

```
app.py                          GUI entry point (dark desktop theme)
mlo/                            Core package — all processing logic
    paths.py                    Locations & constants (exe-aware)
    deps.py                     Optional dependency detection
    config.py                   config.json load/save & defaults
    ui.py                       Console output helpers
    stats.py                    Run stats, byte accounting, progress hooks
    report.py                   Result report printing
    tools.py                    .dependencies tool auto-detection
    fetchdeps.py                GitHub release downloader / installer
    containers.py               FLAC/JXL/JPEG/PNG metadata tag I/O
    audio.py                    Unified multi-format tag abstraction
    lyrics.py / cue.py /        The feature modules
    flac.py / images.py /
    grader.py / discs.py        discs.py: CD-N naming + per-disc LOG_GRADE
    audit.py                    AudioAuditor CLI integration (script 6)
    cli.py                      Interactive console menu
config.json                     Persisted settings (created on first save)
app_icon.ico                    Application icon
.dependencies/                  External toolchain (auto-downloaded):
    flac v1.5.0/                flac.exe, metaflac.exe
    libjxl v0.12.0/             cjxl.exe, djxl.exe
    libjpeg-turbo v3.2.0/       jpegtran.exe
    oxipng v10.2.0/             oxipng.exe
    AudioAuditor v2.0.0/        AudioAuditorCLI.exe
```

## Rebuilding the exe

```
pip install pyinstaller mutagen pillow
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "Music Library Optimizer" --icon app_icon.ico ^
    --hidden-import mutagen.aac app.py
```

The exe reads `config.json` and `.dependencies/` from its own folder.
