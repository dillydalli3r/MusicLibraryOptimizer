import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Disc3, Heart, Maximize2, Play, Pause, SkipBack, SkipForward, Shuffle, Repeat, Volume2 } from "lucide-react";
import { api } from "../api";
import { toast, useStore } from "../store";
import { fmtDuration } from "../pages/LibraryPage";
import NowPlayingView from "./NowPlayingView";
import TrackDownloadExport from "./TrackDownloadExport";

export default function PlayerBar() {
  const { queue, index, setIndex, playing, setPlaying, queueId, vol, setVol } = useStore();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [shuffle, setShuffle] = useState(false);
  const [loop, setLoop] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const qc = useQueryClient();

  const current = queue[index] ?? null;

  // Queue entries built outside the library pages (e.g. .m3u8 playlist rows)
  // carry no title — fetch the tag lazily so the bar shows the song title,
  // never the file name, whenever a TITLE tag exists. Also yields the
  // MusicBrainz recording ID used for move-safe likes.
  const { data: currentTags } = useQuery({
    queryKey: ["tags", current?.path],
    queryFn: () => api.tags(current!.path),
    enabled: !!current,
    staleTime: 5 * 60 * 1000,
  });
  const displayTitle =
    current?.title || currentTags?.tags?.TITLE || (current ? current.file.replace(/\.[^.]+$/, "") : "");
  // Audio tech summary for the now playing bar: "FLAC · 1022 kbps · 16 bit · 44.1 kHz"
  const t = currentTags?.tech as
    | { bitrate?: number; sample_rate?: number; bits_per_sample?: number; codec?: string }
    | undefined;
  const techStr = t
    ? [
        t.codec ?? null,
        t.bitrate ? `${Math.round(t.bitrate / 1000)} kbps` : null,
        t.bits_per_sample ? `${Math.round(t.bits_per_sample)} bit` : null,
        t.sample_rate ? `${(t.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  const [thumbFailed, setThumbFailed] = useState(false);
  useEffect(() => setThumbFailed(false), [current?.path]);
  const stepRef = useRef<(dir: 1 | -1) => void>(() => {});

  // OS-level media controls (lockscreen / media keys) — guarded, best effort.
  useEffect(() => {
    const ms = (navigator as any).mediaSession;
    if (!ms || !current) return;
    try {
      if (typeof (window as any).MediaMetadata === "function") {
        ms.metadata = new (window as any).MediaMetadata({
          title: displayTitle,
          artist: current.artist ?? "",
          album: current.album ?? "",
          artwork: [{ src: api.coverUrl(current.albumPath), sizes: "512x512", type: "image/jpeg" }],
        });
      }
      ms.setActionHandler("play", () => {
        audioRef.current?.play();
        setPlaying(current.path);
      });
      ms.setActionHandler("pause", () => {
        audioRef.current?.pause();
        setPlaying(null);
      });
      ms.setActionHandler("previoustrack", () => stepRef.current(-1));
      ms.setActionHandler("nexttrack", () => stepRef.current(1));
    } catch {
      /* media session unsupported — ignore */
    }
  }, [current, displayTitle]);

  const { data: likesData } = useQuery({ queryKey: ["likes"], queryFn: api.likes });
  const liked = !!current && (likesData?.paths ?? []).includes(current.path);
  const toggleLike = () => {
    if (!current) return;
    api
      .likeToggle(current.path, currentTags?.tags?.MUSICBRAINZ_TRACKID ?? undefined)
      .then((r) => {
        qc.invalidateQueries({ queryKey: ["likes"] });
        toast(`${r.liked ? "Liked" : "Unliked"} — ${displayTitle}`);
      })
      .catch((e) => toast(String(e)));
  };

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

  // Global volume: the stored value is re-applied to the <audio> element
  // whenever it changes or a new source loads.
  useEffect(() => {
    const audio = audioRef.current;
    if (audio) audio.volume = vol;
  }, [vol, current?.path]);

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
        if (document.querySelector("[data-lrc-editor]")) return; // lyrics editor owns seeking
        const a = audioRef.current;
        if (a) a.currentTime = Math.max(0, a.currentTime - 5);
      } else if (code === "ArrowRight") {
        if (document.querySelector("[data-lrc-editor]")) return;
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
  stepRef.current = step;

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
      <div className="shrink-0 px-3 pb-3 pt-1">
        <div className="h-12 rounded-2xl border border-border bg-panel flex items-center px-4 text-xs text-zinc-600">
          No track playing — use Play on an album, artist or track.
        </div>
      </div>
    );
  }

  return (
    // Floating rounded bar: margins + pill radius instead of a full-bleed
    // strip, lifted with a border and shadow. Center column: the seek bar
    // sits ABOVE the transport controls; the right cluster keeps like /
    // volume / fullscreen.
    <div className="shrink-0 px-3 pb-3 pt-1">
    <div className="h-20 rounded-lg border border-border bg-panel shadow-lg shadow-black/40 flex items-center gap-4 px-4">
      <audio
        ref={audioRef}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
      />

      <button
        className="relative h-16 w-16 rounded-lg overflow-hidden border border-border bg-raise shrink-0 flex items-center justify-center hover:scale-[1.03] transition-transform"
        onClick={() => setFullscreen(true)}
        title="Album art — click for the fullscreen player"
      >
        {!thumbFailed ? (
          <img
            src={api.coverUrl(current.albumPath)}
            alt=""
            onError={() => setThumbFailed(true)}
            className="h-full w-full object-cover"
          />
        ) : (
          <Disc3 className="h-4 w-4 text-zinc-600" />
        )}
      </button>

      <div className="min-w-0 w-52 shrink-0">
        <div className="text-sm truncate font-semibold">{displayTitle}</div>
        <div className="text-[11px] text-zinc-500 truncate">
          {[current.artist ?? current.albumPath.split("/").pop(), current.album]
            .filter(Boolean)
            .join(" · ")}
          <span className="ml-2">{queue.length > 1 ? `${index + 1}/${queue.length}` : ""}</span>
          {techStr && (
            <span className="ml-2 font-mono text-[10px] text-zinc-600" title="Bitrate · sample rate · bit depth">
              {techStr}
            </span>
          )}
        </div>
      </div>

      {/* center: seek bar above the transport controls */}
      <div className="flex-1 min-w-0 flex flex-col items-center justify-center gap-0.5">
        <div className="flex items-center gap-2 w-full max-w-2xl text-[10px] text-zinc-500 tabular-nums">
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
            className="flex-1"
            title="Seek — ← / → nudge 5s"
          />
          <span className="w-10 shrink-0">{fmtDuration(duration)}</span>
        </div>
        <div className="flex items-center gap-1">
          <button className={`p-2 rounded-lg hover:bg-raise ${shuffle ? "text-accent" : "text-zinc-500"}`} onClick={() => setShuffle(!shuffle)} title="Shuffle">
            <Shuffle className="h-4 w-4" />
          </button>
          <button className="p-2 rounded-lg hover:bg-raise text-zinc-300" onClick={() => step(-1)}>
            <SkipBack className="h-4 w-4" />
          </button>
          <button
            className="p-2.5 rounded-lg bg-accent on-accent hover:bg-accent-soft active:scale-95 transition-transform"
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
          <button className="p-2 rounded-lg hover:bg-raise text-zinc-300" onClick={() => step(1)}>
            <SkipForward className="h-4 w-4" />
          </button>
          <button className={`p-2 rounded-lg hover:bg-raise ${loop ? "text-accent" : "text-zinc-500"}`} onClick={() => setLoop(!loop)} title="Repeat one">
            <Repeat className="h-4 w-4" />
          </button>
          <button
            className="p-1.5 rounded-lg hover:bg-raise text-xs font-mono text-zinc-400 min-w-[46px]"
            onClick={cycleSpeed}
            title="Playback speed — [ slower · ] faster · 0 reset to 1×"
          >
            {fmtSpeed(speed)}
          </button>
        </div>
      </div>

      {/* keep the file: browser download of the original + transcode export */}
      <TrackDownloadExport path={current.path} compact />

      <button
        className={`p-2 rounded-lg hover:bg-raise shrink-0 ${liked ? "text-accent" : "text-zinc-500 hover:text-zinc-300"}`}
        onClick={toggleLike}
        title={liked ? "Unlike" : "Like this track"}
      >
        <Heart className={`h-4 w-4 ${liked ? "fill-current" : ""}`} />
      </button>

      <div className="flex items-center gap-2 text-zinc-400 shrink-0" title={`Volume — ${Math.round(vol * 100)}%`}>
        <Volume2 className="h-4 w-4 text-zinc-500" />
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={vol}
          onChange={(e) => setVol(Number(e.target.value))}
          className="w-32"
          title="Volume — shared by the whole app"
        />
      </div>

      <button
        className="p-2 rounded-lg hover:bg-raise text-zinc-400 hover:text-white shrink-0"
        onClick={() => setFullscreen(true)}
        title="Fullscreen player with lyrics"
      >
        <Maximize2 className="h-4 w-4" />
      </button>

      {fullscreen && (
        <NowPlayingView
          current={current}
          queuePos={queue.length > 1 ? `${index + 1}/${queue.length}` : ""}
          playing={!!playing}
          time={time}
          duration={duration}
          shuffle={shuffle}
          loop={loop}
          liked={liked}
          onTogglePlay={() => {
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
          onSeek={(t) => {
            const a = audioRef.current;
            if (!a) return;
            a.currentTime = t;
            setTime(t);
          }}
          onStep={step}
          onToggleShuffle={() => setShuffle(!shuffle)}
          onToggleLoop={() => setLoop(!loop)}
          onToggleLike={toggleLike}
          onClose={() => setFullscreen(false)}
          getAudioTime={() => audioRef.current?.currentTime ?? 0}
        />
      )}
    </div>
    </div>
  );
}