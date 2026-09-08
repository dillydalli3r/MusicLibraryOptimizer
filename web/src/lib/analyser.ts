/** Shared WebAudio graph for playback: ReplayGain loudness + the visualizer.
 *
 * A single AudioContext holds one MediaElementSource per <audio> element
 * (a media element can only ever be attached once) routed through a
 * GainNode (ReplayGain) into an AnalyserNode back to the speakers. The
 * stream responses carry CORS headers and the elements are loaded with
 * crossOrigin="anonymous", so the frequency data is never tainted-silence.
 *
 * Everything is defensive: if WebAudio is unavailable or the context
 * can't run, callers fall back to the synthetic animation and unity gain
 * instead of ever risking playback itself.
 */

let ctx: AudioContext | null = null;
let current: AnalyserNode | null = null;
const chains = new WeakMap<HTMLMediaElement, { analyser: AnalyserNode; gain: GainNode }>();
let broken = false;

function ensureCtx(): AudioContext | null {
  if (ctx) return ctx;
  if (broken) return null;
  try {
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) {
      broken = true;
      return null;
    }
    ctx = new AC();
  } catch {
    broken = true;
    ctx = null;
  }
  return ctx;
}

/** Attach (once) the source → ReplayGain gain → analyser → speakers chain
 * to an <audio> element and make it the active visualizer source. Safe to
 * call on every play event. */
export function attachAnalyser(el: HTMLMediaElement): AnalyserNode | null {
  const c = ensureCtx();
  if (!c) return null;
  if (!chains.has(el)) {
    try {
      const source = c.createMediaElementSource(el);
      const gain = c.createGain();
      const analyser = c.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.78;
      source.connect(gain);
      gain.connect(analyser);
      analyser.connect(c.destination);
      chains.set(el, { analyser, gain });
    } catch {
      // Attach raced (hot reload) or the media is tainted — never try
      // again; playback itself is untouched either way. Keep whatever
      // analyser is currently active.
      return current;
    }
  }
  current = chains.get(el)?.analyser ?? current;
  return current;
}

/** Apply a ReplayGain preamp (dB, e.g. −7.20) to an element's playback
 * chain. Unity (0 dB) when no value is given. Smoothed to avoid clicks. */
export function applyReplayGain(el: HTMLMediaElement, db?: number | null) {
  const chain = chains.get(el);
  if (!chain || !ctx) return;
  const v =
    typeof db === "number" && isFinite(db)
      ? Math.pow(10, Math.max(-24, Math.min(24, db)) / 20)
      : 1;
  try {
    chain.gain.gain.setTargetAtTime(v, ctx.currentTime, 0.05);
  } catch {
    /* never let loudness matching break playback */
  }
}

/** Must be called from a user gesture (play buttons) — a suspended context
 * would otherwise route audio into silence. */
export function resumeAnalyser() {
  if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
}

/** The analyser to read now, or null when WebAudio isn't available. */
export function activeAnalyser(): AnalyserNode | null {
  return current;
}
