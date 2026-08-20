# Music Library Optimizer v1.0.9

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
- **Audit** — fake-lossless detection via AudioAuditor, plus **CD checksum
  verification** against `.log` CRCs for MEDIA=CD rips; verdicts written as
  AUDIT tags.
- **Grader** — per-album compliance grading (tags, lyrics, cover, DR, logs,
  **allowed file types**) with a live library tree, grade details, and
  column/filter options.
- **Safe updates** — GitHub update checks, one-click download & install that
  closes idle instances and waits for every process before running setup.
  Optional auto-install on start.
- **Dependencies manager** — downloads and pins every bundled CLI tool.
- **Setup Guide** — modal first-run wizard with folder validation, presets
  and dependency list; reopenable via the status bar ★ Guide button.

## What's new in v1.0.9

- **Fixed updates being blocked by stale instances.** Dead processes were
  treated as alive, so ghost instance records (all stuck on "library scan")
  permanently blocked Download & Install with an "Update postponed" dialog.
  Dead-PID detection now checks the Windows error code and stale records are
  pruned, so updates can actually start.
- **Check for Updates on Start actually works.** The on-start check always
  queries GitHub (no silent interval skip) and logs the result: "Checking
  for updates…", "Update available", "already on the latest version", or the
  error.
- **Force options only apply when Force is on.** Items ticked in the Force ▾
  dropdown arm individual options; nothing is forced unless the master Force
  toggle is on.
- **Strict file-type grading.** An album folder with files other than music,
  cover art, `.cue`, `.log` and `.lrc` now fails grading by default. What
  counts is configurable in Settings → **Grading** (Allow Music / Cover /
  .cue / .log / .lrc / Other).
- **CD rip checksum verification.** For MEDIA=CD albums, tracks are verified
  against the CRC-32 checksums in the `.log` (EAC Test/Copy CRC, AccurateRip,
  or XLD CRC32 hash) by decoding with ffmpeg. Match → AUDIT=REAL, mismatch →
  AUDIT=FAKE, taking precedence over AudioAuditor for those files
  (Settings → Audio Auditor → Verify CD Rips vs .log Checksums).
- **Lyrics `[00:00.00]` blank-marker fix confirmed.** Empty timing lines that
  were glued onto the following line are split back onto separate lines,
  fixing the ESLyrics "duplicate first line" display.
- **Cleanup** — removed stale build artifacts; every `mlo` module is used.

## Install

- **Installer:** `MusicLibraryOptimizer_Setup_v1.0.9_x64.exe` — run it and
  follow the first-launch wizard to pick your music folder.
- **Portable:** `MusicLibraryOptimizer_v1.0.9_portable_x64.exe` — run from
  any folder; creates `config.json` and `.dependencies/` next to itself.
- **From source:** `Music Library Optimizer.bat` or `python app.py`
  (requires `pip install mutagen`; optionally `Pillow` and `tqdm`).
