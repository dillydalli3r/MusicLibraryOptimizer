# Music Library Optimizer v1.2.0

> ## ⚠️ VIBE CODED
>
> This project was **vibe coded** — written with AI assistance and very
> little careful review. It works for the author's specific use case, but
> expect rough edges, unexpected behavior, and a few questionable design
> decisions. Use at your own risk, file corruption may occur Contributions,
> bug reports, and patience are welcome.

A Windows program for optimizing music libraries. It targets FLAC files,
image files (now with **cover resize / crop to square**), cue sheets, and
lyrics (including **Enhanced / Extended LRC word-sync**) — optimizing both
storage space and formatting. It also grades the library for tag/lyrics/cover
compliance (now with **cover size & squareness enforcement**) and audits audio
integrity (fake-lossless detection via AudioAuditor). Mostly written in Python.

Desktop GUI (Tkinter, dark-themed, titlebar shows `v1.2.0`) + command-line app (`mlo`) +
optional interactive console menu. **v1.2.0 adds cover resize/crop (now with
Force Exact `1000×1000`), per-format overrides, Enhanced LRC (now with
`[00:00.00]` compat), black spectrum icon (white ascending bars), and a reorganized
Settings dialog (PySide6/Qt revamp removed — stable Tkinter is now the GUI).**

## Quick Start

**Desktop app (installer):** Download `MusicLibraryOptimizer_Setup_v1.2.0_x64.exe`
from [Releases](https://github.com/dillydalli3r/MusicLibraryOptimizer/releases),
run it, and follow the first-launch wizard to pick your music folder.

**Portable:** Download `MusicLibraryOptimizer_v1.2.0_portable_x64.exe` and run it
directly from any folder — it is fully **self-contained**: it creates
`config.json` and `.dependencies/` next to itself on first run and uses no
external folders. Keep the whole folder together to move it anywhere.

**Command line:** the release also ships `mlo.exe` - run it directly,
or `mlo install --user` / `mlo install --system` to put `mlo` on your
PATH (the system scope requests admin elevation automatically). See
[CLI (mlo)](#cli-mlo) below.

**From source:** `Music Library Optimizer.bat` or `python app.py`
(requires `pip install mutagen`, optionally `Pillow` and `tqdm` — Tkinter is stdlib).

**Console menu:** `python -m mlo` or `mlo menu`

> **64-bit only.** The app and every bundled tool (FLAC, libjxl, libjpeg-turbo,
> oxipng, AudioAuditor, rsgain, ffmpeg) are Windows x64 builds. A 32-bit
> build is not provided — the whole toolchain is 64-bit only.

## New in v1.2.0

- **Cover Art — Resize to Target Resolution** — `Settings → Cover Art → Resize & Crop`
  → `Resize Covers to Target Size` + `Global Target Size (px)` (e.g., `1000 → 1000×1000`).
  When enabled, every cover is center-cropped (if needed) and resized with Pillow
  `LANCZOS` before `cjxl` / `jpegtran` / `oxipng`. Per-format overrides
  `Apply to JPEG / PNG / JXL` + `Target Size (0=global)` let you keep e.g. JPEG at
  `1000` while leaving PNG untouched. Disabled by default for compatibility.
- **Auto-Crop Threshold** — `Crop Threshold (0.00–0.50)` — `0.05 = 5%` means
  `1000×1050` stays, `1000×1100` is center-cropped to `1:1`. Only crops when
  `|w/h−1| > threshold`.
- **Force Exact Size (e.g. 1000×1000)** — `Settings → Cover Art → Resize & Crop → Force
  Exact Size` — when on with Resize enabled, *every* non-square cover is
  center-cropped to 1:1 *before* resizing, guaranteeing exactly `target×target`
  output (e.g. `1000×1000`) regardless of original aspect or threshold. Off by
  default; when on, `1000×1050`, `800×600`, `500×700` etc. all become exactly
  `1000×1000` (cropped then LANCZOS-resized). Grading with `Enforce Size` + `Enforce
  Square` will then pass only for exactly-sized covers.
- **Cover Grading Enforcement** — `Settings → Grading — Cover Enforce` adds
  `Enforce Size` (exact `target×target` ±1px) + `Enforce Square` (aspect within
  threshold). Off by default; when on, albums with wrong covers fail grading with
  details like `wrong size 500×500 → 1000×1000` or `not square 800×500`.
- **Enhanced / Extended LRC** — `Settings → Lyrics → Enhanced LRC` adds
  word-level `<mm:ss.xx>` support (e.g., `"[00:12.34] <00:12.34> Hello <00:12.60> world"`).
  Timestamps are normalized to the chosen precision (2/3 decimals, carry handled),
  `Extended` allows multiple `[mm:ss.xx]` on one line for karaoke, and the grader
  validates word-timestamp order/format.
- **Reorganized Settings** — Tkinter `app.py` dialog is now grouped as `FLAC Encoding /
  Cover Art — Processing / Resize & Crop / Per-Format / Lyrics / Enhanced LRC (now with
  `[00:00.00]` compat) / CUE / Tags / Grading / Audio Audit / Interface / Updates` with
  clear sub-sections and tooltips, keeping ~60 options scannable.
- **Library Viewer / Updater / Deps polish** — Tkinter viewer has larger expand arrows
  (28→32px row, wider hit-area), fixed checkbox cascade (selecting a folder now correctly
  checks all children even after expand, no more stale unchecked children), `Clear Filters`,
  persistent `Bad only / Show files / Sort`, faster inserts; updater retries on `429/5xx`
  with `Retry-After`, verifies `MZ`+size + speed/ETA; deps installer resumes, SHA256 checks,
  `7-Zip` hint.

## New in v1.1.0

- **New GUI (PySide6/Qt):** every screen restyled - sidebar navigation,
  animated toggles, colored console, responsive library tree with real
  tri-state checkboxes, and worker threads for scans/runs (Refresh can
  no longer trip over itself).
- **Themes:** Dark, Light, Follow-system plus eight accent colors or a
  custom picker. The **native window title bar** is recolored to match
  (caption, title text, accent-tinted border).
- **CLI version of the app** (`mlo.exe`) with run/config/deps/menu/gui
  commands and a **PATH self-installer** (`--user` / `--system` with
  automatic UAC elevation). Shares `config.json` and `.dependencies`
  with the GUI.
- **Lyrics formatter hardened:** stacked timestamps expand one line per
  timestamp, a `[00:00.00]` stacked against another timestamp is treated
  as a start marker and dropped, timestamp-only fragments lend their
  stamps to the next untimed line, and the EMBEDDED consolidation only
  deletes an LRC after the lyrics are safely inside the tag. `BOTH`
  format now reconciles both sides (embedded wins a disagreement).
- **Library toolbar:** **Unselect All** button, **Show: Audio files /
  All files** view switch, and right-click **Open in Mp3tag / Picard**
  acts on the whole checked selection.
- New app icon; the v1.0.x Tkinter GUI is preserved under `legacy/`.

## New in v1.0.10

- **Open selected tracks in Mp3tag** now uses the checked selection
  (not just the right-clicked row); "Clear Sel" renamed to
  **Unselect All**.

## New in v1.0.9

- **Fixed updates being blocked by stale instances.** Instance records are
  now pruned correctly — dead processes were being treated as alive (a
  "still working" dialog listed many ghost PIDs all stuck on "library
  scan", so **Download & Install** could never start). Dead-PID detection
  now checks the actual Windows error code.
- **Check for Updates on Start actually works.** The on-start check always
  performs a real GitHub query (no more silent interval skip) and reports
  the outcome to the console ("Checking for updates…", "Update available",
  "already on the latest version", or the error).
- **Force options only apply when Force is on.** Checking items in the
  Force ▾ dropdown arms them; nothing is forced unless the master Force
  toggle is on.
- **Strict file-type grading.** An album folder that contains files other
  than music, cover art, `.cue`, `.log` and `.lrc` now **fails grading**
  by default (e.g. stray `.txt`, `.m3u`, `.db`, thumbs.db). What counts is
  configurable in Settings → **Grading** (Allow Music / Cover / .cue /
  .log / .lrc / Other).
- **CD rip checksum verification.** For albums with **MEDIA = CD**, tracks
  are verified against the CRC-32 checksums printed in the `.log` (EAC
  Test/Copy CRC, AccurateRip, or XLD CRC32 hash) by decoding each file with
  ffmpeg and comparing CRCs. A match writes **AUDIT = REAL**, a mismatch
  writes **AUDIT = FAKE** — the checksum result takes precedence over
  AudioAuditor for those files (Settings → Audio Auditor → **Verify CD Rips
  vs .log Checksums**, default on).
- **Lyrics `[00:00.00]` blank-marker fix confirmed.** Embedded lyrics whose
  empty timing line was glued onto the next line (a `[00:00.00][00:45.53]
  Stretching, filing[00:46.86]…` mess that ESLyrics showed as a duplicated
  first line) are now split back onto separate lines by the Lyrics script.
- **Cleanup** — removed stale build artifacts; every `mlo` module is used.

## New in v1.0.8

- **Reworked library checkboxes.** **Select All** / **Ctrl+A** now actually
  ticks every row (the old handler set the internal state but never
  re-rendered the ☑ glyphs). Folder rows cascade: an album is checked when
  all of its tracks are, an artist when all albums are, and partially
  selected folders show a ◐ partial box. Clicking a folder checks or
  unchecks everything under it; clicking a leaf updates its folder chain.
  Shift+click ranges and Clear Selection follow the same rules.
- **Show other files in the library viewer.** The new **Show files** toggle
  (Library filter bar, and Settings → Interface → **Show Other Files in
  Library**) displays `.cue`, `.log`, `.lrc`, `.jxl`, `.jpg`/`.jpeg` and
  `.png` rows under each album, **each with its own grade**: cues and LRCs
  are checked against the canonical formatting (PASS/FAIL with a
  "needs formatting" note), logs for being non-empty, and images for being
  real files. They participate in the checkbox cascade and Select All too.
- **Force menu is now complete.** Added **Format lyrics** and **Format CUE
  sheets** to the Force ▾ menu (all force-able scripts are now listed).
  `force_lyrics` bypasses the optimize on/off switches and forces a
  re-format; `force_cue` rewrites every cue unconditionally. Run All always
  runs all eight scripts across the whole library and honors every Force
  option.
- **Fixed embedded lyrics failing to optimize.** The old formatter bug
  (space-after-timestamp regex eating newlines) glued lines together into
  forms like `[00:00.00][00:45.53]Stretching, filing[00:46.86]Against her
  skin`. The formatter now splits every timestamp boundary back onto its
  own line, so running the Lyrics script fixes previously mangled embedded
  lyrics (this also resolves the ESLyrics "duplicate first line" display).

## New in v1.0.7

- **Fixed "Download & Install" closing the app without updating.** The
  shutdown helper is now launched through `Win32_Process.Create` so it is a
  fully detached process that survives the app exiting (a plain child was
  torn down with the parent's console on some setups). It waits for every
  app PID, then runs setup and deletes the downloaded installer. A fallback
  launch path is used if the WMI bootstrap fails.
- **Auto-install updates on start (new setting).** Settings → Interface →
  **Auto-Install Updates on Start** (default off) downloads and installs a
  newer release found at startup when the app is idle; it still honors
  **Confirm Before Installing Updates**. The previous launch-time check only
  logged — the auto-check handler was never actually reached (it unpacked a
  `None` result and was swallowed by the drain-loop guard).
- **Grader now checks lyrics / cue FORMATTING**, not just presence. It runs
  the same canonical form the Lyrics and CUE scripts would produce and fails
  the album when they differ: LRC timestamp precision, metadata lines,
  blank collapsing, trailing newlines, CUE CRLF/BOM, FILE type and quoting,
  DISCID/track/index normalization. It also flags **merged timestamps**
  (`[00:00.00][00:45.53]…`) that break ESLyrics on foobar2000.
- **Fixed lyrics formatter gluing timestamp-only lines.** An empty timing
  line `[00:00.00]` followed by `[00:45.53]Stretching, filing` was being
  merged into `[00:00.00][00:45.53]Stretching, filing` because the
  space-after-timestamp regex also consumed newlines. It now only strips
  spaces/tabs, so timestamp-only markers stay on their own line.
- **Performance**
  - Targeted grades (right-click → Grade, GUI scans) no longer walk the
    whole library first; albums are derived from the explicit targets.
  - Auto Tagging loads each file **once** per album instead of parsing it
    up to ~6 times (advisory + instrumental passes share one read).
  - `config.json` is only rewritten when the library folder actually
    changes, not on every run start.
  - Postponed/refused updates no longer leave the dialog button stuck on
    "Downloading…"; the downloaded installer is kept for an instant retry.
- **Code split for maintainability.** `app.py` (now ~2600 lines) moved its
  theme/constants/widgets into `mlo/gui.py` and its four dialog windows
  (Dependencies, Settings, Custom Run, First-run wizard) into
  `mlo/gui_dialogs.py`.
- **Other hardening** — scanning errors are surfaced instead of silently
  swallowed; a release tag with no installer asset is no longer offered as
  an update; Compact-mode toggling rebuilds the tree; tab-switching no
  longer un-maximizes the window; the update checker’s helper output is
  escaped for PowerShell.

## New in v1.0.6

- **Fixed installer never launching / launching too early** — the in-app
  "Download & Install" flow now works reliably. The shutdown helper used to
  receive PIDs in a format PowerShell 5.1 mis-parsed (commas treated as a
  thousands separator), so the installer silently never ran for a single
  window. The helper now takes a space-separated list, waits for **every**
  app PID (including the caller) to exit, launches setup, and deletes the
  downloaded installer afterwards. The app also waits up to 20 s for other
  instances to close and asks before forcing the installer through.
- **Fixed image data loss** — JPEG XL conversion no longer deletes the
  source before the destination is secured (a failed rename previously lost
  **both** files), and with "rename to cover" enabled, a folder with
  front/back/booklet images no longer clobbers them all into a single
  `cover.*` — only one image per folder takes the cover name (preferring
  `cover`/`front`/`folder`), the rest keep their own names.
- **Fixed Dynamic Range grading** — the simple-dr-meter row parser expected
  one extra column and never matched, so DYNAMIC RANGE / ALBUM DYNAMIC RANGE
  tags were never written (the grader failed every album on DR). Now parsed
  and written correctly.
- **No more permanently wedged app** — closing the Dependencies dialog
  mid-download no longer leaves the app stuck "busy" forever; the download
  finishes in the background and the busy flag is released. The update /
  scan drain loops also survive a single malformed message instead of
  freezing, and closing the window during work now offers "Close anyway".
- **CUE formatting no longer corrupts sheets** — structural directives
  (PREGAP/POSTGAP/FLAGS/PERFORMER/TITLE/CATALOG/ISRC/SONGWRITER) are always
  kept; only REM comment lines are stripped. CRLF-only files are normalized
  to LF, a UTF-8 BOM is dropped cleanly, unquoted/single-quoted FILE lines
  are preserved, and renamed `CD-N.cue` files are still formatted.
- **Lyrics timestamp carry fix** — `[1:59.999]` at 2-decimal precision now
  becomes `[02:00.00]` instead of `[01:59.00]`; `[au:]`/`[la:]` metadata
  tags are stripped with the rest.
- **Cross-drive safety** — grading/auditing targets on a different drive
  than the music folder no longer crash on `relpath`.
- **Other hardening** — guarded mutagen import so the source/one-file build
  shows the friendly dependency dialog instead of crashing; metaflac
  failures are now surfaced instead of silently claiming success; mp3
  COMMENT writes no longer delete other-language translations; dependency
  downloads verify size and 7-Zip exit codes; temp files use `mkstemp`.

## New in v1.0.5

- **Safe update workflow** — the app now closes all idle instances and
  waits for external encoder processes before launching the installer.
  Updates are blocked while a script, dependency download, or library
  scan is active.
- **Worker limit** — Settings → Interface → **Worker Limit** caps the
  thread pool size used by every processing pass (0 = automatic), preventing
  disk contention on slower or shared machines.
- **Exact LRC/CUE/image controls** — new settings for LRC timestamp precision
  (2/3 decimals), metadata stripping, blank-line collapsing, optional final
  newline, CUE FILE type (WAVE/MP3), JPEG progressive output, and PNG
  optimization level (0–6).
- **Explicit target scope** — choosing a script from the right-click
  "Run Script…" menu or the sidebar now operates **only** on the selected
  files/folders; it never falls back to a full-library scan.
- **Open selected tracks in Mp3tag** — the built-in tag editor was removed
  and replaced with a right-click **Open selected tracks in Mp3tag** item:
  a single track opens directly in Mp3tag, an album opens its folder, and
  the sidebar **Mp3tag** button still opens the checked folders. Mp3tag is
  auto-detected (registry, common install dirs, PATH) or located manually
  on first use.
- **Music-tag write toggles** — Settings → Tags now lets you enable/disable
  AUDIT, LOG_GRADE, ReplayGain, and Dynamic Range tag writes independently.
- **Setup Guide** — the first-run wizard is now a modal **Setup Guide**
  with folder validation, preset overview, and dependency list. It can be
  reopened anytime via the status bar ★ Guide button.
- **Atomic config saves** — `config.json` is written to a temporary file
  and `os.replace`’d, so power loss or crashes never leave a corrupt file.
- **Toolbar wrapping** — the left action cluster wraps onto new rows when
  the window is narrow, so it never overlaps the right-side controls.
- **Tab border alignment** — Library/Console tabs now share identical
  padding and a 2px left margin so the selected tab’s white border isn’t
  clipped at the strip edge.
- **Sidebar redesign** — buttons are compact (8×6 padding, centered),
  carry icon glyphs, and the sidebar’s minimum width is 204 for a more
  square look.

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
each force option individually (the master pill sets all of them). When a
Force option is on, the corresponding script *always* reprocesses files and
*overwrites* the tags it writes to, even if they are already considered
up-to-date (the ENCODER/AUDIT/DR tags are rewritten with current values):

- **Re-encode FLACs** — re-encode every FLAC regardless of ENCODER markers
  (rewrites `ENCODER_PROGRAM/QUALITY/VERSION` after encoding).
- **Re-encode images** — reprocess images regardless of ENCODER markers
  (rewrites JPEG/PNG/JXL ENCODER tags after `jpegtran`/`oxipng`/`cjxl`).
- **Audit** — re-audit files that already carry an `AUDIT` verdict and
  re-score rip logs even when `LOG_GRADE` is present (rewrites `AUDIT`/`LOG_GRADE`).
- **Format Lyrics** — re-format LRC/embedded lyrics even if already canonical
  (rewrites `LYRICS`/`.lrc` and fixes `INSTRUMENTAL` if needed).
- **Format CUE sheets** — rewrite every `.cue` unconditionally (normalizes
  `FILE` lines, `TRACK`/`INDEX` padding, `DISCID`).
- **DR & ReplayGain** — re-calculate DR/ReplayGain even when already tagged
  (rewrites `REPLAYGAIN_*` and `DYNAMIC RANGE`/`ALBUM DYNAMIC RANGE`).
- **Auto Tagging** — re-derive `ALBUMITUNESADVISORY`/`INSTRUMENTAL` even when
  already correct.

Applies to **Optimize Selected**, **Run All** and **Run Custom**. The CLI
`mlo run --force` / `mlo all --force` sets *all* of the above at once.

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
  the **whole checked selection** loaded (the right-clicked folder when
  nothing is checked).

The toolbar also has **Enqueue in foobar2000**, **Mp3tag** and
**Picard** buttons that act on every checked folder in the tree, plus
**Refresh**, **Unselect All**, a **Show: Audio files / All files**
switch (lists each album's non-audio contents) and a **Compact** toggle
that hides the column headers. All
three apps are auto-detected via the registry (App Paths), common
install locations, or PATH; the first manual locate is remembered in
`config.json` (`foobar2000_path` / `mp3tag_path` / `picard_path`).

## CLI (mlo)

```
mlo run 1,2,3       run scripts by number (or names, or 'all')
mlo lyrics          single-script shortcuts: lyrics cues flac grade
mlo audit           ... images audit dr autotag - all accept the flags below
mlo all             run the scripts in your configured Run All order
mlo config          show all settings
mlo config key val  set a setting (e.g. music_folder)
mlo deps            list toolchain versions; mlo deps --install [all]
mlo install --user      put mlo on the current user's PATH (no admin)
mlo install --system    machine-wide PATH (UAC elevation requested)
mlo uninstall --user | --system
mlo menu            interactive console menu
mlo gui             launch the desktop GUI
```

Run options: `--folder DIR` overrides the music folder, `--targets P... P...`
restricts processing to given files/dirs, `--force` re-processes
everything, `--thorough` enables the deep audio audit.

The installer copies the CLI to `%LocalAppData%\Programs\Music Library
Optimizer` (user) or `C:\Program Files\Music Library Optimizer` (system)
and updates the matching PATH in the registry. A `mlo-home.txt` marker
next to the installed copy points back at the folder holding
`config.json` and `.dependencies`, so GUI and CLI always share settings
and the downloaded toolchain.

## Auto-Updates

The app checks for updates on GitHub Releases every 7 days (silent check).
When an update is found, the **About** dialog (status bar → ⓘ About) shows
a notification with release notes and a **Download & Install** button that
fetches the new installer and launches it automatically.

You can also manually check anytime via **About** → **Check for Updates**.

## Project layout

```
app.py                          GUI entry point (Tkinter, dark-themed) — v1.2.0
                                (PySide6/Qt `gui/` revamp removed; Tkinter is now primary)
mlo_cli.py                      CLI entry point (argparse; builds mlo.exe)
mlo/                            Core package — all processing logic
    __init__.py                 version + public re-exports (1.2.0)
    __main__.py                 python -m mlo entry
    paths.py                    Locations & constants (exe-aware)
    deps.py                     Optional dependency detection (mutagen/Pillow/tqdm)
    config.py                   config.json load/save & defaults (v1.2.0 keys)
    ui.py                       Console output helpers
    stats.py                    Run stats, byte accounting, progress hooks
    report.py                   Result report printing
    tools.py                    .dependencies tool auto-detection
    fetchdeps.py                GitHub release downloader / installer
    subproc.py                  Safe subprocess wrapper
    updater.py                  Auto-update checker (GitHub Releases)
    containers.py               FLAC/JXL/JPEG/PNG metadata tag I/O
    audio.py                    Unified multi-format tag abstraction
    lyrics.py / cue.py /        The feature modules
    flac.py / images.py /
    grader.py / discs.py        discs.py: CD-N naming + per-disc LOG_GRADE
    audit.py                    AudioAuditor CLI integration (script 6)
    loudness.py                 DR (simple-dr-meter) + ReplayGain (rsgain)
    autotag.py                  Advisory / instrumental tagging (script 8)
    cli.py                      Interactive console menu
    cliapp.py                   Non-interactive CLI + PATH installer
legacy/                         The v1.0.x Tkinter GUI (kept for reference)
    app_tkinter_v1_0_9.py       legacy GUI snapshot
assets/                         Application icons (black bg, white ascending spectrum)
    icon_256.png / icon_64.png  pre-rendered PNGs (main)
    icon_window_256.png         window-only transparent white bars
tools/                          Dev helpers & tests
    make_icon.py                Icon generator (Pillow)
    make_test_library.py        Synthetic music library builder
    test_*.py                   Lyrics / GUI regression tests
docs/
    archive/                    Historical release notes
        RELEASE_NOTES_v1.1.0.md v1.1.0 detailed notes (archived)
RELEASE_NOTES.md                v1.2.0 + v1.1.0 summary (current)
config.json                     Persisted settings (created on first save, ignored)
config.example.json             Example/default config (tracked)
app_icon.ico                    Application icon (256px ICO, black #0d0d0d bg)
app_icon_window.ico             Window icon (transparent white bars, for titlebar)
build_exe.bat                   PyInstaller one-file builder (GUI + CLI)
mlo.spec                        PyInstaller spec for CLI (mlo.exe)
Music Library Optimizer.spec    PyInstaller spec for GUI
Music Library Optimizer.iss     Inno Setup installer script (→ dist/*.exe)
Music Library Optimizer.bat     Windows launcher (pythonw app.py)
.github/workflows/
    release.yml                 CI: build + release on tag push
    opencode.yml                /oc PR review workflow
.dependencies/                  External toolchain (pinned versions, ignored):
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

Output: `dist/MusicLibraryOptimizer_Setup_v1.2.0_x64.exe` + `dist/MusicLibraryOptimizer_v1.2.0_portable_x64.exe` + `dist/mlo.exe`

## Rebuilding the exe (without installer)

```bash
# Or use the helper batch (builds both GUI + CLI):
build_exe.bat

# Manual PyInstaller (GUI):
pip install pyinstaller mutagen pillow
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "Music Library Optimizer" --icon app_icon.ico ^
    --hidden-import mutagen.aac app.py
# CLI:
python -m PyInstaller --noconfirm --clean --onefile --console ^
    --name mlo --icon app_icon.ico ^
    --hidden-import mutagen.aac mlo_cli.py
```

The exe reads `config.json` and `.dependencies/` from its own folder.

## License

MIT License — see [LICENSE](LICENSE) for details.
