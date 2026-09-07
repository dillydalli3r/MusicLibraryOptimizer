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
