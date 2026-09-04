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
  // Numeric strings ("10" vs "2") compare numerically, not as text.
  if (typeof a !== "object" && typeof b !== "object") {
    const sa = String(a);
    const sb = String(b);
    if (/^\d+$/.test(sa) && /^\d+$/.test(sb)) return Number(sa) - Number(sb);
  }
  if (typeof a === "number" || typeof b === "number") {
    const na = Number(a);
    const nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  }
  const sa = String(a).toLowerCase();
  const sb = String(b).toLowerCase();
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

/** Tie-breaker keys used when the primary sort values are equal. */
const SECONDARY_KEYS: Record<string, string[]> = {
  // Track # must fall back to disc number, then filename ("1-01 …").
  tracknumber: ["discnumber", "file"],
  discnumber: ["tracknumber", "file"],
};

export function sortRows<T extends Record<string, any>>(rows: T[], sort: SortState | null): T[] {
  if (!sort) return rows;
  const key = sort.key;
  const secondary = SECONDARY_KEYS[key] ?? [];
  return [...rows].sort((x, y) => {
    let c = compareValues(rowValue(x, key), rowValue(y, key));
    if (c === 0) {
      for (const k of secondary) {
        c = compareValues(rowValue(x, k), rowValue(y, k));
        if (c !== 0) break;
      }
      if (c === 0 && key !== "file") c = compareValues(rowValue(x, "file"), rowValue(y, "file"));
    }
    return c * sort.dir;
  });
}

export interface DiscGroup<T> {
  disc: number | null;
  tracks: T[];
}

/** Group tracks by disc number for album tracklists. One group (disc=null)
 *  unless the album really has more than one disc. */
export function groupByDisc<T extends Record<string, any>>(tracks: T[]): DiscGroup<T>[] {
  const discs = new Set<number>();
  for (const t of tracks) {
    if (typeof t.discnumber === "number") discs.add(t.discnumber);
  }
  if (discs.size <= 1) return [{ disc: discs.size ? [...discs][0] : null, tracks }];
  const groups: DiscGroup<T>[] = [];
  for (const d of [...discs].sort((a, b) => a - b)) {
    groups.push({ disc: d, tracks: tracks.filter((t) => t.discnumber === d) });
  }
  const noDisc = tracks.filter((t) => typeof t.discnumber !== "number");
  if (noDisc.length) groups.push({ disc: null, tracks: noDisc });
  return groups;
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
    <th className={`th cursor-pointer hover:text-zinc-300 ${className ?? ""}`} onClick={() => onSort(sortKey)}>
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