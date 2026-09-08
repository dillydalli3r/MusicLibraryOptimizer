import { useEffect, useRef, useState } from "react";
import { Ellipsis } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface OverflowMenuItem {
  label: string;
  icon?: LucideIcon;
  onClick?: () => void;
  danger?: boolean;
  disabled?: boolean;
  hidden?: boolean;
  title?: string;
}

export interface OverflowMenuSection {
  title?: string;
  items: OverflowMenuItem[];
}

/** "…" overflow menu with grouped sections — keeps page headers to the
 * primary action plus one button. Closes on outside click / Esc / item click. */
export default function OverflowMenu({
  sections,
  buttonTitle = "More actions",
  buttonClass = "btn-ghost !px-2.5",
  align = "right",
}: {
  sections: OverflowMenuSection[];
  buttonTitle?: string;
  buttonClass?: string;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const visible = sections
    .map((s) => ({ ...s, items: s.items.filter((i) => !i.hidden) }))
    .filter((s) => s.items.length);

  return (
    <div className="relative" ref={ref}>
      <button className={buttonClass} onClick={() => setOpen(!open)} title={buttonTitle} aria-label={buttonTitle}>
        <Ellipsis className="h-4 w-4" />
      </button>
      {open && (
        <div
          className={`absolute z-50 mt-1 ${align === "right" ? "right-0" : "left-0"} w-64 max-h-[70vh] overflow-y-auto rounded-xl shadow-2xl bg-zinc-950 border border-white/10 p-1.5`}
          onClick={() => setOpen(false)}
        >
          {visible.map((s, si) => (
            <div key={si} className={si > 0 ? "mt-1 pt-1 border-t border-white/10" : ""}>
              {s.title && (
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 px-2.5 pt-1 pb-0.5">{s.title}</div>
              )}
              {s.items.map((it, ii) => (
                <button
                  key={ii}
                  disabled={it.disabled}
                  title={it.title}
                  onClick={it.onClick}
                  className={`w-full text-left text-xs px-2.5 py-1.5 rounded-lg flex items-center gap-2.5 transition-colors disabled:opacity-40 ${
                    it.danger ? "text-red-300 hover:bg-red-950/50" : "text-zinc-300 hover:bg-white/10"
                  }`}
                >
                  {it.icon && <it.icon className="h-3.5 w-3.5 shrink-0" />}
                  <span className="flex-1 truncate">{it.label}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
