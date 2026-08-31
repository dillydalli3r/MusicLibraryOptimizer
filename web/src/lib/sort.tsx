import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

export interface SortState {
  key: string;
  dir: 1 | -1;
}

export function toggleSort(current: SortState | null, key: string): SortState {
  if (current?.key === key) return { key, dir: current.dir === 1 ? -1 : 1 };
  return { key, dir: 1 };
}

/** Resolve a dotted path like "tags.GENRE" or "tech.length" against a row. */
export function rowValue(row: Record<string, any>, key: string): unknown {
  let v: unknown = row;
  for (const part of key.split(".")) {
    if (v === null || v === undefined) return undefined;
    v = (v as Record<string, unknown>)[part];
  }
  return v;
}

export function compareValues(a: unknown, b: unknown): number {
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : -1;
  if (b === null || b === undefined) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "number" || typeof b === "number") {
    const na = Number(a);
    const nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  }
  const sa = String(a).toLowerCase();
  const sb = String(b).toLowerCase();
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

export function sortRows<T extends Record<string, any>>(rows: T[], sort: SortState | null): T[] {
  if (!sort) return rows;
  const key = sort.key;
  return [...rows].sort((x, y) => compareValues(rowValue(x, key), rowValue(y, key)) * sort.dir);
}

export function SortHeader({
  label,
  sort,
  sortKey,
  onSort,
  className,
}: {
  label: string;
  sort: SortState | null;
  sortKey: string;
  onSort: (k: string) => void;
  className?: string;
}) {
  const active = sort?.key === sortKey;
  return (
    <th className={`th-sticky cursor-pointer hover:text-zinc-300 ${className ?? ""}`} onClick={() => onSort(sortKey)}>
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          sort!.dir === 1 ? (
            <ArrowUp className="h-3 w-3 text-accent" />
          ) : (
            <ArrowDown className="h-3 w-3 text-accent" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-30" />
        )}
      </span>
    </th>
  );
}