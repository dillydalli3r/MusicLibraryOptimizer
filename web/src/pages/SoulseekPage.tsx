import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download, Eye, EyeOff, FolderOpen, Loader2, Play, Power, RefreshCw, Search, User, Zap,
  Square, FileCheck2, FileVideo, Music2, Save, Tag, Trash2, PackageOpen,
} from "lucide-react";
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

const fmtRate = (n: number | null | undefined) => {
  if (!n) return "0 kB/s";
  if (n > 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB/s`;
  return `${(n / 1024).toFixed(0)} kB/s`;
};
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

type FilterId = "all" | "cdrip" | "lossless" | "lossy";const FILTERS: { id: FilterId; label: string }[] = [
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

/** Saved credentials exist and slskd isn't logged in (yet) — usually the
 * few seconds a reconnect takes, sometimes a Soulseek-server cooldown after
 * a disconnect. Shows what the app is doing and a one-click retry that does
 * NOT restart slskd (restarting resets the server's cooldown and made the
 * old stop → start → login loop stop working). */
function ReconnectingCard({ username, password, onDone }: {
  username: string;
  password: string;
  onDone: () => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    setBusy(true);
    try {
      const r = await api.soulseekLogin(username, password);
      toast(r.message);
      if (r.logged_in) onDone();
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };
  if (showForm) return <LoginCard onDone={onDone} initialUsername={username} initialPassword={password} />;
  return (
    <div className="bg-card rounded-lg border border-amber-900/50 p-3 flex items-center gap-2 flex-wrap text-xs">
      <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-300 shrink-0" />
      <span className="text-zinc-300">
        Reconnecting to Soulseek as <b>{username}</b>…
      </span>
      <span className="text-zinc-600">
        the network sometimes enforces a short cooldown after a disconnect
      </span>
      <div className="ml-auto flex gap-1.5">
        <button className="btn-ghost !py-1 text-xs" onClick={retry} disabled={busy}>
          {busy ? "Reconnecting…" : "Reconnect now"}
        </button>
        <button className="btn-ghost !py-1 text-xs" onClick={() => setShowForm(true)}>
          Different account
        </button>
      </div>
    </div>
  );
}

/** Sign in to the Soulseek network (or register a brand-new username — the
 * server creates accounts on first login). Shown whenever slskd is running
 * but not logged in. Credentials are SAVED by the server, so the form comes
 * prefilled and future starts reconnect on their own. */
function LoginCard({ onDone, initialUsername, initialPassword }: {
  onDone: () => void;
  initialUsername?: string;
  initialPassword?: string;
}) {
  const [username, setUsername] = useState(initialUsername ?? "");
  const [password, setPassword] = useState(initialPassword ?? "");
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

// Containers the browser decodes natively; the preview endpoint transcodes
// everything else (DVD VOB, Blu-ray M2TS, MPEG-2 in AVI…) live to MP4.
const NATIVE_VIDEO_EXTS = new Set(["MP4", "M4V", "WEBM", "MKV", "MOV", "OGV", "3GP", "3G2"]);

interface ReviewFile {
  path: string;
  file: string;
  ext: string;
  is_video: boolean;
  size: number;
  mtime: number;
  user: string;
  tags: Record<string, string | null>;
  tech: Record<string, number | string>;
}

/** Pull a probable artist / title / track# out of a raw download filename
 * ("01 - Artist - Title.flac", "Artist - 01 - Title.vob", …) so the tag
 * form starts from something better than a filename. */
function parseDownloadName(file: string): { artist?: string; title: string; track?: string } {
  let base = fileName(file).replace(/\.[a-z0-9]+$/i, "").replace(/_/g, " ").trim();
  let track: string | undefined;
  const tm = /^(\d{1,3})\s*[-._]?\s+(.+)$/.exec(base);
  if (tm) {
    track = tm[1];
    base = tm[2].trim();
  }
  const parts = base.split(/\s+-\s+/);
  if (parts.length >= 2) return { artist: parts[0], title: parts.slice(1).join(" - "), track };
  return { title: base, track };
}

const TAG_FIELDS: { key: string; label: string; placeholder?: string }[] = [
  { key: "TITLE", label: "Title" },
  { key: "ARTIST", label: "Artist" },
  { key: "ALBUM", label: "Album" },
  { key: "DISCNUMBER", label: "Disc", placeholder: "1" },
  { key: "TRACKNUMBER", label: "Track", placeholder: "1" },
  { key: "DATE", label: "Date", placeholder: "1997" },
  { key: "GENRE", label: "Genre" },
];

/** One completed download on disk: preview it (audio/video player), tag it
 * (VOB and friends are remuxed to MKV by the tag write — stream copy, no
 * quality or caption loss), or discard it. */
function ReviewRow({ f, onChanged }: { f: ReviewFile; onChanged: () => void }) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [tagOpen, setTagOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [armDelete, setArmDelete] = useState(false);
  const parsed = useMemo(() => parseDownloadName(f.file), [f.file]);
  const [form, setForm] = useState<Record<string, string>>({
    TITLE: f.tags.TITLE ?? parsed.title ?? "",
    ARTIST: f.tags.ARTIST ?? parsed.artist ?? "",
    ALBUM: f.tags.ALBUM ?? "",
    DISCNUMBER: f.tags.DISCNUMBER ?? "",
    TRACKNUMBER: f.tags.TRACKNUMBER ?? parsed.track ?? "",
    DATE: f.tags.DATE ?? "",
    GENRE: f.tags.GENRE ?? "",
    ITUNESADVISORY: f.tags.ITUNESADVISORY ?? "0",
  });
  const set = (k: string, v: string) => setForm((m) => ({ ...m, [k]: v }));

  const save = async () => {
    setBusy(true);
    try {
      const clean: Record<string, string> = {};
      for (const [k, v] of Object.entries(form)) if (v.trim()) clean[k] = v.trim();
      const r = await api.videoTag(f.path, clean);
      toast(r.renamed
        ? `Tagged & remuxed to MKV: ${String(r.path).split(/[\\/]/).pop()}`
        : "Tags written");
      onChanged();
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!armDelete) {
      setArmDelete(true);
      setTimeout(() => setArmDelete(false), 3000);
      return;
    }
    setBusy(true);
    try {
      await api.soulseekDeleteLocal(f.path);
      toast(`Discarded ${f.file}`);
      onChanged();
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
      setArmDelete(false);
    }
  };

  const native = NATIVE_VIDEO_EXTS.has(f.ext);
  const src = f.is_video ? api.soulseekPreviewStreamUrl(f.path) : api.soulseekLocalFileUrl(f.path);

  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-panel/60">
        <button className="flex-1 min-w-0 text-left" onClick={() => setPreviewOpen(!previewOpen)} title={f.path}>
          <div className="text-xs text-zinc-100 truncate font-medium flex items-center gap-1.5">
            {f.is_video
              ? <FileVideo className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
              : <Music2 className="h-3.5 w-3.5 shrink-0 text-zinc-500" />}
            {f.file}
          </div>
          <div className="text-[10px] text-zinc-500 flex items-center gap-1.5 mt-0.5 flex-wrap">
            <span className="chip text-[9px] bg-raise border border-border">{f.ext}</span>
            {f.is_video && !native && (
              <span title="Browser can't decode this container — preview streams a live transcode (the file itself is untouched)">
                transcode preview
              </span>
            )}
            <span>· {f.user}</span>
            <span>· {fmtSize(f.size)}</span>
            {f.tech?.length ? <span>· {fmtDur(Number(f.tech.length))}</span> : null}
          </div>
        </button>
        <button
          className={`btn-ghost !py-1 text-xs shrink-0 ${previewOpen ? "!text-accent" : ""}`}
          onClick={() => setPreviewOpen(!previewOpen)}
          title={f.is_video ? "Watch (preview player)" : "Listen (preview player)"}
        >
          <Play className="h-3.5 w-3.5" /> Preview
        </button>
        <button
          className={`btn-ghost !py-1 text-xs shrink-0 ${tagOpen ? "!text-accent" : ""}`}
          onClick={() => setTagOpen(!tagOpen)}
          title="Check / edit the tags before import — video files are remuxed to MKV on save (stream copy, no quality loss)"
        >
          <Tag className="h-3.5 w-3.5" /> Tag
        </button>
        <button
          className={`btn-ghost !py-1 text-xs shrink-0 ${armDelete ? "!text-red-300 border border-red-800" : ""}`}
          disabled={busy}
          onClick={discard}
          title={armDelete ? "Click again to delete this download" : "Delete this download without importing"}
        >
          <Trash2 className="h-3.5 w-3.5" /> {armDelete ? "Sure?" : ""}
        </button>
      </div>
      {previewOpen && (
        <div className="border-t border-border/60 p-2 bg-black/30">
          {f.is_video ? (
            <video
              key={f.path}
              controls
              autoPlay
              className="w-full max-h-72 rounded-lg bg-black"
              src={src}
            />
          ) : (
            <audio key={f.path} controls autoPlay className="w-full" src={src} />
          )}
        </div>
      )}
      {tagOpen && (
        <div className="border-t border-border/60 p-3 space-y-2 bg-panel/40">
          <div className="grid sm:grid-cols-4 gap-2">
            {TAG_FIELDS.map((t) => (
              <label key={t.key} className="text-[10px] text-zinc-500 block">
                {t.label}
                <input
                  className="input !py-1 !px-2 text-xs mt-0.5 w-full"
                  value={form[t.key] ?? ""}
                  placeholder={t.placeholder}
                  onChange={(e) => set(t.key, e.target.value)}
                />
              </label>
            ))}
            <label className="text-[10px] text-zinc-500 block">
              Advisory
              <select
                className="input !py-1 !px-2 text-xs mt-0.5 w-full"
                value={form.ITUNESADVISORY ?? "0"}
                onChange={(e) => set("ITUNESADVISORY", e.target.value)}
              >
                <option value="0">Clean (0)</option>
                <option value="1">Explicit (1)</option>
                <option value="2">Cleaned (2)</option>
              </select>
            </label>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-primary !py-1 text-xs" disabled={busy} onClick={save}>
              <Save className="h-3.5 w-3.5" /> Save tags{f.is_video ? " (remux to MKV)" : ""}
            </button>
            <span className="text-[10px] text-zinc-600">
              {f.is_video
                ? "Video / audio / captions are stream-copied — nothing is re-encoded."
                : "Writes ID3/Vorbis/MP4 tags in place."}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/** Review completed downloads: preview, tag (and remux VOB→MKV), discard,
 * then import the keepers into the library. */
function ReviewPanel() {
  const qc = useQueryClient();
  const { data, refetch } = useQuery({
    queryKey: ["soulseekReview"],
    queryFn: api.soulseekReview,
    refetchInterval: 8000,
  });
  const files = data?.files ?? [];
  const refresh = () => {
    refetch();
    qc.invalidateQueries({ queryKey: ["library"] });
  };
  const importAll = async () => {
    try {
      const r = await api.soulseekImport();
      if (r.moved.length) {
        toast(r.organized === false
          ? `Imported ${r.moved.length} album folder(s) — organize failed: ${r.organize_error ?? "see console"}`
          : `Imported and organized ${r.moved.length} album folder(s) into the library`);
        refresh();
      } else {
        toast("Nothing to import — no completed downloads found");
      }
    } catch (e) {
      toast(String(e));
    }
  };

  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 flex items-center gap-1.5">
          <PackageOpen className="h-3.5 w-3.5" /> Review downloads
          {files.length > 0 && (
            <span className="text-[10px] font-mono normal-case text-zinc-400">{files.length} file(s) ready</span>
          )}
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost !py-1 text-xs" onClick={() => refetch()} title="Rescan the download folder">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button className="btn-primary !py-1 text-xs" onClick={importAll} title="Ingest completed downloads into the library">
            <Download className="h-3.5 w-3.5" /> Import completed
          </button>
        </div>
      </div>
      <div className="text-[11px] text-zinc-500 mb-2.5">
        Preview each download, fix its tags (untagged DVD/Blu-ray rips included — saving remuxes them to MKV without
        re-encoding), discard the misses, then import the keepers. Files land in{" "}
        <span className="font-mono text-zinc-400">{data?.dir ?? "…"}</span>
      </div>
      {files.length === 0 ? (
        <div className="text-xs text-zinc-600 py-3 text-center">
          Nothing waiting for review — finished downloads appear here automatically.
        </div>
      ) : (
        <div className="space-y-2 max-h-[420px] overflow-auto pr-1">
          {files.map((f) => (
            <ReviewRow key={f.path} f={f} onChanged={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Share configuration (la musica settings are the source of truth — the
 * slskd yaml is regenerated from them at start) with live rescan and the
 * autostart preference. Reserved folders (Data / .mlo_downloads /
 * .mlo_trash) are filtered server-side and never shared. */
function SharingCard({ running }: { running: boolean }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["soulseekShares"], queryFn: api.soulseekShares });
  const [dirs, setDirs] = useState<string[] | null>(null);
  const [newDir, setNewDir] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data && dirs === null) setDirs((data.dirs as string[]) ?? []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const autostart: boolean = data?.autostart ?? true;
  const scanState: string | undefined = data?.slskd?.scanState;
  const savedDirs: string[] = data?.dirs ?? [];
  const dirty =
    dirs !== null &&
    (JSON.stringify([...dirs].sort()) !== JSON.stringify([...savedDirs].sort()));

  const save = async (autostartOverride?: boolean) => {
    setBusy(true);
    try {
      const r = await api.soulseekSharesSave(dirs ?? [], autostartOverride ?? null, true);
      toast(r.restarted ? "Shares saved — slskd restarted and rescanning" : "Shares saved");
      qc.invalidateQueries({ queryKey: ["soulseekShares"] });
      qc.invalidateQueries({ queryKey: ["soulseekStatus"] });
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const rescan = async () => {
    setBusy(true);
    try {
      await api.soulseekSharesRescan();
      toast("Share rescan started");
      qc.invalidateQueries({ queryKey: ["soulseekShares"] });
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleAutostart = async () => {
    setBusy(true);
    try {
      await api.soulseekSharesSave(dirs ?? [], !autostart, false);
      qc.invalidateQueries({ queryKey: ["soulseekShares"] });
      qc.invalidateQueries({ queryKey: ["soulseekStatus"] });
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-card rounded-lg border border-border p-3 text-xs space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-widest text-zinc-500">Sharing</span>
        {scanState && (
          <span className={`chip text-[9px] border ${scanState === "Complete" ? "bg-emerald-900/40 text-emerald-300 border-emerald-800" : "bg-raise border-border text-zinc-400"}`}>
            scan: {scanState.toLowerCase()}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2.5">
          <label className="flex items-center gap-1.5 cursor-pointer text-zinc-400" title="Start slskd automatically when the app starts">
            <input type="checkbox" checked={autostart} onChange={() => toggleAutostart()} disabled={busy} />
            Start with the app
          </label>
          <button className="btn-ghost !py-1 text-xs" onClick={rescan} disabled={busy || !running}>
            <RefreshCw className="h-3.5 w-3.5" /> Rescan
          </button>
        </div>
      </div>
      {dirs !== null && (
        <div className="space-y-1">
          {dirs.map((d) => (
            <div key={d} className="flex items-center gap-2">
              <FolderOpen className="h-3.5 w-3.5 text-zinc-600 shrink-0" />
              <span className="truncate flex-1 font-mono text-[11px] text-zinc-300" title={d}>{d}</span>
              <button
                className="text-zinc-600 hover:text-red-300 shrink-0"
                onClick={() => setDirs(dirs.filter((x) => x !== d))}
                title="Stop sharing this folder"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <input
              className="input !py-1 flex-1 font-mono text-[11px]"
              placeholder="Add a folder to share (full path)"
              value={newDir}
              onChange={(e) => setNewDir(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newDir.trim()) {
                  setDirs([...(dirs ?? []), newDir.trim()]);
                  setNewDir("");
                }
              }}
            />
            <button
              className="btn-ghost !py-1 text-xs"
              disabled={!newDir.trim()}
              onClick={() => {
                setDirs([...(dirs ?? []), newDir.trim()]);
                setNewDir("");
              }}
            >
              Add
            </button>
          </div>
          {dirty && (
            <button className="btn-primary !py-1 text-xs w-full" onClick={() => save()} disabled={busy}>
              {busy ? "Applying…" : "Save & apply (restarts slskd to rescan)"}
            </button>
          )}
        </div>
      )}
      <div className="text-[10px] text-zinc-600">
        Reserved folders are never shared: Data (app state), .mlo_downloads, .mlo_trash.
      </div>
    </div>
  );
}

export default function SoulseekPage() {
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

  const running = !!status?.running;

  // Start/stop transitions poll status once a second (instead of waiting for
  // the 10s background refresh) so pressing the button feels immediate.
  const [pending, setPending] = useState<null | "start" | "stop">(null);
  useEffect(() => {
    if (!pending) return;
    const iv = setInterval(refetchStatus, 1000);
    const timeout = setTimeout(() => setPending(null), 45000);
    return () => {
      clearInterval(iv);
      clearTimeout(timeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);
  useEffect(() => {
    if (pending === "start" && running) {
      setPending(null);
      toast("slskd is up");
    }
    if (pending === "stop" && !running) {
      setPending(null);
      toast("slskd stopped");
    }
  }, [pending, running]);

  // Network ports — saved into the app settings; slskd re-reads them from
  // its generated config at every start (saving while running restarts it).
  const [listenPort, setListenPort] = useState("");
  const [webPort, setWebPort] = useState("");
  const [portsBusy, setPortsBusy] = useState(false);
  useEffect(() => {
    setListenPort(String(status?.listen_port ?? ""));
    setWebPort(String(status?.web_port ?? ""));
  }, [status?.listen_port, status?.web_port]);
  const portsChanged =
    !!status && (Number(listenPort) !== Number(status.listen_port) || Number(webPort) !== Number(status.web_port));
  const savePorts = async () => {
    setPortsBusy(true);
    try {
      await api.saveConfig({
        soulseek_listen_port: Number(listenPort) || 50000,
        soulseek_web_port: Number(webPort) || 5030,
      });
      if (running) {
        await api.soulseekRestart();
        toast(`Ports saved — slskd restarted on ${Number(listenPort)}/${Number(webPort)}`);
      } else {
        toast("Ports saved — applied at the next start");
      }
      refetchStatus();
    } catch (e) {
      toast(String(e));
    } finally {
      setPortsBusy(false);
    }
  };

  const [query, setQuery] = useState("");
  const [searchId, setSearchId] = useState<string | null>(null);
  const [results, setResults] = useState<SlskFile[]>([]);
  const [searching, setSearching] = useState(false);
  const [busyUser, setBusyUser] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterId>("all");
  const [closedGroups, setClosedGroups] = useState<Set<string>>(new Set()); // groups OPEN by default
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
      setPending("start");
      const r = await api.soulseekStart();
      if (r.ready === false) toast("slskd is starting — coming up in a moment");
      // "slskd is up" toast fires when the status poll sees it running
    } catch (e) {
      setPending(null);
      toast(String(e));
    }
  };

  const stop = async () => {
    try {
      setPending("stop");
      await api.soulseekStop();
    } catch (e) {
      setPending(null);
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

  const groups = useMemo(() => groupResults(results), [results]);
  const visible = groups.filter((g) => groupMatches(g, filter));
  const counts: Record<FilterId, number> = {
    all: groups.length,
    cdrip: groups.filter((g) => g.isCdRip).length,
    lossless: groups.filter((g) => g.lossless).length,
    lossy: groups.filter((g) => g.format === "MP3" || g.format === "M4A" || g.format === "AAC").length,
  };
  const toggleGroup = (key: string) =>
    setClosedGroups((prev) => {
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

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Soulseek</h1>
          <div className="text-xs text-zinc-500 mt-0.5">
            Managed slskd · {pending === "start" ? (
              <span className="text-amber-300">starting…</span>
            ) : pending === "stop" ? (
              <span className="text-amber-300">stopping…</span>
            ) : running ? (
              <span className="text-emerald-400">running{status?.logged_in ? " · logged in" : status?.logged_in === false ? " · not logged in" : ""}</span>
            ) : "stopped"}
            {" · downloads: "}{status?.download_dir ?? "—"}
            {running && status?.server?.uploadSpeed != null && (
              <>
                {" · "}
                <span className="text-zinc-400">
                  ↓ {fmtRate(status.server.downloadSpeed)} · ↑ {fmtRate(status.server.uploadSpeed)}
                </span>
              </>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {running ? (
            <button className="btn-ghost" onClick={stop} disabled={pending !== null}>
              {pending === "stop" ? "Stopping…" : <><Power className="h-4 w-4" /> Stop</>}
            </button>
          ) : (
            <button className="btn-primary" onClick={start} disabled={pending !== null}>
              {pending === "start" ? "Starting…" : <><Play className="h-4 w-4" /> Start slskd</>}
            </button>
          )}
          <button className="btn-ghost" onClick={() => { refetchStatus(); refetchDownloads(); }}><RefreshCw className="h-4 w-4" /></button>
        </div>
      </div>

      {status && (
        <div className="bg-card rounded-lg border border-border p-3 flex items-center gap-2 flex-wrap text-xs">
          <span className="text-[10px] uppercase tracking-widest text-zinc-500 mr-1">Ports</span>
          <label className="flex items-center gap-1.5 text-zinc-500">
            Listen (Soulseek)
            <input
              className="input w-28 !py-1 !px-2 font-mono"
              inputMode="numeric"
              value={listenPort}
              onChange={(e) => setListenPort(e.target.value.replace(/\D/g, ""))}
              title="Port the Soulseek network sees (listen_port in slskd)"
            />
          </label>
          <label className="flex items-center gap-1.5 text-zinc-500">
            Web UI
            <input
              className="input w-28 !py-1 !px-2 font-mono"
              inputMode="numeric"
              value={webPort}
              onChange={(e) => setWebPort(e.target.value.replace(/\D/g, ""))}
              title="Local slskd API/web port"
            />
          </label>
          <button className="btn-ghost !py-1 text-xs" disabled={!portsChanged || portsBusy} onClick={savePorts}>
            <Save className="h-3.5 w-3.5" /> {portsBusy ? "Saving…" : "Save"}
          </button>
          <span className="text-[10px] text-zinc-600">
            saved in settings · {running ? "saving restarts slskd to apply" : "applied at the next start"}
          </span>
        </div>
      )}

      <SharingCard running={running} />

      {running && status?.logged_in === false && (
        status?.has_credentials ? (
          <ReconnectingCard
            username={String(status.username ?? "")}
            password={String(status.password ?? "")}
            onDone={refetchStatus}
          />
        ) : (
          <LoginCard onDone={refetchStatus} />
        )
      )}

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
                const open = !closedGroups.has(g.key);
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
                          <span>· {g.files.length} file(s) · {fmtSize(g.totalSize)}</span>
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

      <ReviewPanel />

      <div className="bg-card rounded-lg border border-border p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Downloads</div>
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
