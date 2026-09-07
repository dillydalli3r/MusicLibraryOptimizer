import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, ExternalLink, Loader2, Search, Zap } from "lucide-react";
import { api } from "../api";
import { EmptyState } from "../components/Badges";
import { toast } from "../store";

/* In-app MusicBrainz browser: search across the four browsable entities and
 * drill into artist / release-group / release / recording pages. Every page
 * deep-links to MusicBrainz itself and hands release names to the Soulseek
 * search so a browse can turn into an import without retyping anything. */

const TYPES = [
  { id: "artist", label: "Artists" },
  { id: "release-group", label: "Release groups" },
  { id: "release", label: "Releases" },
  { id: "recording", label: "Recordings" },
] as const;
type MBType = (typeof TYPES)[number]["id"];

/** app route path for an entity ("release-group" browses at /mb/rg/…) */
const routeFor = (type: string) =>
  type === "release-group" ? "rg" : type === "release" ? "release" : type;

interface RGRow {
  id: string; title: string; primary_type?: string; secondary_types?: string[];
  first_release_date?: string;
}
interface MBTrackRow {
  disc: number; position: number; title: string; length?: number | null;
  recording_mbid?: string | null; artist_credit?: string;
}
interface RelRow {
  id: string; title: string; date?: string; country?: string; status?: string;
  formats?: string; track_count?: number; barcode?: string; release_group?: string;
}
const mbUrl = (type: string, id: string) =>
  `https://musicbrainz.org/${type === "release-group" ? "release-group" : type}/${id}`;

const fmtLen = (ms?: number | null) => {
  if (!ms) return "—";
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

function ExtLink({ href, title }: { href: string; title: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={title}
      className="p-1.5 rounded-lg text-zinc-500 hover:text-white hover:bg-raise transition-colors shrink-0"
      onClick={(e) => e.stopPropagation()}
    >
      <ExternalLink className="h-3.5 w-3.5" />
    </a>
  );
}

function Spinner() {
  return (
    <div className="flex items-center justify-center gap-2 py-24 text-sm text-zinc-500">
      <Loader2 className="h-4 w-4 animate-spin" /> Asking MusicBrainz…
    </div>
  );
}

function LoadError({ e }: { e: unknown }) {
  return (
    <EmptyState
      title="MusicBrainz request failed"
      hint={String(e instanceof Error ? e.message : e)}
    />
  );
}

/** Page header shared by the detail views: title, meta line, chips + actions. */
function PageHeader({
  overline,
  title,
  meta,
  chips,
  mbHref,
  soulseekQuery,
  children,
}: {
  overline: string;
  title: string;
  meta?: string;
  chips?: string[];
  mbHref?: string;
  /** what the Soulseek handoff button searches (defaults to the title) */
  soulseekQuery?: string;
  children?: React.ReactNode;
}) {
  const nav = useNavigate();
  return (
    <div className="p-6 pb-4 max-w-4xl mx-auto">
      <Link to="/mb/search" className="text-[11px] text-zinc-500 hover:text-zinc-300">
        ← MusicBrainz search
      </Link>
      <div className="flex items-start justify-between gap-4 mt-2">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-widest text-zinc-500">{overline}</div>
          <h1 className="text-2xl font-bold text-white truncate" title={title}>
            {title}
          </h1>
          {meta && <div className="text-sm text-zinc-400 mt-1">{meta}</div>}
          {chips && chips.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {chips.map((c) => (
                <span key={c} className="chip bg-raise border border-border text-zinc-300">
                  {c}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {children}
          {mbHref && <ExtLink href={mbHref} title="Open on MusicBrainz" />}
          <button
            className="btn-ghost !py-1.5 text-xs"
            title="Search Soulseek for this"
            onClick={() => nav(`/soulseek?q=${encodeURIComponent(soulseekQuery ?? title)}`)}
          >
            <Search className="h-3.5 w-3.5" /> Soulseek
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Search                                                              */
/* ------------------------------------------------------------------ */

export function MBSearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const type = (params.get("type") as MBType) || "release";
  const [text, setText] = useState(q);
  const nav = useNavigate();

  useEffect(() => setText(q), [q]); // stay in sync with back/forward

  // Debounced URL sync so every keystroke doesn't fire a request.
  useEffect(() => {
    if (text === q) return;
    const t = setTimeout(() => {
      const next = new URLSearchParams();
      if (text.trim()) next.set("q", text.trim());
      next.set("type", type);
      setParams(next, { replace: true });
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  // Catalog numbers and barcodes ("SRCS 8757") often don't rank in a free
  // text search — when the query looks like one, run the exact catno/barcode
  // search in parallel and merge both result sets (exact hits first).
  const looksCatno = /^[a-z0-9]{1,8}[\s-]?\d{3,8}([-]?\d{1,4})?$/i.test(q.trim());
  const looksBarcode = /^\d{8,14}$/.test(q.trim());
  const { data, isLoading, error } = useQuery({
    queryKey: ["mbSearch", type, q, looksCatno ? "catno" : looksBarcode ? "barcode" : "free"],
    queryFn: async () => {
      const free = await api.mbSearch(type, q, 20);
      if (type !== "release" || (!looksCatno && !looksBarcode)) return free;
      // Exact catno/barcode hits replace the free-text list entirely — a
      // catalog number search is precise, and free-text matching on a catno
      // only surfaces noise.
      const extra = await api.mbSearch(type, q, 20, looksBarcode ? "barcode" : "catno").catch(() => []);
      return (extra as any[]).length ? extra : free;
    },
    enabled: q.trim().length >= 2,
  });

  const rows = (data ?? []) as Record<string, string | number | null | undefined | string[] | number>[];

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold">MusicBrainz</h1>
      <div className="relative mt-3">
        <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
        <input
          className="input !pl-10"
          placeholder="Search artists, release groups, releases, recordings…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
        />
      </div>
      <div className="flex gap-1 mt-3">
        {TYPES.map((t) => (
          <button
            key={t.id}
            className={`chip px-2.5 py-1 border ${
              type === t.id
                ? "bg-accent on-accent border-transparent font-semibold"
                : "bg-raise border-border text-zinc-400 hover:text-white"
            }`}
            onClick={() => {
              const next = new URLSearchParams(params);
              next.set("type", t.id);
              setParams(next, { replace: true });
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {!q || q.trim().length < 2 ? (
          <EmptyState title="Type at least two characters" hint="Results come straight from musicbrainz.org (rate-limited to 1 request/second — repeated views are cached)." />
        ) : isLoading ? (
          <Spinner />
        ) : error ? (
          <LoadError e={error} />
        ) : rows.length === 0 ? (
          <EmptyState title="No results" hint={`Nothing on MusicBrainz for “${q}”.`} />
        ) : (
          <div className="rounded-lg border border-border overflow-hidden">
            {rows.map((r) => (
              <div
                key={String(r.id)}
                className="table-row !cursor-pointer"
                onClick={() => nav(`/mb/${routeFor(type)}/${r.id}`)}
              >
                <div className="px-3 py-2.5 flex items-center gap-3 min-w-0">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-zinc-100 truncate">
                      {String(r.title)}
                      {r.disambiguation ? (
                        <span className="text-zinc-500 font-normal"> ({String(r.disambiguation)})</span>
                      ) : null}
                    </div>
                    <div className="text-[11px] text-zinc-500 truncate">
                      {type === "artist" &&
                        [r.type, r.country, (r.life_span as string[])?.filter(Boolean).join(" – "), (r.tags as string[])?.join(" · ")]
                          .filter(Boolean)
                          .join(" · ")}
                      {type === "release-group" &&
                        [r.artist, [r.primary_type, ...(r.secondary_types as string[] ?? [])].filter(Boolean).join("/"), r.first_release_date]
                          .filter(Boolean)
                          .join(" · ")}
                      {type === "release" &&
                        [r.artist, r.date, r.formats, r.country, r.catalog_number].filter(Boolean).join(" · ")}
                      {type === "recording" &&
                        [r.artist, r.first_release_date, r.length ? fmtLen(Number(r.length)) : ""]
                          .filter(Boolean)
                          .join(" · ")}
                    </div>
                  </div>
                  <span className="text-[10px] font-mono text-zinc-600 shrink-0" title="Search score">
                    {String(r.score ?? "")}
                  </span>
                  <ExtLink href={mbUrl(type, String(r.id))} title="Open on MusicBrainz" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Artist                                                              */
/* ------------------------------------------------------------------ */

export function MBArtistPage() {
  const { id = "" } = useParams();
  const { data: a, isLoading, error } = useQuery({
    queryKey: ["mbArtist", id],
    queryFn: () => api.mbArtist(id),
    enabled: !!id,
  });
  if (isLoading) return <Spinner />;
  if (error) return <div className="p-6"><LoadError e={error} /></div>;
  if (!a) return null;
  const life = (a.life_span ?? []).filter(Boolean).join(" – ");

  // Discography grouped by primary type keeps long artist pages scannable.
  const groups: RGRow[] = a.release_groups ?? [];
  const byType: Record<string, RGRow[]> = {};
  for (const rg of groups) {
    const key = rg.primary_type || "Other";
    (byType[key] ??= []).push(rg);
  }

  return (
    <div>
      <PageHeader
        overline="MusicBrainz artist"
        title={a.name}
        meta={[a.disambiguation, a.type, a.country, life].filter(Boolean).join(" · ")}
        chips={[...(a.genres ?? []), ...(a.tags ?? []).slice(0, 5)].slice(0, 8)}
        mbHref={mbUrl("artist", a.id)}
      />
      <div className="px-6 pb-8 max-w-4xl mx-auto space-y-5">
        {groups.length === 0 && <EmptyState title="No release groups on MusicBrainz" />}
        {Object.entries(byType).map(([type, list]) => (
          <div key={type}>
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1.5">
              {type}s · {list.length}
            </div>
            <div className="rounded-lg border border-border overflow-hidden">
              {list.map((rg) => (
                <div
                  key={rg.id}
                  className="table-row !cursor-pointer"
                  onClick={() => location.assign(`/mb/rg/${rg.id}`)}
                >
                  <div className="px-3 py-2 flex items-center gap-3 min-w-0">
                    <span className="text-xs font-mono text-zinc-500 w-10 shrink-0">
                      {(rg.first_release_date || "—").slice(0, 4)}
                    </span>
                    <span className="text-sm text-zinc-200 truncate flex-1">
                      {rg.title}
                      {rg.secondary_types?.length ? (
                        <span className="text-zinc-500 text-xs"> ({rg.secondary_types.join(" + ")})</span>
                      ) : null}
                    </span>
                    <ExtLink href={mbUrl("release-group", rg.id)} title="Open on MusicBrainz" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Release group                                                       */
/* ------------------------------------------------------------------ */

export function MBReleaseGroupPage() {
  const { id = "" } = useParams();
  const { data: rg, isLoading, error } = useQuery({
    queryKey: ["mbRG", id],
    queryFn: () => api.mbReleaseGroup(id),
    enabled: !!id,
  });
  if (isLoading) return <Spinner />;
  if (error) return <div className="p-6"><LoadError e={error} /></div>;
  if (!rg) return null;
  const typeLabel = [rg.primary_type, ...(rg.secondary_types ?? [])].filter(Boolean).join(" + ");

  return (
    <div>
      <PageHeader
        overline="MusicBrainz release group"
        title={rg.title}
        meta={[
          rg.artist,
          typeLabel,
          rg.first_release_date,
          rg.disambiguation,
        ]
          .filter(Boolean)
          .join(" · ")}
        chips={rg.genres ?? []}
        mbHref={mbUrl("release-group", rg.id)}
      >
        {rg.artist_mbid && (
          <Link className="btn-ghost !py-1.5 text-xs" to={`/mb/artist/${rg.artist_mbid}`}>
            Artist page
          </Link>
        )}
      </PageHeader>
      <div className="px-6 pb-8 max-w-4xl mx-auto">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1.5">
          Releases · {rg.releases?.length ?? 0}
        </div>
        <div className="rounded-lg border border-border overflow-hidden">
          {((rg.releases ?? []) as RelRow[]).map((r) => (
            <div
              key={r.id}
              className="table-row !cursor-pointer"
              onClick={() => location.assign(`/mb/release/${r.id}`)}
            >
              <div className="px-3 py-2 flex items-center gap-3 min-w-0">
                <span className="text-xs font-mono text-zinc-500 w-12 shrink-0">
                  {r.date || "—"}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-200 truncate">{r.title}</div>
                  <div className="text-[11px] text-zinc-500 truncate">
                    {[r.formats, r.country, r.status, r.track_count ? `${r.track_count} tracks` : "", r.barcode]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
                <ExtLink href={mbUrl("release", r.id)} title="Open on MusicBrainz" />
              </div>
            </div>
          ))}
          {!rg.releases?.length && <EmptyState title="No releases in this group" />}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Release                                                             */
/* ------------------------------------------------------------------ */

export function MBReleasePage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const { data: r, isLoading, error } = useQuery({
    queryKey: ["mbRelease", id],
    queryFn: () => api.mbRelease(id),
    enabled: !!id,
  });
  if (isLoading) return <Spinner />;
  if (error) return <div className="p-6"><LoadError e={error} /></div>;
  if (!r) return null;

  const cover = `https://coverartarchive.org/release/${r.id}/front-500`;
  const artist = r.artists?.map((a) => a.name).join(", ") || "";
  const discs: Record<number, MBTrackRow[]> = {};
  for (const t of (r.media ?? []) as MBTrackRow[]) {
    (discs[t.disc] ??= []).push(t);
  }

  return (
    <div>
      <PageHeader
        overline="MusicBrainz release"
        title={r.title}
        soulseekQuery={[r.artists?.[0]?.name, r.title].filter(Boolean).join(" ")}
        meta={[
          artist,
          r.release_type,
          r.date,
          [r.label, r.catalog_number].filter(Boolean).join(" · "),
          r.country,
          r.barcode,
        ]
          .filter(Boolean)
          .join(" · ")}
        chips={r.genres ?? []}
        mbHref={mbUrl("release", r.id)}
      >
        <button
          className="btn-primary !py-1.5 text-xs"
          title="Find → verify → download → audit → import this exact release from Soulseek"
          onClick={async () => {
            try {
              await api.soulseekAutoStart({ release_mbid: r.id });
              toast("Auto-import started");
              nav(`/soulseek?release=${encodeURIComponent(r.id)}`);
            } catch (e) {
              toast(String(e));
            }
          }}
        >
          <Zap className="h-3.5 w-3.5" /> Auto-import
        </button>
        {r.release_group_id && (
          <Link className="btn-ghost !py-1.5 text-xs" to={`/mb/rg/${r.release_group_id}`}>
            Release group
          </Link>
        )}
        <a className="btn-ghost !py-1.5 text-xs" href={cover} target="_blank" rel="noreferrer" title="Cover Art Archive">
          Cover art
        </a>
      </PageHeader>

      <div className="px-6 pb-8 max-w-4xl mx-auto grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-6">
        <div>
          <img
            src={cover}
            alt=""
            className="w-full rounded-lg border border-border bg-raise"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
            }}
          />
          <div className="text-[10px] text-zinc-600 mt-1.5">
            Artwork from the Cover Art Archive — download it into a local album via the album page's “Find cover online”.
          </div>
        </div>
        <div className="space-y-4">
          {Object.entries(discs).map(([disc, tracks]) => (
            <div key={disc}>
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1.5">
                Disc {disc}{r.medium_formats?.[Number(disc) - 1] ? ` · ${r.medium_formats[Number(disc) - 1]}` : ""}
              </div>
              <div className="rounded-lg border border-border overflow-hidden">
                {tracks.map((t) => (
                  <div key={`${t.disc}-${t.position}`} className="flex items-center gap-3 px-3 py-1.5 border-t border-border/60 first:border-t-0">
                    <span className="text-[11px] font-mono text-zinc-600 w-6 text-right shrink-0">
                      {t.position}
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className="text-sm text-zinc-200 truncate">{t.title}</span>
                      {t.artist_credit && t.artist_credit !== artist && (
                        <span className="text-[11px] text-zinc-500"> — {t.artist_credit}</span>
                      )}
                    </div>
                    <span className="text-[11px] font-mono text-zinc-500 shrink-0">{fmtLen(t.length)}</span>
                    {t.recording_mbid && (
                      <Link
                        to={`/mb/recording/${t.recording_mbid}`}
                        className="p-1 rounded-lg text-zinc-600 hover:text-white hover:bg-raise transition-colors shrink-0"
                        title="Open this track on MusicBrainz"
                      >
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      </Link>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Recording ("track")                                                 */
/* ------------------------------------------------------------------ */

export function MBRecordingPage() {
  const { id = "" } = useParams();
  const { data: r, isLoading, error } = useQuery({
    queryKey: ["mbRecording", id],
    queryFn: () => api.mbRecording(id),
    enabled: !!id,
  });
  if (isLoading) return <Spinner />;
  if (error) return <div className="p-6"><LoadError e={error} /></div>;
  if (!r) return null;

  return (
    <div>
      <PageHeader
        overline="MusicBrainz recording"
        title={r.title}
        soulseekQuery={[r.artist, r.title].filter(Boolean).join(" ")}
        meta={[
          r.artist,
          r.length ? fmtLen(r.length) : "",
          r.disambiguation,
          r.isrcs?.length ? `ISRC ${r.isrcs.join(", ")}` : "",
        ]
          .filter(Boolean)
          .join(" · ")}
        chips={r.genres ?? []}
        mbHref={mbUrl("recording", r.id)}
      >
        {r.artist_mbid && (
          <Link className="btn-ghost !py-1.5 text-xs" to={`/mb/artist/${r.artist_mbid}`}>
            Artist page
          </Link>
        )}
      </PageHeader>
      <div className="px-6 pb-8 max-w-4xl mx-auto">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1.5">
          Appears on · {r.releases?.length ?? 0} releases
        </div>
        <div className="rounded-lg border border-border overflow-hidden">
          {((r.releases ?? []) as RelRow[]).map((rel) => (
            <div
              key={rel.id}
              className="table-row !cursor-pointer"
              onClick={() => location.assign(`/mb/release/${rel.id}`)}
            >
              <div className="px-3 py-2 flex items-center gap-3 min-w-0">
                <span className="text-xs font-mono text-zinc-500 w-12 shrink-0">{rel.date || "—"}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-200 truncate">{rel.title}</div>
                  <div className="text-[11px] text-zinc-500 truncate">
                    {[rel.release_group, rel.formats, rel.country, rel.status].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <ExtLink href={mbUrl("release", rel.id)} title="Open on MusicBrainz" />
              </div>
            </div>
          ))}
          {!r.releases?.length && <EmptyState title="No releases carry this recording" />}
        </div>
      </div>
    </div>
  );
}
