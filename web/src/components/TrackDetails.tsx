import { X, ShieldCheck, CircleAlert } from "lucide-react";
import type { Track } from "../types";
import { AuditBadge, GradeBadge } from "./Badges";

/** Per-track grading + audit detail modal (checks, values, verdicts). */
export default function TrackDetails({
  track,
  albumPath,
  onClose,
}: {
  track: Track;
  albumPath: string;
  onClose: () => void;
}) {
  const issues: string[] = track.issues ?? [];
  const values = track.values ?? {};
  const checkRows = Object.entries(values).filter(([k]) => !["GENRE", "ITUNESADVISORY", "INSTRUMENTAL", "MEDIA", "SOURCE"].includes(k));
  const failKeys = new Set(issues.map((i) => i.toUpperCase()));

  return (
    <div className="fixed inset-0 z-40 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-card border border-border rounded-xl w-full max-w-lg max-h-[85vh] overflow-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-5 py-3 border-b border-border sticky top-0 bg-card z-10">
          <ShieldCheck className="h-4 w-4 text-accent" />
          <span className="font-semibold text-sm truncate">{track.tags?.TITLE ?? track.file}</span>
          <button className="ml-auto p-1 text-zinc-500 hover:text-white" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <GradeBadge pass={!issues.length} score={issues.length ? 0 : 100} />
            <AuditBadge audit={track.audit} />
            {track.log_grade != null && track.log_grade !== "" && (
              <span className="chip bg-raise border border-border text-zinc-300">log {track.log_grade}/100</span>
            )}
            {track.accuraterip_status && (
              <span className="chip bg-raise border border-border text-zinc-300">AR {track.accuraterip_status}</span>
            )}
            {track.checksum_status && (
              <span className="chip bg-raise border border-border text-zinc-300">CS {track.checksum_status}</span>
            )}
          </div>

          {issues.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-1.5">
                <CircleAlert className="h-3.5 w-3.5 text-red-400" /> Failed checks ({issues.length})
              </div>
              <ul className="space-y-1">
                {issues.map((iss, i) => (
                  <li key={i} className="text-xs text-red-300/90 bg-red-950/30 border border-red-900/40 rounded px-2 py-1">
                    {iss}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {checkRows.length > 0 && (
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-1.5">Check results</div>
              <div className="rounded-md border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <tbody>
                    {checkRows.map(([k, v]) => {
                      const failed = failKeys.has(k.toUpperCase());
                      return (
                        <tr key={k} className={failed ? "bg-red-950/20" : ""}>
                          <td className="px-2 py-1 text-zinc-500">{k}</td>
                          <td className={`px-2 py-1 text-right ${failed ? "text-red-400" : "text-emerald-400"}`}>
                            {failed ? "FAIL" : v === null || v === "" ? "—" : "OK"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 text-xs text-zinc-400">
            <div>Sidecar cover <span className="text-zinc-200">{track.sidecar_cover ? "yes" : "no"}</span></div>
            <div>Lyrics <span className="text-zinc-200">{track.lyrics_embedded ? "embedded" : ""}{track.lyrics_lrc ? " .lrc" : ""}{!track.lyrics_embedded && !track.lyrics_lrc ? "missing" : ""}</span></div>
            <div>Unreadable <span className="text-zinc-200">{track.unreadable ? "yes" : "no"}</span></div>
            <div>Path <span className="text-zinc-200 truncate block max-w-[180px]">{track.path ?? albumPath}</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}