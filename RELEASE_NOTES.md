# Music Library Optimizer v1.0.8

A Windows desktop app (dark-theme GUI + optional console menu) for optimizing
music libraries: lossless FLAC re-encoding, JPEG XL image conversion, cue-sheet
and lyrics formatting, ReplayGain/Dynamic Range calculation, per-album
tag/lyrics/cover compliance grading, and fake-lossless audio auditing.

**64-bit only.** The app and every bundled tool are Windows x64 builds.

## Current featureset

- **FLAC optimizer** — lossless re-encode at the chosen compression level,
  removes padding/seektable, strips PICTURE/CUESHEET blocks, and tags output
  with encoder markers so re-runs skip finished files.
- **Image processing** — re-encode to JPEG XL, convert JXL back to JPEG/PNG,
  or lossless in-place optimization (jpegtran / oxipng) with configurable
  JPEG progressive output and PNG optimization level. Alpha removal, metadata
  stripping, and "rename to cover" (one image per folder).
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
  with a live library tree, grade details, and column/filter options. Also
  grades lyrics/cue **formatting** and non-audio files.
- **Safe updates** — GitHub update checks, one-click download & install that
  closes idle instances and waits for every process before running setup.
  Optional auto-install on start.
- **Dependencies manager** — downloads and pins every bundled CLI tool.
- **Setup Guide** — modal first-run wizard with folder validation, presets
  and dependency list; reopenable via the status bar ★ Guide button.

## What's new in v1.0.8

- **Reworked library checkboxes.** Select All / Ctrl+A now actually ticks
  every row (the old handler set the internal state but never re-rendered
  the ☑ glyphs). Folder rows cascade: an album is checked when all of its
  tracks are, an artist when all albums are, and partially selected folders
  show a ◐ partial box. Clicking a folder checks or unchecks everything
  under it; clicking a leaf updates its folder chain. Shift+click ranges
  and Clear Selection follow the same rules.
- **Show other files in the library viewer.** The new "Show files" toggle
  (Library filter bar, and Settings → Interface) displays `.cue`, `.log`,
  `.lrc`, `.jxl`, `.jpg`/`.jpeg` and `.png` rows under each album, each with
  its own grade: cues and LRCs are checked against the canonical formatting,
  logs for being non-empty, and images for being real files. They
  participate in the checkbox cascade and Select All.
- **Force menu is now complete.** Added Format lyrics and Format CUE sheets
  to the Force ▾ menu. `force_lyrics` bypasses the optimize on/off switches
  and forces a re-format; `force_cue` rewrites every cue unconditionally.
  Run All always runs all eight scripts across the whole library and honors
  every Force option.
- **Fixed embedded lyrics failing to optimize.** The old formatter bug glued
  lines together into forms like
  `[00:00.00][00:45.53]Stretching, filing[00:46.86]Against her skin`. The
  formatter now splits every timestamp boundary back onto its own line, so
  running the Lyrics script fixes previously mangled embedded lyrics (and
  resolves the ESLyrics "duplicate first line" display).

## Install

- **Installer:** `MusicLibraryOptimizer_Setup_v1.0.8_x64.exe` — run it and
  follow the first-launch wizard to pick your music folder.
- **Portable:** `MusicLibraryOptimizer_v1.0.8_portable_x64.exe` — run from
  any folder; creates `config.json` and `.dependencies/` next to itself.
- **From source:** `Music Library Optimizer.bat` or `python app.py`
  (requires `pip install mutagen`; optionally `Pillow` and `tqdm`).
