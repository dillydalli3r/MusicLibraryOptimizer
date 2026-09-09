import { useEffect, useState } from "react";

/** Percentage readout + typeable box for a volume slider. Typed values are
 * clamped to 0-100 and committed on Enter or blur (so typing "50" doesn't
 * jump to 5% mid-keystroke). The box stays in sync when the slider moves. */
export default function VolumePct({ value, onChange, className }: {
  value: number;
  onChange: (v: number) => void;
  className?: string;
}) {
  const [text, setText] = useState(() => String(Math.round(value * 100)));

  // slider / store moved the volume — reflect it in the box
  useEffect(() => {
    setText(String(Math.round(value * 100)));
  }, [value]);

  const commit = () => {
    const n = Number(text.trim());
    if (text.trim() === "" || Number.isNaN(n)) {
      setText(String(Math.round(value * 100)));
      return;
    }
    const clamped = Math.max(0, Math.min(100, n));
    setText(String(clamped));
    onChange(clamped / 100);
  };

  return (
    <span className={`relative inline-flex items-center shrink-0 ${className ?? ""}`}>
      <input
        className="w-11 !py-0.5 pl-1.5 pr-4 text-right text-[10px] font-mono bg-panel/60 border border-border rounded text-zinc-300 outline-none focus:border-accent"
        inputMode="numeric"
        value={text}
        title="Volume — type a percentage"
        onChange={(e) => setText(e.target.value.replace(/[^\d]/g, "").slice(0, 3))}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            commit();
            (e.target as HTMLInputElement).blur();
          } else if (e.key === "Escape") {
            setText(String(Math.round(value * 100)));
          }
        }}
      />
      <span className="absolute right-1.5 text-[9px] text-zinc-600 pointer-events-none">%</span>
    </span>
  );
}
