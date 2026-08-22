# v1.1.0 — The Qt Revamp

A ground-up rebuild of the desktop app plus a brand-new command-line
companion. The processing core (`mlo` package) is unchanged in spirit
but gains a long-overdue lyrics normalizer and a few audit fixes.

## ✨ New UI (PySide6)

- Every screen restyled: sidebar navigation, animated toggle switches,
  colored ANSI console, and a library tree with real tri-state
  checkboxes (checking an artist checks its albums and tracks).
- **Themes:** Dark, Light, Follow-system + 8 accent colors or a custom
  picker (top bar → Theme, or Settings → Appearance). The **native
  title bar** is colored to match — caption, title text and an
  accent-tinted border (DWM attributes on Windows 10 2004+/11).
- Runs, scans and grading now happen on proper Qt worker threads with
  generation-guarded results — **Refresh/scan can no longer crash or
  freeze the app**, and stale scans are ignored.

## 🖥 CLI: mlo.exe

- `mlo run 1,2,3` / `mlo all` / single-script commands (`mlo lyrics`,
  `mlo grade`, …) with `--folder`, `--targets`, `--force`,
  `--thorough`.
- `mlo config [key [value]]`, `mlo deps [--install]`, `mlo menu`
  (the old interactive menu), `mlo gui`.
- **`mlo install --user`** copies the CLI to
  `%LocalAppData%\Programs\Music Library Optimizer` and appends it to
  the user PATH. **`mlo install --system`** does the machine-wide
  install and **requests UAC elevation automatically**. Both share
  `config.json` + `.dependencies` with the GUI via a home marker, and
  `mlo uninstall` cleanly reverses everything.

## 🩹 Fixes carried in from v1.0.9 feedback

- **Embedded lyrics formatting (the big one):** stacked timestamps
  (`[00:00.00][00:45.53]Stretching, filing`) and timestamps glued
  mid-line (`filing[00:46.86]Against her skin`) now split into one
  canonical line per timestamp; `[00:00.00]` start markers and
  trailing timestamp-only fragments are dropped. The **grader** now
  has a *Lyrics formatting* check — albums with mangled lyrics get
  flagged, and running **Format Lyrics** clears it (verified
  idempotent).
- **Open in Mp3tag/Picard now acts on the whole checked selection**,
  not just the right-clicked row.
- **Unselect All** button added to the library toolbar.
- **Show: Audio files / All files** — the file-type view option lives
  directly in the library toolbar (not buried in Settings).
- `BOTH` lyrics format now syncs both sides (embeds LRC-only tracks,
  writes LRC for embedded-only tracks).
- Audio audit batches match returned paths via realpath — no more
  phantom "(no audit result)" entries for short-name/temp folders; the
  audit summary row says "files" instead of "albums".
- New application icon (indigo→violet gradient, beamed note).

## 📦 Upgrading

Replace the old executable(s) with the two new ones
(`Music Library Optimizer.exe` + `mlo.exe`). `config.json` and
`.dependencies` carry over as-is; new settings (theme, accent,
library view) default sensibly.
