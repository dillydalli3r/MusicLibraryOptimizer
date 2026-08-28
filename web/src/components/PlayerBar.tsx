import { useEffect, useRef, useState } from "react";
import { Play, Pause, SkipBack, SkipForward, Shuffle, Repeat, Volume2 } from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import { fmtDuration } from "../pages/LibraryPage";

export default function PlayerBar() {
  const { queue, index, setIndex, playing, setPlaying } = useStore();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [shuffle, setShuffle] = useState(false);
  const [loop, setLoop] = useState(false);
  const [vol, setVol] = useState(1);

  const current = queue[index] ?? null;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !current) return;
    audio.src = api.streamUrl(current.path);
    audio.play().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.path]);

  const step = (dir: 1 | -1) => {
    if (!queue.length) return;
    if (shuffle) {
      let n = Math.floor(Math.random() * queue.length);
      if (queue.length > 1) while (n === index) n = Math.floor(Math.random() * queue.length);
      setIndex(n);
      return;
    }
    setIndex((index + dir + queue.length) % queue.length);
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
          className="p-2.5 rounded-full bg-accent text-white hover:bg-accent-soft"
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
      </div>

      <div className="hidden md:flex items-center gap-2 text-xs text-zinc-400 w-[420px]">
        <span className="w-10 text-right">{fmtDuration(time)}</span>
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
          className="flex-1 accent-violet-500"
        />
        <span className="w-10">{fmtDuration(duration)}</span>
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
          className="w-20 accent-violet-500"
        />
      </div>
    </div>
  );
}