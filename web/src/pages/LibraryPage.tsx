import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search, FolderOpen, ListPlus } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import { sortRows, SortHeader, type SortState } from "../lib/sort.tsx";
import { AuditBadge, EmptyState, GradeBadge, ScoreRing, AdvisoryBadge } from "../components/Badges";
import type { Album, Artist } from "../types";

export default function LibraryPage() {
  const { data: lib, isLoading, error } = useQuery({ queryKey: ["library"], queryFn: api.library });
  const { query, setQuery, filter, setFilter, setToast, folder } = useStore();
  const [albumSort, setAlbumSort] = useLocalSort("album");
  const [trackSort, setTrackSort] = useLocalSort("track");

  const artists = useMemo(() => {
    if (!lib) return [];
    let list: Artist[] = [...lib.artists];
    if (query) {
      const q = query.toLowerCase();
      list = list
        .map((a) => ({
          ...a,
          albums: a.albums.filter((al) =>
            [a.name, al.meta?.ALBUM, al.meta?.DATE, ...(al.tracks?.map((t) => `${t.tags.TITLE} ${t.file}`) ?? [])]
              .join(" ")
              .toLowerCase()
              .includes(q)
          ),
        }))
        .filter((a) => a.albums.length);
    }
    if (filter.failOnly) {
      list = list
        .map((a) => ({ ...a, albums: a.albums.filter((al) => !al.pass) }))
        .filter((a) => a.albums.length);
    }
    return sortRows(list, null);
  }, [lib, query, filter]);

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

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-xl">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search artists / albums / tracks…"
            className="input pl-9"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={!!filter.failOnly}
            onChange={(e) => setFilter({ ...filter, failOnly: e.target.checked })}
            className="accent-violet-500"
          />
          Fail only
        </label>
        <span className="text-xs text-zinc-500">
          {artists.reduce((n, a) => n + a.albums.length, 0)} albums ·{" "}
          {artists.reduce((n, a) => n + a.aggregate.track_count, 0)} tracks
        </span>
        {folder && (
          <span className="text-xs text-zinc-600 flex items-center gap-1">
            <FolderOpen className="h-3 w-3" /> {folder}
          </span>
        )}
      </div>

      {artists.length === 0 && <EmptyState title="No artists found" hint="Set the music folder in Settings, or drag files onto the Import page." />}

      {artists.map((artist) => {
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