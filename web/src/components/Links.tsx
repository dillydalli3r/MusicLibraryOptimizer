import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Link2, Loader2 } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";

/* MusicBrainz / RateYourMusic identity links.
 *
 * LinkChips renders the open-in-database icon row from a tags object;
 * LinkEditorButton opens the paste-a-URL editor that maps a pasted
 * musicbrainz.org / rateyourmusic.com link (or bare MBID) onto the right
 * tags and writes them to every given path via /api/mb/assign. */

const MBID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Pull a bare MBID out of a pasted URL (any entity) or accept a bare ID. */
function mbidFrom(input: string): string | null {
  const t = input.trim();
  if (!t) return null;
  const fromUrl = /musicbrainz\.org\/[a-z-]+\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i.exec(t);
  if (fromUrl) return fromUrl[1].toLowerCase();
  if (MBID_RE.test(t)) return t.toLowerCase();
  return null;
}

interface FieldDef {
  key: string; // tag written
  label: string;
  placeholder: string;
  kind: "mb" | "rym"; // MB fields store bare IDs; RYM stores the URL
}

const FIELDS: Record<"artist" | "album" | "track", FieldDef[]> = {
  artist: [
    { key: "MUSICBRAINZ_ARTISTID", label: "MusicBrainz artist", placeholder: "musicbrainz.org/artist/… or MBID", kind: "mb" },
    { key: "RATEYOURMUSIC_ARTIST", label: "RYM artist", placeholder: "rateyourmusic.com/artist/…", kind: "rym" },
  ],
  album: [
    { key: "MUSICBRAINZ_ALBUMID", label: "MusicBrainz release", placeholder: "musicbrainz.org/release/… or MBID", kind: "mb" },
    { key: "MUSICBRAINZ_RELEASEGROUPID", label: "MusicBrainz release group", placeholder: "musicbrainz.org/release-group/… or MBID", kind: "mb" },
    { key: "RATEYOURMUSIC_ALBUM", label: "RYM album", placeholder: "rateyourmusic.com/release/album/…", kind: "rym" },
  ],
  track: [
    { key: "MUSICBRAINZ_TRACKID", label: "MusicBrainz recording", placeholder: "musicbrainz.org/recording/… or MBID", kind: "mb" },
    { key: "RATEYOURMUSIC_TRACK", label: "RYM track", placeholder: "rateyourmusic.com/song/…", kind: "rym" },
  ],
};

const MB_URL: Record<string, (v: string) => string> = {
  MUSICBRAINZ_ARTISTID: (v) => `https://musicbrainz.org/artist/${v}`,
  MUSICBRAINZ_ALBUMID: (v) => `https://musicbrainz.org/release/${v}`,
  MUSICBRAINZ_RELEASEGROUPID: (v) => `https://musicbrainz.org/release-group/${v}`,
  MUSICBRAINZ_TRACKID: (v) => `https://musicbrainz.org/recording/${v}`,
  MUSICBRAINZ_ALBUMARTISTID: (v) => `https://musicbrainz.org/artist/${v}`,
};

/** MusicBrainz mark: the stylized eighth-note in a circle. */
export function MbIcon({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M12 1.5C6.2 1.5 1.5 6.2 1.5 12S6.2 22.5 12 22.5 22.5 17.8 22.5 12 17.8 1.5 12 1.5Zm0 2.1a8.4 8.4 0 1 1 0 16.8 8.4 8.4 0 0 1 0-16.8Z" />
      <path d="M10.2 7.2 16.3 5.6v8.6a2.2 2.2 0 1 1-1.4-2V8.9l-3.3.9v6.4a2.2 2.2 0 1 1-1.4-2V7.2Z" />
    </svg>
  );
}

/** RateYourMusic mark: the angled "RYM" wordmark block. */
export function RymIcon({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 24" className={className} fill="currentColor" aria-hidden>
      <rect x="1" y="4" width="30" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="2" />
      <text
        x="16"
        y="15.8"
        textAnchor="middle"
        fontSize="8.5"
        fontWeight="800"
        fontFamily="ui-sans-serif, system-ui"
        fill="currentColor"
      >
        RYM
      </text>
    </svg>
  );
}

/** Icon row opening every identity link present in `tags`.
 *
 * `only` narrows the row to specific tags (and prefers the first listed):
 * album pages pass their album-level tags so exactly one MusicBrainz and
 * one RateYourMusic link show, even when a release-group ID also exists. */
export function LinkChips({ tags, only }: { tags: Record<string, unknown>; only?: string[] }) {
  let mbEntries = Object.entries(MB_URL).filter(([tag]) => {
    const v = tags?.[tag];
    return typeof v === "string" && !!v.trim();
  });
  let rymEntries = ([
    ["RATEYOURMUSIC_ARTIST", "RYM artist"],
    ["RATEYOURMUSIC_ALBUM", "RYM album"],
    ["RATEYOURMUSIC_TRACK", "RYM track"],
  ] as const).filter(([tag]) => {
    const v = tags?.[tag];
    return typeof v === "string" && !!v.trim();
  });
  if (only?.length) {
    const rank = new Map(only.map((t, i) => [t, i]));
    mbEntries = mbEntries
      .filter(([tag]) => rank.has(tag))
      .sort((a, b) => (rank.get(a[0]) ?? 99) - (rank.get(b[0]) ?? 99))
      .slice(0, 1); // exactly one MusicBrainz link
    rymEntries = rymEntries
      .filter(([tag]) => rank.has(tag))
      .sort((a, b) => (rank.get(a[0]) ?? 99) - (rank.get(b[0]) ?? 99))
      .slice(0, 1); // exactly one RYM link
  }
  const items: { href: string; label: string; service: "mb" | "rym" }[] = [
    ...mbEntries.map(([tag, build]) => ({
      href: build(tags[tag] as string),
      label: tag.replace("MUSICBRAINZ_", "MusicBrainz ").replace("ID", "").replace("RELEASEGROUP", "release-group "),
      service: "mb" as const,
    })),
    ...rymEntries.map(([tag, label]) => ({
      href: tags[tag] as string,
      label,
      service: "rym" as const,
    })),
  ];
  if (!items.length) return null;
  return (
    <span className="inline-flex items-center gap-1">
      {items.map((it, i) => (
        <a
          key={i}
          href={it.href}
          target="_blank"
          rel="noreferrer"
          title={`Open ${it.label}`}
          className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-raise transition-colors inline-flex items-center"
        >
          {it.service === "mb" ? <MbIcon /> : <RymIcon className="h-4 w-5" />}
        </a>
      ))}
    </span>
  );
}

/** "Links" button + popover editor. Writes go to EVERY path given, which is
 * what makes album/artist level linking one paste per field. */
export function LinkEditorButton({
  mode,
  paths,
  current,
  onSaved,
}: {
  mode: "artist" | "album" | "track";
  paths: string[];
  current?: Record<string, unknown>;
  onSaved?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();

  const save = async () => {
    const writes: Record<string, Record<string, string>> = {};
    for (const f of FIELDS[mode]) {
      const raw = (values[f.key] ?? "").trim();
      if (!raw) continue;
      let value = raw;
      if (f.kind === "mb") {
        const id = mbidFrom(raw);
        if (!id) {
          toast(`${f.label}: not a MusicBrainz URL or MBID`);
          return;
        }
        value = id;
      } else if (!/^https?:\/\//i.test(raw)) {
        toast(`${f.label}: paste the full URL`);
        return;
      }
      for (const p of paths) (writes[p] ??= {})[f.key] = value;
    }
    if (!Object.keys(writes).length) {
      toast("Nothing to save");
      return;
    }
    setBusy(true);
    try {
      await api.mbAssign(writes);
      toast(`Links written to ${paths.length} file(s)`);
      setValues({});
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["album"] });
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["artist"] });
      onSaved?.();
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative">
      <button
        className="btn-ghost !py-1.5 text-xs"
        onClick={() => setOpen(!open)}
        title="Paste MusicBrainz / RateYourMusic links"
      >
        <Link2 className="h-3.5 w-3.5" /> Links
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-30 w-80 rounded-lg border border-border bg-zinc-950 shadow-2xl p-3 space-y-2.5">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">
              Identity links · {mode} level
            </div>
            {FIELDS[mode].map((f) => {
              const cur = current?.[f.key];
              return (
                <div key={f.key}>
                  <label className="text-[11px] text-zinc-400 flex items-center gap-1.5">
                    {f.label}
                    {typeof cur === "string" && cur && (
                      <a
                        href={f.kind === "mb" && MBID_RE.test(cur) ? MB_URL[f.key]?.(cur) : cur}
                        target="_blank"
                        rel="noreferrer"
                        className="text-accent-soft hover:underline inline-flex items-center gap-0.5"
                        title="Open the current link"
                      >
                        set <ExternalLink className="h-2.5 w-2.5" />
                      </a>
                    )}
                  </label>
                  <input
                    className="input !py-1 !px-2 text-xs mt-0.5"
                    placeholder={f.placeholder}
                    value={values[f.key] ?? ""}
                    onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  />
                </div>
              );
            })}
            <div className="flex justify-end gap-1.5 pt-1">
              <button className="btn-ghost !py-1 text-xs" onClick={() => setOpen(false)}>
                Cancel
              </button>
              <button className="btn-primary !py-1 text-xs" onClick={save} disabled={busy}>
                {busy && <Loader2 className="h-3 w-3 animate-spin" />} Write to {paths.length} file(s)
              </button>
            </div>
            <div className="text-[10px] text-zinc-600">
              Paste links (or bare MBIDs). Values are written as real tags so grading sees them.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
