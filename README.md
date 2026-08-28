# Music Library Optimizer v2

A modern web-based music library optimizer and tagger. Built on the proven
`mlo` engine (grading, auditing, FLAC/image optimization, CUE/lyrics
formatting, AccurateRip) with a brand-new React UI, playback, playlists,
MusicBrainz / LRCLIB / RateYourMusic integration, and an import wizard.

## Highlights

- **Library explorer** — artists → albums → tracks with live grade/audit
  badges, search, "fail only" filter, and sortable columns (year, title,
  grade, audit, genre, advisory, duration, bitrate, …).
- **Artist / Album / Track pages** — every entity shows its grading and
  auditing state, plus MusicBrainz and RateYourMusic links (editable).
- **Playback** — queue player with shuffle, repeat-one, seek and volume.
- **Playlists** — manual playlists (reorder, .m3u8 export/import) and
  **smart playlists** driven by saved tag/grade/audit filters.
- **Import wizard** — drag & drop uploads, MusicBrainz release linking,
  per-track/disc matching, cascading genre import (track → release →
  release-group → artist), LRCLIB lyrics with a synced line editor
  (spacebar stamps timestamps), INSTRUMENTAL flags, and per-track
  ITUNESADVISORY ratings.
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
             accurip, loudness, autotag (v1 engine, preserved)
tools/       test-library generator and helpers
```

## API overview

| Endpoint | Purpose |
| --- | --- |
| `GET /api/library` | tag-rich library tree (grades, audits, tags, tech info) |
| `GET /api/album` `GET /api/artist` | entity details |
| `GET /api/stream` | audio streaming (Range) |
| `GET/POST /api/tags` `POST /api/tags/batch` | tag read/write |
| `POST /api/run` | run scripts (1–10) on targets |
| `GET/POST /api/playlists…` | manual + smart playlists, .m3u8 |
| `GET /api/mb/release/{id}` `…/genres` | MusicBrainz release + genre cascade |
| `POST /api/mb/match` `POST /api/mb/assign` | track/disc matching, MBID writes |
| `GET /api/lyrics/*` `POST /api/lyrics/write` | LRCLIB proxy + LRC sidecar write |
| `POST /api/import/upload` `…/commit` | upload + link assignment |
| `WS /ws/progress` | live progress |

## Test library

```bash
python tools/make_test_library.py
```

Generates a small synthetic library (real FLACs when `flac` is available,
otherwise MP3 fallback) for end-to-end testing.

---

Legacy v1 (Tkinter app, CLI, PyInstaller/Inno packaging) is archived on the
`archive/legacy-v1.7` branch.