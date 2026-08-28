import { useEffect, useRef, useState } from "react";
import { CloudDownload, Play, Square, Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";

export interface LrcLine {
  ts: string; // [mm:ss.xx]
  time: number; // seconds
  text: string;
}

export function parseLrc(lrc: string): LrcLine[] {
  const re = /\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g;
  const lines: LrcLine[] = [];
  for (const raw of lrc.split(/\r?\n/)) {
    const matches = [...raw.matchAll(re)];
    if (!matches.length) continue;
    const text = raw.replace(re, "").trim();
    for (const m of matches) {
      const mm = parseInt(m[1], 10);
      const ss = parseInt(m[2], 10);
      const frac = (m[3] ?? "0").padEnd(2, "0").slice(0, 2);
      const time = mm * 60 + ss + parseInt(frac, 10) / 100;
      lines.push({ ts: `[${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}.${frac}]`, time, text });
    }
  }
  return lines.sort((a, b) => a.time - b.time);
}

export function serializeLrc(lines: LrcLine[], decimals = 2): string {
  return lines
    .map((l) => {
      const mm = Math.floor(l.time / 60);
      const ss = Math.floor(l.time % 60);
      const frac = Math.round((l.time - Math.floor(l.time)) * 10 ** decimals);
      const fracStr = String(frac).padStart(decimals, "0");
      return `[${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}.${fracStr}]${l.text}`;
    })
    .join("\n");
}

export default function LyricsViewer({
  path,
  initialLyrics,
  onChange,
  artist,
  track,
  album,
  decimals = 2,
}: {
  path: string;
  initialLyrics: string;
  onChange: (lrc: string) => void;
  artist?: string;
  track?: string;
  album?: string;
  decimals?: number;
}) {
  const [lines, setLines] = useState<LrcLine[]>(() => parseLrc(initialLyrics));
  const [rawMode, setRawMode] = useState(false);
  const [raw, setRaw] = useState(initialLyrics);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [selIdx, setSelIdx] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => setLines(parseLrc(initialLyrics)), [initialLyrics]);

  useEffect(() => {
    if (!lines.length) return;
    const idx = lines.findIndex((l) => l.time > current + 0.05);
    const shown = idx === -1 ? lines.length - 1 : Math.max(0, idx - 1);
    if (shown !== current && shown >= 0) {
      setCurrent(shown);
      lineRefs.current[shown]?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [current, lines]);

  // Spacebar = stamp current playback time into the selected lyric line.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) {
        if (e.code === "Space") {
          e.preventDefault();
          stampTime();
        }
        return;
      }
      if (e.code === "Space") {
        e.preventDefault();
        stampTime();
      }
    };
    const stampTime = () => {
      const audio = audioRef.current;
      if (!audio || !playing) return;
      const t = Math.max(0, audio.currentTime - 0.05);
      setLines((ls) => {
        const next = [...ls];
        const target = Math.min(selIdx, Math.max(0, next.length - 1));
        if (next[target]) next[target] = { ...next[target], time: t };
        emit(next);
        return next;
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, selIdx, lines.length]);

  const emit = (ls: LrcLine[]) => {
    onChange(serializeLrc(ls, decimals));
  };

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
    } else {
      audio.src = api.streamUrl(path);
      audio.play().catch(() => toast("Playback failed"));
      setPlaying(true);
    }
  };

  const importFromLrclib = async () => {
    if (!artist || !track) {
      toast("Track needs ARTIST and TITLE tags first");
      return;
    }
    setLoading(true);
    try {
      const res = await api.lyricsGet(artist, track, album);
      const lrc = res?.syncedLyrics ?? res?.plainLyrics;
      if (!lrc) {
        toast("No lyrics found on LRCLIB");
        return;
      }
      const parsed = parseLrc(lrc);
      if (!parsed.length) {
        toast("LRCLIB returned unsynced lyrics — check the track page");
        return;
      }
      setLines(parsed);
      emit(parsed);
      toast("Imported from LRCLIB");
    } catch (e) {
      toast(String(e));
    } finally {
      setLoading(false);
    }
  };

  const updateLine = (i: number, patch: Partial<LrcLine>) => {
    setLines((ls) => {
      const next = [...ls];
      next[i] = { ...next[i], ...patch };
      emit(next);
      return next;
    });
  };

  const addLine = (i: number) => {
    const base = lines[i]?.time ?? lines[lines.length - 1]?.time ?? 0;
    setLines((ls) => {
      const next = [...ls];
      next.splice(i + 1, 0, { ts: "[00:00.00]", time: base, text: "" });
      emit(next);
      return next;
    });
    setSelIdx(i + 1);
  };

  const removeLine = (i: number) => {
    setLines((ls) => {
      const next = ls.filter((_, j) => j !== i);
      emit(next);
      return next;
    });
  };

  return (
    <div className="bg-card rounded-lg border border-border p-4 flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Lyrics</div>
        <div className="flex gap-1.5">
          <button className="btn-ghost !py-1 text-xs" onClick={togglePlay}>
            {playing ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {playing ? "Stop" : "Preview"}
          </button>
          <button className="btn-ghost !py-1 text-xs" onClick={importFromLrclib} disabled={loading}>
            <CloudDownload className="h-3.5 w-3.5" /> LRCLIB
          </button>
          <button
            className="btn-ghost !py-1 text-xs"
            onClick={() => {
              setRawMode(!rawMode);
              setRaw(serializeLrc(lines, decimals));
            }}
          >
            {rawMode ? "Lines" : "Raw"}
          </button>
        </div>
      </div>

      <audio ref={audioRef} onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)} onEnded={() => setPlaying(false)} className="hidden" />

      {rawMode ? (
        <textarea
          className="input flex-1 font-mono text-xs min-h-[300px]"
          value={raw}
          onChange={(e) => {
            setRaw(e.target.value);
            onChange(e.target.value);
          }}
        />
      ) : lines.length === 0 ? (
        <div className="text-sm text-zinc-500 py-10 text-center">
          No lyrics. Press <kbd className="chip bg-raise border border-border">Space</kbd> while previewing to stamp the
          selected line's timestamp, or import from LRCLIB.
        </div>
      ) : (
        <div className="flex-1 space-y-1.5 max-h-[420px] overflow-auto pr-1">
          {lines.map((l, i) => (
            <div
              key={i}
              ref={(el) => { lineRefs.current[i] = el; }}
              className={`group flex items-center gap-2 rounded-md border px-2 py-1.5 transition-colors ${
                i === current && playing
                  ? "border-accent/50 bg-violet-950/30"
                  : "border-transparent hover:border-border hover:bg-panel"
              }`}
              onClick={() => setSelIdx(i)}
            >
              <input
                className="w-[88px] bg-transparent font-mono text-xs text-zinc-400 outline-none border border-transparent focus:border-accent rounded px-1 py-0.5"
                value={l.ts}
                onChange={(e) => {
                  const m = e.target.value.match(/(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?/);
                  if (!m) return;
                  const time = parseInt(m[1], 10) * 60 + parseInt(m[2], 10) + parseInt((m[3] ?? "0").padEnd(2, "0").slice(0, 2), 10) / 100;
                  updateLine(i, { ts: e.target.value, time });
                }}
              />
              <input
                className="flex-1 bg-transparent text-sm text-zinc-200 outline-none border border-transparent focus:border-accent rounded px-1 py-0.5"
                value={l.text}
                placeholder="Lyric line…"
                onChange={(e) => updateLine(i, { text: e.target.value })}
              />
              <div className="opacity-0 group-hover:opacity-100 flex gap-1 transition-opacity">
                <button className="text-zinc-500 hover:text-accent-soft" onClick={() => addLine(i)} title="Add line after">
                  <Plus className="h-3.5 w-3.5" />
                </button>
                <button className="text-zinc-500 hover:text-red-400" onClick={() => removeLine(i)} title="Remove line">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="mt-2 text-[10px] text-zinc-600">
        Space = stamp current preview time into the selected line · timestamps auto-format to {decimals} decimals on save
      </div>
    </div>
  );
}