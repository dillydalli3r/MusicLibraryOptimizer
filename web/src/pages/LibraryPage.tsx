import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search, FolderOpen, ListPlus, Play, Disc3 } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import { sortRows, SortHeader, type SortState } from "../lib/sort.tsx";
import { AuditBadge, EmptyState, GradeBadge, ScoreRing, AdvisoryBadge } from "../components/Badges";
import type { Album, Artist, Track } from "../types";

type View = "artists" | "albums" | "tracks";

const ALBUM_SORTS = [
  { key: "meta.DATE", label: "Year" },
  { key: "meta.ALBUM", label: "Album name" },
  { key: "artist", label: "Artist" },
  { key: "grade_pct", label: "Grade" },
  { key: "audit_summary", label: "Audit" },
  { key: "track_count", label: "Tracks" },
];

export default function LibraryPage() {
  const { data: lib, isLoading, error } = useQuery({ queryKey: ["library"], queryFn: api.library });
  const { query, setQuery, filter, setFilter, setToast, folder } = useStore();
  const [view, setView] = useState<View>("artists");
  const [albumSort, setAlbumSort] = useLocalSort("album");
  const [trackSort, setTrackSort] = useLocalSort("track");

  const flat = useMemo(() => {
    if (!lib) return { albums: [] as (Album & { artist: string })[], tracks: [] as (Track & { artist: string; album: string })[] };
    const albums: (Album & { artist: string })[] = [];
    const tracks: (Track & { artist: string; album: string })[] = [];
    for (const a of lib.artists)
      for (const al of a.albums) {
        albums.push({ ...al, artist: a.name });
        for (const t of al.tracks) tracks.push({ ...t, artist: a.name, album: al.meta?.ALBUM ?? al.path.split("/").pop() ?? "" });
      }
    return { albums, tracks };
  }, [lib]);

  const filtered = useMemo(() => {
    if (!lib) return { artists: [], albums: [] as typeof flat.albums, tracks: [] as typeof flat.tracks };
    const q = query.toLowerCase();
    const matches = (hay: string) => !q || hay.toLowerCase().includes(q);

    const artists: Artist[] = lib.artists
      .map((a) => ({
        ...a,
        albums: a.albums.filter((al) =>
          matches([a.name, al.meta?.ALBUM, al.meta?.DATE, al.meta?.ARTIST, ...(al.tracks?.map((t) => `${t.tags.TITLE} ${t.file}`) ?? [])].join(" "))
        ),
      }))
      .filter((a) => a.albums.length);
    if (filter.failOnly) {
      for (const a of artists) a.albums = a.albums.filter((al) => !al.pass);
    }

    const albums = flat.albums.filter((al) =>
      matches([al.artist, al.meta?.ALBUM, al.meta?.DATE, ...(al.tracks?.map((t) => `${t.tags.TITLE} ${t.file}`) ?? [])].join(" ")) &&
      (!filter.failOnly || !al.pass)
    );
    const tracks = flat.tracks.filter((t) =>
      matches([t.artist, t.album, t.tags.TITLE, t.file, t.tags.GENRE, t.tags.MEDIA].join(" ")) &&
      (!filter.failOnly || !t.grade_pass)
    );
    return { artists: artists.filter((a) => a.albums.length), albums, tracks };
  }, [lib, query, filter, flat]);

  const addAllToPlaylist = async (paths: string[]) => {
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

  if (error) return <EmptyState title="Backend unreachable" hint={String(error)} />;
  if (isLoading || !lib) return <div className="p-8 text-zinc-500">Scanning library…</div>;

  const sortedAlbums = sortRows(filtered.albums, albumSort);
  const sortedTracks = sortRows(filtered.tracks, trackSort);
  const albumCount = filtered.albums.length;
  const trackCount = filtered.tracks.length;

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-xl min-w-[220px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search artists / albums / tracks…"
            className="input pl-9"
          />
        </div>

        <div className="flex rounded-md border border-border overflow-hidden">
          {(["artists", "albums", "tracks"] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                view === v ? "bg-accent text-white" : "bg-panel text-zinc-400 hover:text-white"
              }`}
            >
              {v[0].toUpperCase() + v.slice(1)}
            </button>
          ))}
        </div>

        {view === "albums" && (
          <select
            className="input !w-auto text-xs"
            value={albumSort?.key ?? ""}
            onChange={(e) => setAlbumSort(e.target.value)}
          >
            <option value="">Sort…</option>
            {ALBUM_SORTS.map((s) => (
              <option key={s.key} value={s.key}>{s.label} {albumSort?.key === s.key ? (albumSort.dir === 1 ? "↑" : "↓") : ""}</option>
            ))}
          </select>
        )}

        <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={!!filter.failOnly}
            onChange={(e) => setFilter({ ...filter, failOnly: e.target.checked })}
            className="accent-violet-500"
          />
          Fail only
        </label>
        <span className="text-xs text-zinc-500 whitespace-nowrap">
          {view === "artists" ? `${albumCount} albums · ${trackCount} tracks` : view === "albums" ? `${albumCount} albums` : `${trackCount} tracks`}
        </span>
        {folder && (
          <span className="text-xs text-zinc-600 flex items-center gap-1">
            <FolderOpen className="h-3 w-3" /> {folder}
          </span>
        )}
      </div>

      {albumCount === 0 && <EmptyState title="No albums found" hint="Set the music folder in Settings, or drag an album folder onto the Import page." />}

      {view === "artists" && (
        <div className="space-y-3">
          {filtered.artists.map((artist) => {
            const albums = sortRows(artist.albums, albumSort);
            return (
              <div key={artist.path} className="bg-card rounded-lg border border-border overflow-hidden">
                <div className="flex items-center gap-3 px-4 py-3">
                  <ScoreRing pct={artist.aggregate.grade_pct} size={40} />
                  <div className="flex-1 min-w-0">
                    <Link to={`/artist/${encodeURIComponent(artist.path)}`} className="font-semibold hover:text-accent-soft truncate">
                      {artist.name}
                    </Link>
                    <div className="text-xs text-zinc-500">
                      {artist.aggregate.album_count} albums · {artist.aggregate.track_count} tracks ·{" "}
                      {artist.aggregate.pass_count}/{artist.aggregate.total_checks} checks
                    </div>
                  </div>
                  <AuditBadge audit={artist.aggregate.audit_summary} />
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-panel/60">
                      <tr>
                        {[
                          { key: "meta.DATE", label: "Year" },
                          { key: "meta.ALBUM", label: "Album" },
                          { key: "grade_pct", label: "Grade" },
                          { key: "audit_summary", label: "Audit" },
                          { key: "track_count", label: "Tracks" },
                          { key: "", label: "" },
                        ].map(({ key, label }) =>
                          key ? (
                            <SortHeader key={key} label={label} sort={albumSort} sortKey={key} onSort={setAlbumSort} />
                          ) : (
                            <th key="actions" className="th text-right">Actions</th>
                          )
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {albums.map((al) => (
                        <AlbumRow key={al.path} album={al} trackSort={trackSort} setTrackSort={setTrackSort} addAllToPlaylist={addAllToPlaylist} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {view === "albums" && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-3">
          {sortedAlbums.map((al) => (
            <Link
              key={al.path}
              to={`/album/${encodeURIComponent(al.path)}`}
              className="group bg-card rounded-lg border border-border overflow-hidden hover:border-accent/50 transition-colors"
            >
              <div className="aspect-square bg-raise relative overflow-hidden">
                {al.cover_file ? (
                  <img src={api.coverUrl(al.path, al.cover_file)} alt="cover" loading="lazy" className="h-full w-full object-cover group-hover:scale-[1.03] transition-transform" />
                ) : (
                  <div className="h-full w-full flex items-center justify-center text-zinc-700">
                    <Disc3 className="h-8 w-8" />
                  </div>
                )}
                <div className="absolute top-1.5 right-1.5">
                  <GradeBadge pass={al.pass} score={al.grade_pct} size="sm" />
                </div>
                <div className="absolute bottom-1.5 right-1.5">
                  <AuditBadge audit={al.audit_summary} size="sm" />
                </div>
              </div>
              <div className="p-2.5">
                <div className="text-sm font-medium truncate" title={al.meta?.ALBUM ?? al.path.split("/").pop()}>
                  {al.meta?.ALBUM ?? al.path.split("/").pop()}
                </div>
                <div className="text-xs text-zinc-500 truncate">{al.artist}</div>
                <div className="text-[11px] text-zinc-600 mt-0.5">
                  {al.meta?.DATE ?? "—"} · {al.track_count} tracks
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

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
                  <SortHeader label="Grade" sort={trackSort} sortKey="grade_pass" onSort={setTrackSort} />
                  <SortHeader label="Audit" sort={trackSort} sortKey="audit" onSort={setTrackSort} />
                  <SortHeader label="Advisory" sort={trackSort} sortKey="tags.ITUNESADVISORY" onSort={setTrackSort} />
                  <SortHeader label="Dur" sort={trackSort} sortKey="tech.length" onSort={setTrackSort} />
                  <SortHeader label="Bitrate" sort={trackSort} sortKey="tech.bitrate" onSort={setTrackSort} />
                  <th className="th text-right">Play</th>
                </tr>
              </thead>
              <tbody>
                {sortedTracks.map((tr) => (
                  <tr key={tr.path} className="table-row group">
                    <td className="td text-zinc-600">{tr.tags.TRACKNUMBER ?? "—"}</td>
                    <td className="td max-w-[280px]">
                      <Link to={`/track/${encodeURIComponent(tr.path)}`} className="hover:text-accent-soft truncate inline-block max-w-full">
                        {tr.tags.TITLE ?? tr.file}
                      </Link>
                      {tr.tags.INSTRUMENTAL === "1" && (
                        <span className="ml-2 chip bg-zinc-800 text-zinc-400 border border-border text-[10px]">INST</span>
                      )}
                    </td>
                    <td className="td text-zinc-400 truncate max-w-[180px]">{tr.artist}</td>
                    <td className="td text-zinc-500 truncate max-w-[180px]">{tr.album}</td>
                    <td className="td text-zinc-500">{tr.tags.DATE ?? "—"}</td>
                    <td className="td text-zinc-500 truncate max-w-[140px]">{tr.tags.GENRE ?? "—"}</td>
                    <td className="td"><GradeBadge pass={tr.grade_pass} score={tr.grade_pass ? 100 : null} size="sm" /></td>
                    <td className="td"><AuditBadge audit={tr.audit} size="sm" /></td>
                    <td className="td"><AdvisoryBadge value={tr.tags.ITUNESADVISORY} /></td>
                    <td className="td text-zinc-500">{fmtDuration(tr.tech.length)}</td>
                    <td className="td text-zinc-500">{tr.tech.bitrate ? `${Math.round(tr.tech.bitrate / 1000)}k` : "—"}</td>
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
                        <button className="btn-ghost !px-1.5 !py-1" title="Add to playlist" onClick={() => addAllToPlaylist([tr.path])}>
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

function AlbumRow({
  album,
  trackSort,
  setTrackSort,
  addAllToPlaylist,
}: {
  album: Album;
  trackSort: SortState | null;
  setTrackSort: (key: string) => void;
  addAllToPlaylist: (paths: string[]) => void;
}) {
  const tracks = sortRows(album.tracks, trackSort);
  const albumPath = `/album/${encodeURIComponent(album.path)}`;

  return (
    <>
      <tr className="table-row">
        <td className="td text-zinc-500 whitespace-nowrap">{album.meta?.DATE ?? "—"}</td>
        <td className="td">
          <Link to={albumPath} className="font-medium hover:text-accent-soft truncate inline-block max-w-full">
            {album.meta?.ALBUM ?? album.path.split("/").pop()}
          </Link>
          <span className="ml-2 text-xs text-zinc-500">{album.media}</span>
        </td>
        <td className="td"><GradeBadge pass={album.pass} score={album.grade_pct} /></td>
        <td className="td"><AuditBadge audit={album.audit_summary} /></td>
        <td className="td text-zinc-500">{album.track_count}</td>
        <td className="td text-right whitespace-nowrap">
          <button
            className="btn-ghost !px-2 !py-1 text-xs"
            onClick={() => addAllToPlaylist(album.tracks.map((t) => t.path))}
            title="Add album to playlist"
          >
            <ListPlus className="h-3.5 w-3.5" />
          </button>
        </td>
      </tr>
      <tr className="border-t border-border/40">
        <td colSpan={6} className="p-0">
          <table className="w-full">
            <thead className="bg-panel/40">
              <tr>
                <SortHeader label="#" sort={trackSort} sortKey="tags.TRACKNUMBER" onSort={setTrackSort} className="w-10" />
                <SortHeader label="Title" sort={trackSort} sortKey="tags.TITLE" onSort={setTrackSort} />
                <SortHeader label="Grade" sort={trackSort} sortKey="grade_pass" onSort={setTrackSort} />
                <SortHeader label="Audit" sort={trackSort} sortKey="audit" onSort={setTrackSort} />
                <SortHeader label="Genre" sort={trackSort} sortKey="tags.GENRE" onSort={setTrackSort} />
                <SortHeader label="Advisory" sort={trackSort} sortKey="tags.ITUNESADVISORY" onSort={setTrackSort} />
                <SortHeader label="Dur" sort={trackSort} sortKey="tech.length" onSort={setTrackSort} />
                <th className="th text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tracks.map((tr) => (
                <tr key={tr.path} className="table-row">
                  <td className="td text-zinc-600">{tr.tags.TRACKNUMBER ?? "—"}</td>
                  <td className="td max-w-[300px]">
                    <Link to={`/track/${encodeURIComponent(tr.path)}`} className="hover:text-accent-soft truncate inline-block max-w-full">
                      {tr.tags.TITLE ?? tr.file}
                    </Link>
                    {tr.tags.INSTRUMENTAL === "1" && (
                      <span className="ml-2 chip bg-zinc-800 text-zinc-400 border border-border text-[10px]">INST</span>
                    )}
                  </td>
                  <td className="td"><GradeBadge pass={tr.grade_pass} score={tr.grade_pass ? 100 : null} size="sm" /></td>
                  <td className="td"><AuditBadge audit={tr.audit} size="sm" /></td>
                  <td className="td text-zinc-500 truncate max-w-[160px]">{tr.tags.GENRE ?? "—"}</td>
                  <td className="td"><AdvisoryBadge value={tr.tags.ITUNESADVISORY} /></td>
                  <td className="td text-zinc-500">{fmtDuration(tr.tech.length)}</td>
                  <td className="td text-right">
                    <button className="btn-ghost !px-2 !py-1 text-xs" onClick={() => addAllToPlaylist([tr.path])}>+</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </td>
      </tr>
    </>
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