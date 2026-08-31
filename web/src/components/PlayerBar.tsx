import { useEffect, useRef, useState } from "react";
import { Play, Pause, SkipBack, SkipForward, Shuffle, Repeat, Volume2 } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import { fmtDuration } from "../pages/LibraryPage";

export default function PlayerBar() {
  const { queue, index, setIndex, playing, setPlaying, queueId } = useStore();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [shuffle, setShuffle] = useState(false);
  const [loop, setLoop] = useState(false);
  const [vol, setVol] = useState(1);
  const [speed, setSpeed] = useState(1);

  const current = queue[index] ?? null;

  // Reload + play whenever the queue identity or index changes (keyed on
  // queueId so a fresh queue at the same index still reloads).
  useEffect(() => {
    const audio = audioRef.current;
    const track = queue[index];
    if (!audio || !track) return;
    setTime(0);
    setDuration(0);
    audio.src = api.streamUrl(track.path);
    audio.playbackRate = speed; // fresh <src> resets the rate
    audio.play().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, queueId]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) audio.playbackRate = speed;
  }, [speed]);

  // Keyboard shortcuts: Space pause/play · [ / ] speed down/up · 0 reset ·
  // ← / → seek ±5s. Never hijacks typing or the lyrics editor (which owns
  // Space while stamping).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t.isContentEditable) return;
      const code = e.code;
      if (code === "Space") {
        if (document.querySelector("[data-lrc-editor]")) return;
        e.preventDefault();
        const a = audioRef.current;
        if (!a || !current) return;
        if (playing) {
          a.pause();
          setPlaying(null);
        } else {
          a.play().catch(() => {});
          setPlaying(current.path);
        }
      } else if (code === "BracketLeft") {
        setSpeed((s) => Math.max(0.5, Math.round((s - 0.25) * 100) / 100));
      } else if (code === "BracketRight") {
        setSpeed((s) => Math.min(2, Math.round((s + 0.25) * 100) / 100));
      } else if (code === "Digit0") {
        setSpeed(1);
      } else if (code === "ArrowLeft") {
        const a = audioRef.current;
        if (a) a.currentTime = Math.max(0, a.currentTime - 5);
      } else if (code === "ArrowRight") {
        const a = audioRef.current;
        if (a && a.duration) a.currentTime = Math.min(a.duration, a.currentTime + 5);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [playing, current]);

  const SPEEDS = [0.75, 1, 1.25, 1.5, 2];
  const cycleSpeed = () =>
    setSpeed((s) => {
      const i = SPEEDS.indexOf(s);
      return SPEEDS[(i + 1) % SPEEDS.length];
    });
  const fmtSpeed = (s: number) =>
    s === 1 ? "1×" : `${s.toFixed(2).replace(/0+$/, "").replace(/\.$/, "")}×`;

  const step = (dir: 1 | -1) => {
    const n = queue.length;
    if (!n) return;
    let next: number;
    if (shuffle) {
      next = Math.floor(Math.random() * n);
      if (n > 1) while (next === index) next = Math.floor(Math.random() * n);
    } else {
      next = (index + dir + n) % n;
    }
    setIndex(next);
    setPlaying(queue[next]?.path ?? null);
  };

  useEffect(() => {
    const onEnded = () => {
      if (loop) {
        const a = audioRef.current;
        if (a) {
          a.currentTime = 0;
          a.play().catch(() => {});
        }
      } else step(1);
    };
    const audio = audioRef.current;
    audio?.addEventListener("ended", onEnded);
    return () => audio?.removeEventListener("ended", onEnded);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queue.length, index, shuffle, loop]);

  if (!current) {
    return (
      <div className="h-14 shrink-0 border-t border-border bg-panel flex items-center px-4 text-xs text-zinc-600">
        No track playing — use Play on an album, artist or track.
      </div>
    );
  }

  return (
    <div className="h-16 shrink-0 border-t border-border bg-panel flex items-center gap-4 px-4">
      <audio
        ref={audioRef}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
      />

      <div className="min-w-0 flex-1">
        <div className="text-sm truncate font-medium">{current.file.replace(/\.[^.]+$/, "")}</div>
        <div className="text-[11px] text-zinc-500 truncate">
          {current.artist ?? current.albumPath.split("/").pop()}
          <span className="ml-2">{queue.length > 1 ? `${index + 1}/${queue.length}` : ""}</span>
        </div>
      </div>

      <div className="flex items-center gap-1">
        <button className={`p-2 rounded hover:bg-raise ${shuffle ? "text-accent" : "text-zinc-500"}`} onClick={() => setShuffle(!shuffle)} title="Shuffle">
          <Shuffle className="h-4 w-4" />
        </button>
        <button className="p-2 rounded hover:bg-raise text-zinc-300" onClick={() => step(-1)}>
          <SkipBack className="h-4 w-4" />
        </button>
        <button
          className="p-2.5 rounded-full bg-accent on-accent hover:bg-accent-soft"
          onClick={() => {
            const a = audioRef.current;
            if (!a) return;
            if (playing) {
              a.pause();
              setPlaying(null);
            } else {
              a.play().catch(() => {});
              setPlaying(current.path);
            }
          }}
        >
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
        </button>
        <button className="p-2 rounded hover:bg-raise text-zinc-300" onClick={() => step(1)}>
          <SkipForward className="h-4 w-4" />
        </button>
        <button className={`p-2 rounded hover:bg-raise ${loop ? "text-accent" : "text-zinc-500"}`} onClick={() => setLoop(!loop)} title="Repeat one">
          <Repeat className="h-4 w-4" />
        </button>
        <button
          className="p-1.5 rounded hover:bg-raise text-xs font-mono text-zinc-400 min-w-[46px]"
          onClick={cycleSpeed}
          title="Playback speed — [ slower · ] faster · 0 reset to 1×"
        >
          {fmtSpeed(speed)}
        </button>
      </div>

      <div className="flex items-center gap-2 text-xs text-zinc-400 flex-1 max-w-[460px]">
        <span className="w-10 text-right shrink-0">{fmtDuration(time)}</span>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.05}
          value={Math.min(time, duration || 0)}
          onChange={(e) => {
            const a = audioRef.current;
            if (!a) return;
            a.currentTime = Number(e.target.value);
            setTime(Number(e.target.value));
          }}
          className="flex-1 "
          title="Seek — ← / → nudge 5s"
        />
        <span className="w-10 shrink-0">{fmtDuration(duration)}</span>
        <Volume2 className="h-4 w-4 text-zinc-500" />
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={vol}
          onChange={(e) => {
            const v = Number(e.target.value);
            setVol(v);
            if (audioRef.current) audioRef.current.volume = v;
          }}
          className="w-20 "
        />
      </div>
    </div>
  );
}