import { Fragment, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {  FolderOpen, ListPlus, Play, Trash2, ChevronRight, ChevronDown, Columns3, Wand2, FolderSync, BarChart3, Info as InfoIcon, CloudDownload,
  ListFilter,
} from "lucide-react";
import { api } from "../api";
import { SCRIPTS, DEFAULT_RUN_ALL } from "../lib/scripts";
import { toast, useStore } from "../store";
import { sortRows, SortHeader, groupByDisc, type SortState } from "../lib/sort.tsx";
import { gradeSliver, statusFor, auditFails } from "../lib/status";
import { albumRef, trackRef, artistRef } from "../lib/refs";
import { EmptyState, GradeBadge, MediaChip, AdvisoryBadge } from "../components/Badges";
import { forceDict, loadForceSel } from "../lib/force";
import CoverImg from "../components/CoverImg";
import FavHeart from "../components/FavHeart";
import AlbumCard from "../components/AlbumCard";
import StatsPanel from "../components/StatsPanel";
import TrackDetails from "../components/TrackDetails";
import type { Album, Artist, Track } from "../types";

type View = "grid" | "compact" | "albums" | "artists" | "tracks";

type Preset =
  | "all"
  | "failing"
  | "cd"
  | "digital"
  | "explicit"
  | "instrumental"
  | "missingLyrics";

const PRESETS: { id: Preset; label: string }[] = [
  { id: "all", label: "All" },
  { id: "failing", label: "Failing" },
  { id: "cd", label: "CD rips" },
  { id: "digital", label: "Digital" },
  { id: "explicit", label: "Explicit" },
  { id: "instrumental", label: "Instrumental" },
  { id: "missingLyrics", label: "No lyrics" },
];

const VIEW_TABS: { id: View; label: string }[] = [
  { id: "grid", label: "Grid" },
  { id: "compact", label: "Compact" },
  { id: "albums", label: "Albums" },
  { id: "artists", label: "Artists" },
  { id: "tracks", label: "Tracks" },
];

/** Grid cover sizes (small / medium / large) → grid-template min column. */
const GRID_SIZE_MIN: Record<"s" | "m" | "l", number> = { s: 126, m: 164, l: 214 };

const ALBUM_SORTS = [
  { key: "meta.ALBUM", label: "Album name" },
  { key: "artist", label: "Artist" },
  { key: "meta.DATE", label: "Year" },
  { key: "track_count", label: "Tracks" },
  { key: "grade_pct", label: "Grade" },
  { key: "audit_summary", label: "Audit" },
];

interface Col {
  id: string;
  label: string;
  sortKey: string;
}

const ALBUM_COLS: Col[] = [
  { id: "album", label: "Album", sortKey: "meta.ALBUM" },
  { id: "artist", label: "Artist", sortKey: "artist" },
  { id: "year", label: "Year", sortKey: "meta.DATE" },
  { id: "tracks", label: "Tracks", sortKey: "track_count" },
  { id: "grade", label: "Grade", sortKey: "grade_pct" },
  { id: "media", label: "Media", sortKey: "media" },
  { id: "source", label: "Source", sortKey: "source_summary" },
];

const ARTIST_COLS: Col[] = [
  { id: "albums", label: "Albums", sortKey: "aggregate.album_count" },
  { id: "tracks", label: "Tracks", sortKey: "aggregate.track_count" },
  { id: "checks", label: "Checks", sortKey: "aggregate.grade_pct" },
  { id: "grade", label: "Grade", sortKey: "aggregate.grade_pct" },
];

const TRACK_COLS: Col[] = [
  { id: "num", label: "#", sortKey: "tracknumber" },
  { id: "title", label: "Title", sortKey: "tags.TITLE" },
  { id: "artist", label: "Artist", sortKey: "artist" },
  { id: "album", label: "Album", sortKey: "album" },
  { id: "year", label: "Year", sortKey: "tags.DATE" },
  { id: "genre", label: "Genre", sortKey: "tags.GENRE" },
  { id: "media", label: "Media", sortKey: "tags.MEDIA" },
  { id: "grade", label: "Grade", sortKey: "grade_pass" },
  { id: "advisory", label: "Advisory", sortKey: "tags.ITUNESADVISORY" },
  { id: "duration", label: "Duration", sortKey: "tech.length" },
  { id: "bitrate", label: "Bitrate", sortKey: "tech.bitrate" },
  { id: "source", label: "Source", sortKey: "tags.SOURCE" },
];

interface FlatAlbum extends Album {
  artist: string;
}

interface FlatTrack extends Track {
  artist: string;
  album: string;
}

export default function LibraryPage() {
  const { data: lib, isLoading, error } = useQuery({ queryKey: ["library"], queryFn: api.library });
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config });
  const runAllIds = Array.isArray(config?.run_all_order) && config.run_all_order.length
    ? config.run_all_order.filter((n: number) => n >= 1 && n <= 15)
    : DEFAULT_RUN_ALL;
  const qc = useQueryClient();
  const { query, setToast, folder } = useStore();
  const {
    selection, setSelection, toggleTrack, toggleAlbum, toggleArtist, clearSelection, playNow,
  } = useStore();
  const [view, setView] = useState<View>(() => (localStorage.getItem("mlo.defaultView.v2") as View) ?? "grid");
  const [preset, setPreset] = useState<Preset>("all");
  const [filterOpen, setFilterOpen] = useState(false);
  const [albumSort, setAlbumSort] = useLocalSort("album");
  const [artistSort, setArtistSort] = useLocalSort("artist");
  const [trackSort, setTrackSort] = useLocalSort("track");
  const [removing, setRemoving] = useState<string | null>(null);
  const [lyricsBusy, setLyricsBusy] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [groupByArtist, setGroupByArtist] = useState(false);
  const [gridSize, setGridSize] = useState<"s" | "m" | "l">(() => {
    const v = localStorage.getItem("mlo.gridSize");
    return v === "s" || v === "l" ? v : "m";
  });
  const [statsOpen, setStatsOpen] = useState(false);
  const [detailTrack, setDetailTrack] = useState<{ track: Track; albumPath: string } | null>(null);

  const [fullDates, setFullDates] = useLocalPref("full-dates", false);
  const [albumCols, toggleAlbumCol] = useColumnPrefs("albums", ALBUM_COLS);
  const [artistCols, toggleArtistCol] = useColumnPrefs("artists", ARTIST_COLS);
  const [trackCols, toggleTrackCol] = useColumnPrefs("tracks", TRACK_COLS);

  const flat = useMemo(() => {
    const albums: FlatAlbum[] = [];
    const tracks: FlatTrack[] = [];
    for (const a of lib?.artists ?? [])
      for (const al of a.albums) {
        // Prefer the tag-derived album artist (ALBUMARTIST/ARTIST); the
        // artist folder name is only a fallback (it carries the MBID suffix).
        const artistName = al.album_artist || a.name;
        albums.push({ ...al, artist: artistName });
        for (const t of al.tracks) tracks.push({ ...t, artist: artistName, album: al.meta?.ALBUM ?? al.path.split("/").pop() ?? "" });
      }
    return { albums, tracks };
  }, [lib]);

  // Per-preset predicate, shared by the filter memo and the filter menu
  // counts (search text is applied separately from the preset).
  const trackPresetOK = (t: Track, preset: Preset) => {
    switch (preset) {
      case "all": return true;
      case "failing": return !t.grade_pass;
      case "cd": return (t.tags.MEDIA ?? "").toUpperCase().includes("CD");
      case "digital": return (t.tags.MEDIA ?? "").toUpperCase().includes("DIGITAL");
      case "explicit": return t.tags.ITUNESADVISORY === "1";
      case "instrumental": return t.tags.INSTRUMENTAL === "1";
      case "missingLyrics": return !t.lyrics_present;
    }
  };
  const albumPresetOK = (al: Album, preset: Preset) => {
    switch (preset) {
      case "all": return true;
      case "failing": return !al.pass;
      case "cd": return (al.media ?? "").toUpperCase().includes("CD");
      case "digital": return (al.media ?? "").toUpperCase().includes("DIGITAL");
      case "explicit":
      case "instrumental":
      case "missingLyrics": return (al.tracks ?? []).some((t) => trackPresetOK(t, preset));
    }
  };
  const presetCounts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const { id } of PRESETS) out[id] = flat.albums.filter((al) => albumPresetOK(al, id)).length;
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flat]);

  const filtered = useMemo(() => {
    if (!lib) return { artists: [] as Artist[], albums: [] as FlatAlbum[], tracks: [] as FlatTrack[] };
    const q = query.toLowerCase();
    const matches = (hay: string) => !q || hay.toLowerCase().includes(q);

    const trOK = (t: Track) => trackPresetOK(t, preset);
    const alOK = (al: Album) => albumPresetOK(al, preset);
    const alSearch = (al: Album, artist: string) =>
      matches([artist, al.meta?.ALBUM, al.meta?.DATE, al.meta?.ARTIST, ...(al.tracks?.map((t) => `${t.tags.TITLE} ${t.file}`) ?? [])].join(" "));

    const artists: Artist[] = lib.artists
      .map((a) => ({ ...a, albums: a.albums.filter((al) => alOK(al) && alSearch(al, a.name)) }))
      .filter((a) => a.albums.length);

    const albums = flat.albums.filter((al) => alOK(al) && alSearch(al, al.artist));
    const tracks = flat.tracks.filter((t) => trOK(t) && matches([t.artist, t.album, t.tags.TITLE, t.file, t.tags.GENRE, t.tags.MEDIA].join(" ")));
    return { artists, albums, tracks };
  }, [lib, query, preset, flat]);

  // ---- selection helpers ----
  const selTracks = useMemo(() => {
    const s = new Set(selection.tracks);
    for (const p of selection.albums) {
      const al = flat.albums.find((a) => a.path === p);
      for (const t of al?.tracks ?? []) s.add(t.path);
    }
    for (const p of selection.artists) {
      const a = lib?.artists.find((x) => x.path === p);
      for (const al of a?.albums ?? []) for (const t of al.tracks) s.add(t.path);
    }
    return s;
  }, [selection, flat, lib]);

  const selectionAlbumDirs = useMemo(() => {
    const dirs = new Set<string>();
    for (const p of selection.albums) dirs.add(p);
    for (const p of selection.artists) {
      const a = lib?.artists.find((x) => x.path === p);
      for (const al of a?.albums ?? []) dirs.add(al.path);
    }
    for (const p of selection.tracks) dirs.add(p.split("/").slice(0, -1).join("/"));
    return [...dirs];
  }, [selection, lib]);

  const selectionCount = selection.tracks.length + selection.albums.length + selection.artists.length;

  const addToPlaylist = async (paths: string[]) => {
    if (!paths.length) return;
    const pls = await api.playlists();
    const manual = pls.find((p) => p.kind === "manual");
    if (!manual) {
      const created = await api.createPlaylist("Library selection", "manual");
      await api.playlistAdd(created.id, paths);
    } else {
      await api.playlistAdd(manual.id, paths);
    }
    setToast(`Added ${paths.length} track(s) to playlist`);
  };

  const removeAlbums = async (paths: string[]) => {
    if (!paths.length) return;
    const names = paths.map((d) => d.split("/").pop()).join(", ");
    if (!window.confirm(`Remove ${paths.length} album(s) from the library?\n${names}\n\nThey move to .mlo_trash in your music folder (recoverable).`)) return;
    setRemoving("batch");
    try {
      for (const d of paths) await api.removeAlbum(d);
      setToast(`Moved ${paths.length} album(s) to trash`);
      clearSelection();
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    } finally {
      setRemoving(null);
    }
  };

  /** Batch LRCLIB lyric download for the selection: skips instrumentals and
   * tracks that already have lyrics; writes per the global lyrics_format. */
  const downloadLyricsSelection = async () => {
    if (!selectionCount) {
      toast("Select albums, artists or tracks first");
      return;
    }
    setLyricsBusy(true);
    try {
      const cfg = await api.config();
      const fmt = String(cfg.lyrics_format ?? "EMBEDDED").toUpperCase();
      const albumSet = new Set(selection.albums);
      const artistSet = new Set(selection.artists);
      const trackSet = new Set(selection.tracks);
      const targets: { track: Track; displayArtist?: string }[] = [
        ...flat.albums
          .filter((al) => albumSet.has(al.path))
          .flatMap((al) => (al.tracks ?? []).map((t) => ({ track: t, displayArtist: al.artist }))),
        ...(lib?.artists ?? [])
          .filter((a) => artistSet.has(a.path))
          .flatMap((a) => a.albums.flatMap((al) => al.tracks.map((t) => ({ track: t, displayArtist: al.album_artist || a.name })))),
        ...flat.tracks.filter((t) => trackSet.has(t.path)).map((t) => ({ track: t as Track, displayArtist: t.artist })),
      ];
      let fetched = 0;
      let skipped = 0;
      let missing = 0;
      let failed = 0;
      for (const { track: t, displayArtist } of targets) {
        if (t.tags.INSTRUMENTAL === "1" || t.lyrics_present) {
          skipped++;
          continue;
        }
        const artist = t.tags.ARTIST || displayArtist || undefined;
        const title = t.tags.TITLE;
        if (!artist || !title) {
          skipped++;
          continue;
        }
        try {
          const res = await api.lyricsGet(artist, title, t.tags.ALBUM || undefined, t.tech?.length ? Math.round(t.tech.length) : undefined);
          const lrc = res?.syncedLyrics ?? res?.plainLyrics;
          if (!lrc) {
            missing++;
          } else {
            if (fmt === "LRC" || fmt === "BOTH") await api.lyricsWrite(t.path, lrc);
            if (fmt === "EMBEDDED" || fmt === "BOTH") await api.lyricsEmbed(t.path, lrc);
            fetched++;
          }
        } catch {
          failed++;
        }
        await new Promise((r) => setTimeout(r, 350)); // LRCLIB rate-limit pacing
      }
      toast(`Lyrics: ${fetched} downloaded · ${skipped} skipped · ${missing} not on LRCLIB${failed ? ` · ${failed} failed` : ""}`);
      if (fetched) {
        clearSelection();
        qc.invalidateQueries({ queryKey: ["library"] });
      }
    } catch (e) {
      toast(String(e));
    } finally {
      setLyricsBusy(false);
    }
  };

  const organizeSelection = async () => {
    if (!selectionAlbumDirs.length) {
      toast("Select albums or artists to organize");
      return;
    }
    if (!window.confirm(`Organize ${selectionAlbumDirs.length} album(s) with the naming script from Settings?\nFiles are MOVED into the scripted folder structure.`)) return;
    try {
      const r = await api.organize(selectionAlbumDirs);
      const moved = r.results.reduce((n: number, x: any) => n + (x.moved ?? 0), 0);
      const errs = r.results.filter((x: any) => x.error);
      if (errs.length) toast(`Organized ${moved} file(s) — ${errs.length} album(s) had errors`);
      else toast(`Organized ${moved} file(s)`);
      clearSelection();
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    }
  };

  const playSelection = () => {
    const out: { path: string; file: string; albumPath: string; artist?: string; album?: string; title?: string }[] = [];
    for (const al of sortedAlbums)
      if (selection.albums.includes(al.path))
        for (const t of al.tracks) out.push({ path: t.path, file: t.file, albumPath: al.path, artist: al.artist, album: al.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined });
    for (const a of sortedArtists)
      if (selection.artists.includes(a.path))
        for (const al of a.albums)
          for (const t of al.tracks) out.push({ path: t.path, file: t.file, albumPath: al.path, artist: al.album_artist || a.name, album: al.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined });
    for (const tr of sortedTracks)
      if (selection.tracks.includes(tr.path))
        out.push({ path: tr.path, file: tr.file, albumPath: tr.path.split("/").slice(0, -1).join("/"), artist: tr.artist, album: tr.album, title: tr.tags.TITLE || undefined });
    if (out.length) playNow(out);
  };

  const runScriptsOnSelection = async (ids: number[], force = false) => {
    if (!selectionAlbumDirs.length) {
      toast("Select albums or artists to run scripts on");
      return;
    }
    try {
      // Same selection the header Force menu configures (Settings → General
      // force toggles keep working independently as saved defaults).
      const forceOpts = force ? forceDict(loadForceSel()) : undefined;
      await api.run(ids, selectionAlbumDirs, forceOpts);
      setToast(`Scripts run on ${selectionAlbumDirs.length} album(s)${force ? " (forced)" : ""}`);
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    }
  };

const toggleExpand = (path: string) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  // Sorting is memoized so typing in the search box / toggling selection
  // doesn't re-sort the whole library on every keystroke.
  const sortedAlbums = useMemo(() => sortRows(filtered.albums, albumSort), [filtered.albums, albumSort]);
  const sortedArtists = useMemo(() => sortRows(filtered.artists, artistSort), [filtered.artists, artistSort]);
  const sortedTracks = useMemo(() => sortRows(filtered.tracks, trackSort), [filtered.tracks, trackSort]);

  // Grid sections: one flat list, or artist-headed groups.
  const gridSections = useMemo(() => {
    if (!groupByArtist) return [{ artist: null as string | null, albums: sortedAlbums }];
    const out: { artist: string | null; albums: FlatAlbum[] }[] = [];
    let cur: string | null = null;
    for (const al of sortedAlbums) {
      if (al.artist !== cur) {
        cur = al.artist;
        out.push({ artist: cur, albums: [] });
      }
      out[out.length - 1].albums.push(al);
    }
    return out;
  }, [sortedAlbums, groupByArtist]);

  const pickGridSize = (s: "s" | "m" | "l") => {
    setGridSize(s);
    try {
      localStorage.setItem("mlo.gridSize", s);
    } catch {
      /* ignore */
    }
  };

  if (error) return <EmptyState title="Backend unreachable" hint={String(error)} />;
  if (isLoading || !lib)
    return (
      <div className="p-4 space-y-4">
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="h-3.5 w-3.5 rounded-full border-2 border-zinc-700 border-t-zinc-400 animate-spin inline-block" />
          Scanning library…
        </div>
        <div className="grid gap-x-4 gap-y-5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(164px, 1fr))" }}>
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="p-2 animate-pulse">
              <div className="aspect-square w-full rounded-xl bg-zinc-800/60" />
              <div className="h-3 w-3/4 rounded bg-zinc-800/60 mt-2.5" />
              <div className="h-2.5 w-1/2 rounded bg-zinc-800/40 mt-1.5" />
            </div>
          ))}
        </div>
      </div>
    );

  const albumRows: ({ kind: "header"; artist: string } | { kind: "album"; album: FlatAlbum })[] = [];
  if (groupByArtist) {
    let current = "";
    for (const al of sortedAlbums) {
      if (al.artist !== current) {
        current = al.artist;
        albumRows.push({ kind: "header", artist: current });
      }
      albumRows.push({ kind: "album", album: al });
    }
  }

  const albumColSpan = 4 + albumCols.length + 1; // play, checkbox, chevron+cover, cols, actions

  const allAlbumsSelected = sortedAlbums.length > 0 && sortedAlbums.every((a) => selection.albums.includes(a.path));
  const allArtistsSelected = sortedArtists.length > 0 && sortedArtists.every((a) => selection.artists.includes(a.path));
  const allTracksSelected = sortedTracks.length > 0 && sortedTracks.every((t) => selection.tracks.includes(t.path));

  return (
    <div className="p-4 space-y-3">
      {/* toolbar — search lives in the top bar now (same store query) */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex rounded-md border border-border overflow-hidden">
          {VIEW_TABS.map((v) => (
            <button
              key={v.id}
              onClick={() => setView(v.id)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                view === v.id ? "bg-accent on-accent" : "bg-panel text-zinc-400 hover:text-white"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>

        {(view === "albums" || view === "compact" || view === "grid") && (
          <>
            <select
              className="input !w-auto text-xs"
              value={albumSort?.key ?? ""}
              onChange={(e) => setAlbumSort(e.target.value)}
              title="Sort albums"
            >
              <option value="">Sort…</option>
              {ALBUM_SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label} {albumSort?.key === s.key ? (albumSort.dir === 1 ? "↑" : "↓") : ""}
                </option>
              ))}
            </select>
            {view === "grid" && (
              <div className="flex rounded-md border border-border overflow-hidden" title="Cover size">
                {(["s", "m", "l"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => pickGridSize(s)}
                    className={`px-2.5 py-1.5 text-xs font-medium uppercase transition-colors ${
                      gridSize === s ? "bg-accent on-accent" : "bg-panel text-zinc-400 hover:text-white"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            {(view === "albums" || view === "grid") && (
              <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none" title="Group albums under artist headers">
                <input type="checkbox" checked={groupByArtist} onChange={(e) => setGroupByArtist(e.target.checked)} className="" />
                Group by artist
              </label>
            )}
          </>
        )}

        {view !== "compact" && view !== "grid" && (
          <ColumnsMenu
            cols={view === "albums" ? ALBUM_COLS : view === "artists" ? ARTIST_COLS : TRACK_COLS}
            visible={view === "albums" ? albumCols : view === "artists" ? artistCols : trackCols}
            onToggle={view === "albums" ? toggleAlbumCol : view === "artists" ? toggleArtistCol : toggleTrackCol}
            fullDates={fullDates}
            onFullDates={setFullDates}
          />
        )}
        <button
          className="btn-ghost !py-1 text-xs"
          onClick={() => setStatsOpen(true)}
          title={selectionCount ? "Statistics for the current selection" : "Library-wide statistics"}
        >
          <BarChart3 className="h-3.5 w-3.5" /> Stats
        </button>

        <span className="text-xs text-zinc-500 whitespace-nowrap">
          {sortedAlbums.length} albums · {sortedTracks.length} tracks
        </span>
        {folder && (
          <span className="hidden xl:flex text-xs text-zinc-600 items-center gap-1">
            <FolderOpen className="h-3 w-3" /> {folder}
          </span>
        )}
      </div>

      {/* quick filter — one dropdown instead of a chip row */}
      <div className="relative w-fit">
        <button
          className="btn-ghost !py-1 text-xs"
          onClick={() => setFilterOpen(!filterOpen)}
          title="Filter the library"
        >
          <ListFilter className="h-3.5 w-3.5" />
          {PRESETS.find((p) => p.id === preset)?.label}
          <span className="text-zinc-600 font-mono">{presetCounts[preset] ?? ""}</span>
        </button>
        {filterOpen && (
          <>
            <div className="fixed inset-0 z-20" onClick={() => setFilterOpen(false)} />
            <div className="absolute left-0 top-full mt-1 z-30 w-52 rounded-lg border border-border bg-zinc-950 shadow-xl p-1">
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => {
                    setPreset(p.id);
                    setFilterOpen(false);
                  }}
                  className={`w-full text-left px-2.5 py-1.5 rounded-md text-xs flex items-center justify-between gap-3 ${
                    preset === p.id ? "bg-raise text-white" : "text-zinc-400 hover:text-white hover:bg-raise"
                  }`}
                >
                  <span>{p.label}</span>
                  <span className="text-zinc-600 font-mono">{presetCounts[p.id] ?? 0}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {/* selection toolbar */}
      {selectionCount > 0 && (
        <div className="flex items-center gap-2 bg-accent/15 border border-accent/40 rounded-lg px-3 py-2 flex-wrap">
          <span className="text-xs font-medium text-accent-soft">
            {selection.albums.length} album{selection.albums.length === 1 ? "" : "s"} · {selection.artists.length} artist{selection.artists.length === 1 ? "" : "s"} · {selection.tracks.length} track{selection.tracks.length === 1 ? "" : "s"} · {selTracks.size} total tracks
          </span>
          <div className="ml-auto flex gap-1.5 flex-wrap">
            <button className="btn-primary !py-1 text-xs" onClick={playSelection}>
              <Play className="h-3.5 w-3.5" /> Play
            </button>
            <button className="btn-ghost !py-1 text-xs" onClick={() => addToPlaylist([...selTracks])}>
              <ListPlus className="h-3.5 w-3.5" /> Playlist
            </button>
            <button
              className="btn-danger !py-1 text-xs"
              onClick={() => removeAlbums(selectionAlbumDirs)}
              disabled={removing === "batch" || !selectionAlbumDirs.length}
              title={selectionAlbumDirs.length ? "Move selected albums to trash" : "Select albums or artists to remove"}
              hidden={!selection.albums.length && !selection.artists.length}
            >
              <Trash2 className="h-3.5 w-3.5" /> Remove
            </button>
            <ScriptsDropdown onRun={runScriptsOnSelection} runAllIds={runAllIds} />
            <button
              className="btn-ghost !py-1 text-xs"
              onClick={downloadLyricsSelection}
              disabled={lyricsBusy}
              title="Download missing lyrics from LRCLIB for the selection (skips instrumentals)"
            >
              <CloudDownload className="h-3.5 w-3.5" /> {lyricsBusy ? "Fetching…" : "Lyrics"}
            </button>
            <button
              className="btn-ghost !py-1 text-xs"
              onClick={organizeSelection}
              disabled={removing === "batch" || !selectionAlbumDirs.length}
              title="Apply the naming script from Settings"
            >
              <FolderSync className="h-3.5 w-3.5" /> Organize
            </button>
            <button className="btn-ghost !py-1 text-xs" onClick={clearSelection}>
              Clear
            </button>
          </div>
        </div>
      )}

      {sortedAlbums.length === 0 && (
        <EmptyState title="Nothing matches" hint="Set the music folder in Settings, import an album, or clear the search/filters." />
      )}

      {statsOpen && (
        <StatsPanel
          title={
            selectionCount
              ? `${selTracks.size} selected track${selTracks.size === 1 ? "" : "s"}`
              : "whole library"
          }
          albums={selectionCount ? flat.albums.filter((a) => selectionAlbumDirs.includes(a.path)) : flat.albums}
          tracks={selectionCount ? flat.tracks.filter((t) => selTracks.has(t.path)) : flat.tracks}
          onClose={() => setStatsOpen(false)}
        />
      )}


      {detailTrack && (
        <TrackDetails track={detailTrack.track} albumPath={detailTrack.albumPath} onClose={() => setDetailTrack(null)} />
      )}

      {/* ---------------- Grid browse view (Apple Music style, default) ---------------- */}
      {view === "grid" && (
        <div>
          <div
            className="grid gap-x-4 gap-y-5"
            style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${GRID_SIZE_MIN[gridSize]}px, 1fr))` }}
          >
            {gridSections.map((sec) => (
              <Fragment key={sec.artist ?? "all"}>
                {sec.artist !== null && (
                  <div className="col-span-full mt-3 first:mt-0">
                    <div className="text-sm font-bold uppercase tracking-wider text-zinc-300">{sec.artist}</div>
                    <div className="h-px bg-border mt-1" />
                  </div>
                )}
                {sec.albums.map((al) => {
                  const sel = selection.albums.includes(al.path);
                  return (
                    <AlbumCard
                      key={al.path}
                      al={al}
                      selectable
                      selected={sel}
                      onSelect={toggleAlbum}
                    />
                  );
                })}
              </Fragment>
            ))}
          </div>
          <div className="h-2" />
        </div>
      )}

      {/* ---------------- Compact status view ---------------- */}
      {view === "compact" && (
        <div className="space-y-1">
          <div className="flex gap-4 flex-wrap text-[10px] text-zinc-600 items-center pb-1">
            <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-emerald-600/60 inline-block" /> PASS — graded clean, audit OK</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-red-500/70 inline-block" /> FAIL — grading / audit problems (hover a row for details)</span>
          </div>
          {sortedAlbums.map((al) => {
            const st = statusFor(!!al.pass, al.audit_summary);
            const sel = selection.albums.includes(al.path);
            const isExp = expanded.has(al.path);
            const tracks = [...(al.tracks ?? [])].sort((a, b) =>
              (a.discnumber ?? 99) - (b.discnumber ?? 99) ||
              (a.tracknumber ?? 999) - (b.tracknumber ?? 999) ||
              String(a.file).localeCompare(String(b.file))
            );
            return (
              <div key={al.path}>
                <div
                  className={`group flex items-center gap-2.5 rounded-md border px-2 py-1.5 cursor-pointer transition-colors ${st.tint} ${sel ? "border-accent/50" : "border-transparent hover:border-border"}`}
                  onClick={() => toggleExpand(al.path)}
                >
                  <button
                    className="btn-ghost !px-1.5 !py-0.5 opacity-0 group-hover:opacity-100 shrink-0 transition-opacity"
                    title="Play album"
                    onClick={(e) => {
                      e.stopPropagation();
                      useStore.getState().playNow(
                        tracks.map((t) => ({
                          path: t.path, file: t.file, albumPath: al.path,
                          artist: al.artist, album: al.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
                        }))
                      );
                    }}
                  >
                    <Play className="h-3.5 w-3.5" />
                  </button>
                  <div className={`w-1 self-stretch rounded-sm ${st.edge} shrink-0`} title={st.label} />
                  <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={sel} onChange={() => toggleAlbum(al.path)} />
                  </div>
                  <Link
                    to={albumRef(al)}
                    onClick={(e) => e.stopPropagation()}
                    className="shrink-0"
                    title="Open album page"
                  >
                    <CoverImg
                      albumPath={al.path}
                      coverFile={al.cover_file}
                      wrapperClass="h-9 w-9 rounded bg-raise border border-border overflow-hidden shrink-0"
                    />
                  </Link>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 min-w-0">
                      <Link
                        to={albumRef(al)}
                        onClick={(e) => e.stopPropagation()}
                        className="text-sm font-medium truncate hover:text-accent-soft"
                        title={al.meta?.ALBUM ?? al.path}
                      >
                        {al.meta?.ALBUM ?? al.path.split("/").pop()}
                      </Link>
                      <span className="text-[11px] text-zinc-500 truncate">
                        {al.artist}
                        {al.meta?.DATE ? ` · ${String(al.meta.DATE).slice(0, 4)}` : ""}
                        {al.meta?.ORIGINALDATE && String(al.meta.ORIGINALDATE).slice(0, 4) !== String(al.meta?.DATE ?? "").slice(0, 4)
                          ? ` (orig. ${String(al.meta.ORIGINALDATE).slice(0, 4)})` : ""}
                      </span>
                    </div>
                  </div>
                  <span className={`text-[9px] font-mono shrink-0 ${st.text}`} title={st.label}>
                    {st.key === "fail" ? gradeSliver(!!al.pass, al.audit_summary) : ""}
                  </span>
                  <span className="text-[10px] text-zinc-600 shrink-0 w-8 text-right">{al.track_count}t</span>
                  <div className="opacity-0 group-hover:opacity-100 flex gap-1 shrink-0 transition-opacity" onClick={(e) => e.stopPropagation()}>
                    <button className="btn-ghost !px-1.5 !py-0.5" title={isExp ? "Collapse" : "Show tracks"}>
                      {isExp ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
                {isExp && (
                  <div className="ml-8 border-l border-border pl-3 py-1 space-y-0.5">
                    {tracks.map((t) => {
                      const ts = statusFor(!!t.grade_pass, t.audit);
                      const tSel = selection.tracks.includes(t.path);
                      return (
                        <div key={t.path} className={`group flex items-center gap-2 text-xs py-0.5 rounded ${tSel ? "bg-accent/10" : ""}`}>
                          <button
                            className="btn-ghost !px-1 !py-0.5 opacity-0 group-hover:opacity-100 shrink-0 transition-opacity"
                            title="Play from here"
                            onClick={() =>
                              useStore.getState().playNow(
                                tracks.map((x) => ({
                                  path: x.path, file: x.file, albumPath: al.path,
                                  artist: al.artist, album: al.meta?.ALBUM ?? undefined, title: x.tags.TITLE || undefined,
                                })),
                                tracks.findIndex((x) => x.path === t.path)
                              )
                            }
                          >
                            <Play className="h-3 w-3" />
                          </button>
                          <div className="shrink-0">
                            <input type="checkbox" checked={tSel} onChange={() => toggleTrack(t.path)} />
                          </div>
                          <span className={`h-3 w-1 rounded-sm ${ts.edge} shrink-0`} title={ts.label} />
                          <span className="w-8 text-right text-zinc-600 font-mono shrink-0">{t.tracknumber ?? t.tags.TRACKNUMBER ?? "—"}</span>
                          <Link to={trackRef(t)} className="truncate hover:text-accent-soft flex-1 min-w-0">
                            {t.tags.TITLE ?? t.file}
                          </Link>
                          <FavHeart kind="track" id={t.path} mbid={t.tags.MUSICBRAINZ_TRACKID} iconClass="h-3.5 w-3.5" className="opacity-0 group-hover:opacity-100 transition-opacity" />
                          {t.tags.INSTRUMENTAL === "1" && (
                            <span className="chip bg-zinc-800 text-zinc-400 border border-border text-[9px] shrink-0">INST</span>
                          )}
                          {!!t.issues?.length && (
                            <button
                              className="text-[9px] text-red-400/70 shrink-0 hover:underline"
                              title={t.issues.join("\n")}
                              onClick={() => setDetailTrack({ track: t, albumPath: al.path })}
                            >
                              {t.issues.length}✗
                            </button>
                          )}
                          <span className={`text-[9px] font-mono shrink-0 ${ts.text}`} title={ts.label}>
                            {ts.key === "fail" ? gradeSliver(!!t.grade_pass, t.audit) : ""}
                          </span>
                          <span className="text-[10px] text-zinc-600 font-mono w-10 text-right shrink-0">{fmtDuration(t.tech.length)}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ---------------- Albums table ---------------- */}
      {view === "albums" && (
        <div className="bg-card rounded-lg border border-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-panel/60">
                <tr>
                  <th className="th w-8">
                    <input type="checkbox" className="" checked={allAlbumsSelected}
                      onChange={() => setSelection({ albums: allAlbumsSelected ? [] : sortedAlbums.map((a) => a.path) })} />
                  </th>
                  <th className="th w-8"></th>
                  <th className="th w-12"></th>
                  {ALBUM_COLS.filter((c) => albumCols.includes(c.id)).map((c) => (
                    <SortHeader key={c.id} label={c.label} sort={albumSort} sortKey={c.sortKey} onSort={setAlbumSort} />
                  ))}
                  <th className="th text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(groupByArtist ? albumRows : sortedAlbums.map((al) => ({ kind: "album" as const, album: al }))).map((row) =>
                  row.kind === "header" ? (
                    <tr key={`h-${row.artist}`} className="bg-panel/70">
                      <td colSpan={albumColSpan} className="px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-zinc-300">
                        {row.artist}
                      </td>
                    </tr>
                  ) : (
<AlbumRowGroup
                      key={row.album.path}
                      album={row.album}
                      expanded={expanded.has(row.album.path)}
                      onToggle={() => toggleExpand(row.album.path)}
                      visibleCols={albumCols}
                      selected={selection.albums.includes(row.album.path)}
                      onToggleSel={() => toggleAlbum(row.album.path)}
                      selTracks={selTracks}
                      onToggleTrack={toggleTrack}
                      removing={removing !== null}
                      onRemove={() => removeAlbums([row.album.path])}
                      onPlaylist={() => addToPlaylist(row.album.tracks.map((t) => t.path))}
                      onTrackDetails={(t) => setDetailTrack({ track: t, albumPath: row.album.path })}
                      colSpan={albumColSpan}
                      fullDates={fullDates}
                    />
                  )
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ---------------- Artists table ---------------- */}
      {view === "artists" && (
        <div className="bg-card rounded-lg border border-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-panel/60">
                <tr>
                  <th className="th w-12" title="Play all"></th>
                  <th className="th w-8">
                    <input type="checkbox" className="" checked={allArtistsSelected}
                      onChange={() => setSelection({ artists: allArtistsSelected ? [] : sortedArtists.map((a) => a.path) })} />
                  </th>
                  {ARTIST_COLS.filter((c) => artistCols.includes(c.id)).map((c) => (
                    <SortHeader key={c.id} label={c.label} sort={artistSort} sortKey={c.sortKey} onSort={setArtistSort} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedArtists.map((a) => {
                  const all = a.albums.flatMap((al) =>
                    al.tracks.map((t) => ({
                      path: t.path, file: t.file, albumPath: al.path,
                      artist: al.album_artist || a.name, album: al.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
                    }))
                  );
                  const sel = selection.artists.includes(a.path);
                  return (
                    <tr key={a.path} className={`table-row group ${sel ? "bg-accent/15" : ""}`}>
                      <td className="td">
                        <button className="btn-ghost !px-1.5 !py-1 opacity-0 group-hover:opacity-100 transition-opacity" title="Play all" onClick={() => playNow(all)}>
                          <Play className="h-3.5 w-3.5" />
                        </button>
                      </td>
                      <td className="td pr-0">
                        <input type="checkbox" className="" checked={sel} onChange={() => toggleArtist(a.path)} />
                      </td>
                      <td className="td">
                        <Link to={artistRef(a)} className="font-medium hover:text-accent-soft">
                          {a.name}
                        </Link>
                      </td>
                      {artistCols.includes("albums") && <td className="td text-zinc-500">{a.aggregate.album_count}</td>}
                      {artistCols.includes("tracks") && <td className="td text-zinc-500">{a.aggregate.track_count}</td>}
                      {artistCols.includes("checks") && (
                        <td className="td text-zinc-500">{a.aggregate.pass_count}/{a.aggregate.total_checks}</td>
                      )}
                      {artistCols.includes("grade") && (
                        <td className="td"><GradeBadge pass={(a.aggregate.grade_pct ?? 0) >= 100} score={a.aggregate.grade_pct} audit={a.aggregate.audit_summary} /></td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ---------------- Tracks table ---------------- */}
      {view === "tracks" && (
        <div className="bg-card rounded-lg border border-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-panel/60">
                <tr>
                  <th className="th w-12" title="Play"></th>
                  <th className="th w-8">
                    <input type="checkbox" className="" checked={allTracksSelected}
                      onChange={() => setSelection({ tracks: allTracksSelected ? [] : sortedTracks.map((t) => t.path) })} />
                  </th>
                  {TRACK_COLS.filter((c) => trackCols.includes(c.id)).map((c) => (
                    <SortHeader key={c.id} label={c.label} sort={trackSort} sortKey={c.sortKey} onSort={setTrackSort} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedTracks.map((tr) => {
                  const sel = selection.tracks.includes(tr.path);
                  return (
                    <tr
                      key={tr.path}
                      className={`table-row group cursor-pointer ${sel ? "bg-accent/15" : ""}`}
                      title="Click to play"
                      onClick={() =>
                        playNow(
                          sortedTracks.map((t) => ({ path: t.path, file: t.file, albumPath: t.path.split("/").slice(0, -1).join("/"), artist: t.artist, album: t.album, title: t.tags.TITLE || undefined })),
                          sortedTracks.findIndex((t) => t.path === tr.path)
                        )
                      }
                    >
                      <td className="td" onClick={(e) => e.stopPropagation()}>
                        <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            className="btn-ghost !px-1.5 !py-1"
                            title="Play"
                            onClick={() =>
                              playNow(
                                sortedTracks.map((t) => ({ path: t.path, file: t.file, albumPath: t.path.split("/").slice(0, -1).join("/"), artist: t.artist, album: t.album, title: t.tags.TITLE || undefined })),
                                sortedTracks.findIndex((t) => t.path === tr.path)
                              )
                            }
                          >
                            <Play className="h-3.5 w-3.5" />
                          </button>
                          <button className="btn-ghost !px-1.5 !py-1" title="Add to playlist" onClick={() => addToPlaylist([tr.path])}>
                            <ListPlus className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                      <td className="td pr-0" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" className="" checked={sel} onChange={() => toggleTrack(tr.path)} />
                      </td>
                      {trackCols.includes("num") && <td className="td text-zinc-600">{tr.tracknumber ?? tr.tags.TRACKNUMBER ?? "—"}</td>}
                      {trackCols.includes("title") && (
                        <td className="td max-w-[260px]">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <Link
                              to={trackRef(tr)}
                              className="hover:text-accent-soft truncate inline-block max-w-full"
                              title="Click to play · Ctrl-click to open track page"
                              onClick={(e) => {
                                // plain click plays (row handler); Ctrl/Shift/middle opens the page
                                if (e.ctrlKey || e.metaKey || e.shiftKey) e.stopPropagation();
                                else e.preventDefault();
                              }}
                            >
                              {tr.tags.TITLE ?? tr.file}
                            </Link>
                            <span className="opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                              <FavHeart kind="track" id={tr.path} mbid={tr.tags.MUSICBRAINZ_TRACKID} iconClass="h-3.5 w-3.5" />
                            </span>
                            <button
                              className="text-zinc-500 hover:text-accent-soft shrink-0"
                              title="Grading & audit details"
                              onClick={(e) => {
                                e.stopPropagation();
                                setDetailTrack({ track: tr, albumPath: tr.path.split("/").slice(0, -1).join("/") });
                              }}
                            >
                              <InfoIcon className="h-3.5 w-3.5" />
                            </button>
                            {tr.tags.INSTRUMENTAL === "1" && (
                              <span className="chip bg-zinc-800 text-zinc-400 border border-border text-[10px] shrink-0">INST</span>
                            )}
                          </div>
                        </td>
                      )}
                      {trackCols.includes("artist") && <td className="td text-zinc-400 truncate max-w-[160px]">{tr.artist}</td>}
                      {trackCols.includes("album") && <td className="td text-zinc-500 truncate max-w-[160px]">{tr.album}</td>}
                      {trackCols.includes("year") && <td className="td text-zinc-500" title={tr.tags.DATE ?? undefined}>{fmtDateCell(tr.tags.DATE, fullDates)}</td>}
                      {trackCols.includes("genre") && <td className="td text-zinc-500 truncate max-w-[130px]">{tr.tags.GENRE ?? "—"}</td>}
                      {trackCols.includes("media") && <td className="td"><MediaChip media={tr.tags.MEDIA} /></td>}
                      {trackCols.includes("grade") && <td className="td"><GradeBadge pass={!!tr.grade_pass && !auditFails(tr.audit)} score={null} audit={tr.audit} size="sm" /></td>}
                      {trackCols.includes("advisory") && <td className="td"><AdvisoryBadge value={tr.tags.ITUNESADVISORY} /></td>}
                      {trackCols.includes("duration") && <td className="td text-zinc-500">{fmtDuration(tr.tech.length)}</td>}
                      {trackCols.includes("bitrate") && <td className="td text-zinc-500">{tr.tech.bitrate ? `${tr.tech.codec ? tr.tech.codec + " · " : ""}${Math.round(tr.tech.bitrate / 1000)}k` : "—"}</td>}
                      {trackCols.includes("source") && <td className="td text-zinc-500 truncate max-w-[100px]">{tr.tags.SOURCE ?? "—"}</td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function AlbumRowGroup({
  album,
  expanded,
  onToggle,
  visibleCols,
  selected,
  onToggleSel,
  selTracks,
  onToggleTrack,
  removing,
  onRemove,
  onPlaylist,
  onTrackDetails,
  colSpan,
  fullDates,
}: {
  album: FlatAlbum;
  expanded: boolean;
  onToggle: () => void;
  visibleCols: string[];
  selected: boolean;
  onToggleSel: () => void;
  selTracks: Set<string>;
  onToggleTrack: (p: string) => void;
  removing: boolean;
  onRemove: () => void;
  onPlaylist: () => void;
  onTrackDetails: (t: Track) => void;
  colSpan: number;
  fullDates: boolean;
}) {
  const tracks = [...(album.tracks ?? [])].sort((a, b) =>
    (a.discnumber ?? 99) - (b.discnumber ?? 99) ||
    (a.tracknumber ?? 999) - (b.tracknumber ?? 999) ||
    String(a.file).localeCompare(String(b.file))
  );

  return (
    <>
      <tr className={`table-row group ${selected ? "bg-accent/15" : ""}`} onClick={onToggle}>
        <td className="td" onClick={(e) => e.stopPropagation()}>
          <button
            className="btn-ghost !px-1.5 !py-1 opacity-0 group-hover:opacity-100 transition-opacity"
            title="Play album"
            onClick={() =>
              useStore.getState().playNow(
                tracks.map((t) => ({
                  path: t.path, file: t.file, albumPath: album.path,
                  artist: album.artist, album: album.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
                }))
              )
            }
          >
            <Play className="h-3.5 w-3.5" />
          </button>
        </td>
        <td className="td pr-0" onClick={(e) => e.stopPropagation()}>
          <input type="checkbox" className="" checked={selected} onChange={onToggleSel} />
        </td>
        <td className="td pr-0">
          <button className="p-1 text-zinc-500 hover:text-white" onClick={(e) => { e.stopPropagation(); onToggle(); }}>
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        </td>
        <td className="td">
          <Link
            to={albumRef(album)}
            onClick={(e) => e.stopPropagation()}
            title="Open album page"
            className="inline-block"
          >
            <CoverImg albumPath={album.path} coverFile={album.cover_file} />
          </Link>
        </td>
        {visibleCols.includes("album") && (
          <td className="td max-w-[280px]">
            <Link
              to={albumRef(album)}
              onClick={(e) => e.stopPropagation()}
              className="font-medium hover:text-accent-soft truncate inline-block max-w-full"
            >
              {album.meta?.ALBUM ?? album.path.split("/").pop()}
            </Link>
          </td>
        )}
        {visibleCols.includes("artist") && <td className="td text-zinc-400 truncate max-w-[200px]">{album.artist}</td>}
        {visibleCols.includes("year") && (
                    <td className="td text-zinc-500" title={album.meta?.DATE ?? undefined}>{fmtDateCell(album.meta?.DATE, fullDates)}</td>
                  )}
        {visibleCols.includes("tracks") && <td className="td text-zinc-500">{album.track_count}</td>}
        {visibleCols.includes("grade") && (
          <td className="td">
            <GradeBadge pass={!!album.pass && !auditFails(album.audit_summary)} score={album.grade_pct} audit={album.audit_summary} />
          </td>
        )}
        {visibleCols.includes("media") && <td className="td"><MediaChip media={album.media} /></td>}
        {visibleCols.includes("source") && <td className="td text-zinc-500 truncate max-w-[100px]">{album.source_summary ?? "—"}</td>}
        <td className="td text-right">
          <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
            <button
              className="btn-ghost !px-1.5 !py-1"
              title="Play album"
              onClick={() =>
                useStore.getState().playNow(
                  tracks.map((t) => ({
                    path: t.path, file: t.file, albumPath: album.path,
                    artist: album.artist, album: album.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
                  }))
                )
              }
            >
              <Play className="h-3.5 w-3.5" />
            </button>
            <button className="btn-ghost !px-1.5 !py-1" title="Add to playlist" onClick={onPlaylist}>
              <ListPlus className="h-3.5 w-3.5" />
            </button>
            <button className="btn-danger !px-1.5 !py-1" title="Remove album (to trash)" disabled={removing} onClick={onRemove}>
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-panel/30">
          <td colSpan={colSpan} className="p-0">
            <table className="w-full">
              <thead className="bg-panel/60">
                <tr>
                  <th className="th w-12" title="Play from here"></th>
                  <th className="th w-8"></th>
                  <th className="th w-10">#</th>
                  <th className="th w-10"></th>
                  <th className="th">Title</th>
                  <th className="th">Genre</th>
                  <th className="th">Grade</th>
                  <th className="th">Advisory</th>
                  <th className="th">Dur</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const groups = groupByDisc(tracks);
                  const multiDisc = groups.length > 1;
                  return groups.map((g) => (
                    <Fragment key={g.disc ?? 0}>
                      {multiDisc && (
                        <tr className="bg-panel/60">
                          <td colSpan={9} className="td text-[10px] uppercase tracking-wider text-zinc-500">
                            Disc {g.disc ?? "?"}
                          </td>
                        </tr>
                      )}
                      {g.tracks.map((t) => (
                  <tr
                    key={t.path}
                    className={`table-row group cursor-pointer ${selTracks.has(t.path) ? "bg-accent/15" : ""}`}
                    title="Click to play"
                    onClick={() =>
                      useStore.getState().playNow(
                        tracks.map((x) => ({
                          path: x.path, file: x.file, albumPath: album.path,
                          artist: album.artist, album: album.meta?.ALBUM ?? undefined, title: x.tags.TITLE || undefined,
                        })),
                        tracks.findIndex((x) => x.path === t.path)
                      )
                    }
                  >
                    <td className="td" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="btn-ghost !px-1.5 !py-1 opacity-0 group-hover:opacity-100 transition-opacity"
                        title="Play from here"
                        onClick={() =>
                          useStore.getState().playNow(
                            tracks.map((x) => ({
                              path: x.path, file: x.file, albumPath: album.path,
                              artist: album.artist, album: album.meta?.ALBUM ?? undefined, title: x.tags.TITLE || undefined,
                            })),
                            tracks.findIndex((x) => x.path === t.path)
                          )
                        }
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                    </td>
                    <td className="td pr-0" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" className="" checked={selTracks.has(t.path)} onChange={() => onToggleTrack(t.path)} />
                    </td>
                    <td className="td text-zinc-600">{t.tracknumber ?? t.tags.TRACKNUMBER ?? "—"}</td>
                    <td className="td pr-0">
                      {t.cover_file && (
                        <CoverImg
                          albumPath={album.path}
                          coverFile={t.cover_file}
                          wrapperClass="h-7 w-7 rounded bg-raise border border-border overflow-hidden shrink-0"
                        />
                      )}
                    </td>
                    <td className="td max-w-[300px]">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <Link
                          to={trackRef(t)}
                          className="hover:text-accent-soft truncate inline-block max-w-full"
                          title="Click to play · Ctrl-click to open track page"
                          onClick={(e) => {
                            if (e.ctrlKey || e.metaKey || e.shiftKey) e.stopPropagation();
                            else e.preventDefault();
                          }}
                        >
                          {t.tags.TITLE ?? t.file}
                        </Link>
                        <span className="opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                          <FavHeart kind="track" id={t.path} mbid={t.tags.MUSICBRAINZ_TRACKID} iconClass="h-3.5 w-3.5" />
                        </span>
                        <button
                          className="text-zinc-500 hover:text-accent-soft shrink-0"
                          title="Grading & audit details"
                          onClick={(e) => {
                            e.stopPropagation();
                            onTrackDetails(t);
                          }}
                        >
                          <InfoIcon className="h-3.5 w-3.5" />
                        </button>
                        {t.tags.INSTRUMENTAL === "1" && (
                          <span className="chip bg-zinc-800 text-zinc-400 border border-border text-[10px] shrink-0">INST</span>
                        )}
                        {!!t.issues?.length && (
                          <button
                            className="text-[9px] text-red-400/70 shrink-0 hover:underline"
                            title={t.issues.join("\n")}
                            onClick={(e) => {
                              e.stopPropagation();
                              onTrackDetails(t);
                            }}
                          >
                            {t.issues.length}✗
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="td text-zinc-500 truncate max-w-[150px]">{t.tags.GENRE ?? "—"}</td>
                    <td className="td"><GradeBadge pass={!!t.grade_pass && !auditFails(t.audit)} audit={t.audit} size="sm" /></td>
                    <td className="td"><AdvisoryBadge value={t.tags.ITUNESADVISORY} /></td>
                    <td className="td text-zinc-500">{fmtDuration(t.tech.length)}</td>
                  </tr>
                      ))}
                    </Fragment>
                  ));
                })()}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  );
}

function ScriptsDropdown({ onRun, runAllIds }: { onRun: (ids: number[], force?: boolean) => void; runAllIds: number[] }) {
  const [open, setOpen] = useState(false);
  const items: { ids: number[]; label: string; force?: boolean }[] = [
    { ids: runAllIds, label: "Run all" },
    { ids: runAllIds, label: "Run all (force)", force: true },
    ...SCRIPTS,
  ];
  return (
    <div className="relative">
      <button className="btn-ghost !py-1 text-xs" onClick={() => setOpen(!open)}>
        <Wand2 className="h-3.5 w-3.5" /> Scripts
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-lg p-1.5 w-44 shadow-2xl">
            {items.map((s) => (
              <button
                key={s.label}
                className={`w-full text-left px-2.5 py-1.5 text-xs rounded hover:bg-panel ${s.force ? "text-accent-soft" : "text-zinc-300"} hover:text-white`}
                onClick={() => {
                  setOpen(false);
                  onRun(s.ids, s.force);
                }}
              >
                {s.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function ColumnsMenu({
  cols,
  visible,
  onToggle,
  fullDates,
  onFullDates,
}: {
  cols: Col[];
  visible: string[];
  onToggle: (id: string) => void;
  fullDates?: boolean;
  onFullDates?: (v: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button className={`btn-ghost text-xs ${open ? "!text-white !bg-raise" : ""}`} onClick={() => setOpen(!open)}>
        <Columns3 className="h-3.5 w-3.5" /> Columns
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-lg p-2 w-48 shadow-2xl">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-2 pt-1 pb-1.5">Visible columns</div>
            {cols.map((c) => (
              <label key={c.id} className="flex items-center gap-2 px-2 py-1.5 text-xs cursor-pointer hover:bg-panel rounded">
                <input type="checkbox" checked={visible.includes(c.id)} onChange={() => onToggle(c.id)} className="" />
                {c.label}
              </label>
            ))}
            {onFullDates && (
              <>
                <div className="border-t border-border my-1.5" />
                <label className="flex items-center gap-2 px-2 py-1.5 text-xs cursor-pointer hover:bg-panel rounded">
                  <input type="checkbox" checked={!!fullDates} onChange={(e) => onFullDates(e.target.checked)} />
                  Show full dates
                </label>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function useColumnPrefs(key: string, defs: Col[]): [string[], (id: string) => void] {
  const storageKey = `mlo-cols-${key}`;
  const [visible, setVisible] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const arr = JSON.parse(raw) as string[];
        const ids = new Set(defs.map((d) => d.id));
        const kept = arr.filter((x) => ids.has(x));
        if (kept.length) return kept;
      }
    } catch {
      /* fall through to defaults */
    }
    return defs.map((d) => d.id);
  });
  const toggle = (id: string) =>
    setVisible((v) => {
      const next = v.includes(id) ? v.filter((x) => x !== id) : [...v, id];
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  return [visible, toggle];
}

/** Year by default ("2010-12-15" -> "2010"); full value when the user
 *  enables Show full dates. The raw date is always the tooltip. */
export function fmtDateCell(value: string | null | undefined, full: boolean): string {
  if (!value) return "—";
  if (full) return value;
  const m = String(value).match(/^(\d{4})/);
  return m ? m[1] : value;
}

function useLocalPref(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const storageKey = `mlo-pref-${key}`;
  const [value, setValue] = useState<boolean>(() => {
    try {
      return localStorage.getItem(storageKey) === "1";
    } catch {
      return initial;
    }
  });
  const set = (v: boolean) => {
    setValue(v);
    try {
      localStorage.setItem(storageKey, v ? "1" : "0");
    } catch {
      /* ignore */
    }
  };
  return [value, set];
}

export function fmtDuration(sec: number | undefined): string {
  if (sec === undefined || Number.isNaN(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function useLocalSort(key: string): [SortState | null, (key: string) => void] {
  const { sort, setSort } = useStore();
  const cur = sort && sort.key.startsWith(`${key}:`) ? { key: sort.key.slice(key.length + 1), dir: sort.dir } : null;
  const set = (k: string) => {
    const dir = cur?.key === k ? (cur.dir === 1 ? -1 : 1) : 1;
    setSort({ key: `${key}:${k}`, dir });
  };
  return [cur, set];
}