import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Disc3, Heart, ListMusic, ListPlus, Maximize2, Mic2, Play, Pause, SkipBack, SkipForward, Shuffle, Repeat, Timer, Volume2, X } from "lucide-react";
import { api } from "../api";
import { toast, useStore } from "../store";
import { fmtDuration } from "../pages/LibraryPage";
import { fmtTech } from "../lib/fmt";
import NowPlayingView from "./NowPlayingView";
import LyricsSidebar from "./LyricsSidebar";
import TrackDownloadExport from "./TrackDownloadExport";

/** Thin vertical rule separating functional groups in the bar. */
function BarDivider() {
  return <div className="w-px h-6 bg-border/80 shrink-0" aria-hidden />;
}

export default function PlayerBar() {
  const { queue, index, setIndex, setQueue, queueRemoveAt, playing, setPlaying, queueId, vol, setVol } = useStore();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [shuffle, setShuffle] = useState(false);
  const [loop, setLoop] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const [plOpen, setPlOpen] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [lyricsOpen, setLyricsOpen] = useState(false);
  // sleep timer: an epoch-ms deadline, or "pause when this track ends"
  const [sleepOpen, setSleepOpen] = useState(false);
  const [sleepAt, setSleepAt] = useState<number | null>(null);
  const [sleepStopNext, setSleepStopNext] = useState(false);
  const [, setSleepTick] = useState(0);
  const qc = useQueryClient();

  const current = queue[index] ?? null;
  const idle = !current;

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
  // Condensed audio tech readout for beside the title: "FLAC · 1022k · 16/44.1"
  const techStr = fmtTech(currentTags?.tech as
    | { codec?: string; bitrate?: number; bits_per_sample?: number; sample_rate?: number }
    | undefined);
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

  const { data: playlists } = useQuery({
    queryKey: ["playlists"],
    queryFn: api.playlists,
    enabled: plOpen,
  });
  const addToPlaylist = async (pid: number, name: string) => {
    if (!current) return;
    try {
      await api.playlistAdd(pid, [current.path]);
      toast(`Added “${displayTitle}” to ${name}`);
      setPlOpen(false);
      qc.invalidateQueries({ queryKey: ["playlists"] });
    } catch (e) {
      toast(String(e));
    }
  };
  const newPlaylistAndAdd = async () => {
    if (!current) return;
    const name = window.prompt("New playlist name");
    if (!name?.trim()) return;
    try {
      const pl = await api.createPlaylist(name.trim(), "manual");
      await api.playlistAdd(pl.id, [current.path]);
      toast(`Added “${displayTitle}” to ${name.trim()}`);
      setPlOpen(false);
      qc.invalidateQueries({ queryKey: ["playlists"] });
    } catch (e) {
      toast(String(e));
    }
  };

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

  // ---- sleep timer ---------------------------------------------------------
  const SLEEP_CHOICES = [5, 15, 30, 45, 60];
  const armSleep = (mins: number) => {
    setSleepAt(Date.now() + mins * 60000);
    setSleepStopNext(false);
    setSleepOpen(false);
    toast(`Sleep timer — pausing in ${mins} min`);
  };
  const armSleepEndOfTrack = () => {
    setSleepStopNext(true);
    setSleepAt(null);
    setSleepOpen(false);
    toast("Sleep timer — pausing after this track");
  };
  const cancelSleep = () => {
    setSleepAt(null);
    setSleepStopNext(false);
    setSleepOpen(false);
    toast("Sleep timer cancelled");
  };
  const sleepRemaining = sleepAt !== null ? Math.max(0, sleepAt - Date.now()) : null;
  const fmtRemaining = (ms: number) => {
    const s = Math.ceil(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const ss = s % 60;
    return h
      ? `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
      : `${m}:${String(ss).padStart(2, "0")}`;
  };
  // countdown ticker + the actual pause when the deadline passes
  useEffect(() => {
    if (sleepAt === null) return;
    const iv = setInterval(() => {
      if (Date.now() >= sleepAt) {
        audioRef.current?.pause();
        useStore.getState().setPlaying(null);
        setSleepAt(null);
        toast("Sleep timer — playback paused");
      }
      setSleepTick((t) => t + 1);
    }, 1000);
    return () => clearInterval(iv);
  }, [sleepAt]);

  useEffect(() => {
    const onEnded = () => {
      if (sleepStopNext) {
        audioRef.current?.pause();
        useStore.getState().setPlaying(null);
        setSleepStopNext(false);
        toast("Sleep timer — playback paused");
        return;
      }
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
  }, [queue.length, index, shuffle, loop, sleepStopNext]);

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a || !current) return;
    if (playing) {
      a.pause();
      setPlaying(null);
    } else {
      a.play().catch(() => {});
      setPlaying(current.path);
    }
  };

  // ONE bar for both states — same height, radius and layout whether or not
  // something is playing; idle just disables the transport and shows a hint.
  return (
    <div className="shrink-0 px-3 pb-3 pt-1">
      <div className="h-[4.75rem] rounded-lg border border-border bg-panel shadow-lg shadow-black/40 flex items-center gap-3 pr-4">
        <audio
          ref={audioRef}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        />

        {/* left: cover art, flush with the bar's left edge (full bar height,
            square; the bar's own margin keeps it off the screen edge) */}
        <button
          className={`relative self-stretch aspect-square rounded-l-[5px] overflow-hidden bg-raise shrink-0 flex items-center justify-center ${
            idle ? "cursor-default" : "group/cover"
          }`}
          onClick={() => !idle && setFullscreen(true)}
          title={idle ? "Nothing playing" : "Album art — click for the fullscreen player"}
          disabled={idle}
        >
          {current && !thumbFailed ? (
            <img
              src={api.coverUrl(current.albumPath)}
              alt=""
              onError={() => setThumbFailed(true)}
              className="h-full w-full object-cover group-hover/cover:scale-[1.04] transition-transform"
            />
          ) : (
            <Disc3 className={`h-5 w-5 ${idle ? "text-zinc-700" : "text-zinc-600"}`} />
          )}
        </button>

        <div className="min-w-0 w-56 shrink-0" title={current ? [current.artist, current.album].filter(Boolean).join(" · ") : undefined}>
          {current ? (
            <>
              <div className="flex items-baseline gap-2 min-w-0">
                <span className="text-sm truncate font-semibold">{displayTitle}</span>
                {techStr && (
                  <span className="text-[10px] font-mono text-zinc-500 truncate shrink-0" title="Codec · bitrate · bit depth/sample rate">
                    {techStr}
                  </span>
                )}
              </div>
              <div className="text-[11px] text-zinc-500 truncate">{current.album ?? "—"}</div>
              <div className="text-[11px] text-zinc-500 truncate">{current.artist ?? current.albumPath.split("/").pop()}</div>
            </>
          ) : (
            <>
              <div className="text-sm truncate font-semibold text-zinc-500">Nothing playing</div>
              <div className="text-[11px] text-zinc-600 truncate">
                Play an album, artist or playlist to start
              </div>
            </>
          )}
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
              disabled={idle}
              title="Seek — ← / → nudge 5s"
            />
            <span className="w-10 shrink-0">{fmtDuration(duration)}</span>
          </div>
          <div className="flex items-center gap-0.5">
            <button
              className={`p-2 rounded-lg hover:bg-raise ${shuffle ? "text-accent" : "text-zinc-500"}`}
              onClick={() => setShuffle(!shuffle)}
              disabled={idle}
              title="Shuffle"
            >
              <Shuffle className="h-4 w-4" />
            </button>
            <button className="p-2 rounded-lg hover:bg-raise text-zinc-300" onClick={() => step(-1)} disabled={idle}>
              <SkipBack className="h-4 w-4" />
            </button>
            <button
              className={`p-2.5 rounded-lg bg-accent on-accent hover:bg-accent-soft active:scale-95 transition-transform ${
                idle ? "opacity-40 pointer-events-none" : ""
              }`}
              onClick={togglePlay}
              disabled={idle}
            >
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
            </button>
            <button className="p-2 rounded-lg hover:bg-raise text-zinc-300" onClick={() => step(1)} disabled={idle}>
              <SkipForward className="h-4 w-4" />
            </button>
            <button
              className={`p-2 rounded-lg hover:bg-raise ${loop ? "text-accent" : "text-zinc-500"}`}
              onClick={() => setLoop(!loop)}
              disabled={idle}
              title="Repeat one"
            >
              <Repeat className="h-4 w-4" />
            </button>
            <button
              className={`p-1.5 rounded-lg hover:bg-raise text-xs font-mono text-zinc-400 min-w-[46px] ${
                idle ? "opacity-40 pointer-events-none" : ""
              }`}
              onClick={cycleSpeed}
              disabled={idle}
              title="Playback speed — [ slower · ] faster · 0 reset to 1×"
            >
              {fmtSpeed(speed)}
            </button>
          </div>
        </div>

        {/* right cluster, grouped: queue · track actions · volume · view */}
        <div className="flex items-center gap-1 shrink-0">
          {/* queue position — the fraction lives here, left of the playlist
              button; clicking it (or the queue button) opens the queue */}
          {current && queue.length > 1 && (
            <button
              className={`px-1.5 py-1 rounded-md font-mono text-[10px] tabular-nums shrink-0 transition-colors ${
                queueOpen ? "text-accent bg-raise" : "text-zinc-500 hover:text-white hover:bg-raise"
              }`}
              onClick={() => setQueueOpen(!queueOpen)}
              title={`Queue position — ${index + 1} of ${queue.length} · click to view the queue`}
            >
              {index + 1}/{queue.length}
            </button>
          )}

          {/* queue popover: upcoming tracks, click to jump, ✕ to remove */}
          <div className="relative">
            <button
              className={`p-2 rounded-lg hover:bg-raise shrink-0 ${
                queueOpen ? "text-accent bg-raise" : "text-zinc-400 hover:text-white"
              } ${idle ? "opacity-40 pointer-events-none" : ""}`}
              onClick={() => setQueueOpen(!queueOpen)}
              disabled={idle}
              title="Queue"
              aria-label="Queue"
            >
              <ListMusic className="h-4 w-4" />
            </button>
            {queueOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setQueueOpen(false)} />
                <div className="absolute right-0 bottom-full mb-2 z-50 w-80 rounded-lg border border-border bg-zinc-950 shadow-2xl p-1.5 max-h-80 overflow-auto">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-2 pt-1 pb-1 flex items-center justify-between">
                    Queue
                    {queue.length > index + 1 && (
                      <button
                        className="text-[10px] normal-case text-zinc-500 hover:text-white"
                        onClick={() => setQueue(queue.slice(0, index + 1))}
                        title="Remove upcoming tracks"
                      >
                        clear upcoming
                      </button>
                    )}
                  </div>
                  {current && (
                    <div className="px-2 py-1.5 rounded-md bg-raise/60 flex items-center gap-2">
                      <Play className="h-3 w-3 text-accent shrink-0" />
                      <span className="text-xs text-zinc-200 truncate flex-1">{displayTitle}</span>
                      <span className="text-[10px] text-zinc-600 shrink-0">playing</span>
                    </div>
                  )}
                  {queue.slice(index + 1).map((t, off) => {
                    const i = index + 1 + off;
                    return (
                      <div key={`${t.path}-${i}`} className="group/qr flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/10">
                        <button
                          className="min-w-0 flex-1 text-left"
                          onClick={() => {
                            setIndex(i);
                            setPlaying(t.path);
                            setQueueOpen(false);
                          }}
                          title="Play this track now"
                        >
                          <div className="text-xs text-zinc-300 truncate">{t.title || t.file.replace(/\.[^.]+$/, "")}</div>
                          <div className="text-[10px] text-zinc-600 truncate">
                            {[t.artist, t.album].filter(Boolean).join(" · ")}
                          </div>
                        </button>
                        <button
                          className="p-1 rounded text-zinc-600 hover:text-red-300 hover:bg-white/5 opacity-0 group-hover/qr:opacity-100 transition-opacity shrink-0"
                          onClick={() => queueRemoveAt(i)}
                          title="Remove from queue"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    );
                  })}
                  {queue.length <= index + 1 && (
                    <div className="text-[10px] text-zinc-600 px-2 py-1">Nothing up next — it ends after this track.</div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* sleep timer */}
          <div className="relative">
            <button
              className={`p-2 rounded-lg hover:bg-raise shrink-0 flex items-center gap-1 ${
                sleepAt !== null || sleepStopNext
                  ? "text-accent bg-raise"
                  : "text-zinc-400 hover:text-white"
              } ${idle ? "opacity-40 pointer-events-none" : ""}`}
              onClick={() => setSleepOpen(!sleepOpen)}
              disabled={idle}
              title={sleepAt !== null ? `Sleep timer — ${fmtRemaining(sleepRemaining ?? 0)} left` : sleepStopNext ? "Sleep timer — stops after this track" : "Sleep timer"}
              aria-label="Sleep timer"
            >
              <Timer className="h-4 w-4" />
              {sleepAt !== null && (
                <span className="text-[10px] font-mono tabular-nums">{fmtRemaining(sleepRemaining ?? 0)}</span>
              )}
              {sleepStopNext && <span className="text-[10px] font-mono">1t</span>}
            </button>
            {sleepOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setSleepOpen(false)} />
                <div className="absolute right-0 bottom-full mb-2 z-50 w-48 rounded-lg border border-border bg-zinc-950 shadow-2xl p-1.5">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-2 pt-1 pb-1">Sleep timer</div>
                  <button className="w-full text-left text-xs px-2 py-1.5 rounded-md hover:bg-white/10 text-zinc-300" onClick={armSleepEndOfTrack}>
                    After this track
                  </button>
                  {SLEEP_CHOICES.map((m) => (
                    <button
                      key={m}
                      className="w-full text-left text-xs px-2 py-1.5 rounded-md hover:bg-white/10 text-zinc-300 flex items-center justify-between"
                      onClick={() => armSleep(m)}
                    >
                      <span>{m} minutes</span>
                    </button>
                  ))}
                  {(sleepAt !== null || sleepStopNext) && (
                    <button className="w-full text-left text-xs px-2 py-1.5 rounded-md hover:bg-white/10 text-red-300" onClick={cancelSleep}>
                      Cancel timer
                    </button>
                  )}
                </div>
              </>
            )}
          </div>

          <div className="relative">
            <button
              className={`p-2 rounded-lg hover:bg-raise shrink-0 ${
                plOpen ? "text-accent bg-raise" : "text-zinc-400 hover:text-white"
              } ${idle ? "opacity-40 pointer-events-none" : ""}`}
              onClick={() => setPlOpen(!plOpen)}
              disabled={idle}
              title="Add to playlist"
              aria-label="Add to playlist"
            >
              <ListPlus className="h-4 w-4" />
            </button>
            {plOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setPlOpen(false)} />
                <div className="absolute right-0 bottom-full mb-2 z-50 w-56 rounded-lg border border-border bg-zinc-950 shadow-2xl p-1.5 max-h-64 overflow-auto">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-2 pt-1 pb-1">Add to playlist</div>
                  <button
                    className="w-full text-left text-xs px-2 py-1.5 rounded-md hover:bg-white/10 text-accent-soft"
                    onClick={newPlaylistAndAdd}
                  >
                    <ListPlus className="h-3.5 w-3.5 inline mr-1.5 -mt-0.5" /> New playlist…
                  </button>
                  {(playlists ?? []).map((p) => (
                    <button
                      key={p.id}
                      className="w-full text-left text-xs px-2 py-1.5 rounded-md hover:bg-white/10 text-zinc-300 flex items-center justify-between gap-2"
                      onClick={() => addToPlaylist(p.id, p.name)}
                    >
                      <span className="truncate">{p.name}</span>
                      <span className="text-[10px] text-zinc-600 shrink-0">{p.track_count}</span>
                    </button>
                  ))}
                  {(playlists ?? []).length === 0 && (
                    <div className="text-[10px] text-zinc-600 px-2 py-1">No playlists yet — create one above.</div>
                  )}
                </div>
              </>
            )}
          </div>

          {current && <TrackDownloadExport path={current.path} iconOnly />}

          <button
            className={`p-2 rounded-lg hover:bg-raise shrink-0 ${
              liked ? "text-accent" : "text-zinc-500 hover:text-zinc-300"
            } ${idle ? "opacity-40 pointer-events-none" : ""}`}
            onClick={toggleLike}
            disabled={idle}
            title={liked ? "Unlike" : "Like this track"}
          >
            <Heart className={`h-4 w-4 ${liked ? "fill-current" : ""}`} />
          </button>

          <BarDivider />

          <div className="flex items-center gap-2 text-zinc-400 shrink-0" title={`Volume — ${Math.round(vol * 100)}%`}>
            <Volume2 className="h-4 w-4 text-zinc-500" />
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={vol}
              onChange={(e) => setVol(Number(e.target.value))}
              className="w-28"
              title="Volume — shared by the whole app"
            />
          </div>

          <BarDivider />

          <button
            className={`p-2 rounded-lg hover:bg-raise shrink-0 ${
              lyricsOpen ? "text-accent bg-raise" : "text-zinc-400 hover:text-white"
            }`}
            onClick={() => setLyricsOpen(!lyricsOpen)}
            disabled={idle}
            title="Lyrics — open the sidebar"
            aria-label="Lyrics"
          >
            <Mic2 className="h-4 w-4" />
          </button>

          <button
            className={`p-2 rounded-lg hover:bg-raise text-zinc-400 hover:text-white shrink-0 ${
              idle ? "opacity-40 pointer-events-none" : ""
            }`}
            onClick={() => setFullscreen(true)}
            disabled={idle}
            title="Fullscreen player with lyrics"
          >
            <Maximize2 className="h-4 w-4" />
          </button>
        </div>

        {fullscreen && current && (
          <NowPlayingView
            current={current}
            queuePos={queue.length > 1 ? `${index + 1}/${queue.length}` : ""}
            playing={!!playing}
            time={time}
            duration={duration}
            shuffle={shuffle}
            loop={loop}
            liked={liked}
            onTogglePlay={togglePlay}
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

        {lyricsOpen && current && (
          <LyricsSidebar
            current={current}
            playing={!!playing}
            time={time}
            onSeek={(t) => {
              const a = audioRef.current;
              if (!a) return;
              a.currentTime = t;
              setTime(t);
            }}
            getAudioTime={() => audioRef.current?.currentTime ?? 0}
            onClose={() => setLyricsOpen(false)}
          />
        )}
      </div>
    </div>
  );
}
