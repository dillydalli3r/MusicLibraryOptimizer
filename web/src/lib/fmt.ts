/** Shared compact audio-format readout: "FLAC · 1022k · 16/44.1".
 * (codec · bitrate in kbps · bit depth/sample rate in kHz) */
export interface TechInfo {
  codec?: string;
  bitrate?: number;
  bits_per_sample?: number;
  sample_rate?: number;
}

export function fmtTech(t?: TechInfo | null): string {
  if (!t) return "";
  const parts: string[] = [];
  if (t.codec) parts.push(String(t.codec));
  if (t.bitrate) parts.push(`${Math.round(t.bitrate / 1000)}k`);
  if (t.bits_per_sample && t.sample_rate) {
    parts.push(`${Math.round(t.bits_per_sample)}/${(t.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")}`);
  } else {
    if (t.bits_per_sample) parts.push(`${Math.round(t.bits_per_sample)} bit`);
    if (t.sample_rate) parts.push(`${(t.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz`);
  }
  return parts.join(" · ");
}

/** Aggregated album-level readout from the album's tracks: codecs, a
 * bitrate figure (mean when the tracks are close, min–max range when they
 * drift) and the depth/rate pair — "FLAC · 1022k · 16/44.1". `short`
 * drops the bitrate (for badges): "FLAC · 16/44.1". */
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
  const parts: string[] = [];
  if (codecs.length) parts.push(codecs.join("/"));
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
  if (pairs.length === 1) parts.push(pairs[0]);
  else if (pairs.length > 1) parts.push("mixed");
  return parts.join(" · ");
}
