import { useEffect, useMemo, useRef, useState } from "react";
import { CloudDownload, Play, Square, Plus, Trash2, Undo2, Sparkles, Keyboard, Wand2, Eraser } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";
import {
  loadLyricsKeys, saveLyricsKeys, resetLyricsKeys,
  keyLabel, matchKey, LYRICS_ACTIONS, LYRICS_KEY_DEFAULTS,
  type LyricsAction,
} from "../lib/lyricsKeys";

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
  const fracStr = String(Math.min(frac, 10 ** decimals - 1)).padStart(decimals, "0");
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
  onSave,
  artist,
  track,
  album,
  duration,
  decimals = 2,
}: {
  path: string;
  initialLyrics: string;
  onChange: (lrc: string) => void;
  onSave?: () => void;
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
  const [aiBusy, setAiBusy] = useState<string | null>(null);
  const [aiMenu, setAiMenu] = useState(false);
  const [keysMenu, setKeysMenu] = useState(false);
  const [capturing, setCapturing] = useState<LyricsAction | null>(null);
  const [keys, setKeys] = useState(() => loadLyricsKeys());
  const historyRef = useRef<LrcLine[][]>([]);
  const pendingWords = useRef<{ idx: number; parts: string[]; times: number[]; done: number } | null>(null);
  const [searchHits, setSearchHits] = useState<{ id: number; artist: string; track: string; duration?: number }[] | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    setLines(parseLrc(initialLyrics));
    setRaw(initialLyrics);
    historyRef.current = [];
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

  /** Every mutating path goes through commit() so Undo works. */
  const commit = (next: LrcLine[]) => {
    historyRef.current.push(lines);
    if (historyRef.current.length > 100) historyRef.current.shift();
    setLines(next);
    emit(next);
  };

  const undo = () => {
    const prev = historyRef.current.pop();
    if (!prev) {
      toast("Nothing to undo");
      return;
    }
    setLines(prev);
    emit(prev);
    setSelIdx((s) => Math.min(s, Math.max(0, prev.length - 1)));
  };

  const updateLine = (i: number, patch: Partial<LrcLine>) => {
    const next = lines.map((l, j) => {
      if (j !== i) return l;
      // manual text edits take over from ELRC word timestamps
      if ("text" in patch) return { ...l, ...patch, words: undefined };
      return { ...l, ...patch };
    });
    commit(next);
  };

  const addLine = (i: number) => {
    const base = lines[i]?.time ?? lines[lines.length - 1]?.time ?? 0;
    const next = [...lines];
    next.splice(i + 1, 0, { ts: "[00:00.00]", time: base, text: "" });
    commit(next);
    setSelIdx(i + 1);
  };

  const removeLine = (i: number) => {
    const next = lines.filter((_, j) => j !== i);
    commit(next);
    setSelIdx((s) => Math.max(0, Math.min(s, next.length - 1)));
  };

  /** Shift every timestamp by ±delta seconds (fix whole-track drift). */
  const shiftAll = (delta: number) => {
    const next = lines.map((l) => {
      const time = Math.max(0, l.time + delta);
      const out: LrcLine = { ...l, time, ts: fmtTs(time, decimals) };
      if (out.words?.length) out.words = out.words.map((w) => ({ ...w, time: Math.max(0, w.time + delta) }));
      return out;
    });
    commit(next);
    toast(`${delta > 0 ? "+" : ""}${delta.toFixed(1)}s applied to all lines`);
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

  // ---- ELRC word stamping ------------------------------------------------
  // Word stamps accumulate in a ref while the line is being sung; the ELRC
  // word list is only attached once every word has a timestamp, so partial
  // stamping never serializes zeros into the saved lyrics.
  const stampWord = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!playing) {
      toast("Press Play first, then stamp words while the song plays");
      return;
    }
    const idx = Math.max(0, Math.min(selIdx, lines.length - 1));
    const line = lines[idx];
    if (!line) return;
    const parts = line.text.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) {
      toast("Type the lyric text first, then stamp its words");
      return;
    }
    if (
      !pendingWords.current ||
      pendingWords.current.idx !== idx ||
      pendingWords.current.parts.join("\u0000") !== parts.join("\u0000")
    ) {
      pendingWords.current = { idx, parts, times: parts.map(() => 0), done: 0 };
    }
    const pending = pendingWords.current;
    if (pending.done >= parts.length) {
      toast("All words stamped — select the next line");
      return;
    }
    const t = Math.max(0, audio.currentTime - 0.05);
    pending.times[pending.done] = t;
    pending.done += 1;
    setPlayTime(t);
    if (pending.done >= parts.length) {
      const next = lines.map((l, j) =>
        j === idx ? { ...l, words: parts.map((text, wi) => ({ text, time: pending.times[wi] })) } : l
      );
      commit(next);
      pendingWords.current = null;
      toast("Line word-synced ✓ — select the next line");
    } else {
      toast(`Word ${pending.done}/${parts.length} stamped`);
    }
  };

  const stampLine = () => {
    const audio = audioRef.current;
    if (!audio || !playing) {
      toast("Press Play first, then stamp each line's time");
      return;
    }
    const t = Math.max(0, audio.currentTime - 0.05);
    const target = activeLine >= 0 ? activeLine : selIdx;
    const idx = Math.min(target, Math.max(0, lines.length - 1));
    const next = lines.map((l, j) => (j === idx ? { ...l, time: t, ts: fmtTs(t, decimals) } : l));
    commit(next);
    setSelIdx((s) => Math.min(s + 1, Math.max(0, lines.length - 1)));
    setPlayTime(t);
  };

  // ---- Customizable hotkeys ----------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Capturing a new binding always wins (works from any focus).
      if (capturing) {
        e.preventDefault();
        if (e.code === "Escape") {
          setCapturing(null);
          return;
        }
        const label = keyLabel(e);
        const next = { ...keys };
        for (const a of Object.keys(next) as LyricsAction[]) {
          if (next[a] === label) next[a] = LYRICS_KEY_DEFAULTS[a];
        }
        next[capturing] = label;
        setKeys(next);
        saveLyricsKeys(next);
        setCapturing(null);
        return;
      }

      const t = e.target as HTMLElement;
      const isLyricTextInput =
        t instanceof HTMLInputElement && t.dataset.lyrictext !== undefined;
      const isOtherInput =
        (t instanceof HTMLInputElement && t.dataset.lyrictext === undefined) ||
        t instanceof HTMLTextAreaElement ||
        t.isContentEditable;

      if (matchKey(e, keys, "save")) {
        e.preventDefault();
        onSave?.();
        return;
      }
      if (isLyricTextInput || isOtherInput) return; // don't hijack typing
      if (matchKey(e, keys, "stampLine")) {
        e.preventDefault();
        stampLine();
      } else if (matchKey(e, keys, "stampWord")) {
        e.preventDefault();
        stampWord();
      } else if (matchKey(e, keys, "playPause")) {
        e.preventDefault();
        togglePlay();
      } else if (matchKey(e, keys, "seekBack")) {
        e.preventDefault();
        seekTo(Math.max(0, playTime - 2));
      } else if (matchKey(e, keys, "seekForward")) {
        e.preventDefault();
        seekTo(playTime + 2);
      } else if (matchKey(e, keys, "prevLine")) {
        e.preventDefault();
        setSelIdx((s) => Math.max(0, s - 1));
      } else if (matchKey(e, keys, "nextLine")) {
        e.preventDefault();
        setSelIdx((s) => Math.min(lines.length - 1, s + 1));
      } else if (matchKey(e, keys, "undo")) {
        e.preventDefault();
        undo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, selIdx, lines, activeLine, playTime, keys, capturing, onSave]);

  // ---- AI-assisted actions ------------------------------------------------
  const runAi = async (mode: "clean" | "repair" | "wordsync") => {
    setAiMenu(false);
    setAiBusy(mode);
    try {
      if (mode === "wordsync") {
        const res = await api.lyricsAi("wordsync", serializeLrc(lines, decimals));
        const parsed = parseLrc(res.result);
        commit(parsed);
        toast(`Word-synced ${parsed.filter((l) => l.words?.length).length}/${parsed.length} lines (ELRC)`);
      } else if (mode === "clean") {
        const source = rawMode ? raw : lines.length ? lines.map((l) => l.text).join("\n") : raw;
        if (!source.trim()) {
          toast("Nothing to clean — paste lyrics first");
          return;
        }
        const res = await api.lyricsAi("clean", source);
        const parsed = parseLrc(res.result);
        if (parsed.length) {
          commit(parsed);
        } else {
          // plain text without timestamps: put into the first line slot
          commit([{ ts: "[00:00.00]", time: 0, text: res.result.split("\n")[0] ?? "" }]);
          setRaw(res.result);
        }
        toast("Lyrics cleaned with AI");
      } else if (mode === "repair") {
        if (!artist || !track) {
          toast("Track needs ARTIST and TITLE tags for candidate lookup");
          return;
        }
        toast("Fetching LRCLIB candidates…");
        let candidates: string[] = [];
        try {
          const hits = await api.lyricsSearch(artist, track, album, duration);
          candidates = (Array.isArray(hits) ? hits : [])
            .flatMap((h: any) => [h?.plainLyrics, h?.syncedLyrics])
            .filter((s: any): s is string => typeof s === "string" && s.length > 0)
            .flatMap((s: string) => s.split(/\r?\n/))
            .map((s: string) => s.replace(/^\[[^\]]*\]/, "").replace(/<[^>]*>/g, "").trim())
            .filter(Boolean);
        } catch {
          /* no candidates is fine — the LLM still gets the raw text */
        }
        const source = rawMode ? raw : serializeLrc(lines, decimals);
        const res = await api.lyricsAi("repair", source, { artist, track, candidates: candidates.slice(0, 400) });
        const parsed = parseLrc(res.result);
        if (parsed.length) commit(parsed);
        setRaw(res.result);
        toast(parsed.length ? `Repaired — ${parsed.length} lines` : "AI repair returned no timed lines (see raw)");
      }
    } catch (e) {
      toast(String(e));
    } finally {
      setAiBusy(null);
    }
  };

  const importFromLrclib = async () => {
    if (!artist || !track) {
      toast("Track needs ARTIST and TITLE tags first");
      return;
    }
    setLoading(true);
    setSearchHits(null);
    try {
      const res = await api.lyricsGet(artist, track, album, duration);
      const lrc = res?.syncedLyrics ?? res?.plainLyrics;
      if (!lrc) {
        const hits = await api.lyricsSearch(artist, track, album, duration);
        setSearchHits(
          Array.isArray(hits) && hits.length
            ? hits.map((h) => ({ id: h.id, artist: String(h.artist ?? ""), track: String(h.track ?? ""), duration: h.duration ? Number(h.duration) : undefined }))
            : []
        );
        if (!hits?.length) toast("No lyrics found on LRCLIB");
        return;
      }
      applyImport(lrc, "Imported from LRCLIB");
    } catch (e) {
      toast(String(e));
    } finally {
      setLoading(false);
    }
  };

  const applyImport = (lrc: string, message: string) => {
    const parsed = parseLrc(lrc);
    historyRef.current.push(lines);
    setLines(parsed);
    setRaw(lrc);
    emit(parsed);
    setSelIdx(0);
    pendingWords.current = null;
    const wordCount = parsed.reduce((n, l) => n + (l.words?.length ? 1 : 0), 0);
    toast(
      wordCount
        ? `${message} — ${parsed.length} lines, ${wordCount} word-synced (ELRC)`
        : `${message} — ${parsed.length} lines`,
    );
  };

  const importSearchHit = async (hit: { artist: string; track: string; duration?: number }) => {
    setSearchHits(null);
    setLoading(true);
    try {
      const res = await api.lyricsGet(hit.artist, hit.track, undefined, hit.duration);
      const lrc = res?.syncedLyrics ?? res?.plainLyrics;
      if (!lrc) {
        toast("That result has no lyrics on LRCLIB");
        return;
      }
      applyImport(lrc, `Imported "${hit.artist} — ${hit.track}"`);
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
        <div className="flex gap-1.5 flex-wrap">
          <button className="btn-ghost !py-1 text-xs" onClick={togglePlay}>
            {playing ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {playing ? "Stop" : "Preview"}
          </button>
          <button className="btn-ghost !py-1 text-xs" onClick={importFromLrclib} disabled={loading}>
            <CloudDownload className="h-3.5 w-3.5" /> LRCLIB
          </button>
          <div className="relative">
            <button className="btn-ghost !py-1 text-xs" onClick={() => setAiMenu(!aiMenu)} disabled={!!aiBusy}>
              <Sparkles className="h-3.5 w-3.5" />
              {aiBusy ? `${aiBusy}…` : "AI"}
            </button>
            {aiMenu && (
              <div className="absolute right-0 top-full mt-1 z-30 bg-zinc-900 border border-border rounded-lg shadow-xl p-1 w-64">
                <button className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-panel flex items-center gap-2" onClick={() => runAi("wordsync")}>
                  <Wand2 className="h-3.5 w-3.5 text-accent" />
                  <span>Word-sync lines → ELRC<span className="block text-zinc-500 text-[10px]">deterministic, offline</span></span>
                </button>
                <button className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-panel flex items-center gap-2" onClick={() => runAi("clean")}>
                  <Sparkles className="h-3.5 w-3.5 text-accent" />
                  <span>Clean raw lyrics<span className="block text-zinc-500 text-[10px]">strip ads / watermarks (LLM)</span></span>
                </button>
                <button className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-panel flex items-center gap-2" onClick={() => runAi("repair")}>
                  <Eraser className="h-3.5 w-3.5 text-accent" />
                  <span>Repair from LRCLIB candidates<span className="block text-zinc-500 text-[10px]">fill missing lines (LLM)</span></span>
                </button>
              </div>
            )}
          </div>
          <div className="relative">
            <button className="btn-ghost !py-1 text-xs" onClick={() => setKeysMenu(!keysMenu)} title="Keyboard shortcuts">
              <Keyboard className="h-3.5 w-3.5" />
            </button>
            {keysMenu && (
              <div className="absolute right-0 top-full mt-1 z-30 bg-zinc-900 border border-border rounded-lg shadow-xl p-2 w-80">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 px-1 pb-1">Hotkeys</div>
                {LYRICS_ACTIONS.map((a) => (
                  <div key={a.id} className="flex items-center gap-2 py-0.5">
                    <span className="flex-1 text-xs text-zinc-300" title={a.hint}>{a.label}</span>
                    <button
                      className={`chip text-[10px] font-mono border ${capturing === a.id ? "bg-accent/20 border-accent text-accent" : "bg-raise border-border text-zinc-400 hover:border-accent"}`}
                      onClick={() => setCapturing(capturing === a.id ? null : a.id)}
                      title="Click, then press the new key combination (Esc cancels)"
                    >
                      {capturing === a.id ? "press key…" : keys[a.id]}
                    </button>
                  </div>
                ))}
                <div className="flex justify-between items-center mt-2 pt-1.5 border-t border-border">
                  <button
                    className="text-[10px] text-zinc-500 hover:text-zinc-300 px-1"
                    onClick={() => {
                      resetLyricsKeys();
                      setKeys(loadLyricsKeys());
                      toast("Hotkeys reset to defaults");
                    }}
                  >
                    reset to defaults
                  </button>
                  <span className="text-[10px] text-zinc-600 px-1">saved in this browser</span>
                </div>
              </div>
            )}
          </div>
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

      {searchHits && (
        <div className="rounded-md border border-border bg-panel p-3 mb-2">
          <div className="text-[11px] text-zinc-400 mb-1.5">
            {searchHits.length ? "Multiple matches — pick one:" : "No exact match — nothing found on LRCLIB."}
          </div>
          {searchHits.length > 0 && (
            <div className="space-y-1 max-h-40 overflow-auto">
              {searchHits.map((h) => (
                <div key={h.id} className="flex items-center gap-2 text-xs">
                  <span className="flex-1 truncate text-zinc-300">
                    {h.artist} — <span className="text-zinc-400">{h.track}</span>
                  </span>
                  <button className="btn-ghost !py-0.5 text-[11px]" onClick={() => importSearchHit(h)}>
                    Import
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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
          press <kbd className="chip bg-raise border border-border">{keys.stampLine}</kbd> on each line to stamp its
          timestamp — or import from LRCLIB / use the AI menu.
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
              onClick={() => {
                if (i !== selIdx) pendingWords.current = null;
                setSelIdx(i);
              }}
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
                        {w.text}{" "}
                      </span>
                    );
                  })}
                </span>
              ) : (
                <div className="flex-1 flex items-center gap-1.5 min-w-0">
                  <input
                    data-lyrictext
                    className="flex-1 bg-transparent text-sm text-zinc-200 outline-none border border-transparent focus:border-accent rounded px-1 py-0.5 min-w-0"
                    value={l.text}
                    placeholder="Lyric line…"
                    onChange={(e) => updateLine(i, { text: e.target.value })}
                  />
                  {l.words?.length ? (
                    <span className="chip text-[9px] bg-accent/10 border border-accent/25 text-accent-soft shrink-0" title="Word-synced (ELRC)">
                      {l.words.length}w
                    </span>
                  ) : null}
                </div>
              )}
              <div className="opacity-0 group-hover:opacity-100 flex gap-1 transition-opacity shrink-0">
                <button className="text-zinc-500 hover:text-accent-soft" onClick={(e) => { e.stopPropagation(); addLine(i); }} title="Add line after">
                  <Plus className="h-3.5 w-3.5" />
                </button>
                <button className="text-zinc-500 hover:text-red-400" onClick={(e) => { e.stopPropagation(); removeLine(i); }} title="Remove line">
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
        <div className="flex gap-1 shrink-0">
          <button className="btn-ghost !px-1.5 !py-0.5 text-[10px]" onClick={() => shiftAll(-0.1)} title="Shift all timestamps 0.1s earlier">−0.1s</button>
          <button className="btn-ghost !px-1.5 !py-0.5 text-[10px]" onClick={() => shiftAll(0.1)} title="Shift all timestamps 0.1s later">+0.1s</button>
          <button className="btn-ghost !px-1.5 !py-0.5 text-[10px]" onClick={undo} title={`Undo (${keys.undo})`}>
            <Undo2 className="h-3 w-3" />
          </button>
        </div>
      </div>
      <div className="mt-1.5 text-[10px] text-zinc-600">
        {keys.stampLine} stamps the <b>line being sung</b> and advances · {keys.stampWord} stamps word-by-word (ELRC) ·
        {" "}{keys.playPause} play/pause · {keys.seekBack}/{keys.seekForward} seek · click <Keyboard className="inline h-3 w-3" /> to rebind ·
        ▶ seeks to a line · timestamps format to {decimals} decimals on save
      </div>
    </div>
  );
}
