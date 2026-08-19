# Music Library Optimizer v1.0.4

> ## ⚠️ VIBE CODED
>
> This project was **vibe coded** — written with AI assistance and very
> little careful review. It works for the author's specific use case, but
> expect rough edges, unexpected behavior, and a few questionable design
> decisions. Use at your own risk, file corruption may occur Contributions,
> bug reports, and patience are welcome.

A Windows program for optimizing music libraries. It targets FLAC files,
image files (mainly by converting to JPEG XL), cue sheets, and lyrics —
optimizing both storage space and formatting. It also grades the library
for tag/lyrics/cover compliance and audits audio integrity (fake-lossless
detection via AudioAuditor). Mostly written in Python.

Desktop GUI (dark theme) + optional console menu.

## Quick Start

**Desktop app (installer):** Download `MusicLibraryOptimizer_Setup_v1.0.4_x64.exe`
from [Releases](https://github.com/dillydalli3r/MusicLibraryOptimizer/releases),
run it, and follow the first-launch wizard to pick your music folder.

**Portable:** Download `MusicLibraryOptimizer_v1.0.4_portable_x64.exe` and run it
directly from any folder — it is fully **self-contained**: it creates
`config.json` and `.dependencies/` next to itself on first run and uses no
external folders. Keep the whole folder together to move it anywhere.

**From source:** `Music Library Optimizer.bat` or `python app.py`
(requires `pip install mutagen`, optionally `Pillow` and `tqdm`).

**Console menu:** `python -m mlo`

> **64-bit only.** The app and every bundled tool (FLAC, libjxl, libjpeg-turbo,
> oxipng, AudioAuditor, rsgain, ffmpeg) are Windows x64 builds. A 32-bit
> build is not provided — the whole toolchain is 64-bit only.

## New in v1.0.4

- **Zero trailing newlines** — `.lrc`, `.cue` and the embedded `LYRICS` tag
  now end with **no trailing newline byte at all** (previously they kept the
  standard single POSIX newline). No wasted bytes, no blank last line, no
  trailing spaces on any line.
- **Lyrics sync on format switch** — when you change the lyrics format in
  Settings, lyrics are copied between LRC and embedded:
  - **EMBEDDED**: any `.lrc` is copied into the `LYRICS` tag (and the
    `.lrc` removed).
  - **LRC**: embedded `LYRICS` are written to an `.lrc` file (and the
    embedded tag removed).
  - **BOTH**: if embedded lyrics exist, an `.lrc` is written; if only an
    `.lrc` exists, it's copied to embedded — both stay in sync.
- **Truly self-contained portable version** — the portable exe creates
  `config.json` and `.dependencies/` in its own folder on first run and
  uses no external folders. If the folder isn't writable, the app warns on
  startup.
- **Check for updates on start toggle** — Settings → Interface →
  **Check for Updates on Start** (default on) makes the app check GitHub for
  a new release at launch (once per interval), for both the portable and the
  installed version. Turn it off to disable the automatic check; manual
  checking via ⓘ About → Check for Updates always works.

## New in v1.0.3

- **Portable + installer downloads** — every release now ships both a
  portable `MusicLibraryOptimizer_vX.Y.Z_portable_x64.exe` (run anywhere, no
  install) and the Inno Setup installer.
- **Bug fixes**
  - Writing lyrics/removing lyrics no longer fails on files with no tag
    block (FLAC/OGG/Opus without a Vorbis comment) — `set_lyrics`/
    `delete_lyrics` now create the tag block first.
  - Audit Library's skip pass opens each already-audited file once instead
    of twice (read + normalize merged).
- **Performance** — `AudioFile` now caches the Vorbis-comment tag reads,
  so the grader / auto-tagger stop re-scanning every tag on every lookup
  (cache is invalidated on any write). This speeds up per-track grading and
  auto-tagging on large libraries.
- **x64 explicit** — release assets are labelled x64; the app is 64-bit
  only (the entire toolchain is x64).

## New in v1.0.2

- **Update checker fixed** — the "Check for Updates" button (and the About
  dialog) now actually works. Previously every update check failed silently
  because the updater used a logging API that doesn't exist (`log(tag=...)`)
  and the installer asset matcher didn't recognise `MusicLibraryOptimizer_Setup_vX.Y.Z.exe`.
  Now it:
  - lists GitHub releases (not just `/latest`) and picks the newest stable
    version,
  - correctly finds the installer asset URL,
  - gives clear feedback for every outcome (update available / already
    latest / network error), and
  - logs update availability to the console on the periodic auto-check.
  Verified: a v1.0.0 install detects v1.0.1/v1.0.2 and the installer URL
  downloads (HTTP 200).

## New in v1.0.1

- **JXL reverse fix** — "Convert JXL back to JPEG/PNG" is now an exclusive
  mode: it only converts `.jxl` back and leaves other files untouched, so
  files no longer alternate between `.jpg/.png` and `.jxl` on every run.
- **8/8 tools detected** — the sidebar tool counter now counts simple-dr-meter
  too (previously showed 7/8 even though everything worked).
- **Performance** — Auto Tagging and CD rip-log scoring now run
  multithreaded across albums (in addition to the already-threaded lyrics,
  cue, FLAC, image and grading passes).
- **Guaranteed clean text output** — `.lrc`, embedded lyrics and `.cue`
  files are guaranteed to have no trailing spaces on any line, no blank line
  at the end, and **no trailing newline byte at all** (verified byte-exact).
- **Quality of life** — right-click a track/album in the Library tree for a
  **Run Script…** submenu (run any of the 8 scripts on just that item) and
  an **Open in Explorer** option.
- **Setup wizard updated** — reflects the full 8-script feature set, the
  current toolchain (rsgain, ffmpeg, simple-dr-meter) and the new preset.

## New in v1.0.0

- **Windows Installer** (Inno Setup) — proper installation with Start Menu,
  desktop shortcut, uninstaller, and auto-update support.
- **First-Launch Setup Wizard** — on first run, a guided wizard helps you
  choose your music library folder, review the recommended settings preset,
  and understand the external toolchain.
- **Settings Preset** — recommended defaults for FLAC (level 8, no seektables),
  Images (JPEG XL effort 10, convert to JXL), Lyrics (embedded, clean LRC),
  CUE (normalized), MEDIA/SOURCE normalization, Audio Audit (all detectors on),
  and more. User-specific paths (music folder, external tool paths) are never
  overwritten by the preset.
- **Auto-Update Checker** — checks GitHub Releases every 7 days; shows a
  notification in the About dialog when a new version is available with one-click
  download & install.
- **About / Updates Dialog** — version info, release notes, one-click "Check for
  Updates", and direct installer download.
- **Audio Auditor Configuration** — Settings → Audio Auditor now exposes all
  detector toggles (clipping, MQA, AI, fake stereo, silence, dynamic range,
  true peak, LUFS, BPM) and cutoff allowance.
- **CD Rip-Log Grading** — per-disc `LOG_GRADE` (0-100) for `MEDIA=CD`
  releases, deterministic `CD-N.log` / `CD-N.cue` naming.

## Dependencies (automatic)

The GUI's **Dependencies…** dialog (sidebar → MANAGE) downloads **exact,
pinned versions** of every tool (never "latest") from GitHub releases and
installs them into `.dependencies/`, so installs are reproducible:

| Tool           | Pinned    | Source                        | Installed files             |
|----------------|-----------|-------------------------------|-----------------------------|
| FLAC           | 1.5.0     | xiph/flac                     | flac.exe, metaflac.exe      |
| libjxl         | 0.12.0    | libjxl/libjxl                 | cjxl.exe, djxl.exe          |
| libjpeg-turbo  | 3.2.0     | libjpeg-turbo/libjpeg-turbo   | jpegtran.exe                |
| oxipng         | 10.2.0    | oxipng/oxipng                 | oxipng.exe                  |
| AudioAuditor   | 2.0.0     | Angel2mp3/AudioAuditor        | AudioAuditorCLI.exe         |
| rsgain         | 3.7       | complexlogic/rsgain           | rsgain.exe                  |
| ffmpeg         | 2026.8.19 | BtbN/FFmpeg-Builds            | ffmpeg.exe, ffprobe.exe     |
| simple-dr-meter| 0.0.0     | magicgoose/simple-dr-meter    | main.py (source + numpy)    |

Each tool shows its installed and pinned version with a Download / Update /
Reinstall button, plus Install/Update All. The console menu offers the same
via option 11. libjpeg-turbo only ships NSIS installers for Windows, so that
one is unpacked with 7-Zip when available (also used for libjxl's
non-standard zip compression); without 7-Zip it falls back to a silent
install into a temporary folder. AudioAuditor ships a single self-contained
exe that is copied as-is — no extraction needed. simple-dr-meter is a Python
script (no Windows binary) that needs ffmpeg on PATH and the Python packages
`numpy` and `chardet` installed (e.g. `pip install numpy chardet`) in the
Python used to run the app.

## Scripts

| # | Script            | What it does                                              |
|---|-------------------|-----------------------------------------------------------|
| 1 | Format Lyrics     | Cleans embedded/LRC lyrics, converts format, normalizes MEDIA/SOURCE |
| 2 | Format CUEs       | Normalizes .cue sheets (TRACK/INDEX padding, FILE lines, DISCID) |
| 3 | Optimize FLACs    | Lossless re-encode via flac.exe, strips PADDING/PICTURE etc. |
| 4 | Grade Library     | Per-album compliance report; albums grade 100% (all checks pass) or 0% |
| 5 | Process Images    | JPEG XL conversion / lossless JPEG/PNG optimize / reverse  |
| 6 | Audit Library     | Audio integrity audit via the AudioAuditor CLI            |
| 7 | DR & ReplayGain   | Writes ReplayGain (rsgain) and Dynamic Range (simple-dr-meter) tags |
| 8 | Auto Tagging      | Derives ALBUMITUNESADVISORY (from track ITUNESADVISORY) and INSTRUMENTAL (from lyrics presence) |

**Run All** runs **every** script (1–8) by default, in order. The exact order
(and which scripts run at all) is configurable: Settings → **Run All Order**,
or the console menu's configuration. **Optimize Selected** runs the same
pipeline against the checked items.

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

### Force options

The Library toolbar has a **Force** pill next to a **▾** menu that toggles
each force option individually (the master pill sets all of them):

- **Re-encode FLACs** — re-encode every FLAC regardless of ENCODER markers.
- **Re-encode images** — reprocess images regardless of ENCODER markers.
- **Audit** — re-audit files that already carry an `AUDIT` verdict and
  re-score rip logs even when `LOG_GRADE` is present.
- **DR & ReplayGain** — re-calculate DR/ReplayGain even when already tagged.

Applies to **Optimize Selected**, **Run All** and **Run Custom**.

### DR & ReplayGain (script 7)

For every album folder this writes the loudness tags the grader requires:

- **ReplayGain** via [rsgain](https://github.com/complexlogic/rsgain) —
  `rsgain easy` computes and writes `REPLAYGAIN_TRACK_GAIN` /
  `REPLAYGAIN_TRACK_PEAK` / `REPLAYGAIN_ALBUM_GAIN` / `REPLAYGAIN_ALBUM_PEAK`
  (album gain is per folder, matching your album layout). Defaults: -18 LUFS
  target, sample peak, clipping protection on positive gains. Files that
  already carry ReplayGain tags are skipped (`-S`) unless forced.
- **Dynamic Range** via [simple-dr-meter](https://github.com/magicgoose/simple-dr-meter)
  — writes `DYNAMIC RANGE` (per track) and `ALBUM DYNAMIC RANGE` (the
  album's official DR value) parsed from the `dr.txt` log it generates.
  Requires ffmpeg/ffprobe and numpy in the Python that runs the script.

A full-library run invokes rsgain once on the whole tree (its album gain is
still per folder); "selected" runs invoke it per album.

### Auto Tagging (script 8)

Derives tags that would otherwise be filled in by hand:

- **ALBUMITUNESADVISORY** from each track's manual `ITUNESADVISORY`
  (`0` unrated / `1` explicit / `2` edited-safe). Counts **every** track in
  the album (all discs): any explicit → `1`, else any edited/safe → `2`,
  else `0`. The derived value is written to every track.
- **INSTRUMENTAL** from lyrics presence: a track **with** lyrics (embedded
  LYRICS or an `.lrc` sidecar) is always tagged `0` (non-instrumental),
  regardless of its current value. Tracks **without** lyrics are left
  untouched — they may still be non-instrumental, just missing downloaded
  lyric files.

Albums that already carry the correct values are skipped unless forced.

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

## Auto-Updates

The app checks for updates on GitHub Releases every 7 days (silent check).
When an update is found, the **About** dialog (status bar → ⓘ About) shows
a notification with release notes and a **Download & Install** button that
fetches the new installer and launches it automatically.

You can also manually check anytime via **About** → **Check for Updates**.

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
    loudness.py                 DR (simple-dr-meter) + ReplayGain (rsgain)
    cli.py                      Interactive console menu
    updater.py                  Auto-update checker (GitHub Releases)
config.json                     Persisted settings (created on first save)
app_icon.ico                    Application icon
.dependencies/                  External toolchain (pinned versions):
    flac v1.5.0/                flac.exe, metaflac.exe
    libjxl v0.12.0/             cjxl.exe, djxl.exe
    libjpeg-turbo v3.2.0/       jpegtran.exe
    oxipng v10.2.0/             oxipng.exe
    AudioAuditor v2.0.0/        AudioAuditorCLI.exe
    rsgain v3.7/                rsgain.exe
    ffmpeg v2026.8.19/          ffmpeg.exe, ffprobe.exe
    simple-dr-meter/            main.py v0.0.0 (source + numpy)
```

## Building the installer

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed.

```bash
# Build the exe first
pip install pyinstaller mutagen pillow
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "Music Library Optimizer" --icon app_icon.ico ^
    --hidden-import mutagen.aac app.py

# Then compile the installer
iscc "Music Library Optimizer.iss"
```

Output: `dist/MusicLibraryOptimizer_Setup_v1.0.4_x64.exe`

## Rebuilding the exe (without installer)

```bash
pip install pyinstaller mutagen pillow
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "Music Library Optimizer" --icon app_icon.ico ^
    --hidden-import mutagen.aac app.py
```

The exe reads `config.json` and `.dependencies/` from its own folder.

## License

MIT License — see [LICENSE](LICENSE) for details.
