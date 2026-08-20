# Music Library Optimizer v1.0.6

A Windows desktop app (dark-theme GUI + optional console menu) for optimizing
music libraries: lossless FLAC re-encoding, JPEG XL image conversion, cue-sheet
and lyrics formatting, ReplayGain/Dynamic Range calculation, per-album
tag/lyrics/cover compliance grading, and fake-lossless audio auditing.

**64-bit only.** The app and every bundled tool are Windows x64 builds.

## Current featureset

- **FLAC optimizer** — lossless re-encode at the chosen compression level,
  removes padding/seektable, strips PICTURE/CUESHEET blocks, and tags the
  output with encoder markers so re-runs skip finished files.
- **Image processing** — re-encode to JPEG XL, convert JXL back to
  JPEG/PNG, or lossless in-place optimization (jpegtran / oxipng) with
  configurable JPEG progressive output and PNG optimization level. Alpha
  removal, metadata stripping, and "rename to cover" (one image per folder).
- **CUE formatter** — normalizes spacing, FILE type (WAVE/MP3), track/index
  numbering and DISCID, strips REM comments, renames multi-disc cues to
  `CD-N.cue`, and preserves all structural directives.
- **Lyrics** — LRC/embedded conversion, timestamp precision (2/3 decimals),
  metadata stripping, blank-line collapsing, optional final newline, and
  MEDIA/SOURCE + instrumental normalization.
- **Dynamic Range & ReplayGain** — per-track and album Dynamic Range via
  simple-dr-meter, ReplayGain via rsgain, with optional tag-write toggles.
- **Auto tagging** — fills advisory/instrumental/media/source fields.
- **Audit** — fake-lossless detection via AudioAuditor; verdicts written as
  AUDIT tags.
- **Grader** — per-album compliance grading (tags, lyrics, cover, DR, logs)
  with a live library tree, grade details, and column/filter options.
- **Safe updates** — GitHub update checks, one-click download & install that
  closes idle instances and waits for every process before running setup.
- **Dependencies manager** — downloads and pins every bundled CLI tool.
- **Setup Guide** — modal first-run wizard with folder validation, presets
  and dependency list; reopenable via the status bar ★ Guide button.

## What's new in v1.0.6

- **Fixed installer never launching / launching too early.** The in-app
  "Download & Install" flow now works reliably: the shutdown helper takes a
  space-separated PID list (PowerShell 5.1 mis-parsed the old comma form),
  waits for **every** app PID including the caller, runs setup, then deletes
  the downloaded installer. The app also waits up to 20 s for other windows
  to close and asks before forcing the installer through.
- **Fixed image data loss.** JXL conversion now secures the destination
  before removing the source (a failed rename previously lost both files),
  and "rename to cover" no longer clobbers front/back/booklet scans into one
  `cover.*` — only one image per folder takes the cover name.
- **Fixed Dynamic Range grading.** The simple-dr-meter row parser never
  matched (one column off), so DR tags were never written and albums failed
  grading on DR. Now parsed and written correctly.
- **No more permanently wedged app.** Closing the Dependencies dialog
  mid-download no longer leaves the app stuck "busy"; the update/scan drain
  loops survive a single malformed message; closing during work offers
  "Close anyway".
- **CUE formatting no longer corrupts sheets.** Structural directives
  (PREGAP/POSTGAP/FLAGS/PERFORMER/TITLE/CATALOG/ISRC/SONGWRITER) are always
  kept; only REM comments are stripped. CRLF → LF normalization and BOM
  handling fixed; unquoted/single-quoted FILE lines preserved; renamed cues
  still get formatted.
- **Lyrics timestamp carry fix** — `[1:59.999]` at 2 decimals becomes
  `[02:00.00]`; `[au:]`/`[la:]` metadata stripped.
- **Cross-drive safety** — grading/auditing targets on another drive no
  longer crash on `relpath`.
- **Other hardening** — guarded mutagen import (friendly dependency dialog
  instead of a crash), metaflac failures surfaced, mp3 COMMENT writes keep
  other-language translations, dependency downloads verify size + 7-Zip exit
  codes, temp files use `mkstemp`.

## What's new in v1.0.5

- Safe update workflow (close idle instances, wait for encoder processes,
  block updates during active work).
- Worker limit setting (0 = auto) caps all processing thread pools.
- Exact LRC/CUE/image controls: timestamp precision, metadata stripping,
  blank-line collapsing, optional final newline, CUE FILE type, JPEG
  progressive, PNG optimization level.
- Explicit target scope — scripts run **only** on the selected files/folders.
- Built-in tag editor removed; right-click **Open selected tracks in Mp3tag**
  instead (track opens directly, album opens its folder; sidebar Mp3tag
  button unchanged).
- Music-tag write toggles (AUDIT, LOG_GRADE, ReplayGain, Dynamic Range).
- Modal Setup Guide first-run wizard + reopenable ★ Guide button.
- Atomic `config.json` saves (temp file + `os.replace`).
- Toolbar wrapping, tab border alignment, compact icon sidebar.

## Install

- **Installer:** `MusicLibraryOptimizer_Setup_v1.0.6_x64.exe` — run it and
  follow the first-launch wizard to pick your music folder.
- **Portable:** `MusicLibraryOptimizer_v1.0.6_portable_x64.exe` — run from
  any folder; creates `config.json` and `.dependencies/` next to itself.
- **From source:** `Music Library Optimizer.bat` or `python app.py`
  (requires `pip install mutagen`; optionally `Pillow` and `tqdm`).
