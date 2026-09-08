import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, X } from "lucide-react";

/** Two-step button for destructive-ish actions (resets, removals): the first
 * click arms it in place — no native window.confirm dialogs. The armed state
 * confirms on a second click and disarms on outside click, Escape, or after
 * a few seconds of inactivity. */
export default function ConfirmButton({
  onConfirm,
  children,
  confirmLabel = "Confirm?",
  title,
  className = "btn-ghost",
  disabled = false,
}: {
  onConfirm: () => void;
  children: ReactNode;
  confirmLabel?: string;
  title?: string;
  className?: string;
  disabled?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!armed) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setArmed(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setArmed(false);
    };
    const t = setTimeout(() => setArmed(false), 6000);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
      clearTimeout(t);
    };
  }, [armed]);

  if (armed) {
    return (
      <div ref={ref} className="inline-flex items-center gap-1">
        <button
          className="btn-danger !py-1.5 text-xs"
          onClick={() => {
            setArmed(false);
            onConfirm();
          }}
          title="Confirm"
        >
          <Check className="h-3.5 w-3.5" /> {confirmLabel}
        </button>
        <button className="btn-ghost !py-1.5 text-xs" onClick={() => setArmed(false)} title="Cancel">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <button className={className} onClick={() => setArmed(true)} disabled={disabled} title={title}>
      {children}
    </button>
  );
}
