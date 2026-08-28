import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search, FolderOpen, ListPlus, Play, Disc3, Trash2 } from "lucide-react";
import { api } from "../api";
import { toast, useStore } from "../store";
import { sortRows, SortHeader, type SortState } from "../lib/sort.tsx";
import { AuditBadge, EmptyState, GradeBadge, MediaChip, AdvisoryBadge } from "../components/Badges";
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
  const [view, setView] = useState<View>("albums");
  const [preset, setPreset] = useState<Preset>("all");
  const [albumSort, setAlbumSort] = useLocalSort("album");
  const [artistSort, setArtistSort] = useLocalSort("artist");
  const [trackSort, setTrackSort] = useLocalSort("track");
  const [removing, setRemoving] = useState<string | null>(null);

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

  const addToPlaylist = async (paths: string[]) => {
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

  if (error) return <EmptyState title="Backend unreachable" hint={String(error)} />;
  if (isLoading || !lib) return <div className="p-8 text-zinc-500">Scanning library…</div>;

  const sortedAlbums = sortRows(filtered.albums, albumSort);
  const sortedArtists = sortRows(filtered.artists, artistSort);
  const sortedTracks = sortRows(filtered.tracks, trackSort);

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
                view === v.id ? "bg-accent text-white" : "bg-panel text-zinc-400 hover:text-white"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
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
                      ? "bg-violet-900/60 text-violet-200 border-violet-800"
                      : "bg-accent text-white border-accent"
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

      {sortedAlbums.length === 0 && (
        <EmptyState title="Nothing matches" hint="Set the music folder in Settings, import an album, or clear the search/filters." />
      )}

      {/* ---------------- Albums table ---------------- */}
      {view === "albums" && (
        <div className="bg-card rounded-lg border border-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-panel/60">
                <tr>
                  <th className="th w-12"></th>
                  <SortHeader label="Album" sort={albumSort} sortKey="meta.ALBUM" onSort={setAlbumSort} />
                  <SortHeader label="Artist" sort={albumSort} sortKey="artist" onSort={setAlbumSort} />
                  <SortHeader label="Year" sort={albumSort} sortKey="meta.DATE" onSort={setAlbumSort} />
                  <SortHeader label="Tracks" sort={albumSort} sortKey="track_count" onSort={setAlbumSort} />
                  <SortHeader label="Grade" sort={albumSort} sortKey="grade_pct" onSort={setAlbumSort} />
                  <SortHeader label="Audit" sort={albumSort} sortKey="audit_summary" onSort={setAlbumSort} />
                  <th className="th text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedAlbums.map((al) => (
                  <tr key={al.path} className="table-row group">
                    <td className="td">
                      <div className="h-9 w-9 rounded bg-raise border border-border overflow-hidden shrink-0">
                        {al.cover_file ? (
                          <img src={api.coverUrl(al.path, al.cover_file)} alt="" loading="lazy" className="h-full w-full object-cover" />
                        ) : (
                          <div className="h-full w-full flex items-center justify-center text-zinc-700">
                            <Disc3 className="h-4 w-4" />
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="td max-w-[280px]">
                      <Link to={`/album/${encodeURIComponent(al.path)}`} className="font-medium hover:text-accent-soft truncate inline-block max-w-full">
                        {al.meta?.ALBUM ?? al.path.split("/").pop()}
                      </Link>
                    </td>
                    <td className="td text-zinc-400 truncate max-w-[200px]">{al.artist}</td>
                    <td className="td text-zinc-500">{al.meta?.DATE ?? "—"}</td>
                    <td className="td text-zinc-500">{al.track_count}</td>
                    <td className="td"><GradeBadge pass={al.pass} score={al.grade_pct} /></td>
                    <td className="td"><AuditBadge audit={al.audit_summary} /></td>
                    <td className="td text-right">
                      <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          className="btn-ghost !px-1.5 !py-1"
                          title="Play album"
                          onClick={() =>
                            useStore.getState().playNow(
                              al.tracks.map((t) => ({ path: t.path, file: t.file, albumPath: al.path, artist: al.artist }))
                            )
                          }
                        >
                          <Play className="h-3.5 w-3.5" />
                        </button>
                        <button className="btn-ghost !px-1.5 !py-1" title="Add to playlist" onClick={() => addToPlaylist(al.tracks.map((t) => t.path))}>
                          <ListPlus className="h-3.5 w-3.5" />
                        </button>
                        <button
                          className="btn-danger !px-1.5 !py-1"
                          title="Remove album (to trash)"
                          disabled={removing === al.path}
                          onClick={() => removeAlbum(al)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
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
                  <SortHeader label="Artist" sort={artistSort} sortKey="name" onSort={setArtistSort} />
                  <SortHeader label="Albums" sort={artistSort} sortKey="aggregate.album_count" onSort={setArtistSort} />
                  <SortHeader label="Tracks" sort={artistSort} sortKey="aggregate.track_count" onSort={setArtistSort} />
                  <SortHeader label="Checks" sort={artistSort} sortKey="aggregate.grade_pct" onSort={setArtistSort} />
                  <SortHeader label="Grade" sort={artistSort} sortKey="aggregate.grade_pct" onSort={setArtistSort} />
                  <SortHeader label="Audit" sort={artistSort} sortKey="aggregate.audit_summary" onSort={setArtistSort} />
                  <th className="th text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedArtists.map((a) => {
                  const all = a.albums.flatMap((al) =>
                    al.tracks.map((t) => ({ path: t.path, file: t.file, albumPath: al.path, artist: a.name }))
                  );
                  return (
                    <tr key={a.path} className="table-row group">
                      <td className="td">
                        <Link to={`/artist/${encodeURIComponent(a.path)}`} className="font-medium hover:text-accent-soft">
                          {a.name}
                        </Link>
                      </td>
                      <td className="td text-zinc-500">{a.aggregate.album_count}</td>
                      <td className="td text-zinc-500">{a.aggregate.track_count}</td>
                      <td className="td text-zinc-500">
                        {a.aggregate.pass_count}/{a.aggregate.total_checks}
                      </td>
                      <td className="td"><GradeBadge pass={(a.aggregate.grade_pct ?? 0) >= 100} score={a.aggregate.grade_pct} /></td>
                      <td className="td"><AuditBadge audit={a.aggregate.audit_summary} /></td>
                      <td className="td text-right">
                        <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button className="btn-ghost !px-1.5 !py-1" title="Play all" onClick={() => useStore.getState().playNow(all)}>
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
                  <SortHeader label="#" sort={trackSort} sortKey="tags.TRACKNUMBER" onSort={setTrackSort} className="w-10" />
                  <SortHeader label="Title" sort={trackSort} sortKey="tags.TITLE" onSort={setTrackSort} />
                  <SortHeader label="Artist" sort={trackSort} sortKey="artist" onSort={setTrackSort} />
                  <SortHeader label="Album" sort={trackSort} sortKey="album" onSort={setTrackSort} />
                  <SortHeader label="Year" sort={trackSort} sortKey="tags.DATE" onSort={setTrackSort} />
                  <SortHeader label="Genre" sort={trackSort} sortKey="tags.GENRE" onSort={setTrackSort} />
                  <SortHeader label="Media" sort={trackSort} sortKey="tags.MEDIA" onSort={setTrackSort} />
                  <SortHeader label="Grade" sort={trackSort} sortKey="grade_pass" onSort={setTrackSort} />
                  <SortHeader label="Audit" sort={trackSort} sortKey="audit" onSort={setTrackSort} />
                  <SortHeader label="Advisory" sort={trackSort} sortKey="tags.ITUNESADVISORY" onSort={setTrackSort} />
                  <SortHeader label="Dur" sort={trackSort} sortKey="tech.length" onSort={setTrackSort} />
                  <th className="th text-right">Play</th>
                </tr>
              </thead>
              <tbody>
                {sortedTracks.map((tr) => (
                  <tr key={tr.path} className="table-row group">
                    <td className="td text-zinc-600">{tr.tags.TRACKNUMBER ?? "—"}</td>
                    <td className="td max-w-[260px]">
                      <Link to={`/track/${encodeURIComponent(tr.path)}`} className="hover:text-accent-soft truncate inline-block max-w-full">
                        {tr.tags.TITLE ?? tr.file}
                      </Link>
                      {tr.tags.INSTRUMENTAL === "1" && (
                        <span className="ml-2 chip bg-zinc-800 text-zinc-400 border border-border text-[10px]">INST</span>
                      )}
                    </td>
                    <td className="td text-zinc-400 truncate max-w-[160px]">{tr.artist}</td>
                    <td className="td text-zinc-500 truncate max-w-[160px]">{tr.album}</td>
                    <td className="td text-zinc-500">{tr.tags.DATE ?? "—"}</td>
                    <td className="td text-zinc-500 truncate max-w-[130px]">{tr.tags.GENRE ?? "—"}</td>
                    <td className="td"><MediaChip media={tr.tags.MEDIA} /></td>
                    <td className="td"><GradeBadge pass={tr.grade_pass} score={tr.grade_pass ? 100 : null} size="sm" /></td>
                    <td className="td"><AuditBadge audit={tr.audit} size="sm" /></td>
                    <td className="td"><AdvisoryBadge value={tr.tags.ITUNESADVISORY} /></td>
                    <td className="td text-zinc-500">{fmtDuration(tr.tech.length)}</td>
                    <td className="td text-right">
                      <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          className="btn-ghost !px-1.5 !py-1"
                          title="Play"
                          onClick={() =>
                            useStore.getState().playNow(
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
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
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