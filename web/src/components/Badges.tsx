import { Check, X, Disc3, CircleAlert } from "lucide-react";

/** The one condensed grade verdict: PASS or FAIL. `score` (the old
 * percentage) and `audit` survive only as hover details. */
export function GradeBadge({
  pass,
  score,
  audit,
  size = "md",
}: {
  pass: boolean;
  score?: number | null;
  audit?: string | null;
  size?: "sm" | "md";
}) {
  const cls = size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-xs";
  const detail: string[] = [];
  if (score != null && !pass) detail.push(`${score}% of checks passed`);
  const a = (audit ?? "").trim().toUpperCase();
  if (a) detail.push(`audit ${a}`);
  return (
    <span
      className={`chip ${cls} font-semibold ${
        pass
          ? "bg-green-900/60 text-green-300 border border-green-800"
          : "bg-red-900/50 text-red-300 border border-red-900"
      }`}
      title={detail.length ? detail.join(" · ") : pass ? "All checks passed" : "Grading failed — see details"}
    >
      {pass ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
      {pass ? "PASS" : "FAIL"}
    </span>
  );
}

export function AuditBadge({ audit, size = "md" }: { audit: string | null; size?: "sm" | "md" }) {
  const cls = size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-xs";
  switch ((audit || "").toUpperCase()) {
    case "REAL":
      return <span className={`chip ${cls} bg-emerald-900/60 text-emerald-300 border border-emerald-800`}>AUDIT REAL</span>;
    case "FAKE":
      return <span className={`chip ${cls} bg-red-900/50 text-red-300 border border-red-900`}>AUDIT FAKE</span>;
    case "MIX":
      return <span className={`chip ${cls} bg-amber-900/50 text-amber-300 border border-amber-900`}>AUDIT MIX</span>;
    default:
      return <span className={`chip ${cls} bg-zinc-800 text-zinc-500 border border-border`}>AUDIT —</span>;
  }
}

export function MediaChip({ media }: { media: string | null | undefined }) {
  if (!media) return null;
  const cd = media.toUpperCase().includes("CD");
  return (
    <span
      className={`chip ${
        cd ? "bg-sky-900/50 text-sky-300 border border-sky-900" : "bg-accent/10 text-accent-soft border border-accent/25"
      }`}
    >
      {media}
    </span>
  );
}

/** Compact media label for album cards/icons: "CD", "DIGITAL", "VINYL", …
 * Falls back to the first word when the format is something unusual. */
export function mediaShort(media: string | null | undefined): string | null {
  const m = (media ?? "").trim();
  if (!m) return null;
  const u = m.toUpperCase();
  if (u.includes("CD")) return "CD";
  if (u.includes("VINYL")) return "VINYL";
  if (u.includes("DIGITAL") || u.includes("FILE") || u.includes("WEB")) return "DIGITAL";
  if (u.includes("DVD")) return "DVD";
  if (u.includes("BLU")) return "BLU-RAY";
  if (u.includes("SACD")) return "SACD";
  if (u.includes("CASSETTE")) return "TAPE";
  return u.split(/[\s/;,]+/)[0].slice(0, 8);
}

export function AdvisoryBadge({ value }: { value: string | null | undefined }) {
  if (value === "1")
    return <span className="chip bg-red-900/50 text-red-300 border border-red-900">EXPLICIT</span>;
  if (value === "2")
    return <span className="chip bg-emerald-900/50 text-emerald-300 border border-emerald-900">CLEAN</span>;
  return null;
}

export function InstrumentalBadge({ value }: { value: string | null | undefined }) {
  if (value === "1")
    return <span className="chip bg-zinc-800 text-zinc-400 border border-border">INSTRUMENTAL</span>;
  return null;
}

export function ScoreRing({ pct, size = 44 }: { pct: number | null; size?: number }) {
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const v = pct ?? 0;
  const ok = v >= 100;
  const color = ok ? "#34d399" : v >= 80 ? "#fbbf24" : "#f87171";
  return (
    <svg width={size} height={size} className="-rotate-90">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#26262c" strokeWidth={5} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={5}
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c - (c * v) / 100}
      />
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dominantBaseline="central"
        className="rotate-90"
        style={{ transform: "rotate(90deg)", transformOrigin: "center" }}
        fill="#e8e8e8"
        fontSize={size / 4}
        fontWeight={600}
      >
        {pct === null ? "–" : v}
      </text>
    </svg>
  );
}

export function IssueList({ issues }: { issues: string[] }) {
  if (!issues?.length)
    return (
      <span className="text-xs text-emerald-400 flex items-center gap-1">
        <Check className="h-3 w-3" /> Clean
      </span>
    );
  return (
    <span className="text-xs text-red-300 flex items-center gap-1 truncate" title={issues.join(", ")}>
      <CircleAlert className="h-3 w-3 shrink-0" />
      {issues.join(", ")}
    </span>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-24 text-zinc-500">
      <Disc3 className="h-9 w-9 opacity-30" />
      <div className="text-sm font-medium text-zinc-400">{title}</div>
      {hint && <div className="text-xs text-zinc-600 max-w-sm text-center">{hint}</div>}
    </div>
  );
}