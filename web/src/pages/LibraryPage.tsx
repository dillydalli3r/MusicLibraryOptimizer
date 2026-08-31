import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Search, FolderOpen, ListPlus, Play, Trash2, ChevronRight, ChevronDown, Columns3, Wand2, FolderSync, BarChart3, Tags as TagsIcon,
} from "lucide-react";
import { api } from "../api";
import { toast, useStore } from "../store";
import { sortRows, SortHeader, type SortState } from "../lib/sort.tsx";
import { AuditBadge, EmptyState, GradeBadge, MediaChip, AdvisoryBadge } from "../components/Badges";
import CoverImg from "../components/CoverImg";
import StatsPanel from "../components/StatsPanel";
import BatchTagEditor from "../components/BatchTagEditor";
import type { Album, Artist, Track } from "../types";

type View = "albums" | "artists" | "tracks";

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
  { id: "albums", label: "Albums" },
  { id: "artists", label: "Artists" },
  { id: "tracks", label: "Tracks" },
];

const ALBUM_SORTS = [
  { key: "meta.ALBUM", label: "Album name" },
  { key: "artist", label: "Artist" },
  { key: "meta.DATE", label: "Year" },
  { key: "track_count", label: "Tracks" },
  { key: "grade_pct", label: "Grade" },
  { key: "audit_summary", label: "Audit" },
];

const SCRIPTS: { ids: number[]; label: string }[] = [
  { ids: [1, 2, 8, 3, 5, 9, 6, 4, 7, 10], label: "Run all" },
  { ids: [1], label: "Format lyrics" },
  { ids: [2], label: "Format CUEs" },
  { ids: [3], label: "Optimize FLACs" },
  { ids: [5], label: "Process images" },
  { ids: [6], label: "Audit library" },
  { ids: [7], label: "DR & ReplayGain" },
  { ids: [8], label: "Auto tagging" },
  { ids: [4], label: "Grade" },
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
  { id: "audit", label: "Audit", sortKey: "audit_summary" },
  { id: "media", label: "Media", sortKey: "media" },
  { id: "source", label: "Source", sortKey: "source_summary" },
];

const ARTIST_COLS: Col[] = [
  { id: "albums", label: "Albums", sortKey: "aggregate.album_count" },
  { id: "tracks", label: "Tracks", sortKey: "aggregate.track_count" },
  { id: "checks", label: "Checks", sortKey: "aggregate.grade_pct" },
  { id: "grade", label: "Grade", sortKey: "aggregate.grade_pct" },
  { id: "audit", label: "Audit", sortKey: "aggregate.audit_summary" },
];

const TRACK_COLS: Col[] = [
  { id: "num", label: "#", sortKey: "tags.TRACKNUMBER" },
  { id: "title", label: "Title", sortKey: "tags.TITLE" },
  { id: "artist", label: "Artist", sortKey: "artist" },
  { id: "album", label: "Album", sortKey: "album" },
  { id: "year", label: "Year", sortKey: "tags.DATE" },
  { id: "genre", label: "Genre", sortKey: "tags.GENRE" },
  { id: "media", label: "Media", sortKey: "tags.MEDIA" },
  { id: "grade", label: "Grade", sortKey: "grade_pass" },
  { id: "audit", label: "Audit", sortKey: "audit" },
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
  const qc = useQueryClient();
  const { query, setQuery, setToast, folder } = useStore();
  const {
    selection, setSelection, toggleTrack, toggleAlbum, toggleArtist, clearSelection, playNow,
  } = useStore();
  const [view, setView] = useState<View>(() => (localStorage.getItem("mlo.defaultView") as View) ?? "albums");
  const [preset, setPreset] = useState<Preset>("all");
  const [albumSort, setAlbumSort] = useLocalSort("album");
  const [artistSort, setArtistSort] = useLocalSort("artist");
  const [trackSort, setTrackSort] = useLocalSort("track");
  const [removing, setRemoving] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [groupByArtist, setGroupByArtist] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  const [tagEditorOpen, setTagEditorOpen] = useState(false);

  const [albumCols, toggleAlbumCol] = useColumnPrefs("albums", ALBUM_COLS);
  const [artistCols, toggleArtistCol] = useColumnPrefs("artists", ARTIST_COLS);
  const [trackCols, toggleTrackCol] = useColumnPrefs("tracks", TRACK_COLS);

  const flat = useMemo(() => {
    const albums: FlatAlbum[] = [];
    const tracks: FlatTrack[] = [];
    for (const a of lib?.artists ?? [])
      for (const al of a.albums) {
        albums.push({ ...al, artist: a.name });
        for (const t of al.tracks) tracks.push({ ...t, artist: a.name, album: al.meta?.ALBUM ?? al.path.split("/").pop() ?? "" });
      }
    return { albums, tracks };
  }, [lib]);

  const filtered = useMemo(() => {
    if (!lib) return { artists: [] as Artist[], albums: [] as FlatAlbum[], tracks: [] as FlatTrack[] };
    const q = query.toLowerCase();
    const matches = (hay: string) => !q || hay.toLowerCase().includes(q);

    const trOK = (t: Track) => {
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
    const alOK = (al: Album) => {
      switch (preset) {
        case "all": return true;
        case "failing": return !al.pass;
        case "cd": return (al.media ?? "").toUpperCase().includes("CD");
        case "digital": return (al.media ?? "").toUpperCase().includes("DIGITAL");
        case "explicit":
        case "instrumental":
        case "missingLyrics": return (al.tracks ?? []).some(trOK);
      }
    };
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

  const removeAlbum = async (al: FlatAlbum) => {
    if (!window.confirm(`Remove "${al.meta?.ALBUM ?? al.path.split("/").pop()}" from the library?\nIt moves to .mlo_trash in your music folder (recoverable).`)) return;
    setRemoving(al.path);
    try {
      const r = await api.removeAlbum(al.path);
      setToast(`Moved to trash: ${r.trash.split("/").pop()}`);
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    } finally {
      setRemoving(null);
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
    const out: { path: string; file: string; albumPath: string; artist?: string }[] = [];
    for (const al of sortedAlbums)
      if (selection.albums.includes(al.path))
        for (const t of al.tracks) out.push({ path: t.path, file: t.file, albumPath: al.path, artist: al.artist });
    for (const a of sortedArtists)
      if (selection.artists.includes(a.path))
        for (const al of a.albums)
          for (const t of al.tracks) out.push({ path: t.path, file: t.file, albumPath: al.path, artist: a.name });
    for (const tr of sortedTracks)
      if (selection.tracks.includes(tr.path))
        out.push({ path: tr.path, file: tr.file, albumPath: tr.path.split("/").slice(0, -1).join("/"), artist: tr.artist });
    if (out.length) playNow(out);
  };

  const runScriptsOnSelection = async (ids: number[]) => {
    if (!selectionAlbumDirs.length) {
      toast("Select albums or artists to run scripts on");
      return;
    }
    try {
      await api.run(ids, selectionAlbumDirs);
      setToast(`Scripts run on ${selectionAlbumDirs.length} album(s)`);
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

  if (error) return <EmptyState title="Backend unreachable" hint={String(error)} />;
  if (isLoading || !lib) return <div className="p-8 text-zinc-500">Scanning library…</div>;

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

  const albumColSpan = 3 + albumCols.length + 1; // checkbox, chevron+cover, cols, actions

  const allAlbumsSelected = sortedAlbums.length > 0 && sortedAlbums.every((a) => selection.albums.includes(a.path));
  const allArtistsSelected = sortedArtists.length > 0 && sortedArtists.every((a) => selection.artists.includes(a.path));
  const allTracksSelected = sortedTracks.length > 0 && sortedTracks.every((t) => selection.tracks.includes(t.path));

  return (
    <div className="p-4 space-y-3">
      {/* toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-xl min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search artists / albums / tracks…"
            className="input pl-9"
          />
        </div>
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

        {view === "albums" && (
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
            <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none" title="Group albums under artist headers">
              <input type="checkbox" checked={groupByArtist} onChange={(e) => setGroupByArtist(e.target.checked)} className="" />
              Group by artist
            </label>
          </>
        )}

        <ColumnsMenu
          cols={view === "albums" ? ALBUM_COLS : view === "artists" ? ARTIST_COLS : TRACK_COLS}
          visible={view === "albums" ? albumCols : view === "artists" ? artistCols : trackCols}
          onToggle={view === "albums" ? toggleAlbumCol : view === "artists" ? toggleArtistCol : toggleTrackCol}
        />
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

      {/* quick filter tabs */}
      <div className="flex gap-1.5 flex-wrap">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            onClick={() => setPreset(p.id)}
            className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${
              preset === p.id
                ? p.id === "failing" || p.id === "explicit"
                  ? "bg-red-900/60 text-red-200 border-red-800"
                  : p.id === "cd"
                    ? "bg-sky-900/60 text-sky-200 border-sky-800"
                    : p.id === "digital"
                      ? "bg-accent/15 text-accent-soft border-accent/40"
                      : "bg-accent on-accent border-accent"
                : "bg-raise text-zinc-400 border-border hover:text-white"
            }`}
          >
            {p.label}
            <span className="ml-1 opacity-60">
              {p.id === "all"
                ? filtered.albums.length
                : p.id === "failing"
                  ? filtered.albums.filter((a) => !a.pass).length
                  : p.id === "cd"
                    ? filtered.albums.filter((a) => (a.media ?? "").toUpperCase().includes("CD")).length
                    : p.id === "digital"
                      ? filtered.albums.filter((a) => (a.media ?? "").toUpperCase().includes("DIGITAL")).length
                      : p.id === "explicit"
                        ? filtered.tracks.filter((t) => t.tags.ITUNESADVISORY === "1").length
                        : p.id === "instrumental"
                          ? filtered.tracks.filter((t) => t.tags.INSTRUMENTAL === "1").length
                          : filtered.tracks.filter((t) => !t.lyrics_present).length}
            </span>
          </button>
        ))}
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
            <button className="btn-ghost !py-1 text-xs" onClick={() => setTagEditorOpen(true)} disabled={!selTracks.size}>
              <TagsIcon className="h-3.5 w-3.5" /> Edit tags
            </button>
            <button
              className="btn-danger !py-1 text-xs"
              onClick={() => removeAlbums(selectionAlbumDirs)}
              disabled={removing === "batch" || !selectionAlbumDirs.length}
              title={selectionAlbumDirs.length ? "Move selected albums to trash" : "Select albums or artists to remove"}
            >
              <Trash2 className="h-3.5 w-3.5" /> Remove
            </button>
            <ScriptsDropdown onRun={runScriptsOnSelection} />
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

      {tagEditorOpen && selTracks.size > 0 && (
        <BatchTagEditor
          paths={[...selTracks]}
          onClose={() => setTagEditorOpen(false)}
          onDone={() => qc.invalidateQueries({ queryKey: ["library"] })}
        />
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
                      removing={removing === row.album.path}
                      onRemove={() => removeAlbum(row.album)}
                      onPlaylist={() => addToPlaylist(row.album.tracks.map((t) => t.path))}
                      colSpan={albumColSpan}
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
                  <th className="th w-8">
                    <input type="checkbox" className="" checked={allArtistsSelected}
                      onChange={() => setSelection({ artists: allArtistsSelected ? [] : sortedArtists.map((a) => a.path) })} />
                  </th>
                  {ARTIST_COLS.filter((c) => artistCols.includes(c.id)).map((c) => (
                    <SortHeader key={c.id} label={c.label} sort={artistSort} sortKey={c.sortKey} onSort={setArtistSort} />
                  ))}
                  <th className="th text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedArtists.map((a) => {
                  const all = a.albums.flatMap((al) =>
                    al.tracks.map((t) => ({ path: t.path, file: t.file, albumPath: al.path, artist: a.name }))
                  );
                  const sel = selection.artists.includes(a.path);
                  return (
                    <tr key={a.path} className={`table-row group ${sel ? "bg-accent/15" : ""}`}>
                      <td className="td pr-0">
                        <input type="checkbox" className="" checked={sel} onChange={() => toggleArtist(a.path)} />
                      </td>
                      <td className="td">
                        <Link to={`/artist/${encodeURIComponent(a.path)}`} className="font-medium hover:text-accent-soft">
                          {a.name}
                        </Link>
                      </td>
                      {artistCols.includes("albums") && <td className="td text-zinc-500">{a.aggregate.album_count}</td>}
                      {artistCols.includes("tracks") && <td className="td text-zinc-500">{a.aggregate.track_count}</td>}
                      {artistCols.includes("checks") && (
                        <td className="td text-zinc-500">{a.aggregate.pass_count}/{a.aggregate.total_checks}</td>
                      )}
                      {artistCols.includes("grade") && (
                        <td className="td"><GradeBadge pass={(a.aggregate.grade_pct ?? 0) >= 100} score={a.aggregate.grade_pct} /></td>
                      )}
                      {artistCols.includes("audit") && <td className="td"><AuditBadge audit={a.aggregate.audit_summary} /></td>}
                      <td className="td text-right">
                        <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button className="btn-ghost !px-1.5 !py-1" title="Play all" onClick={() => playNow(all)}>
                            <Play className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
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
                  <th className="th w-8">
                    <input type="checkbox" className="" checked={allTracksSelected}
                      onChange={() => setSelection({ tracks: allTracksSelected ? [] : sortedTracks.map((t) => t.path) })} />
                  </th>
                  {TRACK_COLS.filter((c) => trackCols.includes(c.id)).map((c) => (
                    <SortHeader key={c.id} label={c.label} sort={trackSort} sortKey={c.sortKey} onSort={setTrackSort} />
                  ))}
                  <th className="th text-right">Play</th>
                </tr>
              </thead>
              <tbody>
                {sortedTracks.map((tr) => {
                  const sel = selection.tracks.includes(tr.path);
                  return (
                    <tr key={tr.path} className={`table-row group ${sel ? "bg-accent/15" : ""}`}>
                      <td className="td pr-0">
                        <input type="checkbox" className="" checked={sel} onChange={() => toggleTrack(tr.path)} />
                      </td>
                      {trackCols.includes("num") && <td className="td text-zinc-600">{tr.tags.TRACKNUMBER ?? "—"}</td>}
                      {trackCols.includes("title") && (
                        <td className="td max-w-[260px]">
                          <Link to={`/track/${encodeURIComponent(tr.path)}`} className="hover:text-accent-soft truncate inline-block max-w-full">
                            {tr.tags.TITLE ?? tr.file}
                          </Link>
                          {tr.tags.INSTRUMENTAL === "1" && (
                            <span className="ml-2 chip bg-zinc-800 text-zinc-400 border border-border text-[10px]">INST</span>
                          )}
                        </td>
                      )}
                      {trackCols.includes("artist") && <td className="td text-zinc-400 truncate max-w-[160px]">{tr.artist}</td>}
                      {trackCols.includes("album") && <td className="td text-zinc-500 truncate max-w-[160px]">{tr.album}</td>}
                      {trackCols.includes("year") && <td className="td text-zinc-500">{tr.tags.DATE ?? "—"}</td>}
                      {trackCols.includes("genre") && <td className="td text-zinc-500 truncate max-w-[130px]">{tr.tags.GENRE ?? "—"}</td>}
                      {trackCols.includes("media") && <td className="td"><MediaChip media={tr.tags.MEDIA} /></td>}
                      {trackCols.includes("grade") && <td className="td"><GradeBadge pass={tr.grade_pass} score={tr.grade_pass ? 100 : null} size="sm" /></td>}
                      {trackCols.includes("audit") && <td className="td"><AuditBadge audit={tr.audit} size="sm" /></td>}
                      {trackCols.includes("advisory") && <td className="td"><AdvisoryBadge value={tr.tags.ITUNESADVISORY} /></td>}
                      {trackCols.includes("duration") && <td className="td text-zinc-500">{fmtDuration(tr.tech.length)}</td>}
                      {trackCols.includes("bitrate") && <td className="td text-zinc-500">{tr.tech.bitrate ? `${Math.round(tr.tech.bitrate / 1000)}k` : "—"}</td>}
                      {trackCols.includes("source") && <td className="td text-zinc-500 truncate max-w-[100px]">{tr.tags.SOURCE ?? "—"}</td>}
                      <td className="td text-right">
                        <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            className="btn-ghost !px-1.5 !py-1"
                            title="Play"
                            onClick={() =>
                              playNow(
                                sortedTracks.map((t) => ({ path: t.path, file: t.file, albumPath: t.path.split("/").slice(0, -1).join("/"), artist: t.artist })),
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
  colSpan,
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
  colSpan: number;
}) {
  const tracks = [...(album.tracks ?? [])].sort((a, b) => {
    const na = parseInt(a.tags.TRACKNUMBER ?? "0", 10) || 0;
    const nb = parseInt(b.tags.TRACKNUMBER ?? "0", 10) || 0;
    return na - nb;
  });

  return (
    <>
      <tr className={`table-row group ${selected ? "bg-accent/15" : ""}`} onClick={onToggle}>
        <td className="td pr-0" onClick={(e) => e.stopPropagation()}>
          <input type="checkbox" className="" checked={selected} onChange={onToggleSel} />
        </td>
        <td className="td pr-0">
          <button className="p-1 text-zinc-500 hover:text-white" onClick={(e) => { e.stopPropagation(); onToggle(); }}>
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        </td>
        <td className="td">
          <CoverImg albumPath={album.path} coverFile={album.cover_file} />
        </td>
        {visibleCols.includes("album") && (
          <td className="td max-w-[280px]">
            <Link
              to={`/album/${encodeURIComponent(album.path)}`}
              onClick={(e) => e.stopPropagation()}
              className="font-medium hover:text-accent-soft truncate inline-block max-w-full"
            >
              {album.meta?.ALBUM ?? album.path.split("/").pop()}
            </Link>
          </td>
        )}
        {visibleCols.includes("artist") && <td className="td text-zinc-400 truncate max-w-[200px]">{album.artist}</td>}
        {visibleCols.includes("year") && <td className="td text-zinc-500">{album.meta?.DATE ?? "—"}</td>}
        {visibleCols.includes("tracks") && <td className="td text-zinc-500">{album.track_count}</td>}
        {visibleCols.includes("grade") && <td className="td"><GradeBadge pass={album.pass} score={album.grade_pct} /></td>}
        {visibleCols.includes("audit") && <td className="td"><AuditBadge audit={album.audit_summary} /></td>}
        {visibleCols.includes("media") && <td className="td"><MediaChip media={album.media} /></td>}
        {visibleCols.includes("source") && <td className="td text-zinc-500 truncate max-w-[100px]">{album.source_summary ?? "—"}</td>}
        <td className="td text-right">
          <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
            <button
              className="btn-ghost !px-1.5 !py-1"
              title="Play album"
              onClick={() =>
                useStore.getState().playNow(
                  tracks.map((t) => ({ path: t.path, file: t.file, albumPath: album.path, artist: album.artist }))
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
                  <th className="th w-8"></th>
                  <th className="th w-10">#</th>
                  <th className="th">Title</th>
                  <th className="th">Genre</th>
                  <th className="th">Grade</th>
                  <th className="th">Audit</th>
                  <th className="th">Advisory</th>
                  <th className="th">Dur</th>
                  <th className="th text-right">Play</th>
                </tr>
              </thead>
              <tbody>
                {tracks.map((t) => (
                  <tr key={t.path} className={`table-row ${selTracks.has(t.path) ? "bg-accent/15" : ""}`}>
                    <td className="td pr-0">
                      <input type="checkbox" className="" checked={selTracks.has(t.path)} onChange={() => onToggleTrack(t.path)} />
                    </td>
                    <td className="td text-zinc-600">{t.tags.TRACKNUMBER ?? "—"}</td>
                    <td className="td max-w-[300px]">
                      <div className="flex items-center gap-2">
                        <CoverImg
                          albumPath={album.path}
                          coverFile={t.cover_file ?? null}
                          wrapperClass="h-7 w-7 rounded bg-raise border border-border overflow-hidden shrink-0"
                        />
                        <div className="min-w-0">
                          <Link to={`/track/${encodeURIComponent(t.path)}`} className="hover:text-accent-soft truncate inline-block max-w-full">
                            {t.tags.TITLE ?? t.file}
                          </Link>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            {t.audit && (
                              <span className={`text-[9px] font-bold ${t.audit === "REAL" ? "text-emerald-400" : t.audit === "FAKE" ? "text-red-400" : "text-amber-400"}`}>
                                {t.audit}
                              </span>
                            )}
                            {t.log_grade != null && t.log_grade !== "" && (
                              <span className="text-[9px] text-zinc-500">log {t.log_grade}/100</span>
                            )}
                            {!!t.issues?.length && (
                              <span className="text-[9px] text-red-400" title={t.issues.join("\n")}>
                                {t.issues.length} check{t.issues.length === 1 ? "" : "s"} failed
                              </span>
                            )}
                            {t.tags.INSTRUMENTAL === "1" && (
                              <span className="chip bg-zinc-800 text-zinc-400 border border-border text-[10px]">INST</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="td text-zinc-500 truncate max-w-[150px]">{t.tags.GENRE ?? "—"}</td>
                    <td className="td"><GradeBadge pass={t.grade_pass} score={t.grade_pass ? 100 : null} size="sm" /></td>
                    <td className="td"><AuditBadge audit={t.audit} size="sm" /></td>
                    <td className="td"><AdvisoryBadge value={t.tags.ITUNESADVISORY} /></td>
                    <td className="td text-zinc-500">{fmtDuration(t.tech.length)}</td>
                    <td className="td text-right">
                      <button
                        className="btn-ghost !px-1.5 !py-1"
                        onClick={() =>
                          useStore.getState().playNow(
                            tracks.map((x) => ({ path: x.path, file: x.file, albumPath: album.path, artist: album.artist })),
                            tracks.findIndex((x) => x.path === t.path)
                          )
                        }
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  );
}

function ScriptsDropdown({ onRun }: { onRun: (ids: number[]) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button className="btn-ghost !py-1 text-xs" onClick={() => setOpen(!open)}>
        <Wand2 className="h-3.5 w-3.5" /> Scripts
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-lg p-1.5 w-44 shadow-2xl">
            {SCRIPTS.map((s) => (
              <button
                key={s.label}
                className="w-full text-left px-2.5 py-1.5 text-xs rounded hover:bg-panel text-zinc-300 hover:text-white"
                onClick={() => {
                  setOpen(false);
                  onRun(s.ids);
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
}: {
  cols: Col[];
  visible: string[];
  onToggle: (id: string) => void;
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