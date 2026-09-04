import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListMusic, Plus, Trash2, Download, Upload, Play, ChevronUp, ChevronDown, Pencil } from "lucide-react";
import { api } from "../api";
import { toast, useStore } from "../store";
import { EmptyState, AuditBadge } from "../components/Badges";
import type { Playlist, FilterCondition } from "../types";

const FIELDS = [
  { value: "grade_pass", label: "Grade (pass/fail)" },
  { value: "audit", label: "Audit" },
  { value: "tags.GENRE", label: "Genre" },
  { value: "tags.ITUNESADVISORY", label: "Advisory" },
  { value: "tags.INSTRUMENTAL", label: "Instrumental" },
  { value: "tags.MEDIA", label: "Media" },
  { value: "tags.SOURCE", label: "Source" },
  { value: "tags.DATE", label: "Year" },
  { value: "lyrics_present", label: "Has lyrics" },
  { value: "tech.length", label: "Duration (s)" },
  { value: "tech.bitrate", label: "Bitrate" },
  { value: "tags.TITLE", label: "Title" },
];

const OPS = [
  { value: "eq", label: "=" },
  { value: "ne", label: "≠" },
  { value: "contains", label: "contains" },
  { value: "lt", label: "<" },
  { value: "gt", label: ">" },
  { value: "missing", label: "is missing" },
  { value: "present", label: "is present" },
];

export default function PlaylistsPage() {
  const qc = useQueryClient();
  const { playNow } = useStore();
  const { data: playlists, isLoading } = useQuery({ queryKey: ["playlists"], queryFn: api.playlists });
  const { data: lib } = useQuery({ queryKey: ["library"], queryFn: api.library });
  // path -> tag-derived artist/album so the player bar shows real names
  const trackInfo = useMemo(() => {
    const map = new Map<string, { artist?: string; album?: string }>();
    for (const a of lib?.artists ?? [])
      for (const al of a.albums)
        for (const t of al.tracks)
          map.set(t.path, { artist: al.album_artist || a.name, album: al.meta?.ALBUM ?? undefined });
    return map;
  }, [lib]);
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<Playlist | null>(null);
  const [conditions, setConditions] = useState<FilterCondition[]>([]);
  const [matchAll, setMatchAll] = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: ["playlists"] });

  const create = useMutation({
    mutationFn: async () => {
      if (!newName.trim()) return;
      const p = await api.createPlaylist(newName.trim(), "manual");
      setNewName("");
      return p;
    },
    onSuccess: () => refresh(),
  });

  const del = useMutation({
    mutationFn: (id: number) => api.deletePlaylist(id),
    onSuccess: () => refresh(),
  });

  const smartFilter = (p: Playlist) => {
    setEditing(p);
    setConditions(p.filter?.conditions ?? []);
    setMatchAll(p.filter?.match !== "any");
  };

  const saveSmart = async () => {
    if (!editing) return;
    await api.playlistFilter(editing.id, { conditions, match: matchAll ? "all" : "any" });
    const ev = await api.playlistEvaluate(editing.id);
    await api.playlistOrder(editing.id, ev.paths);
    setEditing(null);
    refresh();
    toast("Smart playlist updated");
  };

  const importM3u8 = async (file: File) => {
    await api.playlistImport(file.name.replace(/\.m3u8?$/i, ""), file);
    refresh();
    toast("Playlist imported");
  };

  if (isLoading) return <div className="p-8 text-zinc-500">Loading playlists…</div>;

  const manual = (playlists ?? []).filter((p) => p.kind === "manual");
  const smart = (playlists ?? []).filter((p) => p.kind === "smart");

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <ListMusic className="h-6 w-6 text-accent" /> Playlists
        </h1>
        <input
          className="input max-w-xs ml-auto"
          placeholder="New playlist name…"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create.mutate()}
        />
        <button className="btn-primary" onClick={() => create.mutate()} disabled={!newName.trim()}>
          <Plus className="h-4 w-4" /> Create
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".m3u8,.m3u"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && importM3u8(e.target.files[0])}
        />
        <button className="btn-ghost" onClick={() => fileRef.current?.click()}>
          <Upload className="h-4 w-4" /> Import .m3u8
        </button>
      </div>

      {manual.length === 0 && smart.length === 0 && (
        <EmptyState title="No playlists yet" hint="Create a manual playlist, or import an .m3u8 file." />
      )}

      {manual.map((p) => (
        <PlaylistCard key={p.id} playlist={p} onDelete={() => del.mutate(p.id)} onPlay={(paths) => playNow(paths.map((path) => ({
              path,
              file: path.split("/").pop()!,
              albumPath: path.split("/").slice(0, -1).join("/"),
              artist: trackInfo.get(path)?.artist,
              album: trackInfo.get(path)?.album,
            })))} onSmart={() => smartFilter(p)} />
      ))}

      {smart.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500 mb-2">Smart playlists</h2>
          {smart.map((p) => (
            <PlaylistCard key={p.id} playlist={p} onDelete={() => del.mutate(p.id)} onPlay={(paths) => playNow(paths.map((path) => ({
              path,
              file: path.split("/").pop()!,
              albumPath: path.split("/").slice(0, -1).join("/"),
              artist: trackInfo.get(path)?.artist,
              album: trackInfo.get(path)?.album,
            })))} onSmart={() => smartFilter(p)} />
          ))}
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center" onClick={() => setEditing(null)}>
          <div className="bg-card border border-border rounded-xl p-5 w-[560px] max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-semibold mb-3">Smart playlist: {editing.name}</h3>
            <label className="flex items-center gap-2 text-sm text-zinc-400 mb-3">
              <input type="checkbox" checked={matchAll} onChange={(e) => setMatchAll(e.target.checked)} className="" />
              Match all conditions (AND)
            </label>
            <div className="space-y-2">
              {conditions.map((c, i) => (
                <div key={i} className="flex gap-2">
                  <select className="input flex-1" value={c.field} onChange={(e) => setConditions((cs) => cs.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))}>
                    {FIELDS.map((f) => (
                      <option key={f.value} value={f.value}>{f.label}</option>
                    ))}
                  </select>
                  <select className="input w-28" value={c.op} onChange={(e) => setConditions((cs) => cs.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))}>
                    {OPS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  {!["missing", "present"].includes(c.op) && (
                    <input className="input w-32" value={String(c.value ?? "")} onChange={(e) => setConditions((cs) => cs.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                  )}
                  <button className="btn-danger !px-2" onClick={() => setConditions((cs) => cs.filter((_, j) => j !== i))}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
            <button className="btn-ghost mt-2 text-xs" onClick={() => setConditions((cs) => [...cs, { field: "grade_pass", op: "eq", value: false }])}>
              <Plus className="h-3.5 w-3.5" /> Add condition
            </button>
            <div className="flex justify-end gap-2 mt-4">
              <button className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
              <button className="btn-primary" onClick={saveSmart}>Save & evaluate</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PlaylistCard({ playlist, onDelete, onPlay, onSmart }: { playlist: Playlist; onDelete: () => void; onPlay: (paths: string[]) => void; onSmart: () => void }) {
  const qc = useQueryClient();
  const { data: detail } = useQuery({ queryKey: ["playlist", playlist.id], queryFn: () => api.playlist(playlist.id) });
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(playlist.name);
  const { data: lib } = useQuery({ queryKey: ["library"], queryFn: api.library });

  const { tracks = [] } = detail ?? {};

  const move = async (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= tracks.length) return;
    const next = [...tracks];
    [next[i], next[j]] = [next[j], next[i]];
    await api.playlistOrder(playlist.id, next);
    qc.invalidateQueries({ queryKey: ["playlist", playlist.id] });
  };

  const rename = async () => {
    await api.renamePlaylist(playlist.id, name);
    setRenaming(false);
    qc.invalidateQueries({ queryKey: ["playlists"] });
  };

  const removeTrack = async (path: string) => {
    await api.playlistRemove(playlist.id, [path]);
    qc.invalidateQueries({ queryKey: ["playlist", playlist.id] });
    qc.invalidateQueries({ queryKey: ["playlists"] });
  };

  const trackMeta = useMemo(() => {
    const map = new Map<string, { title: string; audit: string | null; pass: boolean; artist?: string; album?: string }>();
    for (const a of lib?.artists ?? [])
      for (const al of a.albums)
        for (const t of al.tracks)
          map.set(t.path, {
            title: t.tags.TITLE ?? t.file,
            audit: t.audit,
            pass: t.grade_pass,
            artist: al.album_artist || a.name,
            album: al.meta?.ALBUM ?? undefined,
          });
    return map;
  }, [lib]);

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-2.5">
        {renaming ? (
          <>
            <input className="input max-w-xs" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && rename()} />
            <button className="btn-primary text-xs" onClick={rename}>Save</button>
          </>
        ) : (
          <span className="font-semibold">{playlist.name}</span>
        )}
        {playlist.kind === "smart" && (
          <span className="chip bg-accent/10 text-accent-soft border border-accent/25">SMART</span>
        )}
        <span className="text-xs text-zinc-500">{tracks.length} tracks</span>
        <div className="ml-auto flex gap-1.5">
          <button className="btn-ghost !px-2 !py-1 text-xs" onClick={() => onPlay(tracks)}><Play className="h-3.5 w-3.5" /></button>
          <a className="btn-ghost !px-2 !py-1 text-xs" href={api.playlistExportUrl(playlist.id)}><Download className="h-3.5 w-3.5" /></a>
          {playlist.kind === "smart" && (
            <button className="btn-ghost !px-2 !py-1 text-xs" onClick={onSmart}><Pencil className="h-3.5 w-3.5" /></button>
          )}
          <button className="btn-ghost !px-2 !py-1 text-xs" onClick={() => setRenaming(!renaming)} title="Rename"><Pencil className="h-3.5 w-3.5" /></button>
          <button className="btn-danger !px-2 !py-1 text-xs" onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /></button>
        </div>
      </div>
      {tracks.length > 0 && (
        <div className="border-t border-border/60 max-h-72 overflow-auto">
          {tracks.map((t, i) => (
            <div key={`${playlist.id}-${i}-${t}`} className="flex items-center gap-2 px-4 py-1.5 text-sm border-t border-border/40 first:border-t-0 hover:bg-panel">
              <span className="text-xs text-zinc-600 w-6">{i + 1}</span>
              <span className="flex-1 truncate">{trackMeta.get(t)?.title ?? t.split("/").pop()}</span>
              <AuditBadge audit={trackMeta.get(t)?.audit ?? null} size="sm" />
              <div className="flex gap-0.5">
                <button className="text-zinc-600 hover:text-zinc-300 disabled:opacity-30" onClick={() => move(i, -1)} disabled={i === 0}><ChevronUp className="h-4 w-4" /></button>
                <button className="text-zinc-600 hover:text-zinc-300 disabled:opacity-30" onClick={() => move(i, 1)} disabled={i === tracks.length - 1}><ChevronDown className="h-4 w-4" /></button>
                {playlist.kind === "manual" && (
                  <button
                    className="text-zinc-600 hover:text-red-400 ml-1"
                    title="Remove from playlist"
                    onClick={() => removeTrack(t)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}