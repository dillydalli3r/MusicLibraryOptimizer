import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { ExternalLink, Save, Play, Disc3, ListPlus, ShieldCheck, ImageUp, Clapperboard } from "lucide-react";
import { api } from "../api";
import { useStore, toast } from "../store";
import { AuditBadge, GradeBadge, IssueList } from "../components/Badges";
import CoverImg from "../components/CoverImg";
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

  // Full grading/audit context from the album payload (issues, checks,
  // audit verdict, log grade, AccurateRip status, tech).
  const albumDir = decoded.split("/").slice(0, -1).join("/");
  const { data: album } = useQuery({
    queryKey: ["album", albumDir],
    queryFn: () => api.album(albumDir),
    retry: false,
  });
  const track = (album?.tracks ?? []).find((t) => t.path === decoded);

  const [lyrics, setLyrics] = useState("");
  const [dirty, setDirty] = useState(false);
  const [coverBusy, setCoverBusy] = useState(false);
  const [videoOpen, setVideoOpen] = useState(false);
  const coverInput = useRef<HTMLInputElement>(null);

  const tags: Record<string, string> = {};
  for (const [k, v] of Object.entries(data?.tags ?? {})) {
    if (typeof v === "string" && v !== "") tags[k] = v;
  }

  useEffect(() => {
    if (!data) return;
    setLyrics(data.lyrics ?? "");
    setDirty(false);
  }, [data]);

  if (error) return <div className="p-8 text-zinc-500">Track not found: {String(error)}</div>;
  if (isLoading || !data) return <div className="p-8 text-zinc-500">Loading track…</div>;

  const fileName = decoded.split("/").pop() ?? decoded;
  const isVideo = fileName.toLowerCase().endsWith(".mp4");
  const tech = track?.tech ?? data.tech ?? {};
  const issues: string[] = track?.issues ?? [];
  const audit = track?.audit ?? null;
  const logGrade = track?.log_grade ?? null;
  const arStatus = track?.accuraterip_status ?? null;
  const csStatus = track?.checksum_status ?? null;

  const saveLyrics = async () => {
    try {
      await api.lyricsEmbed(decoded, lyrics);
      toast("Lyrics saved");
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    }
  };

  const uploadCover = async (file: File) => {
    setCoverBusy(true);
    try {
      await api.cover(albumDir, file, fileName);
      toast(`Per-track cover saved for ${fileName}`);
      qc.invalidateQueries({ queryKey: ["album", albumDir] });
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    } finally {
      setCoverBusy(false);
      if (coverInput.current) coverInput.current.value = "";
    }
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

  const mainFields = ["TITLE", "ARTIST", "ALBUM", "GENRE", "DATE", "TRACKNUMBER", "DISCNUMBER",
    "ALBUMARTIST", "ORIGINALDATE", "RELEASETYPE", "RELEASECOUNTRY", "CATALOGNUMBER"];
  const extraFields = Object.keys(tags)
    .filter((k) => !mainFields.includes(k) && !(k in linkTags) && !["LYRICS", "UNSYNCEDLYRICS"].includes(k))
    .sort();

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      {videoOpen && isVideo && (
        <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-6" onClick={() => setVideoOpen(false)}>
          <div className="w-full max-w-4xl" onClick={(e) => e.stopPropagation()}>
            <video
              src={api.streamUrl(decoded)}
              controls
              autoPlay
              className="w-full max-h-[80vh] rounded-lg border border-border bg-black"
            />
            <div className="flex justify-between items-center mt-2 text-xs text-zinc-400">
              <span className="truncate">{fileName}</span>
              <button className="btn-ghost !py-1" onClick={() => setVideoOpen(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs text-zinc-500">
            <Link to={`/album/${encodeURIComponent(albumDir)}`} className="hover:text-accent-soft">
              {tags.ALBUM || albumDir.split("/").pop()}
            </Link>
            {" · "}
            <span className="inline-flex items-center gap-1"><Disc3 className="h-3 w-3" /> {fileName}</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight truncate">{tags.TITLE ?? fileName}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <GradeBadge pass={!issues.length} score={issues.length ? 0 : 100} />
            <AuditBadge audit={audit} />
            <IssueList issues={issues} />
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <button className="btn-ghost" onClick={addToPlaylist}><ListPlus className="h-4 w-4" /> Playlist</button>
          {isVideo ? (
            <button className="btn-ghost" onClick={() => setVideoOpen(true)}>
              <Clapperboard className="h-4 w-4" /> Watch
            </button>
          ) : null}
          <button className="btn-ghost" onClick={() => playNow([{ path: decoded, file: fileName, albumPath: albumDir }])}>
            <Play className="h-4 w-4" /> Play
          </button>
          <button className="btn-primary" onClick={saveLyrics} disabled={!dirty}>
            <Save className="h-4 w-4" /> Save lyrics
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <div className="space-y-4">
          <div className="bg-card rounded-lg border border-border p-4 space-y-2.5">
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Metadata (read-only)</div>
            <div className="grid grid-cols-2 gap-2.5">
              {mainFields.map((k) =>
                tags[k] ? (
                  <div key={k} className="min-w-0">
                    <div className="text-[10px] text-zinc-500 uppercase">{k}</div>
                    <div className="text-sm text-zinc-200 truncate" title={tags[k]}>{tags[k]}</div>
                  </div>
                ) : null
              )}
            </div>
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 pt-2">MusicBrainz / RateYourMusic links</div>
            {Object.entries(linkTags).map(([k, spec]) =>
              tags[k] ? (
                <div key={k} className="flex items-center gap-2">
                  <span className="text-[10px] text-zinc-500 uppercase w-40 shrink-0">{spec.label}</span>
                  <span className="text-sm text-zinc-200 truncate flex-1" title={tags[k]}>{tags[k]}</span>
                  {spec.url && (
                    <a href={spec.url(tags[k])} target="_blank" rel="noreferrer" className="text-zinc-500 hover:text-accent-soft shrink-0">
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  )}
                </div>
              ) : null
            )}
            {extraFields.length > 0 && (
              <>
                <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 pt-2">Other tags</div>
                <div className="grid grid-cols-1 gap-1.5 max-h-56 overflow-auto">
                  {extraFields.map((k) => (
                    <div key={k} className="flex gap-2 items-baseline min-w-0">
                      <span className="text-[10px] text-zinc-500 uppercase w-44 shrink-0 truncate" title={k}>{k}</span>
                      <span className="text-sm text-zinc-200 break-all min-w-0">{tags[k]}</span>
                    </div>
                  ))}
                </div>
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

          <div className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">
              <ShieldCheck className="h-3.5 w-3.5" /> Grading & AUDIT details
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm text-zinc-400">
              <div>Grade <span className={issues.length ? "text-red-300" : "text-emerald-300"}>{issues.length ? `FAILED (${issues.length} check${issues.length === 1 ? "" : "s"})` : "PASS"}</span></div>
              <div>AUDIT <span className="text-zinc-200">{audit ?? "not audited"}</span></div>
              <div>Log score <span className="text-zinc-200">{logGrade != null ? `${logGrade}/100` : "—"}</span></div>
              <div>AccurateRip <span className="text-zinc-200">{arStatus ?? "—"}</span></div>
              <div>Checksum <span className="text-zinc-200">{csStatus ?? "—"}</span></div>
              {["AUDIO_MD5", "INTEGRITY", "LOG_CRC", "REPLAYGAIN_TRACK_GAIN", "DYNAMIC RANGE"].map((k) => (
                tags[k] ? (
                  <div key={k}>{k.replace(/_/g, " ")} <span className="text-zinc-200 break-all">{tags[k]}</span></div>
                ) : null
              ))}
            </div>
            {issues.length > 0 && (
              <>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider mt-3 mb-1">Failed checks</div>
                <ul className="space-y-1">
                  {issues.map((iss, i) => (
                    <li key={i} className="text-xs text-red-300/90 bg-red-950/30 border border-red-900/40 rounded px-2 py-1">{iss}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="bg-card rounded-lg border border-border p-4 space-y-2">
            <div className="flex items-center gap-3">
              {track?.cover_file && (
                <CoverImg albumPath={albumDir} coverFile={track.cover_file} wrapperClass="h-16 w-16 rounded-lg bg-raise border border-border overflow-hidden shrink-0" />
              )}
              <div className="text-xs text-zinc-500 flex-1">
                {track?.cover_file ? `Per-track cover: ${track.cover_file}` : "No per-track cover — the album cover is used."}
              </div>
            </div>
            <input
              ref={coverInput}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && uploadCover(e.target.files[0])}
            />
            <button
              className="btn-ghost !py-1 text-xs w-full"
              onClick={() => coverInput.current?.click()}
              disabled={coverBusy}
              title={`Upload an image saved next to the track as "${fileName.replace(/\.[^.]+$/, "")}.jpg"`}
            >
              <ImageUp className="h-3.5 w-3.5" /> {coverBusy ? "Uploading…" : "Upload per-track cover"}
            </button>
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
    </div>
  );
}
