import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown, Heart, ListMusic, ListPlus, Pause, Play, Repeat, Settings2, Shuffle,
  SkipBack, SkipForward, Volume1, Volume2, VolumeX, X,
} from "lucide-react";
import { api } from "../api";
import { toast, useStore } from "../store";
import CoverImg from "./CoverImg";
import { SubtitledVideo } from "./SubtitledVideo";
import { parseLrc, type LrcLine } from "./LyricsViewer";
import type { Playlist } from "../types";

const XLIT_KEY = "mlo.np.xlit";
const TRANS_KEY = "mlo.np.trans";
const SIZE_KEY = "mlo.np.size"; // sm | md | lg
const KARAOKE_KEY = "mlo.np.karaoke"; // "1" = word-level karaoke, "0" = line highlight
const ORBS_KEY = "mlo.np.orbs"; // "1" = animated background
const VIS_KEY = "mlo.np.vis"; // "1" = background pulses with the beat
const ZOOM_KEY = "mlo.np.lyrzoom"; // lyrics zoom multiplier (persisted)

interface Props {
  current: { path: string; file: string; albumPath: string; artist?: string; album?: string; title?: string };
  queuePos: string;
  playing: boolean;
  time: number;
  duration: number;
  shuffle: boolean;
  loop: boolean;
  liked: boolean;
  onTogglePlay: () => void;
  onSeek: (t: number) => void;
  onStep: (d: 1 | -1) => void;
  onToggleShuffle: () => void;
  onToggleLoop: () => void;
  onToggleLike: () => void;
  onClose: () => void;
  getAudioTime?: () => number;
}

function hexToRgbTriplet(hex?: string | null): [number, number, number] | null {
  if (!hex) return null;
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const LYRIC_SIZES = {
  sm: { line: "text-base", active: "text-xl", word: "text-base", xlit: "text-[11px]" },
  md: { line: "text-xl", active: "text-[2rem]", word: "text-xl", xlit: "text-xs" },
  lg: { line: "text-2xl", active: "text-[2.8rem]", word: "text-2xl", xlit: "text-sm" },
} as const;

/** Ease for the active line's growth — slow out, no snap. */
const LINE_EASE = "transition-[font-size,color] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]";

/** Non-current synced lines read greyed-out (a slight blur + dim grey);
 * hovering a line reveals it in full detail. Plain-text lyrics are never
 * styled — only synced lines get the active/inactive treatment. */
const LINE_BLUR = "blur-[2px] opacity-60 hover:blur-none hover:opacity-100 transition-[opacity,filter] duration-300";

export default function NowPlayingView(p: Props) {
  const { vol, setVol } = useStore();
  // Transliteration + translation default ON: script 15 stores the
  // transforms in tags/sidecars, so they render instantly for processed
  // tracks and the AI is only asked for tracks it hasn't seen yet.
  const [showXlit, setShowXlit] = useState(() => localStorage.getItem(XLIT_KEY) !== "0");
  const [showTrans, setShowTrans] = useState(() => localStorage.getItem(TRANS_KEY) !== "0");
  const [lyricSize, setLyricSize] = useState<keyof typeof LYRIC_SIZES>(
    () => (localStorage.getItem(SIZE_KEY) as keyof typeof LYRIC_SIZES) || "md"
  );
  // Extra zoom multiplier on top of the size preset, persisted — the lyrics
  // read "a bit more zoomed in" by default (1.15×).
  const [lyricZoom, setLyricZoom] = useState<number>(
    () => Number(localStorage.getItem(ZOOM_KEY)) || 1.15
  );
  const [karaoke, setKaraoke] = useState(() => localStorage.getItem(KARAOKE_KEY) !== "0");
  const [orbs, setOrbs] = useState(() => localStorage.getItem(ORBS_KEY) !== "0");
  const [vis, setVis] = useState(() => localStorage.getItem(VIS_KEY) !== "0");
  const [options, setOptions] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [plOpen, setPlOpen] = useState(false);
  const [newPlName, setNewPlName] = useState("");
  const [tags, setTags] = useState<Record<string, string> | null>(null);
  const [tech, setTech] = useState<{ bitrate?: number; sample_rate?: number; bits_per_sample?: number; codec?: string } | null>(null);
  const [lyricsText, setLyricsText] = useState<string | null>(null);
  const [transforms, setTransforms] = useState<Record<string, string[]>>({});
  const inFlight = useRef<Set<string>>(new Set());
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const lyricsScrollRef = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();

  // AI availability (checked once): when unconfigured, translation /
  // transliteration are never requested so no endless spinner can appear.
  const [aiReady, setAiReady] = useState<boolean | null>(null);
  useEffect(() => {
    let dead = false;
    api
      .config()
      .then((c) => {
        if (!dead) setAiReady(!!String((c as Record<string, unknown>).ai_base_url ?? "").trim());
      })
      .catch(() => {
        if (!dead) setAiReady(false);
      });
    return () => {
      dead = true;
    };
  }, []);

  const { time, duration } = p;
  const { queue, index, setIndex } = useStore();
  const queueListRef = useRef<HTMLDivElement>(null);

  // Keep the playing row visible when the queue drawer opens.
  useEffect(() => {
    if (!queueOpen) return;
    queueListRef.current
      ?.querySelector(`[data-queue-index="${index}"]`)
      ?.scrollIntoView({ block: "center" });
  }, [queueOpen, index]);

  // ~60 fps lyric clock: while playing, rAF reads the shared <audio> element
  // directly so word highlighting isn't stepped at timeupdate's ~4 Hz.
  const [smoothTime, setSmoothTime] = useState(0);
  useEffect(() => {
    if (!p.playing) return;
    let raf = 0;
    const tick = () => {
      const t = p.getAudioTime?.();
      if (typeof t === "number" && isFinite(t) && t >= 0) setSmoothTime(t);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [p.playing, p.getAudioTime]);
  const dispTime = p.playing && smoothTime > 0 ? smoothTime : time;

  // cover file + dominant color for the ambient background — the album
  // payload also supplies the canonical album artist / album name shown
  // under the cover.
  const { data: album } = useQuery({
    queryKey: ["album", p.current.albumPath],
    queryFn: () => api.album(p.current.albumPath),
    staleTime: 5 * 60 * 1000,
  });
  const coverFile = album?.cover_file ?? null;
  const { data: colorData } = useQuery({
    queryKey: ["coverColor", p.current.albumPath],
    queryFn: () => api.coverColor(p.current.albumPath),
    retry: false,
    staleTime: 10 * 60 * 1000,
  });
  const rgb = hexToRgbTriplet(colorData?.color) ?? [113, 113, 122];

  // ---- background ambience (Apple Music-style, layered) --------------------
  // No uniform brightness flashing: three independent layers keep the
  // background alive —
  //   * the blurred cover slowly "breathes" in scale with a gentle beat pump,
  //   * a colored bloom ring behind the artwork swells only on the beat,
  //   * each color orb waves with its own phase, so light washes around.
  // The envelope is a rAF clock anchored to the track's BPM tag, never tapped
  // from the audio graph, so the shared <audio> element can never be muted by
  // a cross-origin taint. Paused, everything eases into a slow breath.
  const bgRef = useRef<HTMLDivElement>(null);
  const bloomRef = useRef<HTMLDivElement>(null);
  const orbsRef = useRef<HTMLDivElement>(null);
  const eased = useRef({ bloom: 0 });
  useEffect(() => {
    if (!vis) {
      // effect disabled → restore the static ambience
      if (bgRef.current) {
        bgRef.current.style.opacity = "0.25";
        bgRef.current.style.transform = "scale(1.1)";
      }
      if (bloomRef.current) bloomRef.current.style.opacity = "0";
      if (orbsRef.current) {
        orbsRef.current.style.transform = "";
        orbsRef.current.style.filter = "";
        for (const el of orbsRef.current.querySelectorAll<HTMLElement>(".orb")) {
          el.style.opacity = "";
        }
      }
      return;
    }
    const bpm = parseFloat(String(tags?.BPM ?? "")) || 0;
    const bps = bpm > 0 ? Math.min(2.2, bpm / 60) : 1.4; // beats per second
    let raf = 0;
    const t0 = performance.now();
    const orbEls = orbsRef.current
      ? Array.from(orbsRef.current.querySelectorAll<HTMLElement>(".orb"))
      : [];
    const tick = () => {
      const t = (performance.now() - t0) / 1000;
      const frac = p.playing ? (t * bps) % 1 : 0;
      // fast-attack / slow-release envelope on every beat
      const env = p.playing ? Math.pow(Math.exp(-2.2 * frac), 1.4) : 0.12;
      // blurred cover: slow breathing + gentle scale pump (never a flash)
      const breathe = 0.5 + 0.5 * Math.sin(t * 0.21);
      if (bgRef.current) {
        bgRef.current.style.transform = `scale(${(1.08 + 0.05 * breathe + 0.035 * env).toFixed(4)})`;
        bgRef.current.style.opacity = String(0.26 + 0.04 * breathe + 0.02 * env);
      }
      // bloom ring behind the artwork
      eased.current.bloom += (env - eased.current.bloom) * 0.12;
      if (bloomRef.current) {
        bloomRef.current.style.opacity = String(0.18 + 0.3 * eased.current.bloom);
        bloomRef.current.style.transform = `scale(${(0.94 + 0.16 * eased.current.bloom).toFixed(4)})`;
      }
      // Color field: the orbs drift and hue-shift via CSS; the beat only
      // pumps the field's scale and brightness a touch — never opacity, so
      // the background can't flash dark. Each orb keeps its own slow,
      // desynced breathing so light keeps circulating between colors.
      if (orbsRef.current) {
        orbsRef.current.style.transform = `scale(${(1 + 0.025 * env).toFixed(4)})`;
        orbsRef.current.style.filter = `brightness(${(1 + 0.09 * env).toFixed(3)}) saturate(${(1 + 0.18 * env).toFixed(3)})`;
        orbEls.forEach((el, i) => {
          const wave = 0.5 + 0.5 * Math.sin(t * (0.45 + i * 0.17) + i * 2.1);
          el.style.opacity = String(0.6 + 0.25 * wave);
        });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [vis, p.playing, tags?.BPM]);

  // ---- video mirror (music videos in the queue) ----------------------------
  // The <audio> element in the player bar owns the sound — a second unmuted
  // decoder would double the audio — so the picture plays muted and follows
  // the audio clock with a small drift tolerance.
  const videoPath = /\.(mp4|webm|m4v)$/i.test(p.current.file || p.current.path) ? p.current.path : null;
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (!videoPath) return;
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      if (v) {
        const t = p.getAudioTime?.() ?? 0;
        if (isFinite(t) && Math.abs(v.currentTime - t) > 0.35) v.currentTime = t;
        if (p.playing && v.paused) v.play().catch(() => {});
        if (!p.playing && !v.paused) v.pause();
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [videoPath, p.playing, p.getAudioTime]);

  // ---- lyrics for the current track --------------------------------------
  // Stored transforms (script 15 tags / .romaji.lrc / .<lang>.lrc sidecars)
  // arrive with the same payload and are parsed exactly like the original
  // lyrics, so their lines stay 1:1 with `plainLines` without re-alignment.
  useEffect(() => {
    let dead = false;
    setTags(null);
    setTech(null);
    setLyricsText(null);
    setTransforms({});
    setSmoothTime(0);
    inFlight.current.clear();
    api
      .tags(p.current.path)
      .then((t) => {
        if (dead) return;
        setTags(t.tags ?? {});
        setTech((t.tech as typeof tech) ?? null);
        setLyricsText(typeof t.lyrics === "string" ? t.lyrics : null);
        const seeded: Record<string, string[]> = {};
        const splitStored = (s: string): string[] =>
          /\[\d{1,2}:\d{1,2}/.test(s)
            ? parseLrc(s).map((l) => l.text)
            : s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
        if (typeof t.lyrics_xlit === "string" && t.lyrics_xlit.trim())
          seeded.transliterate = splitStored(t.lyrics_xlit);
        if (typeof t.lyrics_trans === "string" && t.lyrics_trans.trim())
          seeded.translate = splitStored(t.lyrics_trans);
        if (Object.keys(seeded).length) setTransforms((prev) => ({ ...prev, ...seeded }));
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
  const hasLyrics = !!lyricsText?.trim() && !instrumental;
  const plainLines = useMemo(() => {
    if (!hasLyrics) return [];
    if (lines.length) return lines.map((l) => l.text);
    return (lyricsText ?? "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  }, [hasLyrics, lines, lyricsText]);
  // Synced lyrics carry timestamps; unsynced ones are plain text — both must
  // flow through renderLine so transliteration/translation applies to each.
  const synced = lines.length > 0;
  const displayLines: LrcLine[] = useMemo(
    () => (synced ? lines : plainLines.map((text) => ({ ts: "", time: 0, text }))),
    [synced, lines, plainLines]
  );

  // ---- translation / transliteration -------------------------------------
  // aiReady === null means the config probe is still running — hold off so
  // we never fire a request that's destined to fail (and spin forever).
  useEffect(() => {
    if (aiReady === null || !aiReady) return;
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
        .catch((e) => {
          // AI failed (rate limit, bad key…) — mark done with no output so
          // the "transforming…" indicator never gets stuck on screen, and
          // surface the reason instead of failing silently.
          setTransforms((prev) => (prev[mode] ? prev : { ...prev, [mode]: [] }));
          toast(`${mode === "translate" ? "Translation" : "Transliteration"} failed: ${e instanceof Error ? e.message : e}`);
        })
        .finally(() => inFlight.current.delete(key));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiReady, showXlit, showTrans, hasLyrics, plainLines, p.current.path]);

  // ---- active line ---------------------------------------------------------
  const activeLine = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].time <= dispTime + 0.02) idx = i;
      else break;
    }
    return idx;
  }, [lines, dispTime]);

  // While the pointer rests on the lyrics the reader owns the pane: the
  // auto-center pauses (it would otherwise scroll the hovered line away)
  // and resumes on leave, re-centering on the active line.
  const [lyricsHover, setLyricsHover] = useState(false);

  useEffect(() => {
    if (activeLine < 0 || lyricsHover) return;
    // Center the active line INSIDE the lyrics scroller only. scrollIntoView
    // would also scroll the outer overflow-hidden containers (they are
    // programmatically scrollable), which shifts the whole layout and leaves
    // the view "stuck" — half filled, impossible to scroll back.
    const c = lyricsScrollRef.current;
    const el = lineRefs.current[activeLine];
    if (!c || !el) return;
    const top =
      el.getBoundingClientRect().top -
      c.getBoundingClientRect().top +
      c.scrollTop -
      c.clientHeight / 2 +
      el.clientHeight / 2;
    c.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }, [activeLine, lyricsHover]);

  // New track → rewind the lyrics pane to the top.
  useEffect(() => {
    lyricsScrollRef.current?.scrollTo({ top: 0 });
  }, [p.current.path]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (plOpen) setPlOpen(false);
        else p.onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plOpen]);

  const persist = (key: string, v: string) => localStorage.setItem(key, v);
  const toggleOpt = (which: "xlit" | "trans") => {
    if (which === "xlit") {
      const v = !showXlit;
      setShowXlit(v);
      persist(XLIT_KEY, v ? "1" : "0");
    } else {
      const v = !showTrans;
      setShowTrans(v);
      persist(TRANS_KEY, v ? "1" : "0");
    }
  };

  // ---- add to playlist -----------------------------------------------------
  const { data: playlists } = useQuery({
    queryKey: ["playlists"],
    queryFn: api.playlists,
    enabled: plOpen,
  });
  const addToPlaylist = async (pl: Playlist) => {
    try {
      await api.playlistAdd(pl.id, [p.current.path]);
      toast(`Added "${title}" to ${pl.name}`);
      setPlOpen(false);
      qc.invalidateQueries({ queryKey: ["playlist", pl.id] });
    } catch (e) {
      toast(String(e));
    }
  };
  const createPlaylistAndAdd = async () => {
    const name = newPlName.trim();
    if (!name) return;
    try {
      const pl = await api.createPlaylist(name, "manual");
      await api.playlistAdd(pl.id, [p.current.path]);
      toast(`Added "${title}" to ${pl.name}`);
      setNewPlName("");
      setPlOpen(false);
      qc.invalidateQueries({ queryKey: ["playlists"] });
    } catch (e) {
      toast(String(e));
    }
  };

  const size = LYRIC_SIZES[lyricSize];
  const transforming =
    !!aiReady && hasLyrics && ((showXlit && !transforms.transliterate) || (showTrans && !transforms.translate));

  const renderLine = (l: LrcLine, i: number) => {
    const isActive = synced && i === activeLine;
    const xlit = showXlit ? transforms.transliterate?.[i] : undefined;
    const trans = showTrans ? transforms.translate?.[i] : undefined;
    // When transliteration is on, the romanized text IS the primary line —
    // for Latin-script originals it equals the original, so hiding the
    // original loses nothing. Karaoke word timing only fits the original
    // wording, so it applies only when the original is displayed (and only
    // for synced lyrics, which is where word timings exist).
    const replaced = !!xlit && xlit.trim() !== "" && xlit.trim() !== l.text.trim();
    const primary = replaced ? xlit : l.text;
    return (
      <div
        key={i}
        ref={(el) => {
          lineRefs.current[i] = el;
        }}
        className={`py-2 ${synced ? "cursor-pointer" : ""} ${
          isActive ? "opacity-100" : synced ? LINE_BLUR : ""
        }`}
        onClick={synced ? () => p.onSeek(l.time) : undefined}
        title={synced ? "Click to seek" : undefined}
      >
        <div
          className={`leading-snug ${LINE_EASE} ${
            isActive
              ? `${size.active} font-semibold text-white`
              : `${size.line} ${synced ? "text-zinc-500" : "text-zinc-200"}`
          }`}
        >
          {!replaced && isActive && karaoke && l.words?.length
            ? l.words.map((w, wi) => {
                const on =
                  w.time <= dispTime + 0.04 &&
                  (wi === l.words!.length - 1 || l.words![wi + 1].time > dispTime + 0.04);
                return (
                  <span key={wi} className={on ? "text-accent" : "text-white/85"}>
                    {w.text}
                  </span>
                );
              })
            : primary}
        </div>
        {trans && <div className={`${size.xlit} text-accent-soft/70 mt-0.5 leading-snug`}>{trans}</div>}
      </div>
    );
  };

  const title = p.current.title || tags?.TITLE || p.current.file.replace(/\.[^.]+$/, "");
  const albumArtist =
    album?.album_artist || tags?.ALBUMARTIST || p.current.artist || p.current.albumPath.split("/").pop() || "";
  const albumName = album?.meta?.ALBUM || p.current.album || tags?.ALBUM || "";
  const upNext = queue[index + 1] as
    | { title?: string; artist?: string; file: string }
    | undefined;
  const upNextLabel = upNext
    ? `${upNext.title || upNext.file.replace(/\.[^.]+$/, "")}${upNext.artist ? ` — ${upNext.artist}` : ""}`
    : "";
  // Codec + bitrate / bit depth / frequency, shown with the song title
  // ("FLAC · 973 kbps · 16 bit · 44.1 kHz") — bit depth always precedes rate.
  const techStr = tech
    ? [
        tech.codec ?? null,
        tech.bitrate ? `${Math.round(tech.bitrate / 1000)} kbps` : null,
        tech.bits_per_sample ? `${Math.round(tech.bits_per_sample)} bit` : null,
        tech.sample_rate ? `${(tech.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";

  const VolIcon = vol <= 0 ? VolumeX : vol < 0.5 ? Volume1 : Volume2;

  return (
    <div className="fixed inset-0 z-50 bg-zinc-950 overflow-clip">
      {/* overflow-clip (not hidden): a hidden box is still a scroll container,
          so wheel / scrollIntoView can silently scroll the whole overlay and
          leave the view "stuck" half-rendered. Clip can never be scrolled. */}
      {/* ---- ambient background: blurred cover + drifting color orbs,
              swelling with the beat when the pulse effect is on ---- */}
      <div ref={bgRef} className="absolute inset-0 blur-3xl" style={{ opacity: 0.25, transform: "scale(1.1)" }}>
        <CoverImg albumPath={p.current.albumPath} coverFile={coverFile} wrapperClass="w-full h-full" />
      </div>
      {orbs && (
        <div ref={orbsRef} className="absolute inset-0 pointer-events-none">
          {/* .orb-field carries the slow hue-cycle CSS animation; the beat
              pump (JS) stays on the outer container so the two never fight */}
          <div className="orb-field absolute inset-0">
            <div
              className="orb orb-a w-[55vw] h-[55vw] -top-[15vw] -left-[10vw]"
              style={{ background: `radial-gradient(circle at 35% 35%, rgb(${rgb.join(" ")} / 0.9), transparent 65%)` }}
            />
            <div
              className="orb orb-b w-[48vw] h-[48vw] bottom-[-14vw] right-[-8vw]"
              style={{ background: `radial-gradient(circle at 60% 40%, rgb(${rgb.join(" ")} / 0.85), transparent 62%)`, filter: "blur(90px) hue-rotate(55deg)" }}
            />
            <div
              className="orb orb-c w-[38vw] h-[38vw] top-[28%] left-[36%]"
              style={{ background: `radial-gradient(circle at 50% 50%, rgb(${rgb.map((v) => Math.min(255, v + 40)).join(" ")} / 0.8), transparent 60%)`, filter: "blur(90px) hue-rotate(-65deg)" }}
            />
            <div
              className="orb orb-d w-[30vw] h-[30vw] top-[-8vw] right-[12vw]"
              style={{ background: `radial-gradient(circle at 45% 55%, rgb(${rgb.map((v) => Math.max(0, v - 20)).join(" ")} / 0.75), transparent 58%)`, filter: "blur(70px) hue-rotate(150deg)" }}
            />
          </div>
        </div>
      )}
      {/* bloom ring behind the artwork — swells on the beat when the
          ambience effect is on */}
      <div
        ref={bloomRef}
        aria-hidden
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(ellipse 62% 52% at 50% 55%, rgb(${rgb.join(" ")} / 0.5), transparent 70%)`,
          opacity: 0.15,
        }}
      />
      {/* legibility wash — deliberately light so the animated color field
          stays visible; only the very top and bottom darken for the bars */}
      <div className="absolute inset-0 bg-gradient-to-b from-zinc-950/55 via-zinc-950/20 to-zinc-950/80" />

      <div className="relative h-full flex flex-col">
        {/* top bar — right-aligned cluster only: the queue position sits as a
            minimal fraction next to the queue button */}
        <div className="flex items-center justify-end px-5 py-3">
          <div className="flex items-center gap-1">
            {p.queuePos && (
              <span className="text-[10px] font-mono text-zinc-500 mr-1 tabular-nums" title="Queue position">
                {p.queuePos}
              </span>
            )}
            <button
              className={`p-2 rounded-lg hover:bg-white/10 ${queueOpen ? "text-white bg-white/10" : "text-zinc-400 hover:text-white"}`}
              onClick={() => setQueueOpen(!queueOpen)}
              title="Up next (queue)"
            >
              <ListMusic className="h-5 w-5" />
            </button>
            <div className="relative">
              <button
                className="p-2 rounded-lg hover:bg-white/10 text-zinc-400 hover:text-white"
                onClick={() => setOptions(!options)}
                title="Lyrics & display options"
              >
                <Settings2 className="h-5 w-5" />
              </button>
              {options && (
                <div className="absolute right-0 top-full mt-1 z-10 glass rounded-xl shadow-xl p-2 w-72 bg-zinc-950/85">
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-1 pb-1">Lyrics</div>
                  {[
                    { id: "xlit" as const, label: "Transliteration (romanized)", on: showXlit, act: () => toggleOpt("xlit") },
                    { id: "trans" as const, label: "Translation", on: showTrans, act: () => toggleOpt("trans") },
                    {
                      id: "karaoke" as const,
                      label: "Karaoke word highlight",
                      on: karaoke,
                      act: () => {
                        const v = !karaoke;
                        setKaraoke(v);
                        persist(KARAOKE_KEY, v ? "1" : "0");
                      },
                    },
                  ].map((o) => (
                    <label key={o.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white/5 cursor-pointer text-xs text-zinc-300">
                      <input type="checkbox" className="accent-[var(--accent)]" checked={o.on} onChange={o.act} />
                      {o.label}
                    </label>
                  ))}
                  <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-zinc-300">
                    <span className="flex-1">Lyrics size</span>
                    {(["sm", "md", "lg"] as const).map((s) => (
                      <button
                        key={s}
                        className={`chip text-[10px] border ${lyricSize === s ? "bg-accent on-accent border-accent" : "bg-white/5 border-white/15 text-zinc-400 hover:text-white"}`}
                        onClick={() => {
                          setLyricSize(s);
                          persist(SIZE_KEY, s);
                        }}
                      >
                        {s.toUpperCase()}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-zinc-300">
                    <span className="flex-1" title="Zoom the lyrics pane — saved for every future visit">Zoom</span>
                    <input
                      type="range"
                      min={0.85}
                      max={1.6}
                      step={0.05}
                      value={lyricZoom}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setLyricZoom(v);
                        persist(ZOOM_KEY, String(v));
                      }}
                      className="w-28"
                    />
                    <span className="w-9 text-right text-[10px] text-zinc-500 tabular-nums">{Math.round(lyricZoom * 100)}%</span>
                  </div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-1 pt-2 pb-1">Background</div>
                  <label className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white/5 cursor-pointer text-xs text-zinc-300">
                    <input
                      type="checkbox"
                      className="accent-[var(--accent)]"
                      checked={orbs}
                      onChange={() => {
                        const v = !orbs;
                        setOrbs(v);
                        persist(ORBS_KEY, v ? "1" : "0");
                      }}
                    />
                    Animated color drift
                  </label>
                  <label className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white/5 cursor-pointer text-xs text-zinc-300">
                    <input
                      type="checkbox"
                      className="accent-[var(--accent)]"
                      checked={vis}
                      onChange={() => {
                        const v = !vis;
                        setVis(v);
                        persist(VIS_KEY, v ? "1" : "0");
                      }}
                    />
                    Background pulse
                  </label>
                  <div className="text-[10px] text-zinc-600 px-2 pt-1">
                    AI translation uses Settings → AI; results are cached per track.
                  </div>
                </div>
              )}
            </div>
            <button className="p-2 rounded-lg hover:bg-white/10 text-zinc-400 hover:text-white" onClick={p.onClose} title="Close (Esc)">
              <ChevronDown className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* main area */}
        <div className={`flex-1 min-h-0 flex flex-col lg:flex-row items-center gap-8 px-8 pb-4 overflow-clip ${hasLyrics ? "" : "lg:justify-center"}`}>
          {/* left column: cover, track/album/artist, all playback controls —
              centered as a group inside the full column height */}
          <div
            className={`flex flex-col items-center justify-center gap-4 shrink-0 min-w-0 ${
              hasLyrics ? "lg:w-[42%] lg:h-full" : ""
            }`}
          >
            {videoPath ? (
              /* music video: muted picture synced to the shared audio clock,
                 subtitles wired in; click toggles playback */
              <SubtitledVideo
                path={videoPath!}
                muted
                controls={false}
                videoRef={videoRef}
                onClick={p.onTogglePlay}
                className="relative aspect-video w-72 lg:w-[min(30rem,50vh)] rounded-2xl bg-black border border-white/10 shadow-2xl object-contain cursor-pointer"
              />
            ) : (
              <div className="relative">
                {orbs && (
                  <div
                    className="artwork-glow absolute -inset-6 rounded-[2rem] blur-2xl"
                    style={{ background: `radial-gradient(circle, rgb(${rgb.join(" ")} / 0.55), transparent 70%)` }}
                  />
                )}
                <CoverImg
                  albumPath={p.current.albumPath}
                  coverFile={coverFile}
                  wrapperClass={`relative rounded-2xl shadow-2xl border border-white/10 bg-raise overflow-hidden ${hasLyrics ? "w-64 h-64 lg:w-[min(24rem,42vh)] lg:h-[min(24rem,42vh)]" : "w-72 h-72 lg:w-[min(30rem,52vh)] lg:h-[min(30rem,52vh)]"}`}
                />
              </div>
            )}
            <div className="text-center w-full max-w-[26rem] min-w-0">
              <div className="text-2xl font-bold text-white truncate" title={title}>
                {title}
              </div>
              <div className="text-zinc-300 mt-1 truncate" title={albumArtist}>
                {albumArtist}
              </div>
              {albumName && (
                <div className="text-xs text-zinc-500 mt-0.5 truncate" title={albumName}>
                  {albumName}
                </div>
              )}
              {techStr && (
                <div className="text-[11px] text-zinc-500 mt-1 font-mono" title={techStr}>
                  {techStr}
                </div>
              )}
              {upNextLabel && (
                <div
                  className="text-[11px] text-zinc-500 mt-2.5 flex items-center justify-center gap-1.5 min-w-0"
                  title={upNextLabel}
                >
                  <span className="text-[9px] uppercase tracking-widest text-zinc-600 shrink-0">Up next</span>
                  <span className="text-zinc-400 truncate">{upNextLabel}</span>
                </div>
              )}
            </div>

            {/* transport + like + add to playlist — directly under the cover */}
            <div className="flex items-center justify-center gap-2.5">
              <button className={`p-2 rounded-lg hover:bg-white/10 ${p.shuffle ? "text-accent" : "text-zinc-500"}`} onClick={p.onToggleShuffle} title="Shuffle">
                <Shuffle className="h-4 w-4" />
              </button>
              <button className="p-2.5 rounded-lg hover:bg-white/10 text-white" onClick={() => p.onStep(-1)} title="Previous track">
                <SkipBack className="h-5 w-5" />
              </button>
              <button
                className="p-4 rounded-lg bg-accent on-accent hover:bg-accent-soft shadow-lg"
                onClick={p.onTogglePlay}
                title="Play / pause (Space)"
              >
                {p.playing ? <Pause className="h-6 w-6" /> : <Play className="h-6 w-6 ml-0.5" />}
              </button>
              <button className="p-2.5 rounded-lg hover:bg-white/10 text-white" onClick={() => p.onStep(1)} title="Next track">
                <SkipForward className="h-5 w-5" />
              </button>
              <button className={`p-2 rounded-lg hover:bg-white/10 ${p.loop ? "text-accent" : "text-zinc-500"}`} onClick={p.onToggleLoop} title="Repeat one">
                <Repeat className="h-4 w-4" />
              </button>
              <span className="w-px h-6 bg-white/15 mx-1" />
              <button
                className={`p-2 rounded-lg hover:bg-white/10 ${p.liked ? "text-accent" : "text-zinc-500 hover:text-zinc-300"}`}
                onClick={p.onToggleLike}
                title={p.liked ? "Unlike" : "Like this track"}
              >
                <Heart className={`h-[18px] w-[18px] ${p.liked ? "fill-current" : ""}`} />
              </button>
              <div className="relative">
                <button
                  className={`p-2 rounded-lg hover:bg-white/10 ${plOpen ? "text-accent bg-white/10" : "text-zinc-500 hover:text-zinc-300"}`}
                  onClick={() => setPlOpen(!plOpen)}
                  title="Add this track to a playlist"
                >
                  <ListPlus className="h-[18px] w-[18px]" />
                </button>
                {plOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setPlOpen(false)} />
                    <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-20 rounded-xl shadow-2xl border border-white/10 p-2 w-60 bg-zinc-950 max-h-72 flex flex-col">
                      <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-1 pb-1">Playlists</div>
                      <div className="overflow-y-auto min-h-0">
                        {(playlists ?? []).filter((pl) => pl.kind === "manual").map((pl) => (
                          <button
                            key={pl.id}
                            className="w-full text-left px-2 py-1.5 rounded-lg text-xs text-zinc-300 hover:bg-white/10 hover:text-white truncate"
                            onClick={() => addToPlaylist(pl)}
                            title={`Add to ${pl.name}`}
                          >
                            {pl.name}
                          </button>
                        ))}
                        {!(playlists ?? []).some((pl) => pl.kind === "manual") && (
                          <div className="px-2 py-1.5 text-[11px] text-zinc-600">No manual playlists yet</div>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 pt-1.5 mt-1 border-t border-white/10">
                        <input
                          className="input !py-1 !px-2 text-[11px] flex-1 min-w-0"
                          placeholder="New playlist name"
                          value={newPlName}
                          onChange={(e) => setNewPlName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") createPlaylistAndAdd();
                          }}
                          autoFocus
                        />
                        <button className="btn-primary !py-1 !px-2 text-[11px] shrink-0" onClick={createPlaylistAndAdd} disabled={!newPlName.trim()}>
                          Create
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* seek + volume — a single line under the transport */}
            <div className="flex items-center gap-2 text-xs text-zinc-400 w-full max-w-[26rem] px-2">
              <span className="w-10 text-right font-mono tabular-nums">{fmtDuration(dispTime)}</span>
              <input
                type="range"
                min={0}
                max={duration || 0}
                step={0.05}
                value={Math.min(dispTime, duration || 0)}
                onChange={(e) => p.onSeek(Number(e.target.value))}
                className="flex-1 min-w-0"
                title="Seek"
              />
              <span className="w-10 font-mono tabular-nums">{fmtDuration(duration)}</span>
              <span className="w-px h-5 bg-white/15 mx-0.5" />
              <div className="flex items-center gap-1.5 text-zinc-500 shrink-0" title={`Volume — ${Math.round(vol * 100)}%`}>
                <VolIcon className="h-4 w-4" />
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={vol}
                  onChange={(e) => setVol(Number(e.target.value))}
                  className="w-20"
                  title="Volume"
                />
              </div>
            </div>
          </div>

          {/* lyrics column — plain, no panel, hugging the right edge; flex-1
              below lg so it can't overflow the viewport (h-full there would
              double-count with the cover block and clip the bottom half
              outside the scroll pane) */}
          {hasLyrics && (
            <div className="flex-1 min-h-0 w-full lg:h-full flex flex-col max-w-3xl lg:max-w-4xl lg:flex-none lg:w-[44%] lg:ml-auto">
              <div
                ref={lyricsScrollRef}
                className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-6 py-5 no-scrollbar"
                style={{ zoom: lyricZoom }}
                onMouseEnter={() => setLyricsHover(true)}
                onMouseLeave={() => setLyricsHover(false)}
              >
                {displayLines.length > 0 ? (
                  displayLines.map(renderLine)
                ) : (
                  <div className="text-zinc-400 text-sm whitespace-pre-wrap leading-relaxed opacity-80">
                    {lyricsText}
                  </div>
                )}
                <div className="h-32" />
              </div>
            </div>
          )}
          {transforming && (
            <div className="absolute bottom-6 right-8 text-[10px] text-zinc-600 flex items-center gap-1">
              <span className="h-3 w-3 rounded-full border border-zinc-600 border-t-transparent animate-spin inline-block" /> transforming lyrics…
            </div>
          )}
        </div>
      </div>

      {/* up-next queue drawer — starts below the top bar so the queue
          toggle button stays clickable to close it */}
      {queueOpen && (
        <div className="absolute top-12 right-0 bottom-0 w-80 z-20 glass bg-zinc-950/90 flex flex-col rounded-l-2xl">
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
            <div className="text-[11px] uppercase tracking-widest text-zinc-400">
              Queue · {queue.length} track{queue.length === 1 ? "" : "s"}
            </div>
            <button className="p-2 rounded-lg hover:bg-white/10 text-zinc-400 hover:text-white" onClick={() => setQueueOpen(false)} title="Close queue">
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-2" ref={queueListRef}>
            {queue.map((t, i) => (
              <button
                key={t.path + i}
                data-queue-index={i}
                className={`w-full text-left px-2.5 py-2 rounded-lg flex items-center gap-3 transition-colors ${
                  i === index ? "bg-accent/15" : "hover:bg-white/5"
                }`}
                onClick={() => setIndex(i)}
                title="Play this track now"
              >
                <span className={`text-[10px] font-mono w-5 text-right shrink-0 ${i === index ? "text-accent" : "text-zinc-600"}`}>
                  {i === index && p.playing ? "▶" : i + 1}
                </span>
                <span className="flex-1 min-w-0">
                  <span className={`block text-xs truncate ${i === index ? "text-white font-medium" : "text-zinc-300"}`}>
                    {t.title || t.file.replace(/\.[^.]+$/, "")}
                  </span>
                  <span className="block text-[10px] text-zinc-500 truncate">
                    {t.artist ?? t.albumPath.split("/").pop()}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}

function fmtDuration(t: number) {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}
