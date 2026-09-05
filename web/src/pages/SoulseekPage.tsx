import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Play, Power, RefreshCw, Search, User, Check } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";
import { EmptyState } from "../components/Badges";

interface SlskFile {
  username: string;
  file: string;
  size: number;
  bitrate: number | null;
  duration: number | null;
  vbr: boolean | null;
  slot: boolean;
  speed: number;
  queue: number;
}

const fmtSize = (n: number) => {
  if (!n) return "—";
  if (n > 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n > 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024).toFixed(0)} kB`;
};
const fmtDur = (s: number | null) => {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};
const fileName = (p: string) => p.replace(/^.*[\\/]/, "");

export default function SoulseekPage() {
  const qc = useQueryClient();
  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ["soulseekStatus"],
    queryFn: api.soulseekStatus,
    refetchInterval: 10000,
  });
  const { data: downloads, refetch: refetchDownloads } = useQuery({
    queryKey: ["soulseekDownloads"],
    queryFn: api.soulseekDownloads,
    enabled: !!status?.running,
    refetchInterval: 3000,
  });

  const [query, setQuery] = useState("");
  const [searchId, setSearchId] = useState<string | null>(null);
  const [results, setResults] = useState<SlskFile[]>([]);
  const [searching, setSearching] = useState(false);
  const [busyUser, setBusyUser] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  const start = async () => {
    try {
      await api.soulseekStart();
      toast("slskd started");
      refetchStatus();
      qc.invalidateQueries({ queryKey: ["soulseekDownloads"] });
    } catch (e) {
      toast(String(e));
    }
  };

  const stop = async () => {
    try {
      await api.soulseekStop();
      toast("slskd stopped");
      refetchStatus();
    } catch (e) {
      toast(String(e));
    }
  };

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setResults([]);
    try {
      const r = await api.soulseekSearch(query.trim());
      setSearchId(r.id);
      let elapsed = 0;
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        elapsed += 2;
        try {
          const res = await api.soulseekSearchResults(r.id);
          setResults(res.responses ?? []);
          const done = elapsed > 30 || res.state === "Completed" || res.state === "TimedOut";
          if (done) {
            if (pollRef.current) clearInterval(pollRef.current);
            setSearching(false);
          }
        } catch {
          if (pollRef.current) clearInterval(pollRef.current);
          setSearching(false);
        }
      }, 2000);
    } catch (e) {
      toast(String(e));
      setSearching(false);
    }
  };

  const downloadFile = async (f: SlskFile, group: boolean) => {
    setBusyUser(f.username);
    try {
      // Group the whole folder of the best-matching result set from this user
      let files = [{ filename: f.file, size: f.size }];
      if (group) {
        const dir = f.file.replace(/[^\\/]*$/, "");
        const siblings = results.filter((r) => r.username === f.username && r.file.replace(/[^\\/]*$/, "") === dir);
        files = siblings.map((s) => ({ filename: s.file, size: s.size }));
      }
      const r = await api.soulseekDownload(f.username, files);
      toast(`Queued ${r.queued} file(s) from ${f.username}`);
      refetchDownloads();
    } catch (e) {
      toast(String(e));
    } finally {
      setBusyUser(null);
    }
  };

  const importDownloaded = async () => {
    const dir = status?.download_dir;
    if (!dir) return;
    try {
      const r = await api.soulseekImport();
      if (r.moved.length) {
        toast(`Imported ${r.moved.length} album folder(s) into the library`);
        qc.invalidateQueries({ queryKey: ["library"] });
      } else {
        toast("Nothing to import — no completed downloads found");
      }
    } catch (e) {
      toast(String(e));
    }
  };

  if (status && !status.installed) {
    return (
      <div className="p-6 max-w-3xl">
        <EmptyState title="slskd is not installed" hint="Install it from Settings → Dependencies (key: slskd), then reload this page." />
      </div>
    );
  }

  const running = !!status?.running;

  return (
    <div className="p-6 space-y-5 max-w-6xl">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Soulseek</h1>
          <div className="text-xs text-zinc-500 mt-0.5">
            Managed slskd · {running ? (
              <span className="text-emerald-400">running{status?.logged_in ? " · logged in" : status?.logged_in === false ? " · not logged in" : ""}</span>
            ) : "stopped"}
            {" · downloads: "}{status?.download_dir ?? "—"}
          </div>
        </div>
        <div className="flex gap-2">
          {running ? (
            <button className="btn-ghost" onClick={stop}><Power className="h-4 w-4" /> Stop</button>
          ) : (
            <button className="btn-primary" onClick={start}><Play className="h-4 w-4" /> Start slskd</button>
          )}
          <button className="btn-ghost" onClick={() => { refetchStatus(); refetchDownloads(); }}><RefreshCw className="h-4 w-4" /></button>
        </div>
      </div>

      <div className="bg-card rounded-lg border border-border p-4">
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="Search Soulseek (artist — album, title, …)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !searching && runSearch()}
          />
          <button className="btn-primary" onClick={runSearch} disabled={searching || !running}>
            <Search className="h-4 w-4" /> {searching ? "Searching…" : "Search"}
          </button>
        </div>
        {!running && (
          <div className="text-[11px] text-zinc-500 mt-2">Start slskd to search and download. Credentials, ports, shares and profile description live in Settings → Soulseek.</div>
        )}

        {results.length > 0 && (
          <div className="mt-3 rounded-md border border-border overflow-auto max-h-[420px]">
            <table className="w-full text-xs">
              <thead className="bg-panel/60 sticky top-0">
                <tr>
                  <th className="th text-left">File</th>
                  <th className="th">Size</th>
                  <th className="th">Bitrate</th>
                  <th className="th">Len</th>
                  <th className="th">User</th>
                  <th className="th">Queue</th>
                  <th className="th"></th>
                </tr>
              </thead>
              <tbody>
                {results.slice(0, 300).map((f, i) => (
                  <tr key={i} className="table-row">
                    <td className="td truncate max-w-[380px]" title={f.file}>{fileName(f.file)}</td>
                    <td className="td text-zinc-500">{fmtSize(f.size)}</td>
                    <td className="td text-zinc-500">{f.bitrate ? `${f.bitrate}${f.vbr ? " vbr" : ""}` : "—"}</td>
                    <td className="td text-zinc-500">{fmtDur(f.duration)}</td>
                    <td className="td text-zinc-400">
                      <span className="inline-flex items-center gap-1">
                        <User className="h-3 w-3" /> {f.username}
                        {f.slot && <span className="chip text-[9px] bg-emerald-900/50 text-emerald-300 border border-emerald-800">slot</span>}
                      </span>
                    </td>
                    <td className="td text-zinc-500">{f.queue}</td>
                    <td className="td whitespace-nowrap">
                      <button className="btn-ghost !px-1.5 !py-0.5" disabled={busyUser === f.username}
                        onClick={() => downloadFile(f, false)} title="Download this file">
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      <button className="btn-ghost !px-1.5 !py-0.5" disabled={busyUser === f.username}
                        onClick={() => downloadFile(f, true)} title="Download this whole folder">
                        <Check className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!searching && results.length === 0 && searchId && (
          <div className="text-[11px] text-zinc-500 mt-2">No results (yet) — try a different query.</div>
        )}
      </div>

      <div className="bg-card rounded-lg border border-border p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Downloads</div>
          <button className="btn-ghost !py-1 text-xs" onClick={importDownloaded} title="Ingest completed downloads into the library">
            <Download className="h-3.5 w-3.5" /> Import completed
          </button>
        </div>
        {(downloads?.downloads ?? []).length === 0 ? (
          <div className="text-xs text-zinc-600">No downloads queued.</div>
        ) : (
          <div className="space-y-2 max-h-[320px] overflow-auto">
            {(downloads?.downloads ?? []).map((u: any) => (
              <details key={u.username} className="rounded border border-border">
                <summary className="px-2 py-1 text-xs cursor-pointer text-zinc-300">{u.username}</summary>
                <div className="px-3 pb-2 space-y-1">
                  {(u.directories ?? []).map((d: any, di: number) => (
                    <div key={di}>
                      <div className="text-[10px] text-zinc-500 truncate">{d.directory}</div>
                      {(d.files ?? []).map((f: any, fi: number) => (
                        <div key={fi} className="flex items-center justify-between text-[11px] text-zinc-400">
                          <span className="truncate">{fileName(f.filename ?? "")}</span>
                          <span className="text-zinc-600 ml-2 shrink-0">{f.state ?? ""} · {fmtSize(f.size ?? 0)}</span>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
