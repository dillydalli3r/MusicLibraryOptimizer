# Music Library Optimizer v1.2.0

A Windows desktop app (PySide6/Qt themed GUI + `mlo` command line) for optimizing music libraries: lossless FLAC re-encoding, **cover resize/crop + JPEG XL conversion**, cue-sheet and lyrics formatting (**now Enhanced/Extended LRC**), ReplayGain/Dynamic Range, per-album grading (**cover size & squareness enforcement**), and fake-lossless auditing.

## What's new in v1.2.0

### Cover Art — Resize, Crop & Per-Format Control
- **Resize to Target Resolution** — `Settings → Cover Art → Resize & Crop → Resize Covers to Target Size` + `Global Target Size (px)` (e.g., `1000 → 1000×1000`). Uses Pillow `LANCZOS`, disabled by default. Covers are center-cropped (if needed) and resized before `cjxl`/`jpegtran`/`oxipng`.
- **Auto-Crop Threshold** — `Crop Threshold (0.00–0.50)` — `0.05 = 5%` means `1000×1050` stays, `1000×1100` is center-cropped to `1:1`. Only crops when `|w/h−1| > threshold`.
- **Per-Format Overrides** — `Cover — Per-Format` adds `Apply to JPEG / PNG / JXL` toggles + `JPEG/PNG/JXL Target Size (0=global)` so you can keep e.g. JPEG at `1000` while leaving PNG untouched.

### Cover Grading Enforcement
- `Settings → Grading — Cover Enforce` adds `Enforce Size` (exact `target×target` ±1px, per-format target respected) + `Enforce Square` (aspect within threshold). Off by default; when on, albums with wrong covers fail grading with details like `wrong size 500×500 → 1000×1000` or `not square 800×500`.

### Enhanced / Extended LRC (word-level sync)
- New `Settings → Lyrics → Enhanced LRC`:
  - `Enable Enhanced LRC (<mm:ss.xx>)` — preserve word-level `<mm:ss.xx>` timestamps inside a line (e.g., `"[00:12.34] <00:12.34> Hello <00:12.60> world"`).
  - `Word-Level Timestamps` — when on, `< >` timestamps are normalized to the chosen precision (2/3 decimals, carry handled).
  - `Enable Extended LRC` — allow multiple `[mm:ss.xx]` on one line for karaoke; when off they are split.
- Formatter and grader both understand the new syntax: `SPACE_AFTER_TS` for `>` is handled, metadata not stripped for enhanced lines, and the grader validates monotonic order and zero-padding.

### Reorganized, Coherent Configuration
- **Qt (`gui/dialogs.py`)** — groups now `FLAC Encoding / Cover Art — Processing / Resize & Crop / Per-Format / Lyrics / Enhanced LRC / CUE / Tags / Grading / Audio Audit / Interface / Updates` with clear sub-sections and tooltips, keeping ~60 options scannable.
- `mlo/config.py` adds `cover_*` and `lrc_enhanced_*` keys with validation (`cover_target_size 0–4000`, `cover_crop_threshold 0.0–0.50`).

### Library Viewer, Updater & Deps — Highest Standard
- Library viewer shows cover thumbnails and `Clear Filters`-style handling, faster inserts, and `cover_detail` in Cover column; Tk filter overlap fixed.
- Updater retries on `429/5xx` with `Retry-After` + exponential backoff, verifies `MZ`+size, reports speed/ETA; deps installer resumes, SHA256 checks, `7-Zip` hint.

### Other
- `mlo/__init__.py` → `1.2.0`, `Music Library Optimizer.iss` → `1.2.0`, `README` header → `v1.2.0` with new section.
- Cleanup: removed leftover `test_*.py`/`verify_scan.py` from release tree.

## What's new in v1.1.0

A ground-up rebuild of the desktop app plus a brand-new command-line companion. The processing core (`mlo` package) is unchanged in spirit but gains a long-overdue lyrics normalizer and a few audit fixes.

## ✨ New UI (PySide6)

- Every screen restyled: sidebar navigation, animated toggle switches, colored ANSI console, and a library tree with real tri-state checkboxes (checking an artist checks its albums and tracks).
- **Themes:** Dark, Light, Follow-system + 8 accent colors or a custom picker (top bar → Theme, or Settings → Appearance). The **native title bar** is colored to match — caption, title text and an accent-tinted border (DWM attributes on Windows 10 2004+/11).
- Runs, scans and grading now happen on proper Qt worker threads with generation-guarded results — **Refresh/scan can no longer crash or freeze the app**, and stale scans are ignored.

## 🖥 CLI: mlo.exe

- `mlo run 1,2,3` / `mlo all` / single-script commands (`mlo lyrics`, `mlo grade`, …) with `--folder`, `--targets`, `--force`, `--thorough`.
- `mlo config [key [value]]`, `mlo deps [--install]`, `mlo menu` (the old interactive menu), `mlo gui`.
- **`mlo install --user`** copies the CLI to `%LocalAppData%\Programs\Music Library Optimizer` and appends it to the user PATH. **`mlo install --system`** does the machine-wide install and **requests UAC elevation automatically**. Both share `config.json` + `.dependencies` with the GUI via a home marker, and `mlo uninstall` cleanly reverses everything.

## 🩹 Fixes carried in from v1.0.9 feedback

- **Embedded lyrics formatting (the big one):** stacked timestamps (`[00:00.00][00:45.53]Stretching, filing`) and timestamps glued mid-line (`filing[00:46.86]Against her skin`) now split into one canonical line per timestamp; `[00:00.00]` start markers and trailing timestamp-only fragments are dropped. The **grader** now has a *Lyrics formatting* check — albums with mangled lyrics get flagged, and running **Format Lyrics** clears it (verified idempotent).
- **Open in Mp3tag/Picard now acts on the whole checked selection**, not just the right-clicked row.
- **Unselect All** button added to the library toolbar.
- **Show: Audio files / All files** — the file-type view option lives directly in the library toolbar (not buried in Settings).
- `BOTH` lyrics format now syncs both sides (embeds LRC-only tracks, writes LRC for embedded-only tracks).
- Audio audit batches match returned paths via realpath — no more phantom "(no audit result)" entries for short-name/temp folders; the audit summary row says "files" instead of "albums".
- New application icon (indigo→violet gradient, beamed note).

## 📦 Upgrading

Replace the old executable(s) with the two new ones (`Music Library Optimizer.exe` + `mlo.exe`). `config.json` and `.dependencies` carry over as-is; new settings (theme, accent, library view) default sensibly.

## What's new in v1.0.10 / v1.0.9 / earlier

See `README.md` for full history or `git log --oneline`.
