import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

export interface LyricsJobResult {
  ok: boolean;
  lrc?: string;
  source?: string;
  aligned?: number;
  total?: number;
  error?: string;
}

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued…",
  prepare: "Preparing…",
  transcode: "Transcoding audio…",
  lookup: "Searching LRCLIB…",
  listen: "Listening to the track…",
  align: "Aligning syllables…",
  build: "Building timings…",
  done: "Done",
  error: "Failed",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

/** Run one lyrics-AI job (acoustic align / detect & sync) with live
 * progress. The reported percent is a stage estimate, so the displayed
 * value eases toward it and keeps creeping during the long "listening"
 * stretch — a stalled-looking bar reads as broken. */
export function useLyricsSyncJob() {
  const [active, setActive] = useState(false);
  const [stage, setStage] = useState("queued");
  const [targetPct, setTargetPct] = useState(0);
  const [pct, setPct] = useState(0);
  const [result, setResult] = useState<LyricsJobResult | null>(null);
  const aliveRef = useRef(false);

  // Smooth crawl toward the reported percent.
  useEffect(() => {
    if (!active) return;
    const iv = setInterval(() => {
      setPct((p) => {
        const next = p + (targetPct - p) * 0.12 + (targetPct > p + 1 ? 0.25 : 0);
        return Math.min(next, Math.max(targetPct - 0.5, 0));
      });
    }, 120);
    return () => clearInterval(iv);
  }, [active, targetPct]);

  const run = useCallback(async (kind: "align" | "sync", path: string, text?: string) => {
    aliveRef.current = true;
    setActive(true);
    setStage("queued");
    setPct(0);
    setTargetPct(2);
    setResult(null);
    try {
      const { job } = await api.lyricsJobStart(kind, path, text);
      for (;;) {
        if (!aliveRef.current) return null;
        const st = await api.lyricsJobPoll(job).catch(() => null);
        if (st) {
          setStage(st.stage);
          setTargetPct(Math.max(st.pct, 1));
          if (st.done) {
            const r: LyricsJobResult = {
              ok: !!st.ok,
              lrc: st.lrc,
              source: st.source,
              aligned: st.aligned,
              total: st.total,
              error: st.error,
            };
            setResult(r);
            return r;
          }
        }
        await new Promise((res) => setTimeout(res, 500));
      }
    } catch (e) {
      const r: LyricsJobResult = { ok: false, error: e instanceof Error ? e.message : String(e) };
      setResult(r);
      return r;
    } finally {
      aliveRef.current = false;
      setActive(false);
    }
  }, []);

  const reset = useCallback(() => {
    aliveRef.current = false;
    setActive(false);
    setResult(null);
  }, []);

  return { run, reset, active, stage, pct: Math.min(pct, 100), result };
}

/** Slim stage + percent bar shown while a lyrics-AI job runs. */
export function LyricsSyncBar({ stage, pct, compact = false }: { stage: string; pct: number; compact?: boolean }) {
  return (
    <div className={compact ? "px-2 pb-1.5" : "px-2 pb-1.5"}>
      <div className="flex items-center justify-between text-[10px] text-zinc-500 pb-1">
        <span className="truncate">{stageLabel(stage)}</span>
        <span className="tabular-nums shrink-0 ml-2">{Math.round(pct)}%</span>
      </div>
      <div className="h-1 rounded-full bg-white/10 overflow-hidden">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-200 ease-linear"
          style={{ width: `${Math.max(2, Math.min(100, pct))}%` }}
        />
      </div>
    </div>
  );
}
