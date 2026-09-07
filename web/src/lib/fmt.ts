/** Shared compact audio-format readout: "FLAC 16/44.1 · 1022k" —
 * codec with its bit depth/sample rate first, bitrate last. */
export interface TechInfo {
  codec?: string;
  bitrate?: number;
  bits_per_sample?: number;
  sample_rate?: number;
}

export function fmtTech(t?: TechInfo | null): string {
  if (!t) return "";
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
  if (t.bitrate) parts.push(`${Math.round(t.bitrate / 1000)}k`);
  return parts.join(" · ");
}

/** Aggregated album-level readout from the album's tracks — codecs with
 * their depth/rate pair first, bitrate figure last (mean when the tracks
 * are close, min–max range when they drift): "FLAC 16/44.1 · 904–1079k".
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
          ? `${Math.round(brs.reduce((a, b) => a + b, 0) / brs.length / 1000)}k`
          : `${Math.round(min / 1000)}–${Math.round(max / 1000)}k`
      );
    }
  }
  return parts.join(" · ");
}
