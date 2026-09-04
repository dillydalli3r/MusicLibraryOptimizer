# Music Library Optimizer v2

A modern web-based music library optimizer. Built on the proven `mlo` engine
(grading, auditing, FLAC/image optimization, CUE/lyrics formatting,
AccurateRip, **lossless video remuxing**) with a React UI, playback of music
*and* music videos, playlists, MusicBrainz / LRCLIB / RateYourMusic
integration, and an import wizard.

Grading and auditing own all tag writes — there is no manual tag editor by
design. Album and per-track cover art are fully supported (upload, sidecar
covers, dominant-color tinting).

## Highlights

- **Library explorer** — artists → albums → tracks with live grade/audit
  badges, search, "fail only" filter, and sortable columns (year, title,
  grade, audit, genre, advisory, duration, bitrate, …). Music-video MP4/M4A
  files are first-class tracks.
- **Artist / Album / Track pages** — grading and auditing state, MusicBrainz
  and RateYourMusic links, album + per-track cover upload, and a built-in
  **music video player** (watch MP4 tracks in a modal, streamed with Range
  support).
- **Playback** — queue player with shuffle, repeat-one, seek and volume.
- **Playlists** — manual playlists (reorder, remove, .m3u8 export/import)
  and **smart playlists** driven by saved grade/audit filters.
- **Import wizard** — drag & drop uploads, MusicBrainz release linking,
  per-track/disc matching, cascading genre import, LRCLIB lyrics with a
  synced line editor, INSTRUMENTAL flags, and per-track ITUNESADVISORY
  ratings (these feed grading — they are the only "metadata" writes left).
- **Video remux (script 11)** — any video container (VOB, MKV, AVI, WMV,
  WebM, TS, MOV, FLV…) → MP4, **losslessly**: the video stream is copied
  bit-exact when MP4-compatible (h264/hevc/mpeg4/av1/vp9), incompatible
  codecs are optionally re-encoded to H.264, and **every audio stream is
  re-encoded to FLAC** (lossless from the decoded source, multi-channel and
  hi-res safe). Output is verified with ffprobe (video present, audio
  stream count, duration) before the original is optionally removed.
  Text subtitles become mov_text; chapters survive. One-click from the
  album page ("Convert N videos") or the scripts menu.
- **Desktop + Web** — served by FastAPI (browser or Docker); a Tauri v2
  desktop shell is planned for native file dialogs and a standalone app.

## Quick start

```bash
# backend
python -m pip install -r server/requirements.txt
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000

# frontend (dev, http://localhost:5173 proxies /api to :8000)
cd web && npm install && npm run dev
```

Production build is served by the backend automatically (`web/dist`):

```bash
cd web && npm run build
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

Set your music folder in **Settings** (or point `MLO_MUSIC_FOLDER` at it).
Install the external toolchain from Settings → Dependencies (ffmpeg, flac,
libjxl, rsgain, AudioAuditor, Logchecker, CUETools, simple-dr-meter).

## Docker

```bash
docker compose up --build
# open http://localhost:8000 — mount your music under ./music
```

The image bundles the React build and the audio/image toolchain
(`ffmpeg`, `flac`, `libjxl`, `jpegtran`, `oxipng`).

## Architecture

```
web/         React 19 + TypeScript + Tailwind UI (Vite)
server/      FastAPI backend: library payload, playlists, integrations,
             import, streaming, WebSocket progress
mlo/         core engine: grader, audit, flac, images, lyrics, cue,
             accurip, loudness, autotag, remux (v1 engine, preserved)
tools/       test-library generator and test suites
```

## API overview

| Endpoint | Purpose |
| --- | --- |
| `GET /api/library` | tag-rich library tree (grades, audits, tags, tech info; gzipped) |
| `GET /api/album` `GET /api/artist` | entity details |
| `GET /api/stream` | audio/video streaming (Range) |
| `GET /api/tags` | tag read-only view (writes belong to the grading scripts) |
| `POST /api/lyrics/embed` | write the embedded LYRICS tag only |
| `POST /api/run` | run scripts (1–11) on targets |
| `GET /api/videos/scan` | list remuxable video files with codec info |
| `GET/POST /api/playlists…` | manual + smart playlists, .m3u8 |
| `GET /api/mb/release/{id}` `…/genres` | MusicBrainz release + genre cascade |
| `POST /api/mb/match` `POST /api/mb/assign` | track/disc matching, MB/RYM/genre/advisory writes |
| `GET /api/lyrics/*` `POST /api/lyrics/write` | LRCLIB proxy + LRC sidecar write |
| `POST /api/cover` | album cover upload (`?track=` writes per-track sidecar covers) |
| `POST /api/import/upload` `…/commit` | upload + link assignment |
| `WS /ws/progress` | live progress |

## Scripts (Run All order is configurable)

| # | Script | Notes |
| --- | --- | --- |
| 1 | Format lyrics | embedded + .lrc canonicalization |
| 2 | Format CUEs | + CD-N sheet renaming, FILE-line fixes |
| 3 | Optimize FLACs | level 8, padding stripped |
| 4 | Grade | the full check battery |
| 5 | Images | cover resize/crop to 1000×1000, JPEG optimization, optional JXL |
| 6 | Audit | AudioAuditor + CD log CRC verification → AUDIT tags |
| 7 | DR & ReplayGain | rsgain + simple-dr-meter (FLAC and MP4 alike) |
| 8 | Auto Tagging | ALBUMITUNESADVISORY + INSTRUMENTAL-from-lyrics |
| 9 | AccurateRip | .accurip generation via CUETools |
| 10 | Format All | final canonical trim pass |
| 11 | Video Remux | any video → MP4, video copied, audio → FLAC |

## Tests

```bash
python tools/make_test_library.py   # synthetic library for end-to-end runs
python tools/test_remux.py          # video remux suite (VOB/MKV/AVI/WebM fixtures)
```

---

Legacy v1 (Tkinter app, CLI, PyInstaller/Inno packaging) is archived on the
`archive/legacy-v1.7` branch.
