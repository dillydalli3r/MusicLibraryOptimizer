import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { HardDriveDownload, Search } from "lucide-react";
import { api } from "../api";
import { toast, useStore } from "../store";
import CoverImg from "../components/CoverImg";

/** Quality choices per export codec — the backend interprets the string. */
const QUALITY: Record<string, { v: string; label: string }[]> = {
  copy: [],
  flac: [
    { v: "8", label: "level 8 (smallest, slowest)" },
    { v: "5", label: "level 5 (balanced)" },
    { v: "0", label: "level 0 (fastest)" },
  ],
  mp3: [
    { v: "V0", label: "V0 (~245 kbps VBR, best)" },
    { v: "V2", label: "V2 (~175 kbps VBR)" },
    { v: "320", label: "320 kbps CBR" },
    { v: "256", label: "256 kbps CBR" },
    { v: "192", label: "192 kbps CBR" },
    { v: "128", label: "128 kbps CBR" },
  ],
  aac: [
    { v: "320", label: "320 kbps" },
    { v: "256", label: "256 kbps" },
    { v: "192", label: "192 kbps" },
    { v: "128", label: "128 kbps" },
  ],
  opus: [
    { v: "256", label: "256 kbps" },
    { v: "192", label: "192 kbps" },
    { v: "160", label: "160 kbps" },
    { v: "128", label: "128 kbps" },
    { v: "96", label: "96 kbps" },
  ],
  vorbis: [
    { v: "q10", label: "q10 (~320 kbps, best)" },
    { v: "q8", label: "q8 (~256 kbps)" },
    { v: "q6", label: "q6 (~192 kbps)" },
    { v: "q4", label: "q4 (~160 kbps)" },
  ],
};

const STRUCTURES = [
  { v: "artist_album", label: "Artist / Album / 01 - Title" },
  { v: "flat", label: "Flat — one folder" },
  { v: "mirror", label: "Mirror library layout" },
];

function fmtGB(n: number | null): string {
  return n === null ? "—" : `${(n / 1024 ** 3).toFixed(1)} GB`;
}

/** Export playlists / albums to a target drive with codec + quality +
 * folder-structure choices — the "put music on my MP3 player" feature. */
export default function ExportPage() {
  const { setToast } = useStore();
  const { data: lib } = useQuery({ queryKey: ["library"], queryFn: api.library });
  const { data: playlists } = useQuery({ queryKey: ["playlists"], queryFn: api.playlists });
  const { data: drivesData } = useQuery({ queryKey: ["exportDrives"], queryFn: api.exportDrives });

  const [sourceKind, setSourceKind] = useState<"playlist" | "albums">("playlist");
  const [playlistId, setPlaylistId] = useState<number | null>(null);
  const [albumPaths, setAlbumPaths] = useState<Set<string>>(new Set());
  const [albumFilter, setAlbumFilter] = useState("");
  const [drive, setDrive] = useState("");
  const [subfolder, setSubfolder] = useState("Music");
  const [codec, setCodec] = useState("copy");
  const [quality, setQuality] = useState("");
  const [structure, setStructure] = useState("artist_album");
  const [busy, setBusy] = useState(false);

  const albums = useMemo(() => lib?.artists?.flatMap((a: any) => a.albums ?? []) ?? [], [lib]);
  const filteredAlbums = useMemo(() => {
    const q = albumFilter.toLowerCase();
    return albums.filter(
      (a: any) => !q || (a.meta?.ALBUM ?? "").toLowerCase().includes(q) || (a.artist ?? "").toLowerCase().includes(q)
    );
  }, [albums, albumFilter]);

  const { data: playlistDetail } = useQuery({
    queryKey: ["playlist", playlistId],
    queryFn: () => api.playlist(playlistId!),
    enabled: sourceKind === "playlist" && playlistId !== null,
  });

  // Resolve the exact track files for the chosen source.
  const paths = useMemo(() => {
    if (sourceKind === "playlist") return playlistDetail?.tracks ?? [];
    const out: string[] = [];
    for (const a of albums) {
      if (albumPaths.has(a.path)) {
        for (const t of a.tracks ?? []) out.push(t.path);
      }
    }
    return out;
  }, [sourceKind, playlistDetail, albums, albumPaths]);

  const run = async () => {
    if (!paths.length) return toast("Select something to export first");
    const destRoot = drivesData?.drives.find((d) => d.root === drive)?.root;
    if (!destRoot) return toast("Choose a destination drive");
    setBusy(true);
    setToast(`Exporting ${paths.length} track(s)…`);
    try {
      const r = await api.exportRun({
        paths, dest: destRoot, subfolder, codec,
        quality: quality || QUALITY[codec]?.[0]?.v || "",
        structure,
      });
      const gb = (r.bytes / 1024 ** 3).toFixed(2);
      setToast(
        r.failed
          ? `Export finished with ${r.failed} failure(s): ${r.errors[0] ?? ""}`
          : `Exported ${r.exported} track(s)${r.skipped ? ` (${r.skipped} already there)` : ""} · ${gb} GB`
      );
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
        <HardDriveDownload className="h-6 w-6" /> Export
      </h1>
      <p className="text-xs text-zinc-500 mt-1">
        Copy or convert playlists and albums onto a drive — MP3 players, DAPs, car USB. Tags and
        artwork ride along; already-exported tracks are skipped on re-runs.
      </p>

      <div className="grid md:grid-cols-2 gap-4 mt-5">
        {/* ---- source ------------------------------------------------- */}
        <div className="bg-card rounded-lg border border-border p-4">
          <div className="text-xs font-bold text-zinc-300 mb-2">Source</div>
          <div className="flex gap-1.5 mb-3">
            {(["playlist", "albums"] as const).map((k) => (
              <button
                key={k}
                className={`chip text-[11px] border ${sourceKind === k ? "bg-accent on-accent border-accent" : "bg-white/5 border-white/15 text-zinc-400 hover:text-white"}`}
                onClick={() => setSourceKind(k)}
              >
                {k === "playlist" ? "Playlist" : "Albums"}
              </button>
            ))}
          </div>
          {sourceKind === "playlist" ? (
            <select
              className="input !py-1 text-xs w-full"
              value={playlistId ?? ""}
              onChange={(e) => setPlaylistId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Choose a playlist…</option>
              {(playlists ?? []).map((pl) => (
                <option key={pl.id} value={pl.id}>
                  {pl.name} ({pl.track_count})
                </option>
              ))}
            </select>
          ) : (
            <>
              <div className="relative mb-2">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
                <input
                  className="input !py-1 !pl-7 text-xs w-full"
                  placeholder="Filter albums / artists…"
                  value={albumFilter}
                  onChange={(e) => setAlbumFilter(e.target.value)}
                />
              </div>
              <div className="max-h-64 overflow-y-auto border border-border rounded-md divide-y divide-border/60">
                {filteredAlbums.map((a: any) => (
                  <label
                    key={a.path}
                    className="flex items-center gap-2 px-2 py-1.5 text-xs text-zinc-300 hover:bg-panel cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={albumPaths.has(a.path)}
                      onChange={() =>
                        setAlbumPaths((prev) => {
                          const next = new Set(prev);
                          next.has(a.path) ? next.delete(a.path) : next.add(a.path);
                          return next;
                        })
                      }
                    />
                    <CoverImg albumPath={a.path} coverFile={a.cover_file} wrapperClass="h-6 w-6 rounded bg-raise border border-border overflow-hidden shrink-0" />
                    <span className="truncate flex-1">{a.meta?.ALBUM ?? a.path}</span>
                    <span className="text-zinc-600 shrink-0">{a.artist}</span>
                  </label>
                ))}
                {!filteredAlbums.length && (
                  <div className="px-2 py-3 text-[11px] text-zinc-600">No albums match.</div>
                )}
              </div>
            </>
          )}
          <div className="text-[11px] text-zinc-500 mt-2">
            {paths.length} track{paths.length === 1 ? "" : "s"} selected
          </div>
        </div>

        {/* ---- destination + options ---------------------------------- */}
        <div className="bg-card rounded-lg border border-border p-4">
          <div className="text-xs font-bold text-zinc-300 mb-2">Destination</div>
          <select
            className="input !py-1 text-xs w-full"
            value={drive}
            onChange={(e) => setDrive(e.target.value)}
          >
            <option value="">Choose a drive…</option>
            {(drivesData?.drives ?? []).map((d) => (
              <option key={d.root} value={d.root}>
                {d.letter} {d.type !== "fixed" ? `(${d.type})` : ""} — {fmtGB(d.free)} free
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 mt-2 text-xs text-zinc-300">
            <span className="shrink-0">Subfolder</span>
            <input className="input !py-1 text-xs flex-1" value={subfolder} onChange={(e) => setSubfolder(e.target.value)} />
          </label>

          <div className="text-xs font-bold text-zinc-300 mt-4 mb-2">Format</div>
          <div className="grid grid-cols-2 gap-2">
            <select
              className="input !py-1 text-xs"
              value={codec}
              onChange={(e) => {
                setCodec(e.target.value);
                setQuality("");
              }}
            >
              {Object.entries(api_codec_labels).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
            <select
              className="input !py-1 text-xs"
              value={quality || QUALITY[codec]?.[0]?.v || ""}
              onChange={(e) => setQuality(e.target.value)}
              disabled={codec === "copy"}
            >
              {(QUALITY[codec] ?? []).map((q) => (
                <option key={q.v} value={q.v}>{q.label}</option>
              ))}
            </select>
          </div>
          <select
            className="input !py-1 text-xs mt-2 w-full"
            value={structure}
            onChange={(e) => setStructure(e.target.value)}
          >
            {STRUCTURES.map((s) => (
              <option key={s.v} value={s.v}>{s.label}</option>
            ))}
          </select>

          <button className="btn-primary w-full mt-4 text-xs" disabled={busy || !paths.length} onClick={run}>
            <HardDriveDownload className="h-3.5 w-3.5" />
            {busy ? "Exporting…" : `Export ${paths.length || ""} track${paths.length === 1 ? "" : "s"}`}
          </button>
          <div className="text-[10px] text-zinc-600 mt-2">
            FLAC → FLAC exports are bit-copies; anything else is re-encoded with ffmpeg and fully re-tagged.
          </div>
        </div>
      </div>
    </div>
  );
}

// codec -> display label (mirrors server/exporter.py CODECS labels)
const api_codec_labels: Record<string, string> = {
  copy: "Copy (original codec)",
  flac: "FLAC (lossless)",
  mp3: "MP3",
  aac: "AAC / M4A",
  opus: "Opus",
  vorbis: "Ogg Vorbis",
};
