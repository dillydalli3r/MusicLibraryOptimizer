import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { api } from "../api";
import { parsePlayerLrc, type LrcLine } from "./LyricsViewer";

/** A right-docked lyrics panel for the player bar's lyrics button: the
 * current track's lyrics with the same synced-line treatment as the
 * fullscreen player (active line highlighted, click a line to seek,
 * stored translations/transliterations as sub-lines) in a compact,
 * display-only pane. AI generation stays the fullscreen player's job —
 * this view shows whatever is stored.
 *
 * Lives above the player bar (bottom anchored) so transport controls
 * stay visible while lyrics are open. */
export default function LyricsSidebar({
  current,
  playing,
  time,
  onSeek,
  getAudioTime,
  onClose,
}: {
  /** Null when nothing is playing — the panel still opens, showing a hint. */
  current: { path: string; title?: string; file: string; albumPath: string; artist?: string; album?: string } | null;
  playing: boolean;
  time: number;
  onSeek: (t: number) => void;
  getAudioTime: () => number;
  onClose: () => void;
}) {
  const [payload, setPayload] = useState<{
    lyrics: string | null;
    xlit: string[] | null;
    trans: string[] | null;
    title?: string;
    album?: string;
  } | null>(null);

  const path = current?.path ?? null;
  useEffect(() => {
    if (!path) {
      setPayload(null);
      return;
    }
    let dead = false;
    setPayload(null);
    api
      .tags(path)
      .then((t) => {
        if (dead) return;
        const splitStored = (s: string): string[] =>
          /\[\d{1,2}:\d{1,2}/.test(s)
            ? parsePlayerLrc(s).map((l) => l.text)
            : s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
        setPayload({
          lyrics: typeof t.lyrics === "string" ? t.lyrics : null,
          xlit: typeof t.lyrics_xlit === "string" && t.lyrics_xlit.trim() ? splitStored(t.lyrics_xlit) : null,
          trans: typeof t.lyrics_trans === "string" && t.lyrics_trans.trim() ? splitStored(t.lyrics_trans) : null,
          title: (t.tags as Record<string, string>)?.TITLE,
          album: (t.tags as Record<string, string>)?.ALBUM,
        });
      })
      .catch(() => {
        if (!dead) setPayload({ lyrics: null, xlit: null, trans: null });
      });
    return () => {
      dead = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  const instrumental = false; // the fullscreen player owns INSTRUMENTAL handling
  const lines: LrcLine[] = useMemo(
    () => (payload?.lyrics && !instrumental ? parsePlayerLrc(payload.lyrics) : []),
    [payload?.lyrics]
  );
  const synced = lines.length > 0;
  const displayLines: LrcLine[] = useMemo(
    () => (synced ? lines : (payload?.lyrics ?? "").split(/\r?\n/).map((text) => ({ ts: "", time: 0, text })).filter((l) => l.text.trim())),
    [synced, lines, payload?.lyrics]
  );

  // ~60 fps lyric clock: shared <audio> element read directly, so line
  // highlights stay as tight as the fullscreen player's.
  const [smoothTime, setSmoothTime] = useState(0);
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      const t = getAudioTime();
      if (typeof t === "number" && isFinite(t) && t >= 0) setSmoothTime(t);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, getAudioTime]);
  const dispTime = playing && smoothTime > 0 ? smoothTime : time;

  const activeLine = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].time <= dispTime + 0.02) idx = i;
      else break;
    }
    return idx;
  }, [lines, dispTime]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const seekMarkRef = useRef(0);
  const prevDispRef = useRef(-1);
  useEffect(() => {
    const prev = prevDispRef.current;
    prevDispRef.current = dispTime;
    if (prev >= 0 && Math.abs(dispTime - prev) > 1.2) seekMarkRef.current = Date.now();
  }, [dispTime]);

  useEffect(() => {
    const c = scrollRef.current;
    const el = lineRefs.current[activeLine];
    if (!c || !el || activeLine < 0) return;
    const animate = Date.now() - seekMarkRef.current > 600;
    const top =
      el.getBoundingClientRect().top -
      c.getBoundingClientRect().top +
      c.scrollTop -
      c.clientHeight / 2 +
      el.clientHeight / 2;
    c.scrollTo({ top: Math.max(0, top), behavior: animate ? "smooth" : "auto" });
  }, [activeLine]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [path]);

  const title = payload?.title || current?.title || (current ? current.file.replace(/\.[^.]+$/, "") : "Lyrics");
  const album = payload?.album || current?.album || "";

  return (
    <aside className="fixed top-12 bottom-[5.75rem] right-0 w-[380px] z-30 bg-panel/95 backdrop-blur border-l border-border shadow-2xl flex flex-col">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/60">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold truncate">{title}</div>
          {album && <div className="text-[10px] text-zinc-500 truncate">{album}</div>}
        </div>
        <button
          className="p-1.5 rounded-md text-zinc-500 hover:text-white hover:bg-raise transition-colors"
          onClick={onClose}
          title="Close lyrics"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-5 py-4 no-scrollbar">
        {displayLines.length > 0 ? (
          displayLines.map((l, i) => {
            const isActive = synced && i === activeLine;
            const trans = payload?.trans?.[i];
            const xlit = payload?.xlit?.[i];
            return (
              <div
                key={i}
                ref={(el) => {
                  lineRefs.current[i] = el;
                }}
                className={`py-1.5 ${synced ? "cursor-pointer" : ""} ${isActive ? "opacity-100" : synced ? "opacity-70" : ""}`}
                onClick={synced ? () => onSeek(l.time) : undefined}
                title={synced ? "Click to seek" : undefined}
              >
                <div
                  className={`text-[15px] leading-snug font-semibold transition-[transform,color] duration-300 ${
                    isActive ? "text-white" : synced ? "text-zinc-500" : "text-zinc-300"
                  }`}
                  style={{
                    transform: `scale(${isActive ? 1 : 0.92})`,
                    transformOrigin: "0 50%",
                  }}
                >
                  {l.text}
                </div>
                {xlit && xlit.trim() && xlit.trim() !== l.text.trim() && (
                  <div className="text-xs text-zinc-400 mt-0.5 leading-snug">{xlit}</div>
                )}
                {trans && trans.trim() && (
                  <div className="text-xs text-accent-soft/70 mt-0.5 leading-snug">{trans}</div>
                )}
              </div>
            );
          })
        ) : (
          <div className="h-full flex items-center justify-center text-center px-6">
            {payload === null ? (
              <span className="text-xs text-zinc-600">
                {!current
                  ? "Nothing playing — play an album, artist or playlist and its lyrics appear here."
                  : "Loading lyrics…"}
              </span>
            ) : (
              <span className="text-xs text-zinc-600">
                No lyrics stored for this track — fetch or generate them from the track or album page.
              </span>
            )}
          </div>
        )}
        <div className="h-24" />
      </div>
    </aside>
  );
}
