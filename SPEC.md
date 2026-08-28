# MusicLibraryOptimizer — Specification Sheet v1.7.1 → v2.0 (Rewrite Baseline)

> Purpose: frozen spec for a full rewrite. Covers current `mlo/*` behavior + requested `Things to Implement`. Any v2 implementation must satisfy this spec to be considered correct.
> Source of truth: `app.py` (Tkinter, now archived `archive/tkinter-legacy`), `mlo/config.py:13` `DEFAULT_RUN_ALL_ORDER`, `mlo/grader.py:716`, `mlo/audit.py:312`, `mlo/discs.py:81`, `mlo/accurip.py:266`, `mlo/lyrics.py:122`, `mlo/audio.py:AudioFile`.

## 1. Goals / Non-Goals
- **Goal:** Local-only, lossless-correct library optimizer for `F:/Media/Music/Artists`-style trees. Deterministic, skim-safe (re-run changes nothing), crash-safe (atomic + fsync). GRADE = formatting/tag presence, AUDIT = integrity/real-fake/authenticity.
- **Non-goals:** Cloud sync, streaming service upload, lossy transcoding (except JPEG/PNG→JPEG/JXL covers per config).

## 2. Architecture (v2 localhost)
- **Backend:** `server/main.py` `FastAPI 127.0.0.1:8000` wrapping `mlo/*` verbatim. Reuses `mlo/stats.py:80` `progress_hook` → `WS /ws/progress`, `mlo/stats.py:208` `_collect_targets` for per-Track/Album/Artist/All scoping. Disabled `tqdm` so `_HookPbar` always fires (`server/main.py:28`).
- **Frontend:** `web/` `Vite + React + TS + Tailwind + Zustand + TanStack Query` `127.0.0.1:5173` proxy `/api` + `/ws`. `Howler.js`/`<audio>` with `Range` `FileResponse` (`server/main.py:/api/stream`). `web/dist` also mounted at `GET /` when built.
- **Legacy:** Tkinter `app.py` frozen on branch `archive/tkinter-legacy`.

## 3. Data Model
```
Library root (config.music_folder)
 └─ Artist dir (parent of album)
     └─ Album dir (_find_albums: contains AUDIO_EXTS)
         ├─ Disc N (mlo/discs.py:album_discs — 1-01 Title.flac → disc 1, 2-03 → disc 2; else {} = single-disc fallback)
         │   ├─ Tracks: *.flac/.mp3/.m4a/.mp4/.ogg/.opus/.aac (mlo/paths.py:AUDIO_EXTS)
         │   ├─ Sheets: CD-{n}.cue / CD-{n}.log / CD-{n}.accurip (mlo/discs.py:_disc_pattern_for default CD-{n})
         │   ├─ Cover: cover.(jpg|jpeg|png|jxl) + sidecar 01 - Title.jpg (mlo/paths.py:get_sidecar_cover_path)
         │   └─ Lyrics: 01 Title.lrc (+ 01 Title.lrc.translation helper sidecar — never tag)
         └─ Images: any IMAGE_EXTS
```
- **Hierarchy ops:** Every script/API accepts `targets: string[] | null` (null = entire library). `Album → album_dir`, `Artist → child albums`, `Track → dirname`. Single code path `mlo/stats.py:208`.

## 4. Tagging (`mlo/audio.py:AudioFile`, `COMMON_TAGS:70`, `AUDIO_TAG_FAMILIES:16`)

### 4.1 Tag families (per-filetype gated `mlo/config.py:70` `should_write_audio_tag`)
| Family | Tags | Global toggle | Notes |
|---|---|---|---|
| AUDIT | AUDIT (REAL/FAKE) | `write_audit_tag` | per-track, binary |
| LOG_GRADE | LOG_GRADE 0-100 | `write_log_grade` | per-disc |
| REPLAYGAIN | 4× REPLAYGAIN_* | `write_replaygain_tags` | rsgain |
| DYNAMIC_RANGE | DYNAMIC RANGE / ALBUM DYNAMIC RANGE | `write_dynamic_range_tags` | simple-dr-meter |
| MEDIA_SOURCE | MEDIA, SOURCE | `normalize_media_source` | see 4.2 |
| INSTRUMENTAL | INSTRUMENTAL 0/1 | `fix_instrumental_from_lyrics` + `auto_instrumental` | 0=has lyrics |
| ADVISORY | ITUNESADVISORY (0/1/2), ALBUMITUNESADVISORY | `auto_advisory` | album advisory = any explicit→1 else any safe→2 else 0 |
| LYRICS | LYRICS/UNSYNCEDLYRICS + .lrc sidecar | lyrics_format | EMBEDDED/LRC/BOTH |
| GENRE | GENRE | per-track | required |
| BPM_KEY | BPM, INITIALKEY (planned) | `auto_bpm_key` | Essentia |

- ENCODER_* are not families: `encoder_tags: {flac,jpeg,png,jxl: {PROGRAM False default, QUALITY True, VERSION True}}` (`mlo/config.py:312`).

### 4.2 MEDIA/SOURCE rule (`mlo/lyrics.py:600`)
- `MEDIA == Digital Media` → `SOURCE` must exist and be consistent per album; else `SOURCE` must be absent (CD must not carry SOURCE; `strip_source_on_cd True` default). `fill_empty_source False` means empty stays empty. `digital_media_source_value` fallback only when `fill_empty_source True`.

### 4.3 Tag formatting (Format All final pass `mlo/format_all.py:177`)
- All tag values: trim each line `strip(" \t")`, drop ALL blank lines, per-line check `grade_check_tag_spaces/grade_check_tag_blank_lines`. `LYRICS` canonicalized via `mlo/lyrics.py:382` `_format_for_storage`.

## 5. Grading (`mlo/grader.py:716` `_grade_album` → `{pass_count,total_checks,issues,tracks[*].issues}`)

**Invariant:** GRADE = formatting + required-tag presence. Never includes AUDIT/real-fake. (`mlo/config.py:252` `grade_check_audit False`).

| Check | Scope | Config | Detail |
|---|---|---|---|
| `grade_check_missing_tags` | per-track | True | `GENRE/ITUNESADVISORY/RG*/DR/INSTRUMENTAL` must be non-empty per enabled filetype |
| `grade_check_tag_spaces/blank` | per-track all tags | True | any line `strip(" \t")` or blank line fails |
| `grade_check_unreadable` | per-track | True | `AudioFile.audio is None` |
| `grade_check_encoder` | per-track per-format | True | `ENCODER_QUALITY/VERSION` required when enabled |
| `grade_check_instrumental` | per-track | True | `1→no lyrics, 0→needs lyrics` |
| `grade_check_lyrics` | per-track | True | per `lyrics_format` presence |
| `grade_check_lyrics_format` | per-track | True | `_lyrics_formatted` + `_lyrics_word_timestamps_valid` + no merged `[a][b]` |
| `grade_check_lyrics_spaces/blank/zero` | per-track | True | lyrics lines spaces/blank/zero timestamp |
| `grade_check_media/source/album_tags` | album | True | single MEDIA, SOURCE per digital, album tags consistency |
| `grade_check_cd_log/cue` | album | True | CD needs `CD-{n}.log/.cue` |
| `grade_check_disc_naming` | album | True | sheets must match `discs_rename_pattern CD-{n}` |
| `grade_check_log_grade` | per-track | True | LOG_GRADE 0-100, threshold `grade_log_score_threshold` |
| `grade_check_crc` | per-track | True | `parse_log_checksums` covers each `track_number` |
| `grade_check_cd_format` | per-track | True | CD must be 16-bit 44.1kHz (via `info.bits_per_sample/sample_rate`) |
| `grade_check_cover/cue_format/disallowed` | album | True | `cover.jpg/png/jxl` size/square, cue canonical `mlo/cue.py:13`, other file types |
| `grade_check_cover_crop/size/square` | album+sidecar | True | `cover_target_size 1000`, `cover_enforce_*/crop_threshold`, `grader_*_tolerance` |
| `grade_check_sidecar_cover` | per-track | True | sidecar `01 - Title.jpg` same checks |
| `grade_check_log_checksum` | viewer only | True | shows CHECKSUM column, does NOT fail grade |
| `grade_check_accuraterip` | viewer only | True | shows ACCURATERIP column, does NOT fail grade (AUDIT only) |

- **Viewer columns:** `GRADE` `PASS/FAIL` `100%/0%`, `AUDIT` `REAL/FAKE/Mix` `summarize_audits`, `CHECKSUM` `REAL/FAKE/NONE` per-disc `per_disc_checksum_map:1398`, `ACCURATERIP` `REAL/FAKE/NONE` per-track `per_disc_ar_map:1424` via `mlo/accurip.py:367` `parse_accurip_per_track`.

## 6. Auditing (`mlo/audit.py:312` `run_audit_library` → AUDIT tag per file, `mlo/grader.py:1844` realtime `audit_summary`)

AUDIT = integrity + authenticity. Each gate is per-track/disc, not whole-album:

| Gate | Logic | Config |
|---|---|---|
| `.log CRC` | `mlo/discs.py:212` `verify_album_checksums` via `ffmpeg` decoded CRC vs `parse_log_checksums`; per-track `REAL/FAKE`, unverified = no verdict | `audit_verify_cd_checksums` + `audit_cd_require_both` (AND with AudioAuditor when True) |
| `AudioAuditorCLI` | batch `analyze --json` `mlo/audit.py:140`, flags `clipping/MQA/AI/fake stereo/silence` `FLAG_KEYS:50` | `audit_thorough`, `audit_*` detector toggles, `audit_cutoff_allow`, batch/timeouts |
| Integrity | `flac -t` + `ffmpeg -v error -f null` `mlo/audit.py:78` | `audit_integrity` per-track FAKE |
| FLAC MD5 | `metaflac --show-md5sum` vs `AUDIO_MD5` tag `mlo/audit.py:499` | `audit_integrity` per-track FAKE |
| Unscorable log | `mlo/audit.py:885` `unscorable_discs` per disc (was whole album) | `audit_fail_on_unscorable_log` per-disc FAKE |
| Log SHA | `mlo/discs.py:835` `check_log_checksum` (eac-logchecker Rijndael) `invalid/missing→FAKE, unsupported→PASS` per disc | `audit_verify_log_checksum` per-disc FAKE (`mlo/audit.py:974`) |
| AccurateRip | `.accurip` only via CUETools (`mlo/accurip.py:469` `CUETools.ARCUE.exe` + ffmpeg WAV transport) `parse_accurip_status/per_track` per-track `FAKE/NONE→FAKE` | `audit_require_accuraterip` per-track FAKE (`mlo/audit.py:1127`) |
| Log score | `mlo/discs.py:768` `php logchecker.phar analyze` `LOG_GRADE` per disc | `audit_log_score_threshold` per-disc FAKE |
| CD format | `16/44.1` via `AudioFile.info` per-track | `audit_check_cd_format` per-track FAKE |

- Writes `AUDIT=REAL/FAKE` per-track (`should_write_audio_tag` per filetype), respects `force_audit` skip logic.

## 7. Optimization (media, in pipeline order `DEFAULT_RUN_ALL_ORDER`)

`1 Lyrics → 2 CUEs → 8 AutoTag → 3 FLAC → 5 Images → 9 AccurateRip → 6 Audit → 4 Grade → 7 DR/RG → 10 FormatAll` (`mlo/config.py:13` + `app.py:5755` + `server/main.py:/api/run`). FormatAll last guarantees grading passes. Force gates per script `master && per_script` (`app.py:5718`).

| Script | Tool | Skippable via | Notes |
|---|---|---|---|
| 1 Lyrics | `mlo/lyrics.py:828` + `AudioFile` | `optimize_*`, `lyrics_format`, `force_lyrics` | idempotent `format_lyrics_text` + `_canonical_lyrics`, instrumental fix |
| 2 CUE | `mlo/cue.py:13` | `keep_empty/other`, `cue_file_type`, `force_cue` | rename `CD-{n}.cue` via FILE entries, `fix_cue_filenames` atomic fsync |
| 3 FLAC | `flac.exe 1.5.0` | `flac_level 8`, `add_seektables`, `flac_no_padding`, `force_reencode` | `ENCODER_QUALITY/VERSION` gate, atomic `*.opttmp.flac` + replace |
| 5 Images | `cjxl/djxl/jxlinfo`, `jpegtran`, `oxipng` | `reencode_*`, `jpeg_quality 100`, `cover_target_size 1000` | atomic `_atomic_write` fsync |
| 7 DR/RG | `rsgain 3.7` + `simple-dr-meter` + `ffmpeg` | `replaygain_skip_existing`, `force_dr` | 4×RG + `ALBUM DYNAMIC RANGE` |
| 9 AccurateRip | `CUETools v2.2.6` `CUETools.ARCUE.exe` + `ffmpeg` WAV | `write_accurip_files`, `force_accurip` | `_canonical_accurip_text` outer-blanks only, `append_final_newline False` |
| 10 FormatAll | all canons | — | trims `.accurip/.cue/.lrc` + tags, fsync (`mlo/format_all.py:31`) |

- **Corruption safety:** `mkstemp` + `flush` + `fsync` + `os.replace` + `dir fsync` for all sidecars/covers (`mlo/containers.py:13`, `mlo/format_all.py:31`).

## 8. Configuration (`mlo/config.py:128` `DEFAULT_CONFIG`, `normalize_config:434`)
- Music folder, FLAC/Images/Cover/Lyrics/CUE/Discs/Media/AutoTag/Grade/Audit/DR/encoder_tags/audio_tag_writes/worker_limit/run_all_order + UI `theme/accent/library_show_all_files`. `audio_tag_writes:322` per filetype `{flac,mp3,mp4,ogg,opus,aac}` × families. `save_config:587` atomic `mkstemp` + `fsync` + `replace`.

## 9. Requested — To Implement (v2 scope)

### 9.1 Auto-tag via MusicBrainz
- Lookup `musicbrainzngs` by AcoustID (`fpcalc`) + discid + duration. Map `common.WORK` etc. Write `MUSICBRAINZ_*` IDs + standard tags per MB style guide. Must respect `audio_tag_writes` families.

### 9.2 Picard naming scripts (100%)
- JS parser `web/src/lib/picardScript.ts` evaluating `%albumartist% [$left(%musicbrainz_albumartistid%,8)]/.../%discnumber%-$num(%tracknumber%,2) %title%` example. Must support all Picard vars + `$if $left $right $num $replace $and $or $not $eq` etc. Dry-run preview before move.

### 9.3 Picard variables (all)
- Expose every `MUSICBRAINZ_*`, `originaldate`, `releasetype`, `releasecountry`, `catalognumber`, `media` etc. in tag panel + script vars.

### 9.4 Translate Artist/Performer/Title via MusicBrainz Alias
- Setting `preferred_locale` (e.g. `en`). For `ARTIST/ALBUMARTIST/PERFORMER/TITLE/ALBUM` lookup MB alias `locale == preferred` → offer translated value + keep original as `ORIGINAL*` tag. Batch via `POST /api/translate`.

### 9.5 UI
- **Better UI:** dark `BG #0d0d0d` already (`app.py:303` + `web/src/index.css`). Keep Tailwind panels `panel #141414` `card #161616`.
- **Search bar:** `Fuse.js` on indexed `TREE_COLUMNS:126` fields + grade/audit values. Lives in `web/src/components/Library.tsx`.
- **Artist view:** `/artist/{name}` — bio, MB link, RYM link `https://rateyourmusic.com/artist/...`, discography, aggregate `PASS/FAIL` + `AUDIT` mix.
- **Album view:** `/album/{path}` — tracks table + `CHECKSUM/ACCURATERIP` per-track, cover drag-drop (`POST /api/cover`), sidecars, `Logchecker` score badge.
- **Track view:** `/track/{path}` — all tags editor, waveform/preview, `AUDIT` reason, `LOG_GRADE` history, per-track `gradeUtils`.
- **Genre view:** `/genre` sortable/filterable by `genre` value per artist/album/track (`PER_TRACK_TAGS:70`).
- **Untagged view:** `/untagged` sortable/filterable by missing/wrong: `Missing AUDIT` `Missing LOG_GRADE` `Missing GENRE` `COVER FAIL` `CUE not formatted` etc. (reuses `res.issues` + `tr.issues`).

### 9.6 React UI + Drag'n-drop
- Done scaffold `web/` with `Library/TagEditor/Player/LyricsEditor`. Covers remain `cover.*` atomic.

### 9.7 Auto-lyrics (LRClib only per decision)
- `GET /api/lyrics/search|get` proxied to `https://lrclib.net/api/{search,get}`. Write `.lrc` only via `_atomic_write_text`. No tag write for translation helper.

### 9.8 Lyric editor Enhanced + translation/transliteration (no tag write)
- Editor supports `[mm:ss.xx]` + `<mm:ss.xx>` `WORD_TS_RE:92`, merged-timestamp split `lrc_extended_enabled`. Translation sidecar `*.lrc.translation` + transliteration (kakasi/pypinyin) — helper sidecars only, never `LYRICS` tag per ask.

### 9.9 BPM + KEY auto-tag
- `Essentia` `streaming_extractor` > `librosa` fallback, dep `python/essentia` via `mlo/fetchdeps.py`. Tags `BPM` `INITIALKEY` as `BPM_KEY` family, batch via `ThreadPoolExecutor` like audit.

---
## 10. Acceptance (do not merge v2 without)
1. `py_compile` all `mlo/*.py` + `server/main.py` OK; 10 runners smoke `targets=[]` and per-Track/Album/Artist/All gradings identical to Tkinter.
2. Per-track isolation: one `FLAC MD5`/`integrity`/`AccurateRip No match` fails only that track (audit/grade per-disc map tests in `SPEC` §6).
3. `GRADE` never fails on `AUDIT`/`CHECKSUM`/`ACCURATERIP` (viewer only), `AUDIT` per-track covers all §6 gates.
4. `GET /api/library` returns same `pass_count/total_checks` as `run_grade_library`.
5. LRClib editor round-trips Enhanced LRC idempotently (`format_lyrics_text`).
