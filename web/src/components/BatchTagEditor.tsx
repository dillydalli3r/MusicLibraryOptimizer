import { useState } from "react";
import { Tags, X } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";

const FIELDS: { key: string; label: string; kind?: "select"; options?: [string, string][] }[] = [
  { key: "TITLE", label: "Title" },
  { key: "ARTIST", label: "Artist" },
  { key: "ALBUM", label: "Album" },
  { key: "ALBUMARTIST", label: "Album artist" },
  { key: "GENRE", label: "Genre (separate with ;)" },
  { key: "DATE", label: "Date" },
  { key: "TRACKNUMBER", label: "Track number" },
  { key: "DISCNUMBER", label: "Disc number" },
  { key: "MEDIA", label: "Media (CD / Digital Media)" },
  { key: "COMMENT", label: "Comment" },
  {
    key: "ITUNESADVISORY",
    label: "Advisory",
    kind: "select",
    options: [
      ["", "— leave as is"],
      ["0", "0 · clean"],
      ["1", "1 · explicit"],
      ["2", "2 · safe"],
    ],
  },
  {
    key: "INSTRUMENTAL",
    label: "Instrumental",
    kind: "select",
    options: [
      ["", "— leave as is"],
      ["1", "1 · instrumental"],
      ["0", "0 · has vocals"],
    ],
  },
];

/** Modal batch tag editor: applies entered values / clears to every
 * selected track via /api/tags/batch. Empty fields are left untouched. */
export default function BatchTagEditor({
  paths,
  onClose,
  onDone,
}: {
  paths: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [clears, setClears] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    setBusy(true);
    try {
      const writes: Record<string, Record<string, string | null>> = {};
      for (const p of paths) {
        const map: Record<string, string | null> = {};
        for (const f of FIELDS) {
          const v = values[f.key];
          if (clears.has(f.key)) map[f.key] = null;
          else if (v !== undefined && v !== "") map[f.key] = v;
        }
        if (Object.keys(map).length) writes[p] = map;
      }
      if (!Object.keys(writes).length) {
        toast("Enter values or mark fields to clear first");
        return;
      }
      const res = await api.setTagsBatch(writes);
      toast(`Tags updated on ${res.changed} file(s)`);
      onDone();
      onClose();
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-card border border-border rounded-xl w-full max-w-lg max-h-[85vh] overflow-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-5 py-3 border-b border-border sticky top-0 bg-card z-10">
          <Tags className="h-4 w-4 text-accent" />
          <span className="font-semibold text-sm">Edit tags — {paths.length} track(s)</span>
          <button className="ml-auto p-1 text-zinc-500 hover:text-white" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-2.5">
          {FIELDS.map((f) => (
            <div key={f.key} className="flex items-center gap-2">
              <label className="w-32 shrink-0 text-xs text-zinc-400">{f.label}</label>
              {f.kind === "select" ? (
                <select
                  className="input !py-1 text-xs flex-1"
                  value={values[f.key] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                >
                  {(f.options ?? []).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              ) : (
                <input
                  className="input !py-1 text-xs flex-1"
                  value={values[f.key] ?? ""}
                  placeholder="leave unchanged"
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              )}
              <label className="flex items-center gap-1 text-[10px] text-zinc-500 cursor-pointer select-none shrink-0">
                <input
                  type="checkbox"
                  checked={clears.has(f.key)}
                  onChange={(e) =>
                    setClears((s) => {
                      const next = new Set(s);
                      if (e.target.checked) next.add(f.key);
                      else next.delete(f.key);
                      return next;
                    })
                  }
                />
                clear
              </label>
            </div>
          ))}
          <div className="flex justify-end gap-2 pt-3">
            <button className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn-primary" onClick={apply} disabled={busy}>
              Apply to {paths.length} track(s)
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}