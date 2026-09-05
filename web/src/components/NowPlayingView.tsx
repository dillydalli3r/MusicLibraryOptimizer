import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown, Heart, ListMusic, Loader2, Pause, Play, Repeat, Settings2,
  Shuffle, SkipBack, SkipForward, Volume2,
} from "lucide-react";
import { api } from "../api";
import type { QueueTrack } from "../store";
import CoverImg from "./CoverImg";
import { parseLrc, type LrcLine } from "./LyricsViewer";
import { fmtDuration } from "../pages/LibraryPage";

const XLIT_KEY = "mlo.np.xlit";
const TRANS_KEY = "mlo.np.trans";

interface Props {
  current: QueueTrack;
  queuePos: string;
  playing: boolean;
  time: number;
  duration: number;
  shuffle: boolean;
  loop: boolean;
  vol: number;
  liked: boolean;
  onTogglePlay: () => void;
  onSeek: (t: number) => void;
  onStep: (dir: 1 | -1) => void;
  onToggleShuffle: () => void;
  onToggleLoop: () => void;
  onVolume: (v: number) => void;
  onToggleLike: () => void;
  onClose: () => void;
}

export default function NowPlayingView(p: Props) {
  const [showXlit, setShowXlit] = useState(() => localStorage.getItem(XLIT_KEY) === "1");
  const [showTrans, setShowTrans] = useState(() => localStorage.getItem(TRANS_KEY) === "1");
  const [options, setOptions] = useState(false);
  const [tags, setTags] = useState<Record<string, string> | null>(null);
  const [lyricsText, setLyricsText] = useState<string | null>(null);
  const [transforms, setTransforms] = useState<Record<string, string[]>>({});
  const inFlight = useRef<Set<string>>(new Set());
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const { time, duration } = p;

  // cover file for this album (shared cache with AlbumPage)
  const { data: album } = useQuery({
    queryKey: ["album", p.current.albumPath],
    queryFn: () => api.album(p.current.albumPath),
    staleTime: 5 * 60 * 1000,
  });
  const coverFile = album?.cover_file ?? null;

  // ---- lyrics for the current track --------------------------------------
  useEffect(() => {
    let dead = false;
    setTags(null);
    setLyricsText(null);
    setTransforms({});
    inFlight.current.clear();
    api
      .tags(p.current.path)
      .then((t) => {
        if (dead) return;
        setTags(t.tags ?? {});
        setLyricsText(typeof t.lyrics === "string" ? t.lyrics : null);
      })
      .catch(() => {
        if (!dead) setTags({});
      });
    return () => {
      dead = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.current.path]);

  const instrumental = (tags?.INSTRUMENTAL ?? "").toString().trim() === "1";
  const lines: LrcLine[] = useMemo(
    () => (lyricsText && !instrumental ? parseLrc(lyricsText) : []),
    [lyricsText, instrumental]
  );
  // No lyrics at all, or instrumental -> no lyrics UI at all.
  const hasLyrics = !!lyricsText?.trim() && !instrumental;
  const plainLines = useMemo(() => {
    if (!hasLyrics) return [];
    if (lines.length) return lines.map((l) => l.text);
    return (lyricsText ?? "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  }, [hasLyrics, lines, lyricsText]);

  // ---- translation / transliteration -------------------------------------
  useEffect(() => {
    const modes = [
      ...(showXlit ? ["transliterate"] : []),
      ...(showTrans ? ["translate"] : []),
    ];
    if (!hasLyrics || !plainLines.length) return;
    for (const mode of modes) {
      const key = `${p.current.path}|${mode}`;
      if (inFlight.current.has(key) || transforms[mode]) continue;
      inFlight.current.add(key);
      api
        .lyricsAiLines(mode as "translate" | "transliterate", plainLines)
        .then((r) => setTransforms((prev) => ({ ...prev, [mode]: r.lines })))
        .catch(() => {
          /* AI not configured or failed — show plain lyrics */
        })
        .finally(() => inFlight.current.delete(key));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showXlit, showTrans, hasLyrics, plainLines, p.current.path]);

  // ---- active line ---------------------------------------------------------
  const activeLine = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].time <= time + 0.02) idx = i;
      else break;
    }
    return idx;
  }, [lines, time]);

  useEffect(() => {
    if (activeLine < 0) return;
    lineRefs.current[activeLine]?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeLine]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") p.onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleOpt = (which: "xlit" | "trans") => {
    if (which === "xlit") {
      const v = !showXlit;
      setShowXlit(v);
      localStorage.setItem(XLIT_KEY, v ? "1" : "0");
    } else {
      const v = !showTrans;
      setShowTrans(v);
      localStorage.setItem(TRANS_KEY, v ? "1" : "0");
    }
  };

  const renderLine = (l: LrcLine, i: number) => {
    const isActive = i === activeLine;
    const past = i < activeLine;
    const xlit = showXlit ? transforms.transliterate?.[i] : undefined;
    const trans = showTrans ? transforms.translate?.[i] : undefined;
    return (
      <div
        key={i}
        ref={(el) => {
          lineRefs.current[i] = el;
        }}
        className={`py-1.5 cursor-pointer transition-opacity ${isActive ? "opacity-100" : past ? "opacity-50" : "opacity-40"} hover:opacity-90`}
        onClick={() => p.onSeek(l.time)}
        title="Click to seek"
      >
        {xlit && <div className="text-[11px] text-zinc-500 italic leading-tight">{xlit}</div>}
        <div className={`leading-snug ${isActive ? "text-white text-xl font-semibold" : "text-zinc-300 text-base"}`}>
          {isActive && l.words?.length
            ? l.words.map((w, wi) => {
                const on =
                  w.time <= time + 0.04 &&
                  (wi === l.words!.length - 1 || l.words![wi + 1].time > time + 0.04);
                return (
                  <span key={wi} className={on ? "text-accent" : ""}>
                    {w.text}
                  </span>
                );
              })
            : l.text}
        </div>
        {trans && <div className="text-xs text-accent-soft/70 mt-0.5 leading-snug">{trans}</div>}
      </div>
    );
  };

  const transforming = transformingAny(transforms, showXlit, showTrans, hasLyrics);

  return (
    <div className="fixed inset-0 z-50 bg-zinc-950 overflow-hidden">
      {/* blurred cover backdrop */}
      <div className="absolute inset-0 opacity-30 blur-3xl scale-110">
        <CoverImg
          albumPath={p.current.albumPath}
          coverFile={coverFile}
          wrapperClass="w-full h-full"
        />
      </div>
      <div className="absolute inset-0 bg-gradient-to-b from-zinc-950/70 via-zinc-950/40 to-zinc-950/90" />

      <div className="relative h-full flex flex-col">
        {/* top bar */}
        <div className="flex items-center justify-between px-5 py-3">
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 flex items-center gap-2">
            <ListMusic className="h-3.5 w-3.5" /> Now playing{p.queuePos ? ` · ${p.queuePos}` : ""}
          </div>
          <div className="flex items-center gap-1">
            <div className="relative">
              <button
                className="p-2 rounded-full hover:bg-white/10 text-zinc-400 hover:text-white"
                onClick={() => setOptions(!options)}
                title="Lyrics display options"
              >
                <Settings2 className="h-5 w-5" />
              </button>
              {options && (
                <div className="absolute right-0 top-full mt-1 z-10 bg-zinc-900 border border-border rounded-lg shadow-xl p-2 w-64">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-1 pb-1">Lyrics display</div>
                  {[
                    { id: "xlit" as const, label: "Transliteration (romanized)", on: showXlit },
                    { id: "trans" as const, label: "Translation", on: showTrans },
                  ].map((o) => (
                    <label key={o.id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-panel cursor-pointer text-xs text-zinc-300">
                      <input type="checkbox" className="accent-[var(--accent)]" checked={o.on} onChange={() => toggleOpt(o.id)} />
                      {o.label}
                    </label>
                  ))}
                  <div className="text-[10px] text-zinc-600 px-2 pt-1">
                    Uses the AI configured in Settings → AI; results are cached per track.
                  </div>
                </div>
              )}
            </div>
            <button className="p-2 rounded-full hover:bg-white/10 text-zinc-400 hover:text-white" onClick={p.onClose} title="Close (Esc)">
              <ChevronDown className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* main area */}
        <div className="flex-1 min-h-0 flex flex-col lg:flex-row items-center gap-8 px-8 pb-4 overflow-hidden">
          <div className={`flex flex-col items-center gap-4 shrink-0 ${hasLyrics ? "lg:w-[38%]" : ""}`}>
            <CoverImg
              albumPath={p.current.albumPath}
              coverFile={coverFile}
              wrapperClass={`rounded-xl shadow-2xl border border-white/10 bg-raise overflow-hidden ${hasLyrics ? "w-64 h-64 lg:w-80 lg:h-80" : "w-72 h-72 lg:w-[26rem] lg:h-[26rem]"}`}
            />
            <div className="text-center max-w-md">
              <div className="text-2xl font-bold text-white truncate">
                {p.current.file.replace(/\.[^.]+$/, "")}
              </div>
              <div className="text-zinc-400 mt-1 truncate">
                {[p.current.artist ?? p.current.albumPath.split("/").pop(), p.current.album].filter(Boolean).join(" · ")}
              </div>
              <button
                className={`mt-3 inline-flex items-center gap-1.5 text-xs rounded-full px-3 py-1.5 border transition-colors ${
                  p.liked ? "border-accent/60 text-accent bg-accent/10" : "border-white/15 text-zinc-400 hover:text-white hover:border-white/30"
                }`}
                onClick={p.onToggleLike}
                title={p.liked ? "Unlike" : "Like this track"}
              >
                <Heart className={`h-3.5 w-3.5 ${p.liked ? "fill-current" : ""}`} />
                {p.liked ? "Liked" : "Like"}
              </button>
            </div>
          </div>

          {/* lyrics column — hidden entirely when instrumental / no lyrics */}
          {hasLyrics && (
            <div className="flex-1 min-h-0 w-full h-full overflow-y-auto pr-2 py-6">
              {lines.length > 0 ? (
                lines.map(renderLine)
              ) : (
                <div className="text-zinc-400 text-sm whitespace-pre-wrap leading-relaxed max-w-prose opacity-70">
                  {lyricsText}
                </div>
              )}
              <div className="h-40" />
            </div>
          )}
          {hasLyrics && transforming && (
            <div className="absolute bottom-28 right-8 text-[10px] text-zinc-600 flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" /> transforming lyrics…
            </div>
          )}
        </div>

        {/* controls */}
        <div className="border-t border-white/10 bg-zinc-950/60 backdrop-blur px-6 py-4">
          <div className="flex items-center gap-2 text-xs text-zinc-400 max-w-4xl mx-auto w-full">
            <span className="w-10 text-right font-mono">{fmtDuration(time)}</span>
            <input
              type="range"
              min={0}
              max={duration || 0}
              step={0.05}
              value={Math.min(time, duration || 0)}
              onChange={(e) => p.onSeek(Number(e.target.value))}
              className="flex-1"
              title="Seek"
            />
            <span className="w-10 font-mono">{fmtDuration(duration)}</span>
          </div>
          <div className="flex items-center justify-center gap-3 mt-2">
            <button className={`p-2 rounded-full hover:bg-white/10 ${p.shuffle ? "text-accent" : "text-zinc-500"}`} onClick={p.onToggleShuffle} title="Shuffle">
              <Shuffle className="h-4 w-4" />
            </button>
            <button className="p-2.5 rounded-full hover:bg-white/10 text-white" onClick={() => p.onStep(-1)} title="Previous track">
              <SkipBack className="h-5 w-5" />
            </button>
            <button
              className="p-4 rounded-full bg-accent on-accent hover:bg-accent-soft"
              onClick={p.onTogglePlay}
              title="Play / pause (Space)"
            >
              {p.playing ? <Pause className="h-6 w-6" /> : <Play className="h-6 w-6 ml-0.5" />}
            </button>
            <button className="p-2.5 rounded-full hover:bg-white/10 text-white" onClick={() => p.onStep(1)} title="Next track">
              <SkipForward className="h-5 w-5" />
            </button>
            <button className={`p-2 rounded-full hover:bg-white/10 ${p.loop ? "text-accent" : "text-zinc-500"}`} onClick={p.onToggleLoop} title="Repeat one">
              <Repeat className="h-4 w-4" />
            </button>
            <div className="flex items-center gap-1.5 ml-4 text-zinc-500">
              <Volume2 className="h-4 w-4" />
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={p.vol}
                onChange={(e) => p.onVolume(Number(e.target.value))}
                className="w-24"
                title="Volume"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function transformingAny(
  transforms: Record<string, string[]>,
  xlit: boolean,
  trans: boolean,
  hasLyrics: boolean
): boolean {
  if (!hasLyrics) return false;
  return (xlit && !transforms.transliterate) || (trans && !transforms.translate);
}
