import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, EyeOff, Play, Power, RefreshCw, Search, User, Zap, Square, FileCheck2 } from "lucide-react";
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
const dirName = (p: string) => p.replace(/[^\\/]*$/, "");
const extOf = (p: string) => (p.match(/\.([a-z0-9]+)$/i)?.[1] ?? "").toUpperCase();

/** One shared remote folder — the unit worth downloading for album rips. */
interface SlskGroup {
  key: string;
  username: string;
  dir: string;
  files: SlskFile[];
  audio: SlskFile[]; // files that are music (logs/cues/jpegs excluded)
  format: string; // dominant audio extension, e.g. "FLAC"
  lossless: boolean;
  hasLog: boolean;
  hasCue: boolean;
  totalSize: number;
  slotFree: boolean;
  minQueue: number;
  isCdRip: boolean; // log + cue present → a verifiable CD rip
}

const AUDIO_EXTS = new Set(["FLAC", "MP3", "M4A", "AAC", "OGG", "OPUS", "WAV", "WMA", "APE", "WV", "AIFF", "ALAC"]);
const LOSSLESS = new Set(["FLAC", "WAV", "APE", "WV", "AIFF", "ALAC"]);

function groupResults(results: SlskFile[]): SlskGroup[] {
  const map = new Map<string, SlskGroup>();
  for (const f of results) {
    const dir = dirName(f.file);
    const key = `${f.username}\u0000${dir}`;
    let g = map.get(key);
    if (!g) {
      g = {
        key, username: f.username, dir, files: [], audio: [],
        format: "", lossless: false, hasLog: false, hasCue: false,
        totalSize: 0, slotFree: false, minQueue: Number.MAX_SAFE_INTEGER, isCdRip: false,
      };
      map.set(key, g);
    }
    g.files.push(f);
    const ext = extOf(f.file);
    if (ext === "LOG") g.hasLog = true;
    if (ext === "CUE") g.hasCue = true;
    if (AUDIO_EXTS.has(ext)) g.audio.push(f);
    g.totalSize += f.size || 0;
    g.slotFree ||= f.slot;
    g.minQueue = Math.min(g.minQueue, f.queue || 0);
  }
  const groups = [...map.values()];
  for (const g of groups) {
    // dominant audio format by file count; lossless if that format is
    const counts = new Map<string, number>();
    for (const f of g.audio) {
      const e = extOf(f.file);
      counts.set(e, (counts.get(e) ?? 0) + 1);
    }
    g.format = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
    g.lossless = LOSSLESS.has(g.format);
    g.isCdRip = g.hasLog && g.hasCue;
    g.minQueue = g.minQueue === Number.MAX_SAFE_INTEGER ? 0 : g.minQueue;
  }
  // Best imports first: verifiable CD rips, then lossless, then free slots /
  // shortest queues — this ordering is the "well thought out" default.
  groups.sort(
    (a, b) =>
      Number(b.isCdRip) - Number(a.isCdRip) ||
      Number(b.lossless) - Number(a.lossless) ||
      Number(a.slotFree ? 0 : 1) - Number(b.slotFree ? 0 : 1) ||
      a.minQueue - b.minQueue
  );
  return groups;
}

type FilterId = "all" | "cdrip" | "lossless" | "lossy";
const FILTERS: { id: FilterId; label: string }[] = [
  { id: "all", label: "All" },
  { id: "cdrip", label: "CD rips (log + cue)" },
  { id: "lossless", label: "Lossless" },
  { id: "lossy", label: "MP3 / AAC" },
];

function groupMatches(g: SlskGroup, f: FilterId): boolean {
  if (f === "cdrip") return g.isCdRip;
  if (f === "lossless") return g.lossless;
  if (f === "lossy") return g.format === "MP3" || g.format === "M4A" || g.format === "AAC";
  return true;
}

function GroupBadges({ g }: { g: SlskGroup }) {
  return (
    <span className="inline-flex items-center gap-1 shrink-0">
      {g.format && (
        <span className={`chip text-[9px] border ${g.lossless ? "bg-sky-900/40 text-sky-300 border-sky-800" : "bg-zinc-800 text-zinc-300 border-zinc-700"}`}>
          {g.format}
        </span>
      )}
      {g.hasLog && (
        <span className="chip text-[9px] bg-emerald-900/50 text-emerald-300 border border-emerald-800">log</span>
      )}
      {g.hasCue && (
        <span className="chip text-[9px] bg-emerald-900/50 text-emerald-300 border border-emerald-800">cue</span>
      )}
      {g.isCdRip && (
        <span className="chip text-[9px] bg-accent on-accent border border-transparent font-semibold">CD rip</span>
      )}
    </span>
  );
}

/** Strip a MusicBrainz URL down to the bare release MBID. */
const releaseMbid = (s: string) =>
  /(?:release\/)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i.exec(s.trim())?.[1] ?? "";

/** Sign in to the Soulseek network (or register a brand-new username — the
 * server creates accounts on first login). Shown whenever slskd is running
 * but not logged in. */
function LoginCard({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const login = async () => {
    if (!username.trim() || !password) {
      toast("Enter a username and password");
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const r = await api.soulseekLogin(username.trim(), password);
      setResult(r.message);
      if (r.logged_in) {
        toast(r.message);
        onDone();
      }
    } catch (e) {
      setResult(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-card rounded-lg border border-amber-900/50 p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-amber-300 mb-1.5">
        Not logged in to Soulseek
      </div>
      <p className="text-[11px] text-zinc-500 mb-2.5">
        Enter your Soulseek credentials to search, download and share. If the
        username doesn't exist yet, the network registers it automatically on
        first login — same button, no separate sign-up.
      </p>
      <div className="flex gap-2 flex-wrap">
        <input
          className="input w-52"
          placeholder="Soulseek username"
          value={username}
          autoComplete="username"
          onChange={(e) => setUsername(e.target.value)}
        />
        <div className="relative">
          <input
            className="input w-52 pr-9"
            placeholder="Password"
            type={showPw ? "text" : "password"}
            value={password}
            autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !busy && login()}
          />
          <button
            className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-200"
            onClick={() => setShowPw(!showPw)}
            title={showPw ? "Hide password" : "Show password"}
            type="button"
          >
            {showPw ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </button>
        </div>
        <button className="btn-primary" onClick={login} disabled={busy}>
          {busy ? "Connecting…" : "Log in / create account"}
        </button>
      </div>
      {result && <div className="text-[11px] text-zinc-400 mt-2">{result}</div>}
    </div>
  );
}

/** Live view of the auto-import job (search → log test → download → audit → import). */
function AutoPanel({ initialMbid }: { initialMbid?: string }) {
  const { data: job, refetch } = useQuery({
    queryKey: ["soulseekAuto"],
    queryFn: api.soulseekAutoStatus,
    refetchInterval: (q) => ((q.state.data as any)?.state === "running" ? 2000 : 15000),
  });
  const running = job?.state === "running";
  const [mbid, setMbid] = useState(initialMbid ?? "");
  const [queries, setQueries] = useState("");

  const start = async () => {
    const id = releaseMbid(mbid);
    if (!id) {
      toast("Paste a MusicBrainz release URL or MBID");
      return;
    }
    try {
      await api.soulseekAutoStart({
        release_mbid: id,
        queries: queries.split(";").map((s) => s.trim()).filter(Boolean) || undefined,
      });
      toast("Auto-import started");
      refetch();
    } catch (e) {
      toast(String(e));
    }
  };

  const cancel = async () => {
    try {
      await api.soulseekAutoCancel();
      toast("Cancelling after the current step…");
      refetch();
    } catch (e) {
      toast(String(e));
    }
  };

  const r = job?.release;
  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 flex items-center gap-1.5">
          <Zap className="h-3.5 w-3.5" /> Auto-import a MusicBrainz release
        </div>
        {running && (
          <button className="btn-ghost !py-1 text-xs text-red-300" onClick={cancel}>
            <Square className="h-3 w-3" /> Stop
          </button>
        )}
      </div>
      <div className="text-[11px] text-zinc-500 mb-2.5">
        Finds the release on the network by its identifiable traits (catalog number for CDs,
        title + year for digital media — customizable in Settings), tests the rip logs before
        committing, downloads, audits against the logs, and imports it fully tagged.
      </div>
      {!running && (
        <div className="flex gap-2 flex-wrap">
          <input
            className="input flex-1 min-w-[240px]"
            placeholder="MusicBrainz release URL or MBID (e.g. https://musicbrainz.org/release/…)"
            value={mbid}
            onChange={(e) => setMbid(e.target.value)}
          />
          <input
            className="input w-56"
            placeholder="Custom queries (; separated, optional)"
            value={queries}
            onChange={(e) => setQueries(e.target.value)}
            title="Override the search terms for this run. Fields: artist album year country catalognumber barcode label"
          />
          <button className="btn-primary" onClick={start}>
            <Zap className="h-4 w-4" /> Auto-import
          </button>
        </div>
      )}
      {job?.state !== "idle" && (
        <div className="mt-3 rounded-lg border border-border bg-panel/50 p-3">
          {r?.title && (
            <div className="text-xs text-zinc-300 mb-1.5">
              <span className="text-zinc-500">Target:</span> {r.artist} — {r.title}
              {r.catalog_number ? ` · ${r.catalog_number}` : ""}
              {r.date ? ` (${r.date})` : ""} · {r.media}
            </div>
          )}
          <div className="text-xs font-medium text-zinc-200">{job?.stage || job?.state}</div>
          <div className="mt-1.5 max-h-44 overflow-auto font-mono text-[10px] leading-relaxed text-zinc-500 space-y-0.5">
            {(job?.log ?? []).map((l: any, i: number) => (
              <div key={i} className={l.msg.startsWith("ERROR") ? "text-red-400" : l.msg.startsWith("  ✕") ? "text-red-300" : undefined}>
                <span className="text-zinc-700 mr-1.5">{l.t}</span>{l.msg}
              </div>
            ))}
          </div>
          {(job?.attempts ?? []).length > 0 && (
            <details className="mt-1.5 text-[11px] text-zinc-500">
              <summary className="cursor-pointer">{job.attempts.length} rejected candidate(s)</summary>
              <div className="mt-1 space-y-0.5">
                {job.attempts.map((a: any, i: number) => (
                  <div key={i} title={a.dir}>…{String(a.dir).slice(-40)} — {a.reason}</div>
                ))}
              </div>
            </details>
          )}
          {job?.state === "done" && (
            <div className="mt-1.5 text-[11px] text-emerald-400">
              Imported {(job.result?.album_path ?? "").split(/[\\/]/).pop()}
              {!job.result?.organized ? " (organize failed — run it from the album page)" : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function SoulseekPage() {
  const qc = useQueryClient();
  const [params] = useSearchParams();
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
  const [filter, setFilter] = useState<FilterId>("all");
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const [logTest, setLogTest] = useState<Record<string, { ok: boolean; text: string } | "busy">>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoRan = useRef(false); // ?q= handoff runs once per page visit
  const releaseParam = params.get("release") ?? undefined;

  /** Pre-download quality check: fetch only the .log file(s), grade them,
   * clean up — shows the Logchecker score inline on the folder row. */
  const testLogs = async (g: SlskGroup) => {
    const logs = g.files.filter((f) => extOf(f.file) === "LOG");
    if (!logs.length) return;
    setLogTest((m) => ({ ...m, [g.key]: "busy" }));
    try {
      const r = await api.soulseekTestLog(g.username, logs.map((f) => ({ filename: f.file, size: f.size })));
      const text = r.logs
        .map((l) => `${l.file}: ${l.score ?? "?"}/100${l.checksum ? ` · ${l.checksum}` : ""}`)
        .join("  ·  ");
      setLogTest((m) => ({ ...m, [g.key]: { ok: r.ok, text: `${r.ok ? "PASS" : "FAIL"} — ${text}` } }));
    } catch (e) {
      setLogTest((m) => ({ ...m, [g.key]: { ok: false, text: String(e) } }));
    }
  };

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

  const runSearch = async (q?: string) => {
    const text = (q ?? query).trim();
    if (!text) return;
    if (q) setQuery(q);
    setSearching(true);
    setResults([]);
    try {
      const r = await api.soulseekSearch(text);
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

  // MusicBrainz browser handoff: /soulseek?q=… pre-fills and fires a search
  // once slskd is confirmed running (retried via the status poll otherwise).
  const handoff = params.get("q");
  useEffect(() => {
    if (!handoff || autoRan.current) return;
    if (status?.running) {
      autoRan.current = true;
      runSearch(handoff);
    } else if (status && !status.running) {
      autoRan.current = true;
      setQuery(handoff);
      toast("Start slskd to run the search");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoff, status?.running]);

  const downloadFile = async (f: SlskFile, group: boolean) => {
    setBusyUser(f.username);
    try {
      let files = [{ filename: f.file, size: f.size }];
      if (group) {
        // grab every audio file in the folder (logs/cues come along server-side
        // via the remote directory listing; here we queue what we can see)
        const dir = dirName(f.file);
        const siblings = results.filter((r) => r.username === f.username && dirName(r.file) === dir);
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
        toast(r.organized === false
          ? `Imported ${r.moved.length} album folder(s) — organize failed: ${r.organize_error ?? "see console"}`
          : `Imported and organized ${r.moved.length} album folder(s) into the library`);
        qc.invalidateQueries({ queryKey: ["library"] });
      } else {
        toast("Nothing to import — no completed downloads found");
      }
    } catch (e) {
      toast(String(e));
    }
  };

  const groups = useMemo(() => groupResults(results), [results]);
  const visible = groups.filter((g) => groupMatches(g, filter));
  const counts: Record<FilterId, number> = {
    all: groups.length,
    cdrip: groups.filter((g) => g.isCdRip).length,
    lossless: groups.filter((g) => g.lossless).length,
    lossy: groups.filter((g) => g.format === "MP3" || g.format === "M4A" || g.format === "AAC").length,
  };
  const toggleGroup = (key: string) =>
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  if (status && !status.installed) {
    return (
      <div className="p-6 max-w-3xl">
        <EmptyState title="slskd is not installed" hint="Install it from Settings → Dependencies (key: slskd), then reload this page." />
      </div>
    );
  }

  const running = !!status?.running;

  return (
    <div className="p-6 space-y-5">
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

      {running && status?.logged_in === false && <LoginCard onDone={refetchStatus} />}

      <AutoPanel initialMbid={releaseParam} />

      <div className="bg-card rounded-lg border border-border p-4">
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="Search Soulseek manually (artist — album, title, catalog #…)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !searching && runSearch()}
          />
          <button className="btn-primary" onClick={() => runSearch()} disabled={searching || !running}>
            <Search className="h-4 w-4" /> {searching ? "Searching…" : "Search"}
          </button>
        </div>
        {!running && (
          <div className="text-[11px] text-zinc-500 mt-2">Start slskd to search and download. Credentials, ports, shares and profile description live in Settings → Soulseek.</div>
        )}

        {groups.length > 0 && (
          <>
            {/* filter chips with live counts — CD rips with log+cue first */}
            <div className="flex flex-wrap items-center gap-1.5 mt-3">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  className={`chip px-2.5 py-1 border ${
                    filter === f.id
                      ? "bg-accent on-accent border-transparent font-semibold"
                      : "bg-raise border-border text-zinc-400 hover:text-white"
                  }`}
                  onClick={() => setFilter(f.id)}
                >
                  {f.label} <span className={filter === f.id ? "opacity-70" : "text-zinc-600"}>{counts[f.id]}</span>
                </button>
              ))}
            </div>

            <div className="mt-3 space-y-2 max-h-[560px] overflow-auto pr-1">
              {visible.map((g) => {
                const open = openGroups.has(g.key);
                return (
                  <div key={g.key} className="rounded-lg border border-border overflow-hidden">
                    {/* folder header: what you'd actually download */}
                    <div className="flex items-center gap-3 px-3 py-2 bg-panel/60">
                      <button
                        className="flex-1 min-w-0 text-left"
                        onClick={() => toggleGroup(g.key)}
                        title={g.dir}
                      >
                        <div className="text-sm text-zinc-100 truncate font-medium">
                          {g.dir.split(/[\\/]/).filter(Boolean).slice(-2).join(" / ") || g.dir}
                        </div>
                        <div className="text-[11px] text-zinc-500 flex items-center gap-1.5 mt-0.5 flex-wrap">
                          <span className="inline-flex items-center gap-1"><User className="h-3 w-3" /> {g.username}</span>
                          <span>· {g.audio.length || g.files.length} audio file(s) · {fmtSize(g.totalSize)}</span>
                          <span>· {g.slotFree ? <span className="text-emerald-400">free slot</span> : `queue ${g.minQueue}`}</span>
                        </div>
                      </button>
                      <GroupBadges g={g} />
                      {(() => {
                        const lt = logTest[g.key];
                        if (!g.hasLog || !lt || lt === "busy") return null;
                        return (
                          <span
                            className={`chip text-[9px] border ${lt.ok ? "bg-emerald-900/50 text-emerald-300 border-emerald-800" : "bg-red-950/60 text-red-300 border-red-800"}`}
                            title={lt.text}
                          >
                            log {lt.ok ? "pass" : "fail"}
                          </span>
                        );
                      })()}
                      {g.hasLog && (
                        <button
                          className="btn-ghost !py-1 text-xs shrink-0"
                          disabled={logTest[g.key] === "busy"}
                          onClick={() => testLogs(g)}
                          title="Download only the .log file(s) and grade them before committing to the album"
                        >
                          <FileCheck2 className="h-3.5 w-3.5" /> Test logs
                        </button>
                      )}
                      <button
                        className="btn-ghost !py-1 text-xs shrink-0"
                        disabled={busyUser === g.username || !g.files.length}
                        onClick={() => downloadFile(g.files[0], true)}
                        title="Download this whole folder"
                      >
                        <Download className="h-3.5 w-3.5" /> Folder
                      </button>
                    </div>
                    {open && (
                      <div className="border-t border-border/60">
                        {g.files.map((f, i) => (
                          <div key={i} className="flex items-center gap-3 px-3 py-1.5 border-t border-border/40 first:border-t-0 text-xs">
                            <span className="flex-1 min-w-0 truncate text-zinc-300" title={fileName(f.file)}>
                              {fileName(f.file)}
                            </span>
                            <span className="text-zinc-500 w-16 text-right shrink-0">{fmtSize(f.size)}</span>
                            <span className="text-zinc-500 w-20 text-right shrink-0">
                              {f.bitrate ? `${f.bitrate}${f.vbr ? " vbr" : ""}` : extOf(f.file) || "—"}
                            </span>
                            <span className="text-zinc-500 w-10 text-right shrink-0">{fmtDur(f.duration)}</span>
                            <button
                              className="btn-ghost !px-1.5 !py-0.5 shrink-0"
                              disabled={busyUser === g.username}
                              onClick={() => downloadFile(f, false)}
                              title="Download this file"
                            >
                              <Download className="h-3 w-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
              {visible.length === 0 && (
                <div className="text-[11px] text-zinc-500 py-6 text-center">
                  No {FILTERS.find((f) => f.id === filter)?.label.toLowerCase()} groups in this result set.
                </div>
              )}
            </div>
          </>
        )}
        {!searching && results.length === 0 && searchId && (
          <div className="text-[11px] text-zinc-500 mt-3">No results (yet) — try a different query.</div>
        )}
        {searching && results.length === 0 && (
          <div className="text-[11px] text-zinc-500 mt-3 flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-full border border-zinc-600 border-t-transparent animate-spin inline-block" />
            Searching the network… results stream in below.
          </div>
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
