import { useState } from "react";
import { Download, FileOutput } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";

/** Codec choices for per-track exports; lossy codecs expose a bitrate. */
const CODECS = [
  { id: "flac", label: "FLAC (lossless)", lossy: false },
  { id: "alac", label: "ALAC (lossless)", lossy: false },
  { id: "wav", label: "WAV (lossless)", lossy: false },
  { id: "mp3", label: "MP3", lossy: true, defaultBitrate: 320 },
  { id: "aac", label: "AAC / M4A", lossy: true, defaultBitrate: 256 },
  { id: "opus", label: "Opus", lossy: true, defaultBitrate: 192 },
];

const BITRATES = [96, 128, 160, 192, 256, 320, 448, 500];

/** "Download" keeps the original file as a browser download; "Export"
 * transcodes to the chosen codec/bitrate server-side and saves that. */
export default function TrackDownloadExport({ path, title, compact }: {
  path: string;
  title?: string;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [codec, setCodec] = useState("flac");
  const [bitrate, setBitrate] = useState(320);
  const [busy, setBusy] = useState(false);
  const chosen = CODECS.find((c) => c.id === codec) ?? CODECS[0];

  const downloadOriginal = () => {
    // a real navigation (not fetch) keeps the file in the browser's
    // downloads like any other link
    const a = document.createElement("a");
    a.href = api.trackDownloadUrl(path);
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast("Download started");
  };

  const exportTrack = async () => {
    setBusy(true);
    try {
      const a = document.createElement("a");
      a.href = api.trackExportUrl(path, codec, bitrate);
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast(`Exporting as ${chosen.label}${chosen.lossy ? ` @ ${bitrate} kbps` : ""} — the save dialog opens when it's ready`);
      setOpen(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={compact ? "inline-flex items-center gap-1" : "flex items-center gap-1.5 flex-wrap"}>
      <button
        className="btn-ghost !py-1 text-xs"
        onClick={downloadOriginal}
        title="Save the original, untouched file in the browser"
      >
        <Download className="h-3.5 w-3.5" /> Download
      </button>
      <div className="relative">
        <button
          className="btn-ghost !py-1 text-xs"
          onClick={() => setOpen(!open)}
          title="Transcode and save as FLAC / MP3 / … with a chosen bitrate"
        >
          <FileOutput className="h-3.5 w-3.5" /> Export
        </button>
        {open && (
          <div className="absolute z-50 right-0 mt-1 w-60 glass rounded-lg bg-zinc-950/95 border border-border shadow-2xl p-2.5 space-y-2">
            {title && <div className="text-[11px] text-zinc-400 truncate">{title}</div>}
            <label className="block text-[10px] uppercase tracking-wider text-zinc-500">Codec</label>
            <select className="input !py-1 text-xs" value={codec} onChange={(e) => {
              setCodec(e.target.value);
              const c = CODECS.find((x) => x.id === e.target.value);
              if (c?.lossy && c.defaultBitrate) setBitrate(c.defaultBitrate);
            }}>
              {CODECS.map((c) => (
                <option key={c.id} value={c.id}>{c.label}</option>
              ))}
            </select>
            {chosen.lossy && (
              <>
                <label className="block text-[10px] uppercase tracking-wider text-zinc-500">Bitrate</label>
                <select className="input !py-1 text-xs" value={bitrate} onChange={(e) => setBitrate(Number(e.target.value))}>
                  {BITRATES.map((b) => (
                    <option key={b} value={b}>{b} kbps</option>
                  ))}
                </select>
              </>
            )}
            <button className="btn-primary w-full !py-1.5 text-xs" onClick={exportTrack} disabled={busy}>
              {busy ? "Preparing…" : `Export ${chosen.label}${chosen.lossy ? ` · ${bitrate}k` : ""}`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
