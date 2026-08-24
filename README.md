# Music Library Optimizer v1.6.6

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
Desktop GUI (Tkinter, dark-themed, titlebar shows `v1.4.3`) + command-line app (`mlo`) +
optional interactive console menu. **v1.5.0 fixes Grading Enforce not saving, moves [00:00.00] to Lyrics (on by default, works for standard+enhanced), adds fill-empty-SOURCE toggle (default keep empty), makes Thorough Audit on by default, fixes columns menu, widens TAGS to truly use all space, adds Guide max-effort preset and About Install Latest, and keeps PROGRAM off; v1.4.3 made grading require `ENCODER_PROGRAM` only when that format’s toggle is on (off by default, so existing libraries pass), and ensures optimization writes `PROGRAM` even when skipping re-encode; v1.4.2 made `PROGRAM` off by default and stopped deleting tags.**
## Quick Start

**Desktop app (installer):** Download `MusicLibraryOptimizer_Setup_v1.6.6_x64.exe`
from [Releases](https://github.com/dillydalli3r/MusicLibraryOptimizer/releases),
run it, and follow the first-launch wizard to pick your music folder.

**Portable:** Download `MusicLibraryOptimizer_v1.6.6_portable_x64.exe` and run it
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

## New in v1.6.6

- **All procedures now fully configurable + defaults = your `config.json` + Apply Defaults** — `mlo/config.py` now `reencode_to_jxl False` / `convert_jxl_back True` / `images_convert_to_jpeg True` (were `True`/`False`/`False`) to match your strict `config.json` (`convert_jxl_back` + `images_convert_to_jpeg` on, `reencode_to_jxl` off), `164` keys `config.example.json` regenerated. Every formatting (`Lyrics`, `CUE`, `FLAC`, `Images`), grading (`29 grade_check_*` + `grade_include_*` + `cover_enforce` + thresholds) and auditing (`19 audit_*`) procedure now has a toggle in `Settings` to control whether it is counted (`total_checks`/`AUDIT`); disabled = `○ OFF` in `Grade Details`. `app.py:SetupWizard` now `Apply Defaults` button (`_apply_defaults`) — stages `DEFAULT_CONFIG` (your `100/100, 0px, 100q` etc.) for `Save` preview, preserving `music_folder`.

## New in v1.6.5

- **CD `SOURCE` must be empty — auto-cleared** — `mlo/config.py` adds `strip_source_on_cd` `True` default (`Settings → Tagging` `06` + `v1.6.0 Strict` preset), `mlo/lyrics.py:_normalize_album_media_source` now `CD` + `strip_source_on_cd` → `delete_tag SOURCE` per track (via `should_write_audio_tag`), `mlo/grader.py` already fails `SOURCE present but MEDIA is not Digital Media` for `MEDIA=CD` when `grade_check_source` `True`. `CD=16/44.1` + `no SOURCE` = true `CD-DA`.

## New in v1.6.4

- **All scripts respect FORCE + image conversions + separate JPEG qualities** — `mlo/autotag.py` `force` now rewrites `ALBUMITUNESADVISORY` even when already correct (was empty `need_write` loop), `mlo/loudness.py` `rsgain` with `force` now counts album as `modified` even when no files were missing, `mlo/images.py` `BMP/GIF/TIFF/WEBP→JPEG/PNG` now respects `force` (skips if target `cover.jpg`/`cover_1.png` already exists) and `reserved_targets` + `WinError 32` fallback for `cover.bmp`+`cover.tiff`→`cover.png`/`cover_1.png` (was clobber/`WinError 32`), and cover `JPEG` quality correctly split `cover_jpeg_quality 100` for `did_cover`/cover files vs `images_jpeg_quality 100` for re-encoded (was `95`/`100` mix). Verified `cover.jpg 2000×1500→1000×1000` `12741B` `q100` vs `other.jpg 500×500` `q70` `2558B`, `front.bmp`→`front.jpg` `BMP→JPEG` and `back.tiff`→`back.jpg` (or `cover.png`/`cover_1.png`), `Enhanced LRC` word-sync `<00:12.60>` order/precision validated, `Lyrics`/`CUE`/`FLAC` `FORCE` correctly `modified` vs `skipped`.

## New in v1.6.3

- **Cover art: separate JPEG qualities + convert any image type** — `mlo/config.py` splits `images_jpeg_quality` `95` (re-encoded JPEGs via `Convert All Non-JPEG to JPEG`) and new `cover_jpeg_quality` `100` (cropped/resized covers via `cover_jpeg_quality`); `mlo/images.py:_prepare_image_streamlined` now picks `cover_jpeg_quality` when `did_cover` else `images_jpeg_quality`, `_resize_and_crop_image` uses `cover_jpeg_quality`, `mlo/paths.py` adds `ALL_IMAGE_EXTS`/`CONVERTIBLE_EXTENSIONS`/`LOSSLESS_IMAGE_EXTS` (`bmp/gif/tiff/webp/avif/heic` etc.) and `run_process_images` scans `CONVERTIBLE` when either convert on, mode string reflects `q`, new `images_convert_to_jpeg` (`BMP/GIF/TIFF/WEBP→JPEG` lossy) + `images_convert_lossless_to_png` (`BMP/GIF/TIFF→PNG` lossless) via `_process_convert_image` (Pillow, respects `rename_to_cover`/`remove_alpha`/cover resize, handles `cover.bmp`+`cover.tiff`→`cover.png`/`cover_1.png` collision with `WinError 32` fallback).
- **Enhanced LRC fully wired** — `mlo/lyrics.py:format_lyrics_text` now `lrc_zero_timestamp_blank` param + `cfg` handling, tight (`[00:00.00]Hello`) vs blank (`[00:00.00]` alone) correctly inserted/removed per `mlo/grader.py:_lyrics_zero_timestamp_ok` (now checks `startswith` + text for tight). `app.py` `Cover — Resize & Per-Format` now shows `cover_jpeg_quality`.
- **Verified:** `cover.jpg 2000×1500` → `1000×1000` `cover_jpeg_quality 100` (`12741B`) vs `other.jpg 500×500` `images_jpeg_quality 70` (`2558B`), `BMP 500×500`→`JPEG 1824B` / `TIFF 800×600`→`PNG 1936B`, `WEBP→JPEG` OK, `front.bmp`+`back.tiff` → `front.jpg`+`back.jpg` (or `cover.png`/`cover_1.png` with collision handled), `Enhanced LRC` word-sync `<00:12.60>` order/precision validated.

## New in v1.6.2

- **In-app updater fixed + setup name fixed for v1.6.1** — `Music Library Optimizer.iss` `#define AppVersion` now `1.6.2` (was stale `1.5.6` → installer named `v1.5.6` for `v1.6.1` tag) and `.github/workflows/release.yml` now sets `__version__` + `ISS` from `${{ github.ref_name }}` before `PyInstaller`/`ISCC` so `Setup_v1.6.2_x64.exe`/`_portable` match the tag. `mlo/updater.py` hardened: `_find_installer` now prefers `setup` asset matching tag version (handles `v1.6.x` vs `v1.5.6` mis-name), `_download_installer` adds `Authorization` header when `GITHUB_TOKEN` present, retries `429/403/5xx` with `Retry-After`, validates `MZ` + `<html` guard, 500 MB cap, and `launch_installer_after_shutdown` now verifies `MZ` before helper, quotes `Installer` correctly, adds `ShellExecute` fallback via `os.startfile` if WMI `Win32_Process.Create` fails, and logs `Update helper launched…`.

## New in v1.6.1

- **CD must be 16-bit 44.1 kHz — true CD-DA only** — `mlo/config.py` adds `grade_check_cd_format` + `audit_check_cd_format` (both `True` by default, in `Settings → Grading — CD` / `Auditing — Core`, in `v1.6.0 Strict` preset, and in `Grade Details` `✓/✗` + `Auditing checks`). `mlo/grader.py:_grade_album` now checks `audio.info.bits_per_sample`/`sample_rate` per `MEDIA=CD` track (`CD must be 16-bit 44.1 kHz (found …)` → `CD_FORMAT`), `mlo/audit.py:run_audit_library` marks `not 16-bit 44.1 kHz` as `AUDIT=FAKE` (via `mutagen` `info`, no `ffmpeg` needed, independent of `audit_verify_cd_checksums`). Helps detect fake rips from hi-res upsampled sources (the only true CD format).

## New in v1.6.0

- **Strict defaults = your config** — `mlo/config.py` now ships `grade_log_score_threshold=100` + `audit_log_score_threshold=100` (perfect rip required), `cover_crop_threshold=0.0` / `grader_cover_size_tolerance_px=0` / `grader_strict_square_threshold=0.0` (pixel-perfect 1000×1000), `images_jpeg_quality=100` (max), `lrc_add_zero_timestamp=False` (no blank lead-in), all `ENCODER_PROGRAM` on, `run_all_order [1,2,8,3,5,6,4,7]` (Grade before DR), plus every `grade_check_*` on. Your `config.json` is now the factory default and also a preset.
- **Every grading check is a toggle** — 29 `grade_check_*` now cover *all* grading: `unreadable`/`missing_tags`/`encoder`/`audit`/`instrumental`/`lyrics`+`format`/`sidecar_cover`, `media`/`source`/`album_tags`, `cd_log`/`cd_cue`/`disc_naming`/`log_grade`/`crc`/`log_checksum`/`accuraterip`, `cover`/`cue_format`/`disallowed` + `tag/lyrics/cue` spaces/blank/zero/crop. `mlo/grader.py` skips `total_checks`/`failed_checks` when a toggle is off. All 29 appear in `Settings` with descriptions.
- **Track right-click fixed + Grade details for tracks** — `app.py:_on_tree_menu` fallback derives `album_dir` from hierarchy when cache miss, `app.py:_find_album_for_item` now `normcase` so `F:\Music\…` matches `f:\music\…`; `Grade details…` now opens for `1-01 Track.flac` rows and shows per-track `LOG_GRADE`/`AUDIT`/`ISSUES`.
- **Grade Details shows ALL checks, auditing + grading, per config** — `app.py:_show_grade_details` now 860×640, `word`-wrap, `✓/✗/○` icons, grouped sections (`Core`, `Media & Album`, `CD & Logs`, etc. for grading; `CD Verification`, `Detectors`, `Performance` for auditing) with `[PASS]` green / `[FAIL]` red / `[OFF]` muted per `cfg`, plus `Auditing checks` evaluated per album via `discs.py:check_log_checksum`/`check_accuraterip`/score threshold/unscorable/`AUDIT` summary. Disabled checks are listed as `OFF` instead of hidden.
- **Config menus reorganized — pipeline 01-16** — `app.py: ConfigDialog groups` now `01 FLAC` → `02 Images Global` → `03 Cover Resize & Per-Format` (merged cover enforce) → `04 Lyrics` (standard+enhanced) → `05 CUE & Discs` → `06 Tagging` → `07-10 Grading` (General/Core/Content/CD/Strict) → `11-13 Auditing` (Core/Detectors/Performance) → `14 Loudness` → `15 System` (Performance & Updates). Collapsible, searchable `▸/▾`, fewer top-level groups, verbose groups (`Strict`, `Detectors`) start collapsed. Matches `DEFAULT_RUN_ALL_ORDER` order.
- **Guide preset v1.6.0 Strict** — `app.py:SetupWizard.GENERAL_PRESETS` adds `v1.6.0 Strict — Perfect Scores (100/100, 0px, 100q) — User's Config` applying the strict defaults above (100/100, 0px, 100q, `PROGRAM` on, `run_all_order` 6→4→7). One-click re-apply.

## New in v1.5.4

- **Auto-crop to threshold (not 1:1) with 1px overcorrect** — `mlo/images.py:_resize_and_crop_image` now crops `w>h` to `h*(1+thr)` / `h>w` to `w*(1+thr)` instead of to square, so `1000x1100` `thr 0.05` -> `1050x1000` (1px inside) not `1000x1000`; `1000x1000` stays.
- **Per-format cover targets default 0 verified** — `mlo/config.py:158` `cover_*_target_size` already `0` (global 1000 used), `Settings -> Cover Per-Format` shows `0` (was incorrectly showing `1` due to stale UI).
- **`[00:00.00]` always blank + bidirectional** — removed `lrc_zero_timestamp_blank` (`mlo/config.py:172`, `app.py:164`), `mlo/lyrics.py:format_lyrics_text` now always inserts bare `[00:00.00]` when `lrc_add_zero_timestamp` on (for both standard+enhanced via `BOTH` target) and **removes** it when off (same option toggles add/remove). `mlo/grader.py:249` now expects exact `==` `zero_ts`.
- **TAGS full + FAILED column** — `app.py:114` `TREE_COLUMNS` `tags` `800` + new `failed 300`, `app.py:3217` `_track_tags_txt` now `GENRE 30` (was `12`) and `_album_tags_txt` `30` so `Alternative/Avant-Garde` fully visible, `app.py:3248`/`3281`/`3353` now set 8th `failed` value (`,`.join issues) and `app.py:3760` menu keeps `BooleanVar` alive.


## New in v1.5.0

- **Fixes for your config — Grading Enforce now saves, Thorough Audit on, [00:00.00] on + moved** — fixed duplicate cover_enforce_size/square appearing in two groups (Cover Resize + Grading Cover Enforce) which caused self.vars overwrite so Saving did nothing — removed from Cover Resize (kept only in Grading). Changed defaults: udit_thorough=True, cover_enforce_size=True, cover_enforce_square=True (already True in code, now UI correctly persists), lrc_add_zero_timestamp=True (was False, now on by default per request) and moved from Enhanced LRC to Lyrics (mlo/config.py:172 + pp.py:1270) so it applies to both standard and enhanced LRCs via mlo/lyrics.py:_zero_target_allows. Your cover_enforce alse in the posted config.json will now correctly show unchecked and can be turned on.
- **Digital SOURCE — keep empty by default** — new ill_empty_source (mlo/config.py:186 default False, pp.py:1289 Tags — Media & Source group) — when off (default) Digital Media with empty SOURCE stays empty; when on it fills with digital_media_source_value (Digital or custom). mlo/lyrics.py:651 now respects ill_empty_source.
- **Columns menu + TAGS truly fill space** — pp.py:3760 _show_column_menu now keeps BooleanVar alive in self._col_menu_vars so visible columns correctly show checked (was GC’d). pp.py:114 TREE_COLUMNS tags 600→800 + pp.py:2646 #0 stretch=False/	ags stretch=True + pp.py:2174 1500×780 ensures G:Alternative… uses all available width; horizontal scrollbar appears only when needed.
- **Guide max-effort preset + About Install Latest** — pp.py:1859 new GENERAL_PRESETS Maximum Quality — All Encoders sets lac_level 8, jpegxl_effort 10, png_optimization_level 6, cover 1000×1000 forced, udit_thorough on etc.; pp.py:2051 AboutDialog now has Install Latest button enabled when check_for_updates finds X.Y.Z (via self._pending_update), plus mlo/config.py:308 check_updates_on_start=True (already) and pp.py:2230 on-start check now also sets master.status_var so you are notified.

## New in v1.4.3

- **Grading now requires ENCODER_PROGRAM only when enabled** — mlo/grader.py:_grade_album now checks ENCODER_PROGRAM/QUALITY/VERSION per filetype via encoder_tags (e.g. lac with PROGRAM on → FAIL Missing ENCODER_PROGRAM (re-optimize) until you run Optimize FLACs; off by default → no check, so existing libraries pass). Covers also checked per image type (jpeg/png/jxl). mlo/containers.py:_identity_missing now also gates on PROGRAM when enabled (missing PROGRAM when on forces re-optimization, not silent skip).

## New in v1.4.2

- **No more tag deletion — only `LYRICS`/`UNSYNCEDLYRICS` per config** — `mlo/containers.py:_clean_flac_tags` no longer deletes every tag not in `KEEP_VORBIS_KEYS` (that deleted `MUSICBRAINZ_TRACKID`, `ARTISTSORT`, `WORK`, etc. and broke Picard recognition). Now it only ever removes `UNSYNCEDLYRICS` (always, legacy) and `LYRICS` when `Settings → Lyrics → Lyrics Format = LRC` (embedded not wanted), plus `ENCODER_PROGRAM` when that marker is disabled. All other Vorbis comments are left untouched — Picard now recognizes files after the app runs. `mlo/flac.py:_optimize_flac` now passes `config`+`enabled` to the cleaner.
- **`ENCODER_PROGRAM` off by default, still toggleable per format — grading respects it** — `mlo/config.py:encoder_tags` now `{"ENCODER_PROGRAM": False, "ENCODER_QUALITY": True, "ENCODER_VERSION": True}` for `flac`/`jpeg`/`png`/`jxl`. `Settings → Encoder Tags` shows `PROGRAM` off (turn it on per format if you want it), `mlo/containers.py:_write_*` respects `_enabled`, `mlo/containers.py:_identity_missing` only checks `QUALITY`/`VERSION` (so `PROGRAM` off doesn’t force re-encode), and **`mlo/grader.py:_grade_album` now requires `ENCODER_PROGRAM` only when that format’s toggle is on** — e.g. `flac` with `PROGRAM` on will `FAIL` `Missing ENCODER_PROGRAM (re-optimize)` until you run Optimize FLACs (which then writes it). Verified `config.example.json` now `false` for all 4.

## New in v1.4.1
- **TAGS column uses all space — no longer cut off** — `app.py:TREE_COLUMNS tags` widened `420→600`, `FOLDER / TRACK` now `stretch=False` (was `True`) so `TAGS` is the only `stretch=True` column (`minwidth 200`), window widened `1280→1440` (`min 1280`), and `tree_box` properly `columnconfigure(weight=1)`. Long genre strings like `G:Alternative/Avant-GardeNu Metal` now fully visible; horizontal scrollbar appears only when needed.
- **Picard preserve corrected to your 13 + MEDIA (14 sorted)** — `README.md` + `SetupWizard` now list `ALBUM DYNAMIC RANGE, ALBUMITUNESADVISORY, AUDIT, DYNAMIC RANGE, ENCODER_PROGRAM, ENCODER_QUALITY, ENCODER_VERSION, GENRE, INSTRUMENTAL, ITUNESADVISORY, LOG_GRADE, LYRICS, MEDIA, SOURCE` (alphabetical, your 13 + missing `MEDIA`). Note added: add `REPLAYGAIN_*` (4) as well if you use that feature; `GENRE`/`ITUNESADVISORY` kept because you manage them manually. `About → Check for Updates` still on by default (`config.json:check_updates_on_start=True`) with one-click install inside the app.

## New in v1.4.0
- **Grading / auditing hardened + performance** — `mlo/audit.py`: reuse `detect_all_tools()` (no redundant lookup), count CD checksum `AUDIT` writes in `stats`, fix `pbar` undercount on failed batches (`pbar.update(len(batch))`), preserve `warn` flags in dual-source `require_both` (don’t mask `Valid+clipping` as `ok`), pre-filter `grade_album_logs` to only `.log`+`MEDIA==CD` albums (no 5k-thread fan-out). `mlo/lyrics.py`: reuse `final` for LRC to avoid double read. `mlo/grader.py`: fix `unreadable` undercount, fix `CD rip sheets not named` total_checks, cache `Image.open` once for cover size+square. `mlo/config.py`: safe `lrc_zero_timestamp_target` choices.
- **Dependencies manager — far more usable** — `app.py:DependenciesDialog` now has row checkboxes + `Select All/None`, `Update Selected`, `Force reinstall`, `Check Latest`, `Open Folder`, `Copy Paths`, `Show Log`, per-tool `Details` button, bottom `Progressbar` + status label, and a synchronously-set `busy` flag to prevent double-click race. Each download reports `prog` to both the main console and the dialog’s bar. Much easier to update a subset or force-reinstall.
- **Bug sweep + Setup Guide refresh** — `mlo/config.py`: sorted `audio_tag_writes` handling, `mlo/lyrics.py`: blank vs duplicate idempotency, `mlo/autotag.py` & `mlo/loudness.py` per-type stripping already; `SetupWizard` presets now cover all 8 scripts + cover + lyrics (including blank zero) and show a live pending summary.

## New in v1.3.9

- **Per-filetype tag controls — organized, not overwhelming** — `Settings → Audio Tags — Per Format` now lets you choose which semantic tag families each audio container receives. Families: `AUDIT` (`AUDIT`), `LOG` (`LOG_GRADE`), `RG` (`REPLAYGAIN_*` 4 tags), `DR` (`DYNAMIC RANGE` 2 tags), `M/S` (`MEDIA`+`SOURCE`), `ADV` (`ITUNESADVISORY`+`ALBUMITUNESADVISORY`), `INST` (`INSTRUMENTAL`), `LYR` (embedded `LYRICS`). Rows are `FLAC`, `MP3`, `MP4`, `OGG`, `Opus`, `AAC`; each toggle is ANDed with the global master (`Write AUDIT` etc.). Covers the 6 audio types with 8 families (48 toggles) — enough control without per-tag sprawl. `Grader` also skips disabled families so you don't get false FAILs, and every writer (`Audit`, `Discs`, `DR/RG`, `Lyrics`, `AutoTag`) respects the per-type setting. `mlo/config.py: AUDIO_TAG_FAMILIES` + `should_write_audio_tag()` + `audio_tag_writes` dict, normalized and persisted; `ConfigDialog` table uses `ToggleSwitch` per cell.
- **Picard preserve narrowed to app-added only + audit bug fixed** — `README` and `SetupWizard` preserve list now contains only tags this app actually writes (`MEDIA, SOURCE, INSTRUMENTAL, ITUNESADVISORY, ALBUMITUNESADVISORY, REPLAYGAIN_*, DYNAMIC RANGE, AUDIT, LOG_GRADE, ENCODER_*, LYRICS…` 22 tags) — standard MusicBrainz tags (`TITLE`, `ALBUM`, `ARTIST`, `GENRE` etc.) are excluded because Picard already writes them. Fixed `mlo/audit.py: _audit_tag_value` undefined `tag_value` bug in dual-source `audit_cd_require_both` path (added missing `tag_value = _audit_tag_value(...)` and cleaned dead `pass` branches) and verified no other unfinished edits remain (`py_compile` clean on all modules).
- **Full metadata/padding strip verified + TAGS layout kept** — no changes to the `KEEP_VORBIS_KEYS`/`_clean_flac_tags`/`_strip_*` pipelines; previous `v1.3.8` guarantees still hold.

## New in v1.3.8
- **Tag hygiene — all written tags trimmed, preserve list in Guide** — `mlo/audio.py:set_tag` and `set_any_tag` now `strip()` every value (except multi-line `LYRICS`) so `ITUNESADVISORY`/`GENRE`/other tags never have leading/trailing spaces; `mlo/grader.py` now fails `ITUNESADVISORY` if raw `!= stripped` or not in `0/1/2` and `GENRE` if `raw != stripped`, while `mlo/autotag.py` trims `GENRE`/`ITUNESADVISORY` on the fly before deriving `ALBUMITUNESADVISORY`. **Setup Guide** (`app.py: SetupWizard`) had the 40-tag preserve list (`TITLE, ALBUM…`) — now narrowed to app-added only in v1.3.9.
- **Full metadata/padding strip verified for all edited types** — `FLAC` via `mlo/containers.py: KEEP_VORBIS_KEYS` + `_clean_flac_tags()` on every `Optimize` (even when skipped) plus `--no-padding`/`PADDING` removal; `JPEG` via `_strip_jpeg_metadata` (`APP0-APP15`/`COM` stripped, then `ENCODER` XMP kept), `PNG` via `_strip_png_metadata` (`tEXt`/`iTXt`/`zTXt`/`eXIf`/`tIME` stripped, then `ENCODER` `tEXt` kept), `JXL` via `xml ` box replacement. `.log` never touched.
- **Defaults now maximum quality & thorough — `AUDIT` uses both sources, covers `1000×1000`, all efforts max** — `audit_cd_require_both` now `True` (both `.log` CRC + `AudioAuditor` must be `REAL`), `cover_resize_enabled`/`cover_force_exact_size`/`cover_enforce_size`/`cover_enforce_square` all `True` (guarantees exactly `1000×1000`), `png_optimization_level` `6` (max), `jpegxl_effort` `10` (max), `flac_level` `8` (max). New installs get these; existing `config.json` updated on save.
- **TAGS column fully visible & resizable** — `TAGS · G I A AA L` width `320→420`, `FOLDER / TRACK` `#0` now `260` `stretch`, window `1280x780` `minsize 1100x640` so `G:Alternative/Avant-Gard…` no longer cuts off; `Treeview.Heading` now `1px BORDER` (`#262626`) with `padding (5,3)` so the drag handle between `COVER` and `TAGS` is visible and resizable, and `TAGS` stretches to fill leftover space but can be manually dragged.

## New in v1.3.5

- **Square sandwich menu (☰)** — Top bar now has a square `☰` button (`Square.TButton`, `width 2`, `padding (6,6)`, centered) that toggles the left `RUN SCRIPTS / BATCH / MANAGE` sidebar; persists to `config.json:sidebar_visible` and always shows `☰` regardless of state (previously `◀ Hide Menu` / `▶ Show Menu` rectangular).
- **Force menu ↔ Run Scripts consistency** — `Force ▾` dropdown now uses **exact same names and order** as `RUN SCRIPTS` sidebar `1 Format Lyrics, 2 Format CUEs, 3 Optimize FLACs, 5 Process Images, 6 Audit Library, 7 DR & ReplayGain, 8 Auto Tagging` (with comment `Order matches RUN SCRIPTS 1,2,3,5,6,7,8 — Grade Library (4) has no Force`), previously `Re-encode FLACs` vs `Optimize FLACs` etc. mismatched.
- **White outline fix** — `TNotebook`/`TNotebook.client` now `borderwidth 0` with `tabmargins (0,0,0,0)` and both tabs `1px BORDER` (not `BRIGHT`), `Treeview.Heading` now `#0f0f0f` (slightly darker than `#121212`/`#161616`) with `borderwidth 1` and `padding (5,3)` sitting flush at top, no white rectangle; fixes the 2-3px misaligned look in the screenshot where `Library` appeared offset from `Console`.

## New in v1.3.4

- **Picard Preserve Tags** — New section **MusicBrainz Picard — Preserve Tags** lists every Vorbis/ID3/MP4 tag this app writes (`AUDIT`, `LOG_GRADE`, `MEDIA`, `SOURCE`, `ITUNESADVISORY`, etc.) so that `Options → Tags → Clear existing tags` in Picard does not delete them. Paste the provided comma-separated list (covers all 8 scripts) or keep *Clear* off — the app’s own `FLAC` cleaning already whitelists exactly those tags.
- **Full metadata/padding strip** — `FLAC` (`mlo/containers.py: _clean_flac_tags`): all `Vorbis` comments not in `KEEP_VORBIS_KEYS` (27-keep list: `TITLE`/`ALBUM`/`GENRE`/`ITUNESADVISORY`/`AUDIT`/`ENCODER_*` etc.) are removed and padding cleared (`--no-padding`, `PADDING` block) on every Optimize (even when re-encode is skipped). Images: `JPEG` (`_strip_jpeg_metadata` removes `APP0-APP15`/`COM`, then `_insert_jpeg_xmp` keeps only `ENCODER` XMP), `PNG` (`_strip_png_metadata` removes `tEXt`/`iTXt`/`zTXt`/`eXIf`/`tIME` then ` _inject_png_text` keeps only `ENCODER`), `JXL` (`_write_jxl_tags` replaces `xml ` box). `.log` files are never touched.
- **Shift+Click / Ctrl+Click** — Library viewer now handles `Shift` (range between last and current, via `_get_all_items_in_display_order`/`_toggle_range`) and `Ctrl` (single toggle, `cascade=False` for tracks) for easy multi-folder/track selection; `_last_clicked` tracked, collapsed children excluded from range.

## New in v1.3.3

- **Dual-source CD audit option** — `Settings → Audio Auditor → CD: Require Both Log & AudioAuditor = REAL` (default off). When on, **both** the `.log` CRC and AudioAuditor must be `REAL` for `MEDIA=CD` to be `REAL`; if either is `FAKE` the final `AUDIT` is `FAKE`. When off (default), `.log` CRC alone decides for CD rips and AudioAuditor is not run on them — preserving the lossless `ffmpeg→s16le→zlib.crc32` vs Test/Copy/AccurateRip/XLD path.
- **Strict `ITUNESADVISORY` & `GENRE` hygiene** — `ITUNESADVISORY` must be exactly `0`/`1`/`2` with no leading/trailing spaces (grading fails `ITUNESADVISORY must be 0/1/2 without spaces`, e.g. `" 1 "` → fail), and `GENRE` must have no leading/trailing spaces. Optimization (`mlo/audio.py:set_tag` + `mlo/autotag.py`) now trims these on write (`GENRE` strip, `ITUNESADVISORY` strip) so formatting never writes spaced values; grading checks raw vs stripped.
- **Single-disc `.cue` → `CD-1.cue` with `.wav`→`.flac` & Unicode fixes** — `1-01 Suite‐Pee.flac` (`U+2010` `‐`) vs `01 - Suite-Pee.wav` now correctly matched via ASCII dash normalization, stem-insensitive and `D-TT` track-number-aware (`_track_num_of` now returns `TT` for `D-TT`), so `a.cue` (single cue without `D-TT`) trivially becomes `CD-1.cue` and `FILE` lines are conservatively corrected to `.flac`.
- **Select All** — Library toolbar now `Refresh | Select All | Clear Selection` (`app.py:2156`, `_select_all()` checks every visible `artist/album/track` and cascades); easier batch `Optimize Selected`.
- **Run Scripts verified 8/8** — `RUN SCRIPTS` sidebar `Format Lyrics/CUEs/FLACs/Grade/Images/Audit/DR & ReplayGain/Auto Tagging` all present and each covers its feature set (`disc rename` + `FILE` fix inside `Format CUEs`/`Audit`).
- **Viewer polish continued** — heading `FOLDER / TRACK` for the tree column, `Treeview.Heading` now `#1e1e1e` slightly darker than `CARD` with `borderwidth 0` (no white outlines, just darker bar at top), `library_frame`/`filter` padding tightened to `5,3`/`5,3`/`0,2` so bars have minimal space, `8/8` tools still counted.

## New in v1.3.2

- **Setup Wizard — intuitive & sensible presets** — `Guide` (status bar → Guide) now has two groups: **Music Files** (Balanced / Most Aggressive LOSSLESS / Lightweight) and **Cover Images** (Balanced / Most Aggressive LOSSLESS / Compatibility). Each preset lists exactly what it changes (e.g. FLAC 8 vs 5, JXL effort 9 vs 7, forced exact `1000×1000`) in tooltips + live summary; library folder picker validates live; nothing saved until **Save**.
- **Autorename .cue/.log → `CD-1.cue/log … CD-11.cue/log`** — `Settings → CD Rips → Auto-Rename to CD-N` (default on) deterministically renames multi-disc cues/logs using only content-derived evidence (FILE entries for cues; explicit disc number / single-disc trivial / TOC duration match for logs). Ambiguous cases are left untouched instead of guessed. `Settings → CD Rips → Rename pattern` customizes the scheme (default `CD-{n}`, e.g. `Disc {n}` → `Disc 1.log`) — uses `{n}` placeholder; grading checks the same pattern. **`.log` contents are never touched** — only filenames.
- **CUE `FILE` correction (default on)** — `Settings → CUE Sheets → Fix CUE FILE Names` corrects stale `FILE` entries to match actual audio filenames *conservatively*: only when exactly one candidate matches by normalized name or leading track number; ambiguous → left + noted. Minimizes assumptions; runs in CUE formatter and during disc scoring.
- **CD integrity = `.log` checksums only** — `Audit Library` for `MEDIA=CD` is now **only** `ffmpeg→s16le→zlib.crc32` vs the `.log`’s Test/Copy/AccurateRip/XLD CRCs (`REAL` on match, `FAKE` on mismatch). Uncovered tracks (no `.log`, no CRC) get **no `AUDIT`** and grading **fails** the album (unverifiable) instead of guessing via AudioAuditor, which is now reserved for non-CD releases. Only CD albums consult `.log` at all.
- **Grading for CD rips overhauled** — `MEDIA=CD` now requires: `LOG_GRADE` 0-100 on every track, `CD-N` naming per discs-rename pattern (bad names → fail), every track covered by a CRC in its disc’s log (missing → fail), and `AUDIT=REAL` (from checksum). Mismatch → `FAKE` → fail. Non-CD still requires `AUDIT=REAL` from AudioAuditor.
- **Cover enforcement = track/album FAIL** — `Settings → Cover Art → Resize & Crop → Force Exact Size` guarantees exactly `target×target` (crop → LANCZOS); grading’s `Enforce Size`/`Square` (and `Force Exact` implying both) now fails **every track** in the album (not just the album row) with `COVER` issue and `cover.jpg (wrong size …)` detail; respects per-format targets and threshold.
- **TAGS column: `A` + `AA` adjacent** — library `TAGS · G I A AA L` now shows `G:genre I:instrumental A:advisory AA:album advisory L:lyrics` so the two advisory values are side-by-side as requested; heading key updated; `PASS`/`FAIL` standardized (track was `OK` → `PASS`, filter `Bad only` → `Fail only`).
- **Library viewer tighter + easier** — tree `indent` 30, heading padding `10,7→6,4`, rowheight `32→26`, library/filter padding reduced so bars have less space between them; arrow spread `  ☐  ` (two leading spaces) + hit zones (`x<34` arrow, `x<bbox+38` checkbox) make checkboxes/expand much easier to click; last column (`TAGS`) stretches, others have `minwidth` for intuitive resizing.
- **Icon: variable ascending spectrum** — `tools/make_icon.py` heights `0.30,0.36,0.44,0.58,0.74,0.88,0.97` (slow start then shoot up like real spectrum) on black `BG #0d0d0d` (matches titlebar) + transparent window variant `app_icon_window.ico` (white bars only) for the window; taskbar stays black.
- **General hardening** — all grading checks now mirror config (cover dimensions/cropping, `.cue`/`.log` rename pattern), `worker_limit` capped pools, skipped albums not re-run unless **Force** (covers grading/images/logic), bottom bar now `Settings | Guide | About`, progress bar shows `Finished` then clears, `7/8→8/8` tools detected (simple-dr-meter counted), white outline extends to tabs, responsive layout for small windows.

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
- **Setup Wizard Revamped** — `Guide` button (status bar) now shows an intuitive
  two-section wizard: **Music Files** and **Cover Images**, each with 3 presets
  (Balanced / Most Aggressive LOSSLESS / Lightweight or Compatibility) with
  hover tooltips and a live summary of pending changes. Library folder picker
  with live validation; `Skip` keeps current settings.
- **Reorganized Settings** — Tkinter `app.py` dialog is now grouped as `FLAC Encoding /
  Cover Art — Processing / Resize & Crop / Per-Format / Lyrics / Enhanced LRC (now with
  `[00:00.00]` compat) / CUE (now with `Fix CUE FILE Names`) / CD Rips (`CD-N`
  auto-rename) / Tags / Grading / Audio Audit / Interface / Updates` with
  clear sub-sections and tooltips, keeping ~80 options scannable.
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
| 2 | Format CUEs       | Normalizes .cue sheets (TRACK/INDEX padding, FILE lines, DISCID), fixes FILE names to match tracks (conservative), auto-renames multi-CD cues to `CD-N.cue` |
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

For non-CD releases, runs [AudioAuditor](https://github.com/Angel2mp3/AudioAuditor)'s CLI
(`analyze --json`) over every audio file and reports `Real`/`Fake`/`Corrupt`/etc.
For **`MEDIA=CD`** rips, the log-file checksum is the **only** source of truth:
each track's decoded PCM CRC32 (via `ffmpeg -f s16le`) is compared to the CRC
printed in the `.log` (EAC Test/Copy/AccurateRip or XLD CRC32 hash) — `REAL` on
match, `FAKE` on mismatch. Tracks not covered by a checksum get no `AUDIT`
value at all and the album fails grading (unverifiable). AudioAuditor is never
run on CD rips; it is reserved for every other `MEDIA` value. Only CD albums
consult `.log` files at all.

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
logs and verifies checksums. Multi-disc albums are supported:

- Audio files use the `D-TT Title` naming convention (`2-03 Song.flac`),
  which identifies each disc with no guesswork.
- `.log` and `.cue` files are renamed to a shared, deterministic
  `CD-N.log` / `CD-N.cue` scheme (`CD-1`, `CD-2`, … `CD-11`) when
  `Settings → CD Rips → Auto-Rename to CD-N` is on (default). Cues are
  mapped from their `FILE` entries (exact filenames); logs from an
  explicit disc number in the filename (`CD-2.log`, `Disc 2.log`,
  `2 - Album.log`) or a unique total-duration match against the audio.
  Ambiguous cases are left untouched — grading then flags the missing
  file/log. Each disc's `FILE` lines can also be auto-corrected to the
  actual track filenames when `Fix CUE FILE Names` is on (default) —
  only when exactly one candidate matches by normalized name or track
  number, so no guessing.
- Each disc's log is scored with AudioAuditorCLI's `--rip-log` mode in an
  isolated folder (no audio decoding needed) and the cambia 0-100 score is
  written to the **`LOG_GRADE`** tag of that disc's tracks.
- **Integrity via `.log` CRCs:** the same `.log`’s per-track CRC32 hashes
  (Test/Copy CRC, AccurateRip `[…]`, XLD CRC32) are the *only* audit source
  for CD rips. `ffmpeg:153` decodes each track to raw PCM and `zlib.crc32` is
  compared — mismatch → `AUDIT=FAKE`; no `.log` or no CRC → no `AUDIT` at all
  and grading fails the album (`unverifiable CD rip`). Non-CD releases
  are never checked against logs — they go through AudioAuditor only.

Grading requires, for `MEDIA=CD`: the `LOG_GRADE` tag (0-100) on every track,
an `AUDIT` tag of `REAL` (from the log checksum), and every track covered by
a CRC in the log — any missing or mismatched check fails the album — while
for all other media the `AUDIT` tag must be `REAL` from AudioAuditor.

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
a tree of `FOLDER / TRACK` (artists → albums → tracks, first column now labeled) with a slightly darker heading bar at the top (no white outlines, just a darker tone). Checkboxes select items for **Optimize Selected** (which runs the pipeline and finishes with an audit); **Shift+Click** selects a range between two items and **Ctrl+Click** toggles a single item without affecting others, while the arrow (`▸`) is well separated from the checkbox (`☐`/`☑`, indent 30) for easy clicking. The bars between sections have minimal padding (tight `5,3` layout). The filter row narrows by album-artist tag or folder name, can show only failing albums, and sorts by grade.

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

## MusicBrainz Picard — Preserve Tags

If you use **Options → Tags → Clear existing tags** in Picard, add these to **Preserve these tags from being cleared** so that Picard does not delete the tags that **this app adds** and needs for grading. This list is **only** the 13 tags you listed — not the standard MusicBrainz tags (TITLE, ALBUM, ARTIST, TRACKNUMBER etc. are already written by Picard and do not need preserving). `MEDIA` is **not** included because Picard already tags `MEDIA` (e.g. `CD`/`Vinyl`/`File`):

```
ALBUM DYNAMIC RANGE, ALBUMITUNESADVISORY, AUDIT, DYNAMIC RANGE, ENCODER_PROGRAM, ENCODER_QUALITY, ENCODER_VERSION, GENRE, INSTRUMENTAL, ITUNESADVISORY, LOG_GRADE, LYRICS, SOURCE
```

> **Your list was correct** — `MEDIA` is now correctly excluded (Picard handles it). You omitted the 4 `REPLAYGAIN_*` tags (`REPLAYGAIN_TRACK_GAIN`, `REPLAYGAIN_TRACK_PEAK`, `REPLAYGAIN_ALBUM_GAIN`, `REPLAYGAIN_ALBUM_PEAK`) which are written by the **DR & ReplayGain** script via `rsgain` — add those 4 as well if you use that feature, otherwise omit. `UNSYNCEDLYRICS` is the same as `LYRICS` (the app normalizes both to `LYRICS`), so `LYRICS` alone is enough. `GENRE`/`ITUNESADVISORY` are included because you manage them manually and Picard doesn’t preserve them by default when clearing.

For FLAC these are Vorbis comments (`UPPERCASE`), for MP3 they are `TXXX:` frames (`TXXX:ITUNESADVISORY` etc.) and `COMM`/`USLT`, for MP4 they are `----:com.apple.iTunes:*` freeform atoms — Picard handles the mapping automatically when you list the Vorbis-style names above. If you do **not** use *Clear existing tags*, you do not need to set this; just ensure **Preserve these tags** is empty or add only the custom ones you care about (`AUDIT`, `LOG_GRADE`, `SOURCE`).

Tags **not** in this list such as `TITLE`, `ALBUM`, `ARTIST`, `ALBUMARTIST`, `TRACKNUMBER`, `DISCNUMBER`, `DATE`, `COMPOSER`, `PERFORMER`, `WORK` etc. are standard MusicBrainz/Picard tags — you do not need to preserve them separately because Picard will rewrite them anyway.

**Tip:** Keep *Clear existing tags* **off** unless you have a specific reason. Since `v1.4.2` the app **no longer removes tags** at all except for the two lyric variants (`UNSYNCEDLYRICS` is always removed as legacy, `LYRICS` is removed only when `Settings → Lyrics → Lyrics Format = LRC`); all other tags — including every MusicBrainz/Picard tag (`MUSICBRAINZ_TRACKID`, `MUSICBRAINZ_ALBUMID`, `ARTISTSORT`, `WORK`, `ISRC`, `BARCODE`, etc.) — are left untouched so Picard continues to recognize your files. The old `KEEP_VORBIS_KEYS` whitelist is kept only for reference, not for deletion.

## Per-Filetype Tag Writes (v1.3.9)

`Settings → Audio Tags — Per Format` controls which semantic tag families each audio container receives. This is **organized but thorough**: 6 audio types × 8 families = 48 toggles, enough to fine-tune without per-tag sprawl.

| Family | Tags | Script |
|---|---|---|
| **AUDIT** | `AUDIT` (REAL/FAKE) | 6 Audit Library |
| **LOG** | `LOG_GRADE` (0-100) | 6 Audit Library (CD rips) |
| **RG** | `REPLAYGAIN_TRACK/ALBUM_GAIN/PEAK` (4) | 7 DR & ReplayGain (rsgain) |
| **DR** | `DYNAMIC RANGE` / `ALBUM DYNAMIC RANGE` | 7 DR & ReplayGain (simple-dr-meter) |
| **M/S** | `SOURCE` (MEDIA is now Picard-handled) | 1 Lyrics (SOURCE normalizer) |
| **ADV** | `ITUNESADVISORY` + `ALBUMITUNESADVISORY` | 8 Auto Tagging |
| **INST** | `INSTRUMENTAL` | 1 Lyrics + 8 Auto Tagging |
| **LYR** | `LYRICS` (embedded) | 1 Lyrics |

Rows: `FLAC (.flac)` · `MP3 (.mp3)` · `MP4 (.m4a/.mp4)` · `OGG (.ogg)` · `Opus (.opus)` · `AAC (.aac)`.

- Each toggle is **ANDed** with its global master (`Settings → Tags — Writes` / `Audio Audit` / `Auto Tagging`): both must be on for a tag to be written. Example: `MP3 → AUDIT off` means MP3s never get `AUDIT`, even if `Write AUDIT Tags` is on.
- `Encoder Tags` (`ENCODER_PROGRAM/QUALITY/VERSION`) are already per-type via `Settings → Encoder Tags` (Vorbris/XMP/tEXt) — the new table adds the semantic families.
- `Grader` respects disabled families: a disabled tag is not counted as missing and does not cause FAIL, so you can keep a clean grade while tailoring writes.
- Stored as `config.json: audio_tag_writes: { flac: {AUDIT:true,…}, mp3:{…}, … }` — all `true` by default for backward compatibility. Edit via GUI or `mlo config audio_tag_writes` JSON.

## Project layout

```
app.py                          GUI entry point (Tkinter, dark-themed) — v1.5.4
                                 (PySide6/Qt `gui/` revamp removed; Tkinter is now primary)
mlo_cli.py                      CLI entry point (argparse; builds mlo.exe)
mlo/                            Core package — all processing logic
    __init__.py                 version + public re-exports (1.5.3)
    __main__.py                 python -m mlo entry
    paths.py                    Locations & constants (exe-aware)
    deps.py                     Optional dependency detection (mutagen/Pillow/tqdm)
    config.py                   config.json load/save & defaults (v1.5.4 keys, ENCODER_PROGRAM off, no tag deletion)
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
assets/                         Application icons (black #0d0d0d bg, 7 white ascending bars)
    icon_256.png / icon_64.png  pre-rendered PNGs (main, variable heights 0.30→0.97)
    icon_window_256.png         window-only transparent white bars (same 7-bar spectrum)
tools/                          Dev helpers & tests
    make_icon.py                Icon generator (Pillow)
    make_test_library.py        Synthetic music library builder
    test_*.py                   Lyrics / GUI regression tests
docs/
    archive/                    Historical release notes
        RELEASE_NOTES_v1.1.0.md v1.1.0 detailed notes (archived)
RELEASE_NOTES.md                v1.5.4 + v1.5.4 + v1.5.0 + v1.4.3 + v1.4.2 + v1.4.1 + v1.4.0 + v1.3.9 + v1.3.8 + v1.2.0 + v1.1.0 summary (current)
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

Output: `dist/MusicLibraryOptimizer_Setup_v1.4.2_x64.exe` + `dist/MusicLibraryOptimizer_v1.5.4_portable_x64.exe` + `dist/mlo.exe`

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











