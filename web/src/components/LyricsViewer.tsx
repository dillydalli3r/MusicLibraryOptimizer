import { useEffect, useMemo, useRef, useState } from "react";
import { CloudDownload, Play, Square, Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";

export interface LrcWord {
  time: number; // seconds
  text: string;
}

export interface LrcLine {
  ts: string; // [mm:ss.xx]
  time: number; // seconds
  text: string;
  words?: LrcWord[]; // ELRC inline word-level timestamps <mm:ss.xx>
}

const META_RE = /\[(?:ar|ti|al|by|re|ve|length|offset):[^\]]*\]/gi;
const TIME_RE = /\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g;
const WORD_RE = /<(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?>/g;

function tsToTime(mm: string, ss: string, frac?: string): number {
  const f = (frac ?? "0").padEnd(2, "0").slice(0, 2);
  return parseInt(mm, 10) * 60 + parseInt(ss, 10) + parseInt(f, 10) / 100;
}

export function fmtTs(t: number, decimals = 2): string {
  const mm = Math.floor(t / 60);
  const ss = Math.floor(t % 60);
  const frac = Math.round((t - Math.floor(t)) * 10 ** decimals);
  const fracStr = String(frac).padStart(decimals, "0");
  return `[${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}.${fracStr}]`;
}

export function parseLrc(lrc: string): LrcLine[] {
  let offsetMs = 0;
  const off = lrc.match(/\[offset:\s*([+-]?\d+)\s*\]/i);
  if (off) offsetMs = parseInt(off[1], 10) || 0;
  const lines: LrcLine[] = [];
  for (const raw of lrc.split(/\r?\n/)) {
    // drop metadata tags like [ti:...] / [ar:...] (never lyric content)
    const cleaned = raw.replace(META_RE, "");
    const times = [...cleaned.matchAll(TIME_RE)];
    if (!times.length) continue;
    const body = cleaned.replace(TIME_RE, "");
    // ELRC word-level timestamps: <mm:ss.xx>word <mm:ss.xx>word2
    const parts = body.split(WORD_RE);
    const words: LrcWord[] = [];
    for (let k = 0; 4 * k + 3 < parts.length; k++) {
      const mm = parts[4 * k + 1];
      const ss = parts[4 * k + 2];
      if (mm === undefined || ss === undefined) break;
      words.push({ time: tsToTime(mm, ss, parts[4 * k + 3]), text: parts[4 * k + 4] ?? "" });
    }
    const text = words.length
      ? words.map((w) => w.text).join("").replace(/\s+/g, " ").trim()
      : body.trim();
    if (!text && !words.length) continue;
    for (const m of times) {
      const time = tsToTime(m[1], m[2], m[3]) + offsetMs / 1000;
      lines.push({
        ts: fmtTs(time, 2),
        time,
        text,
        words: words.length ? words.map((w) => ({ ...w, time: w.time + offsetMs / 1000 })) : undefined,
      });
    }
  }
  // sort + drop exact duplicates (LRCLIB occasionally repeats lines)
  lines.sort((a, b) => a.time - b.time);
  const seen = new Set<string>();
  return lines.filter((l) => {
    const key = `${l.time.toFixed(3)}|${l.text}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function serializeLrc(lines: LrcLine[], decimals = 2): string {
  return lines
    .map((l) => {
      const ts = fmtTs(l.time, decimals);
      if (l.words?.length) {
        const body = l.words.map((w) => `<${fmtTs(w.time, decimals)}>${w.text}`).join("");
        return `${ts} ${body}`;
      }
      return `${ts}${l.text}`;
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
  duration,
  decimals = 2,
}: {
  path: string;
  initialLyrics: string;
  onChange: (lrc: string) => void;
  artist?: string;
  track?: string;
  album?: string;
  duration?: number;
  decimals?: number;
}) {
  const [lines, setLines] = useState<LrcLine[]>(() => parseLrc(initialLyrics));
  const [rawMode, setRawMode] = useState(false);
  const [raw, setRaw] = useState(initialLyrics);
  const [playing, setPlaying] = useState(false);
  const [playTime, setPlayTime] = useState(0);
  const [dur, setDur] = useState(duration ?? 0);
  const [selIdx, setSelIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    setLines(parseLrc(initialLyrics));
    setRaw(initialLyrics);
  }, [initialLyrics]);

  // Active line derived from playback time (never conflated with the index).
  const activeLine = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].time <= playTime + 0.02) idx = i;
      else break;
    }
    return idx;
  }, [playTime, lines]);

  // Follow the playing line.
  useEffect(() => {
    if (!playing || activeLine < 0) return;
    lineRefs.current[activeLine]?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeLine, playing]);

  const emit = (ls: LrcLine[]) => onChange(serializeLrc(ls, decimals));

  const updateLine = (i: number, patch: Partial<LrcLine>) => {
    const next = lines.map((l, j) => {
      if (j !== i) return l;
      // manual text edits take over from ELRC word timestamps
      if ("text" in patch) return { ...l, ...patch, words: undefined };
      return { ...l, ...patch };
    });
    setLines(next);
    emit(next);
  };

  const addLine = (i: number) => {
    const base = lines[i]?.time ?? lines[lines.length - 1]?.time ?? 0;
    const next = [...lines];
    next.splice(i + 1, 0, { ts: "[00:00.00]", time: base, text: "" });
    setLines(next);
    emit(next);
    setSelIdx(i + 1);
  };

  const removeLine = (i: number) => {
    const next = lines.filter((_, j) => j !== i);
    setLines(next);
    emit(next);
    setSelIdx((s) => Math.max(0, Math.min(s, next.length - 1)));
  };

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
    } else {
      audio.src = api.streamUrl(path);
      audio.play().catch(() => toast("Playback failed — audio format unsupported in browser"));
      setPlaying(true);
    }
  };

  const seekTo = (time: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = time;
    setPlayTime(time);
  };

  // Spacebar stamps the current playback time. While playing, the line being
  // sung (activeLine, which follows playback) is stamped and the selection
  // advances to the next line — so the editor always moves forward in sync
  // with the song. When paused, the selected line is stamped instead.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      const t = e.target as HTMLElement;
      const isLyricTextInput =
        t instanceof HTMLInputElement && t.dataset.lyrictext !== undefined;
      const isOtherInput =
        (t instanceof HTMLInputElement && t.dataset.lyrictext === undefined) ||
        t instanceof HTMLTextAreaElement ||
        t.isContentEditable;
      if (isLyricTextInput) return; // normal space while typing lyrics
      if (isOtherInput) return; // don't hijack other fields
      e.preventDefault();
      stampTime();
    };
    const stampTime = () => {
      const audio = audioRef.current;
      if (!audio || !playing) {
        toast("Press Play first, then Space on each line to stamp its time");
        return;
      }
      const t = Math.max(0, audio.currentTime - 0.05);
      const target = activeLine >= 0 ? activeLine : selIdx;
      const idx = Math.min(target, Math.max(0, lines.length - 1));
      const next = lines.map((l, j) => (j === idx ? { ...l, time: t, ts: fmtTs(t, decimals) } : l));
      setLines(next);
      emit(next);
      setSelIdx((s) => Math.min(s + 1, Math.max(0, lines.length - 1)));
      setPlayTime(t);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, selIdx, lines.length, activeLine]);

  const importFromLrclib = async () => {
    if (!artist || !track) {
      toast("Track needs ARTIST and TITLE tags first");
      return;
    }
    setLoading(true);
    try {
      const res = await api.lyricsGet(artist, track, album, duration);
      const lrc = res?.syncedLyrics ?? res?.plainLyrics;
      if (!lrc) {
        toast("No lyrics found on LRCLIB");
        return;
      }
      const parsed = parseLrc(lrc);
      setLines(parsed);
      setRaw(lrc);
      emit(parsed);
      setSelIdx(0);
      const wordCount = parsed.reduce((n, l) => n + (l.words?.length ? 1 : 0), 0);
      toast(
        wordCount
          ? `Imported from LRCLIB — ${parsed.length} lines, ${wordCount} word-synced (ELRC)`
          : `Imported from LRCLIB — ${parsed.length} lines`,
      );
    } catch (e) {
      toast(String(e));
    } finally {
      setLoading(false);
    }
  };

  const fmtDur = (t: number) => {
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  return (
    <div data-lrc-editor className="bg-card rounded-lg border border-border p-4 flex flex-col">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-1.5">
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

      <audio
        ref={audioRef}
        onTimeUpdate={(e) => setPlayTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
        onEnded={() => setPlaying(false)}
        className="hidden"
      />

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
          No lyrics yet. Press <kbd className="chip bg-raise border border-border">Play</kbd>, then select a line and
          press <kbd className="chip bg-raise border border-border">Space</kbd> on each line to stamp its timestamp —
          or import from LRCLIB.
        </div>
      ) : (
        <div ref={listRef} className="flex-1 space-y-1 max-h-[420px] overflow-auto pr-1">
          {lines.map((l, i) => (
            <div
              key={i}
              ref={(el) => {
                lineRefs.current[i] = el;
              }}
              className={`group flex items-center gap-2 rounded-md border px-2 py-1.5 transition-colors ${
                i === activeLine && playing
                  ? "border-accent/60 bg-accent/20"
                  : i === selIdx
                    ? "border-accent/30 bg-panel"
                    : "border-transparent hover:border-border hover:bg-panel"
              }`}
              onClick={() => setSelIdx(i)}
            >
              <button
                className="p-0.5 text-zinc-600 hover:text-accent-soft shrink-0"
                title={`Seek to ${l.ts}`}
                onClick={(e) => {
                  e.stopPropagation();
                  seekTo(l.time);
                }}
              >
                <Play className="h-3 w-3" />
              </button>
              <input
                className="w-[86px] bg-transparent font-mono text-xs text-zinc-400 outline-none border border-transparent focus:border-accent rounded px-1 py-0.5"
                value={l.ts}
                onChange={(e) => {
                  const m = e.target.value.match(/(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?/);
                  if (!m) return;
                  const time =
                    parseInt(m[1], 10) * 60 +
                    parseInt(m[2], 10) +
                    parseInt((m[3] ?? "0").padEnd(2, "0").slice(0, 2), 10) / 100;
                  updateLine(i, { ts: e.target.value, time });
                }}
              />
              {i === activeLine && playing && l.words?.length ? (
                <span className="flex-1 text-sm text-zinc-300 px-1">
                  {l.words.map((w, wi) => {
                    const isActive =
                      w.time <= playTime + 0.04 &&
                      (wi === l.words!.length - 1 || (l.words![wi + 1].time > playTime + 0.04));
                    return (
                      <span key={wi} className={isActive ? "text-accent font-semibold" : ""}>
                        {w.text}
                      </span>
                    );
                  })}
                </span>
              ) : (
                <input
                  data-lyrictext
                  className="flex-1 bg-transparent text-sm text-zinc-200 outline-none border border-transparent focus:border-accent rounded px-1 py-0.5"
                  value={l.text}
                  placeholder="Lyric line…"
                  onChange={(e) => updateLine(i, { text: e.target.value })}
                />
              )}
              <div className="opacity-0 group-hover:opacity-100 flex gap-1 transition-opacity shrink-0">
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
      <div className="mt-2 flex items-center gap-2">
        <span className="text-[10px] font-mono text-zinc-500 w-10 text-right shrink-0">{fmtDur(playTime)}</span>
        <input
          type="range"
          min={0}
          max={dur || 0}
          step={0.05}
          value={Math.min(playTime, dur || 0)}
          onChange={(e) => seekTo(Number(e.target.value))}
          className="flex-1 "
          title="Seek within the track"
        />
        <span className="text-[10px] font-mono text-zinc-500 w-10 shrink-0">{fmtDur(dur || 0)}</span>
      </div>
      <div className="mt-1.5 text-[10px] text-zinc-600">
        Play → Space stamps the <b>line being sung</b> and advances · ELRC word-level tags{" "}
        <span className="font-mono">{"<mm:ss.xx>word"}</span> highlight word-by-word · ▶ seeks to a line · timestamps
        format to {decimals} decimals on save
      </div>
    </div>
  );
}