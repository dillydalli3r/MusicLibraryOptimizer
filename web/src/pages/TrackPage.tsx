import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { ExternalLink, Save, Play, Disc3, ListPlus } from "lucide-react";
import { api } from "../api";
import { useStore, toast } from "../store";
import { AuditBadge, GradeBadge, IssueList } from "../components/Badges";
import LyricsViewer from "../components/LyricsViewer";

export default function TrackPage() {
  const { path = "" } = useParams();
  const decoded = decodeURIComponent(path);
  const qc = useQueryClient();
  const { playNow } = useStore();

  const { data, isLoading, error } = useQuery({
    queryKey: ["track-tags", decoded],
    queryFn: () => api.tags(decoded),
  });

  const [tags, setTags] = useState<Record<string, string>>({});
  const [lyrics, setLyrics] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!data) return;
    const clean: Record<string, string> = {};
    for (const [k, v] of Object.entries(data.tags ?? {})) {
      if (typeof v === "string") clean[k] = v;
    }
    setTags(clean);
    setLyrics(data.lyrics ?? "");
    setDirty(false);
  }, [data]);

  if (error) return <div className="p-8 text-zinc-500">Track not found: {String(error)}</div>;
  if (isLoading || !data) return <div className="p-8 text-zinc-500">Loading track…</div>;

  const albumDir = decoded.split("/").slice(0, -1).join("/");
  const tech = data.tech ?? {};

  const save = async () => {
    try {
      await api.setTags(decoded, { ...tags, LYRICS: lyrics || null });
      toast("Track saved");
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    }
  };

  const setTag = (k: string, v: string) => {
    setTags((t) => ({ ...t, [k]: v }));
    setDirty(true);
  };

  const addToPlaylist = async () => {
    const pls = await api.playlists();
    const manual = pls.find((p) => p.kind === "manual");
    if (!manual) {
      const created = await api.createPlaylist("Library selection", "manual");
      await api.playlistAdd(created.id, [decoded]);
    } else {
      await api.playlistAdd(manual.id, [decoded]);
    }
    toast("Added to playlist");
  };

  const linkTags: Record<string, { label: string; url?: (v: string) => string }> = {
    MUSICBRAINZ_ALBUMID: { label: "MusicBrainz Album", url: (v) => `https://musicbrainz.org/release/${v}` },
    MUSICBRAINZ_TRACKID: { label: "MusicBrainz Track", url: (v) => `https://musicbrainz.org/recording/${v}` },
    MUSICBRAINZ_ARTISTID: { label: "MusicBrainz Artist", url: (v) => `https://musicbrainz.org/artist/${v}` },
    MUSICBRAINZ_RELEASEGROUPID: { label: "MusicBrainz Release Group", url: (v) => `https://musicbrainz.org/release-group/${v}` },
    RATEYOURMUSIC_ALBUM: { label: "RateYourMusic Album" },
    RATEYOURMUSIC_TRACK: { label: "RateYourMusic Track" },
    RATEYOURMUSIC_ARTIST: { label: "RateYourMusic Artist" },
  };

  const mainFields = ["TITLE", "ARTIST", "ALBUM", "GENRE", "DATE", "TRACKNUMBER", "DISCNUMBER"];
  const extraFields = Object.keys(tags)
    .filter((k) => !mainFields.includes(k) && !(k in linkTags) && !["LYRICS", "UNSYNCEDLYRICS"].includes(k))
    .sort();

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs text-zinc-500">
            <Link to={`/album/${encodeURIComponent(albumDir)}`} className="hover:text-accent-soft">
              {tags.ALBUM || albumDir.split("/").pop()}
            </Link>
            {" · "}
            <span className="inline-flex items-center gap-1"><Disc3 className="h-3 w-3" /> {decoded.split("/").pop()}</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight truncate">{tags.TITLE ?? decoded.split("/").pop()}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <GradeBadge pass={!data.issues?.length} score={data.issues?.length ? 0 : 100} />
            <AuditBadge audit={data.audit} />
            <IssueList issues={data.issues ?? []} />
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <button className="btn-ghost" onClick={addToPlaylist}><ListPlus className="h-4 w-4" /> Playlist</button>
          <button className="btn-ghost" onClick={() => playNow([{ path: decoded, file: decoded.split("/").pop()!, albumPath: albumDir }])}>
            <Play className="h-4 w-4" /> Play
          </button>
          <button className="btn-primary" onClick={save} disabled={!dirty}>
            <Save className="h-4 w-4" /> Save
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <div className="space-y-4">
          <div className="bg-card rounded-lg border border-border p-4 space-y-2.5">
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Metadata</div>
            <div className="grid grid-cols-2 gap-2.5">
              {mainFields.map((k) => (
                <label key={k} className="block">
                  <span className="text-[10px] text-zinc-500 uppercase">{k}</span>
                  <input className="input mt-0.5" value={tags[k] ?? ""} onChange={(e) => setTag(k, e.target.value)} />
                </label>
              ))}
            </div>
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 pt-2">MusicBrainz / RateYourMusic links</div>
            {Object.entries(linkTags).map(([k, spec]) => (
              <div key={k} className="flex items-center gap-2">
                <input
                  className="input flex-1"
                  placeholder={spec.label}
                  value={tags[k] ?? ""}
                  onChange={(e) => setTag(k, e.target.value)}
                />
                {tags[k] && spec.url && (
                  <a href={spec.url(tags[k])} target="_blank" rel="noreferrer" className="text-zinc-500 hover:text-accent-soft shrink-0">
                    <ExternalLink className="h-4 w-4" />
                  </a>
                )}
              </div>
            ))}
            {extraFields.length > 0 && (
              <>
                <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 pt-2">Other tags</div>
                {extraFields.map((k) => (
                  <label key={k} className="block">
                    <span className="text-[10px] text-zinc-500 uppercase">{k}</span>
                    <input className="input mt-0.5" value={tags[k] ?? ""} onChange={(e) => setTag(k, e.target.value)} />
                  </label>
                ))}
              </>
            )}
          </div>

          <div className="bg-card rounded-lg border border-border p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">Audio</div>
            <div className="grid grid-cols-2 gap-2 text-sm text-zinc-400">
              <div>Duration <span className="text-zinc-200">{tech.length ? `${Math.floor(tech.length / 60)}:${String(Math.floor(tech.length % 60)).padStart(2, "0")}` : "—"}</span></div>
              <div>Bitrate <span className="text-zinc-200">{tech.bitrate ? `${Math.round(tech.bitrate / 1000)} kbps` : "—"}</span></div>
              <div>Sample rate <span className="text-zinc-200">{tech.sample_rate ? `${Math.round(tech.sample_rate / 1000)} kHz` : "—"}</span></div>
              <div>Bit depth <span className="text-zinc-200">{tech.bits_per_sample ?? "—"}</span></div>
              <div>Channels <span className="text-zinc-200">{tech.channels ?? "—"}</span></div>
            </div>
          </div>
        </div>

        <LyricsViewer
                  path={decoded}
                  initialLyrics={lyrics}
                  onChange={(v) => { setLyrics(v); setDirty(true); }}
                  artist={tags.ARTIST}
                  track={tags.TITLE}
                  album={tags.ALBUM}
                  duration={tech.length ? Math.round(tech.length) : undefined}
                />
      </div>
    </div>
  );
}