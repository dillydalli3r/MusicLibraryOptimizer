/** Shared compact audio-format readout: "FLAC 16/44.1 · 1022 kbps" —
 * codec with its bit depth/sample rate first, bitrate last. */
export interface TechInfo {
  codec?: string;
  bitrate?: number;
  bits_per_sample?: number;
  sample_rate?: number;
  width?: number;
  height?: number;
}

/** Music-video containers the app plays with <video> (mirrors the
 * backend's LIB_VIDEO_EXTS). */
const VIDEO_EXTS = new Set([
  ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".vob", ".mpg", ".mpeg",
  ".m2v", ".ts", ".m2ts", ".mts", ".avi", ".wmv", ".flv", ".ogv",
  ".3gp", ".3g2",
]);

export function isVideoFile(fileOrPath: string | null | undefined): boolean {
  if (!fileOrPath) return false;
  const m = (fileOrPath.match(/\.([a-z0-9]+)$/i) ?? [])[0];
  return !!m && VIDEO_EXTS.has(m.toLowerCase());
}

/** Human bitrate — always kilobits per second, never Mbps. */
export function fmtBitrate(bps?: number | null): string {
  if (!bps) return "";
  return `${Math.round(bps / 1000)} kbps`;
}

export function fmtTech(t?: TechInfo | null): string {
  if (!t) return "";
  // Video containers: lead with resolution (the thing that tells a video
  // apart), then codec, then a readable total bitrate.
  if ((t.width && t.height) || (t.codec && /^(h264|h265|hevc|av1|vp9|mpeg|vc-?1|theora|prores|divx|xvid|mkv|mp4|mov)/i.test(t.codec))) {
    const parts: string[] = [];
    if (t.width && t.height) parts.push(`${t.width}×${t.height}`);
    else if (t.width) parts.push(`${t.width}p`);
    if (t.codec) parts.push(String(t.codec).toUpperCase());
    if (t.bitrate) parts.push(fmtBitrate(t.bitrate));
    if (!parts.length && t.sample_rate) parts.push(`${(t.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz`);
    return parts.join(" · ");
  }
  const pair =
    t.bits_per_sample && t.sample_rate
      ? `${Math.round(t.bits_per_sample)}/${(t.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")}`
      : t.bits_per_sample
        ? `${Math.round(t.bits_per_sample)} bit`
        : t.sample_rate
          ? `${(t.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz`
          : "";
  const parts: string[] = [];
  if (t.codec) parts.push(`${t.codec}${pair ? ` ${pair}` : ""}`);
  else if (pair) parts.push(pair);
  if (t.bitrate) parts.push(fmtBitrate(t.bitrate));
  return parts.join(" · ");
}

/** Aggregated album-level readout from the album's tracks — codecs with
 * their depth/rate pair first, bitrate figure last (mean when the tracks
 * are close, min–max range when they drift): "FLAC 16/44.1 · 904–1079 kbps".
 * `short` drops the bitrate (for badges): "FLAC 16/44.1". */
export function albumTech(
  tracks?: { tech?: TechInfo & { length?: number; channels?: number } }[] | null,
  short = false
): string {
  const techs = (tracks ?? [])
    .map((t) => t?.tech)
    .filter((t): t is TechInfo => !!t && !!(t.codec || t.sample_rate));
  if (!techs.length) return "";
  const codecs = [...new Set(techs.map((t) => String(t.codec).toUpperCase()).filter(Boolean))];
  const pairs = [
    ...new Set(
      techs
        .filter((t) => t.bits_per_sample && t.sample_rate)
        .map((t) => `${Math.round(t.bits_per_sample!)}/${(t.sample_rate! / 1000).toFixed(1).replace(/\.0$/, "")}`)
    ),
  ];
  const pair = pairs.length === 1 ? pairs[0] : pairs.length > 1 ? "mixed" : "";
  const parts: string[] = [];
  if (codecs.length) parts.push(`${codecs.join("/")}${pair ? ` ${pair}` : ""}`);
  else if (pair) parts.push(pair);
  if (!short) {
    const brs = techs.map((t) => t.bitrate).filter((b): b is number => !!b);
    if (brs.length) {
      const min = Math.min(...brs);
      const max = Math.max(...brs);
      parts.push(
        max - min <= Math.max(0.05 * max, 20000)
          ? `${Math.round(brs.reduce((a, b) => a + b, 0) / brs.length / 1000)} kbps`
          : `${Math.round(min / 1000)}–${Math.round(max / 1000)} kbps`
      );
    }
  }
  return parts.join(" · ");
}
