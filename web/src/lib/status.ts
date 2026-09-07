export interface TrackStatus {
  key: "pass" | "fail";
  label: string;
  edge: string; // status edge strip / dot color
  tint: string; // row/card background tint
  text: string; // sliver text color
}

/**
 * One condensed verdict for grading + auditing: an album/track is either
 * PASS (graded clean and the audit is REAL or pending) or FAIL (grading
 * found problems, or the audit came back FAKE / MIX). Everything that went
 * into the verdict is shown as details next to the badge.
 */
export function auditFails(audit: string | null | undefined): boolean {
  const a = (audit ?? "").trim().toUpperCase();
  return a === "FAKE" || a === "MIX";
}

export function statusFor(pass: boolean, audit: string | null | undefined): TrackStatus {
  if (!pass)
    return { key: "fail", label: "FAIL — grading found problems", edge: "bg-red-500", tint: "bg-red-950/25", text: "text-red-300" };
  if (auditFails(audit)) {
    const a = (audit ?? "").trim().toUpperCase();
    return { key: "fail", label: `FAIL — audit ${a}`, edge: "bg-red-500", tint: "bg-red-950/25", text: "text-red-300" };
  }
  return { key: "pass", label: "PASS", edge: "bg-emerald-500", tint: "", text: "text-emerald-300" };
}

/** Tiny mono grade sliver: just "PASS" or "FAIL" (audit detail on hover). */
export function gradeSliver(pass: boolean, audit: string | null | undefined): string {
  return statusFor(pass, audit).key.toUpperCase();
}
