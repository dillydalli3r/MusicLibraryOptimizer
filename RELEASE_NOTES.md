# Music Library Optimizer v1.0.7

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
  with a live library tree, grade details, and column/filter options. Now
  also grades lyrics/cue **formatting**.
- **Safe updates** — GitHub update checks, one-click download & install that
  closes idle instances and waits for every process before running setup.
  Optional auto-install on start.
- **Dependencies manager** — downloads and pins every bundled CLI tool.
- **Setup Guide** — modal first-run wizard with folder validation, presets
  and dependency list; reopenable via the status bar ★ Guide button.

## What's new in v1.0.7

- **Fixed "Download & Install" closing the app without updating.** The
  shutdown helper is now spawned via `Win32_Process.Create`, making it a
  fully detached process that survives the app exiting (a plain child was
  torn down with the parent's console on some setups). It waits for every
  app PID, then runs setup and deletes the downloaded installer. A fallback
  launch path is used if the WMI bootstrap fails.
- **Auto-install updates on start (new setting).** Settings → Interface →
  Auto-Install Updates on Start (default off) downloads and installs a newer
  release found at startup when the app is idle; it still honors "Confirm
  Before Installing Updates". The previous launch-time check only logged —
  its handler was never reached (it unpacked a `None` result).
- **Grader checks lyrics / cue FORMATTING**, not just presence. It compares
  against the canonical form the Lyrics and CUE scripts produce: LRC
  timestamp precision, metadata lines, blank collapsing, trailing newlines,
  CUE CRLF/BOM, FILE type and quoting, DISCID/track/index normalization. It
  also flags **merged timestamps** (`[00:00.00][00:45.53]…`) that break
  ESLyrics on foobar2000.
- **Fixed lyrics formatter gluing timestamp-only lines.** An empty timing
  line `[00:00.00]` followed by `[00:45.53]Stretching, filing` was merged
  into `[00:00.00][00:45.53]Stretching, filing`; the space-after-timestamp
  regex now only strips spaces/tabs, so timestamp-only markers stay on their
  own line.
- **Performance**
  - Targeted grades no longer walk the whole library first.
  - Auto Tagging loads each file once per album instead of ~6 times.
  - `config.json` is only rewritten when the library folder changes.
  - Postponed/refused updates no longer leave the dialog button stuck on
    "Downloading…"; the installer is kept for an instant retry.
- **Code split for maintainability.** `app.py` moved its theme/constants/
  widgets into `mlo/gui.py` and its four dialog windows into
  `mlo/gui_dialogs.py`.
- **Other hardening** — scan errors surfaced instead of swallowed; a release
  tag with no installer asset is no longer offered as an update; Compact-mode
  toggling rebuilds the tree; tab-switching no longer un-maximizes the
  window; PowerShell helper output is escaped.

## Install

- **Installer:** `MusicLibraryOptimizer_Setup_v1.0.7_x64.exe` — run it and
  follow the first-launch wizard to pick your music folder.
- **Portable:** `MusicLibraryOptimizer_v1.0.7_portable_x64.exe` — run from
  any folder; creates `config.json` and `.dependencies/` next to itself.
- **From source:** `Music Library Optimizer.bat` or `python app.py`
  (requires `pip install mutagen`; optionally `Pillow` and `tqdm`).
