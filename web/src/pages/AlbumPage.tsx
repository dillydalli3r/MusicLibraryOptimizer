import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ExternalLink, Play, Wand2, Trash2, FolderSync } from "lucide-react";
import { api } from "../api";
import { AuditBadge, EmptyState, GradeBadge, MediaChip } from "../components/Badges";
import CoverImg from "../components/CoverImg";
import { SortHeader, sortRows, toggleSort, type SortState } from "../lib/sort.tsx";
import { toast, useStore } from "../store";
import { fmtDuration } from "./LibraryPage";

export default function AlbumPage() {
  const { path = "" } = useParams();
  const decoded = decodeURIComponent(path);
  const { data, isLoading, error } = useQuery({
    queryKey: ["album", decoded],
    queryFn: () => api.album(decoded),
  });
  const { data: coverColor } = useQuery({
    queryKey: ["coverColor", decoded],
    queryFn: () => api.coverColor(decoded),
    retry: false,
  });
  const { playNow } = useStore();
  const navigate = useNavigate();
  const [sort, setSort] = useState<SortState | null>(null);
  const qc = useQueryClient();

  if (error) return <EmptyState title="Album not found" hint={String(error)} />;
  if (isLoading || !data) return <div className="p-8 text-zinc-500">Loading album…</div>;

  const tracks = sortRows(data.tracks, sort);
  const mbid = data.meta?.MUSICBRAINZ_ALBUMID;
  const rym = data.meta?.RATEYOURMUSIC_ALBUM;

  const runScripts = async (ids: number[]) => {
    await api.run(ids, [data.path]);
    qc.invalidateQueries({ queryKey: ["library"] });
  };

  const removeAlbum = async () => {
    if (!window.confirm(`Remove "${data.meta?.ALBUM ?? data.path.split("/").pop()}" from the library?\nIt moves to .mlo_trash in your music folder (recoverable).`)) return;
    try {
      await api.removeAlbum(data.path);
      toast("Album moved to trash");
      qc.invalidateQueries({ queryKey: ["library"] });
      navigate("/");
    } catch (e) {
      toast(String(e));
    }
  };

  const organizeAlbum = async () => {
    if (!window.confirm("Organize this album with the naming script from Settings?\nFiles are MOVED into the scripted folder structure.")) return;
    try {
      const r = await api.organize([data.path]);
      const res = r.results[0];
      if (res.error) {
        toast(`Organize failed: ${res.error}`);
        return;
      }
      toast(`Organized — ${res.moved} file(s) moved, ${res.leftovers} sidecar(s)`);
      qc.invalidateQueries({ queryKey: ["library"] });
      navigate("/");
    } catch (e) {
      toast(String(e));
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div
        className="rounded-xl p-5 border border-border relative overflow-hidden"
        style={
          coverColor
            ? { background: `linear-gradient(135deg, ${coverColor}33 0%, transparent 60%)` }
            : undefined
        }
      >
        <div className="flex items-start gap-5">
          <CoverImg
            albumPath={data.path}
            coverFile={data.cover_file}
            wrapperClass="h-40 w-40 rounded-lg border border-border bg-raise overflow-hidden shrink-0"
          />
        <div className="flex-1 min-w-0">
          <div className="text-xs text-zinc-500 uppercase tracking-wider">{data.meta?.DATE ?? "—"}</div>
          <h1 className="text-3xl font-bold tracking-tight">{data.meta?.ALBUM ?? data.path.split("/").pop()}</h1>
          <div className="text-zinc-400 mt-1">{data.meta?.ARTIST ?? "—"}</div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <GradeBadge pass={data.pass} score={data.grade_pct} />
            <AuditBadge audit={data.audit_summary} />
            <MediaChip media={data.media} />
            <span className="chip bg-zinc-800 text-zinc-400 border border-border">
              {data.pass_count}/{data.total_checks} checks
            </span>
            <span className="chip bg-zinc-800 text-zinc-400 border border-border">
              AR {data.accuraterip_status || "—"} · CS {data.checksum_status || "—"}
            </span>
            <span className="chip bg-zinc-800 text-zinc-400 border border-border">
              CUE {data.has_cue ? "yes" : "no"} · LOG {data.has_log ? "yes" : "no"}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
            {mbid && (
              <a href={`https://musicbrainz.org/release/${mbid}`} target="_blank" rel="noreferrer"
                 className="chip bg-accent/10 text-accent-soft border border-accent/25 hover:bg-accent/20">
                <ExternalLink className="h-3 w-3" /> MusicBrainz release
              </a>
            )}
            {rym && (
              <a href={rym} target="_blank" rel="noreferrer"
                 className="chip bg-sky-900/40 text-sky-300 border border-sky-900 hover:bg-sky-900/60">
                <ExternalLink className="h-3 w-3" /> RateYourMusic
              </a>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-2 shrink-0">
          <button className="btn-primary" onClick={() => playNow(data.tracks.map((t) => ({ path: t.path, file: t.file, albumPath: data.path })))}>
            <Play className="h-4 w-4" /> Play album
          </button>
          <button className="btn-ghost" onClick={() => navigate(`/import?album=${encodeURIComponent(data.path)}`)}>
            <Wand2 className="h-4 w-4" /> Import & tag
          </button>
          <button className="btn-ghost" onClick={organizeAlbum} title="Apply the naming script from Settings">
            <FolderSync className="h-4 w-4" /> Organize
          </button>
          <button className="btn-danger" onClick={removeAlbum}>
            <Trash2 className="h-4 w-4" /> Remove
          </button>
        </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {[
          { ids: [1], label: "Lyrics" },
          { ids: [2], label: "CUEs" },
          { ids: [3], label: "FLACs" },
          { ids: [5], label: "Images" },
          { ids: [6], label: "Audit" },
          { ids: [7], label: "DR/RG" },
          { ids: [8], label: "AutoTag" },
          { ids: [4], label: "Grade" },
        ].map(({ ids, label }) => (
          <button key={label} className="btn-ghost text-xs" onClick={() => runScripts(ids)}>
            {label}
          </button>
        ))}
      </div>

      <div className="bg-card rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-panel/60">
            <tr>
              <SortHeader label="#" sort={sort} sortKey="tags.TRACKNUMBER" onSort={(k) => setSort(toggleSort(sort, k))} className="w-12" />
              <SortHeader label="Title" sort={sort} sortKey="tags.TITLE" onSort={(k) => setSort(toggleSort(sort, k))} />
              <SortHeader label="Grade" sort={sort} sortKey="grade_pass" onSort={(k) => setSort(toggleSort(sort, k))} />
              <SortHeader label="Audit" sort={sort} sortKey="audit" onSort={(k) => setSort(toggleSort(sort, k))} />
              <SortHeader label="Genre" sort={sort} sortKey="tags.GENRE" onSort={(k) => setSort(toggleSort(sort, k))} />
              <SortHeader label="Dur" sort={sort} sortKey="tech.length" onSort={(k) => setSort(toggleSort(sort, k))} />
              <SortHeader label="Bitrate" sort={sort} sortKey="tech.bitrate" onSort={(k) => setSort(toggleSort(sort, k))} />
              <th className="th text-right">Play</th>
            </tr>
          </thead>
          <tbody>
            {tracks.map((tr) => (
              <tr key={tr.path} className="table-row">
                <td className="td text-zinc-500">{tr.tags.TRACKNUMBER ?? "—"}</td>
                <td className="td">
                  <Link to={`/track/${encodeURIComponent(tr.path)}`} className="hover:text-accent-soft">
                    {tr.tags.TITLE ?? tr.file}
                  </Link>
                </td>
                <td className="td"><GradeBadge pass={tr.grade_pass} score={tr.grade_pass ? 100 : null} size="sm" /></td>
                <td className="td"><AuditBadge audit={tr.audit} size="sm" /></td>
                <td className="td text-zinc-500 max-w-[180px] truncate">{tr.tags.GENRE ?? "—"}</td>
                <td className="td text-zinc-500">{fmtDuration(tr.tech.length)}</td>
                <td className="td text-zinc-500">
                  {tr.tech.bitrate ? `${Math.round(tr.tech.bitrate / 1000)} kbps` : "—"}
                  {tr.tech.sample_rate ? ` · ${Math.round(tr.tech.sample_rate / 1000)} kHz` : ""}
                </td>
                <td className="td text-right">
                  <button
                    className="btn-ghost !px-2 !py-1"
                    onClick={() =>
                      playNow(
                        data.tracks.map((t) => ({ path: t.path, file: t.file, albumPath: data.path })),
                        data.tracks.findIndex((t) => t.path === tr.path)
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
      </div>
    </div>
  );
}