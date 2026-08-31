import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Music2, ExternalLink } from "lucide-react";
import { api } from "../api";
import { AuditBadge, EmptyState, GradeBadge, ScoreRing } from "../components/Badges";
import { useStore } from "../store";

export default function ArtistPage() {
  const { path = "" } = useParams();
  const decoded = decodeURIComponent(path);
  const { data, isLoading, error } = useQuery({
    queryKey: ["artist", decoded],
    queryFn: () => api.artist(decoded),
  });
  const { playNow } = useStore();

  if (error) return <EmptyState title="Artist not found" hint={String(error)} />;
  if (isLoading || !data) return <div className="p-8 text-zinc-500">Loading artist…</div>;

  const allTracks = data.albums.flatMap((a) =>
    a.tracks.map((t) => ({ path: t.path, file: t.file, albumPath: a.path, artist: data.name }))
  );

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div className="flex items-start gap-5">
        <div className="h-24 w-24 rounded-xl bg-gradient-to-br from-accent/40 to-indigo-700/40 border border-border flex items-center justify-center shrink-0">
          <Music2 className="h-10 w-10 text-zinc-400" />
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-3xl font-bold tracking-tight">{data.name}</h1>
          <div className="mt-1 flex items-center gap-3 text-sm text-zinc-400">
            <span>
              {data.aggregate.album_count} albums · {data.aggregate.track_count} tracks
            </span>
            <AuditBadge audit={data.aggregate.audit_summary} />
            <GradeBadge pass={(data.aggregate.grade_pct ?? 0) >= 100} score={data.aggregate.grade_pct} />
          </div>
          <div className="mt-2 inline-flex items-center gap-1 text-xs text-zinc-500">
            <ExternalLink className="h-3 w-3" /> MusicBrainz / RYM links live in the track tags — set them from Import & tag
          </div>
        </div>
        <button className="btn-primary" onClick={() => playNow(allTracks)}>
          Play all
        </button>
      </div>

      <div className="space-y-3">
        {data.albums.map((al) => (
          <div key={al.path} className="bg-card rounded-lg border border-border p-4 flex items-center gap-4">
            <ScoreRing pct={al.grade_pct} size={40} />
            <div className="flex-1 min-w-0">
              <Link to={`/album/${encodeURIComponent(al.path)}`} className="font-semibold hover:text-accent-soft">
                {al.meta?.ALBUM ?? al.path.split("/").pop()}
              </Link>
              <div className="text-xs text-zinc-500 mt-0.5">
                {al.meta?.DATE ?? "—"} · {al.media} · {al.track_count} tracks · cover {al.cover_file ?? "missing"}
              </div>
            </div>
            <AuditBadge audit={al.audit_summary} />
            <GradeBadge pass={al.pass} score={al.grade_pct} />
          </div>
        ))}
      </div>
    </div>
  );
}