export function ProgressBar({ progress }: { progress: { done: number; total: number; desc: string } | null }) {
  if (!progress) return null;
  const pct = progress.total ? Math.min(100, (progress.done / progress.total) * 100) : 0;
  return (
    <div className="shrink-0 border-b border-border bg-panel px-4 py-1.5 flex items-center gap-3">
      <div className="h-1.5 flex-1 rounded-full bg-raise overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-accent to-indigo-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[11px] text-zinc-400 whitespace-nowrap">
        {progress.desc} {progress.done}/{progress.total}
      </span>
    </div>
  );
}