import { Fragment, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronDown, ChevronRight, CircleAlert, Play, Wand2, Trash2, FolderSync, FolderOpen, BarChart3, ImageUp, Image as ImageIcon, FileVideo, Disc3, CloudDownload, Sparkles, ListPlus, ListStart, ShieldCheck, FileMusic } from "lucide-react";
import { api } from "../api";
import { LinkChips, LinkEditorButton } from "../components/Links";
import { SubtitledVideo } from "../components/SubtitledVideo";
import { EmptyState, MediaChip } from "../components/Badges";
import CoverImg from "../components/CoverImg";
import CoverSearchModal from "../components/CoverSearchModal";
import FavHeart from "../components/FavHeart";
import { trackRef } from "../lib/refs";
import { auditFails } from "../lib/status";
import OverflowMenu from "../components/OverflowMenu";
import StatsPanel from "../components/StatsPanel";
import TrackDetails from "../components/TrackDetails";
import { SortHeader, sortRows, toggleSort, groupByDisc, type SortState } from "../lib/sort.tsx";
import { toast, useStore } from "../store";
import { fmtDuration } from "./LibraryPage";
import type { Track } from "../types";

export default function AlbumPage() {
  const { path = "" } = useParams();
  const decoded = decodeURIComponent(path);
  const { data, isLoading, error } = useQuery({
    queryKey: ["album", decoded],
    queryFn: () => api.album(decoded),
  });
  const { data: coverColor } = useQuery({
    queryKey: ["coverColor", decoded],
    queryFn: () => api.coverColor(decoded),
    retry: false,
  });
  const { playNow, queue, queueAdd, selection, toggleTrack, clearSelection } = useStore();
  const navigate = useNavigate();
  const [sort, setSort] = useState<SortState | null>(null);
  const [statsOpen, setStatsOpen] = useState(false);
  const [detailTrack, setDetailTrack] = useState<Track | null>(null);
  const [videoOpen, setVideoOpen] = useState<string | null>(null);
  const [remuxing, setRemuxing] = useState(false);
  const [coverSearchOpen, setCoverSearchOpen] = useState(false);
  const [beetsBusy, setBeetsBusy] = useState(false);
  const [lyricsBusy, setLyricsBusy] = useState(false);
  const [aiSyncBusy, setAiSyncBusy] = useState(false);
  const [issuesOpen, setIssuesOpen] = useState(false);
  const coverInput = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  // Raw video files (VOB/MKV/...) in this album folder that the remuxer
  // could convert to MP4 — surfaced as a one-click action in the header.
  const { data: videosData, refetch: refetchVideos } = useQuery({
    queryKey: ["videos", decoded],
    queryFn: () => api.videosScan(decoded),
    retry: false,
  });
  const rawVideos = videosData?.videos ?? [];

  const convertVideos = async () => {
    setRemuxing(true);
    try {
      const res = await api.run([11], [decoded]);
      const r = res.results?.[0];
      if (r?.error) toast(`Remux failed: ${r.error}`);
      else toast(`Remuxed ${r?.stats?.converted ?? 0} video(s) to MKV`);
      qc.invalidateQueries({ queryKey: ["videos", decoded] });
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["album", decoded] });
      refetchVideos();
    } catch (e) {
      toast(String(e));
    } finally {
      setRemuxing(false);
    }
  };

  const uploadCover = async (file: File) => {
    try {
      const r = await api.cover(decoded, file);
      toast(r.ok ? `Cover saved as ${r.path.split("/").pop()}` : "Cover upload failed");
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["coverColor", decoded] });
      qc.invalidateQueries({ queryKey: ["album", decoded] });
    } catch (e) {
      toast(String(e));
    } finally {
      if (coverInput.current) coverInput.current.value = "";
    }
  };

  if (error) return <EmptyState title="Album not found" hint={String(error)} />;
  if (isLoading || !data) return <div className="p-8 text-zinc-500">Loading album…</div>;

  const tracks = sortRows(data.tracks, sort);
  // One condensed verdict: grading problems OR a FAKE/Mix audit → FAIL.
  const verdictPass = !!data.pass && !auditFails(data.audit_summary);
  const issueEntries = Object.entries(data.issues ?? {});
  const verdictTrack = (tr: Track) => !!tr.grade_pass && !auditFails(tr.audit);

  const runScripts = async (ids: number[]) => {
    await api.run(ids, [data.path]);
    qc.invalidateQueries({ queryKey: ["library"] });
  };

  // Tracks of THIS album that are ticked in the global selection.
  const selectedHere = data.tracks.filter((t) => selection.tracks.includes(t.path));

  const queueTracks = data.tracks.map((t) => ({
    path: t.path, file: t.file, albumPath: data.path,
    artist: data.meta?.ALBUMARTIST ?? data.meta?.ARTIST ?? undefined,
    album: data.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
  }));

  /** Append the album to the queue; an empty queue just starts playing. */
  const enqueue = (position: "next" | "end") => {
    if (!queue.length) {
      playNow(queueTracks);
      return;
    }
    queueAdd(queueTracks, position);
    toast(position === "next" ? `Playing ${queueTracks.length} track(s) next` : `Added ${queueTracks.length} track(s) to the queue`);
  };

  const playSelection = () => {
    if (!selectedHere.length) return;
    playNow(
      selectedHere.map((t) => ({
        path: t.path, file: t.file, albumPath: data.path,
        artist: data.meta?.ALBUMARTIST ?? data.meta?.ARTIST ?? undefined,
        album: data.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
      }))
    );
  };

  const addSelectionToPlaylist = async () => {
    if (!selectedHere.length) return;
    const pls = await api.playlists();
    const manual = pls.find((p) => p.kind === "manual");
    const target = manual ?? (await api.createPlaylist("Library selection", "manual"));
    await api.playlistAdd(target.id, selectedHere.map((t) => t.path));
    toast(`Added ${selectedHere.length} track(s) to playlist`);
  };

  /** Pull the top-voted MusicBrainz genres (count from Settings → Import)
   * onto every track of this album, using the linked MB release. */
  const importGenres = async () => {
    try {
      const r = await api.mbGenresWrite(data.tracks.map((t) => t.path));
      toast(r.updated
        ? `Imported ${r.genres.join(", ") || "genres"} on ${r.updated} track(s)${r.per_track ? " (per-track where available)" : ""}`
        : "No genres found on the linked MusicBrainz release");
      qc.invalidateQueries({ queryKey: ["album", decoded] });
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    }
  };

  /** Browse/download the raw file or a transcoded export of this album's
   * tracks — handled per-track from the track page & details panel. */

  const removeAlbum = async () => {
    if (!window.confirm(`Remove "${data.meta?.ALBUM ?? data.path.split("/").pop()}" from the library?\nIt moves to .mlo_trash in your music folder (recoverable).`)) return;
    try {
      await api.removeAlbum(data.path);
      toast("Album moved to trash");
      qc.invalidateQueries({ queryKey: ["library"] });
      navigate("/");
    } catch (e) {
      toast(String(e));
    }
  };

  const organizeAlbum = async () => {
    if (!window.confirm("Organize this album with the naming script from Settings?\nFiles are MOVED into the scripted folder structure.")) return;
    try {
      const r = await api.organize([data.path]);
      const res = r.results[0];
      if (res.error) {
        toast(`Organize failed: ${res.error}`);
        return;
      }
      toast(`Organized — ${res.moved} file(s) moved, ${res.leftovers} sidecar(s)`);
      qc.invalidateQueries({ queryKey: ["library"] });
      navigate("/");
    } catch (e) {
      toast(String(e));
    }
  };

  const beetsTagAlbum = async () => {
    if (!window.confirm("Tag this album with beets (MusicBrainz match + Picard-parity plugin)?\nFiles are moved into the scripted folder structure.")) return;
    setBeetsBusy(true);
    try {
      const r = await api.beetsImport([data.path]);
      toast(`Beets import done${r.organized ? " (re-organized)" : ""}`);
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["album", decoded] });
      qc.invalidateQueries({ queryKey: ["coverColor", decoded] });
    } catch (e) {
      toast(String(e));
    } finally {
      setBeetsBusy(false);
    }
  };

  /** Download missing lyrics from LRCLIB for every track in this album,
   * writing per the global lyrics_format (EMBEDDED / LRC / BOTH). */
  const downloadLyricsAlbum = async () => {
    setLyricsBusy(true);
    try {
      const cfg = await api.config();
      const fmt = String(cfg.lyrics_format ?? "EMBEDDED").toUpperCase();
      let fetched = 0;
      let skipped = 0;
      let missing = 0;
      for (const t of data.tracks) {
        if (t.tags.INSTRUMENTAL === "1" || t.lyrics_present) {
          skipped++;
          continue;
        }
        const artist = t.tags.ARTIST || data.meta?.ALBUMARTIST || data.meta?.ARTIST || undefined;
        const title = t.tags.TITLE;
        if (!artist || !title) {
          skipped++;
          continue;
        }
        try {
          const res = await api.lyricsGet(artist, title, (t.tags.ALBUM ?? data.meta?.ALBUM) || undefined, t.tech?.length ? Math.round(t.tech.length) : undefined);
          const lrc = res?.syncedLyrics ?? res?.plainLyrics;
          if (!lrc) {
            missing++;
          } else {
            if (fmt === "LRC" || fmt === "BOTH") await api.lyricsWrite(t.path, lrc);
            if (fmt === "EMBEDDED" || fmt === "BOTH") await api.lyricsEmbed(t.path, lrc);
            fetched++;
          }
        } catch {
          missing++;
        }
        await new Promise((r) => setTimeout(r, 350)); // LRCLIB rate-limit pacing
      }
      toast(`Lyrics: ${fetched} downloaded · ${skipped} skipped · ${missing} not found`);
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["album", decoded] });
    } catch (e) {
      toast(String(e));
    } finally {
      setLyricsBusy(false);
    }
  };

  /** AI detect & sync for the whole album: existing lyrics are re-aligned /
   * upgraded to ELRC, missing ones are fetched — writes per lyrics_format. */
  const aiSyncLyricsAlbum = async () => {
    const targets = data.tracks.filter((t) => t.tags.INSTRUMENTAL !== "1");
    if (!targets.length) return;
    if (!window.confirm(`AI detect & sync lyrics for all ${targets.length} track(s)?\nExisting lyrics are re-aligned / word-synced; missing lyrics are fetched.`)) return;
    setAiSyncBusy(true);
    try {
      const cfg = await api.config();
      const fmt = String(cfg.lyrics_format ?? "EMBEDDED").toUpperCase();
      let done = 0;
      let failed = 0;
      for (const t of targets) {
        try {
          const res = await api.lyricsAiSync(t.path);
          if (res.lrc?.trim()) {
            if (fmt === "LRC" || fmt === "BOTH") await api.lyricsWrite(t.path, res.lrc);
            if (fmt === "EMBEDDED" || fmt === "BOTH") await api.lyricsEmbed(t.path, res.lrc);
            done++;
          } else {
            failed++;
          }
        } catch {
          failed++;
        }
      }
      toast(`AI lyrics: ${done} synced${failed ? ` · ${failed} unavailable` : ""}`);
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["album", decoded] });
    } finally {
      setAiSyncBusy(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div
        className="rounded-xl p-5 border border-border relative overflow-hidden"
        style={
          coverColor
            ? { background: `linear-gradient(135deg, ${coverColor}33 0%, transparent 60%)` }
            : undefined
        }
      >
        <div className="flex items-start gap-5">
          <div className="shrink-0 relative group/cover">
            <CoverImg
              albumPath={data.path}
              coverFile={data.cover_file}
              wrapperClass="h-40 w-40 rounded-lg border border-border bg-raise overflow-hidden"
            />
            <input
              ref={coverInput}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && uploadCover(e.target.files[0])}
            />
            {/* small square menu over the cover: upload / find online */}
            <div className="absolute top-1.5 right-1.5 opacity-0 group-hover/cover:opacity-100 transition-opacity">
              <OverflowMenu
                buttonClass="!p-1.5 bg-black/60 hover:bg-black/80 border border-white/10 text-zinc-200"
                buttonTitle="Cover art actions"
                sections={[
                  {
                    items: [
                      { label: "Upload cover…", icon: ImageUp, onClick: () => coverInput.current?.click() },
                      { label: "Find cover online", icon: ImageIcon, onClick: () => setCoverSearchOpen(true) },
                    ],
                  },
                ]}
              />
            </div>
          </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-zinc-500 uppercase tracking-wider">{data.meta?.DATE ?? "—"}</div>
          <div className="flex items-center gap-2 min-w-0">
            {/* verdict dot (replaces the old PASS/FAIL badge) — click for the problems */}
            <button
              className={`h-2.5 w-2.5 rounded-full shrink-0 ${verdictPass ? "bg-emerald-400" : "bg-red-500"}`}
              title={verdictPass ? `Pass — ${data.grade_pct ?? "?"}% of checks` : `Fail — ${data.grade_pct ?? "?"}% · ${issueEntries.length} problem type(s)`}
              onClick={() => setIssuesOpen(!issuesOpen)}
            />
            <h1 className="text-3xl font-bold tracking-tight truncate">{data.meta?.ALBUM ?? data.path.split("/").pop()}</h1>
            <FavHeart kind="album" id={data.path} mbid={data.meta?.MUSICBRAINZ_ALBUMID} />
          </div>
          <div className="text-zinc-400 mt-1">{data.meta?.ALBUMARTIST ?? data.meta?.ARTIST ?? "—"}</div>
          {(data.meta?.LABEL || data.meta?.CATALOGNUMBER) && (
            <div className="text-xs text-zinc-500 mt-0.5 truncate">
              {[data.meta?.LABEL, data.meta?.CATALOGNUMBER].filter(Boolean).join(" · ")}
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <MediaChip media={data.media} />
            <span className="chip bg-zinc-800 text-zinc-400 border border-border">
              {data.pass_count}/{data.total_checks} checks
            </span>
            <span className="chip bg-zinc-800 text-zinc-400 border border-border">
              AR {data.accuraterip_status || "—"} · CS {data.checksum_status || "—"}
            </span>
            <span className="chip bg-zinc-800 text-zinc-400 border border-border">
              CUE {data.has_cue ? "yes" : "no"} · LOG {data.has_log ? "yes" : "no"}
            </span>
          </div>
          {issueEntries.length > 0 && (
            <div className="mt-2.5">
              <button
                className="inline-flex items-center gap-1.5 text-xs text-red-300/90 hover:text-red-200"
                onClick={() => setIssuesOpen(!issuesOpen)}
              >
                <CircleAlert className="h-3.5 w-3.5" />
                {issueEntries.length} problem{issueEntries.length === 1 ? "" : "s"} to fix
                {issuesOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              </button>
              {issuesOpen && (
                <div className="mt-1.5 max-w-3xl rounded-lg border border-red-900/40 bg-red-950/20 p-1.5 space-y-0.5">
                  {issueEntries.map(([text, files]) => (
                    <div key={text} className="rounded-md px-2 py-1.5 hover:bg-red-950/40">
                      <div className="text-xs text-red-200 flex items-start gap-1.5">
                        <CircleAlert className="h-3 w-3 mt-0.5 shrink-0 text-red-400" />
                        <span>{text}</span>
                        <span className="ml-auto text-[10px] text-zinc-500 shrink-0">{files.length === 1 && files[0] === "album" ? "whole album" : `${files.length} file(s)`}</span>
                      </div>
                      {files[0] !== "album" && (
                        <div className="text-[10px] text-zinc-500 mt-0.5 pl-[18px]">
                          {files.length > 6 ? `${files.slice(0, 6).join(" · ")} · +${files.length - 6} more` : files.join(" · ")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
            <LinkChips tags={(data.meta ?? {}) as Record<string, unknown>} />
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <LinkEditorButton
            mode="album"
            paths={data.tracks.map((t) => t.path)}
            current={(data.meta ?? {}) as Record<string, unknown>}
          />
          <button
            className="btn-primary"
            onClick={() => playNow(queueTracks)}
            title="Play the album from the top"
          >
            <Play className="h-4 w-4 fill-current" /> Play album
          </button>
          <OverflowMenu
            buttonTitle="All album actions"
            sections={[
              {
                items: [
                  { label: "Play next", icon: ListStart, onClick: () => enqueue("next") },
                  { label: "Add to queue", icon: ListPlus, onClick: () => enqueue("end") },
                ],
              },
              {
                title: "Album",
                items: [
                  { label: "Import & link", icon: Wand2, onClick: () => navigate(`/import?album=${encodeURIComponent(data.path)}`) },
                  { label: "Organize (naming script)", icon: FolderSync, onClick: organizeAlbum },
                  { label: "Open folder", icon: FolderOpen, onClick: async () => { try { await api.openFolder(data.path); } catch (e) { toast(String(e)); } } },
                  { label: "Stats", icon: BarChart3, onClick: () => setStatsOpen(true) },
                ],
              },
              {
                title: "Lyrics",
                items: [
                  { label: lyricsBusy ? "Fetching…" : "Download missing (LRCLIB)", icon: CloudDownload, onClick: downloadLyricsAlbum, disabled: lyricsBusy },
                  { label: aiSyncBusy ? "Syncing…" : "AI detect & sync", icon: Sparkles, onClick: aiSyncLyricsAlbum, disabled: aiSyncBusy },
                ],
              },
              {
                title: "Tags & scripts",
                items: [
                  { label: beetsBusy ? "Beets…" : "Tag with beets", icon: Disc3, onClick: beetsTagAlbum, disabled: beetsBusy },
                  { label: "Import genres (MusicBrainz)", icon: Sparkles, onClick: importGenres },
                  { label: "Format lyrics", icon: FileMusic, onClick: () => runScripts([1]) },
                  { label: "Format CUEs", icon: FileMusic, onClick: () => runScripts([2]) },
                  { label: "Optimize FLACs", icon: FileMusic, onClick: () => runScripts([3]) },
                  { label: "Process images", icon: FileMusic, onClick: () => runScripts([5]) },
                  { label: "Audit", icon: ShieldCheck, onClick: () => runScripts([6]) },
                  { label: "DR & ReplayGain", icon: FileMusic, onClick: () => runScripts([7]) },
                  { label: "Auto tagging", icon: FileMusic, onClick: () => runScripts([8]) },
                  { label: "Grade", icon: FileMusic, onClick: () => runScripts([4]) },
                  { label: "Remux videos", icon: FileVideo, hidden: rawVideos.length === 0, onClick: convertVideos, disabled: remuxing },
                ],
              },
              {
                items: [
                  { label: "Remove album (to trash)", icon: Trash2, danger: true, onClick: removeAlbum },
                ],
              },
            ]}
          />
        </div>
        </div>
      </div>

      {statsOpen && (
        <StatsPanel
          title={data.meta?.ALBUM ?? data.path.split("/").pop() ?? "album"}
          albums={[data]}
          tracks={data.tracks}
          onClose={() => setStatsOpen(false)}
        />
      )}

      {detailTrack && (
        <TrackDetails track={detailTrack} albumPath={data.path} onClose={() => setDetailTrack(null)} />
      )}

      {videoOpen && (
        <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-6" onClick={() => setVideoOpen(null)}>
          <div className="w-full max-w-4xl" onClick={(e) => e.stopPropagation()}>
            <SubtitledVideo path={videoOpen} className="w-full max-h-[80vh] rounded-lg border border-border bg-black" />
            <div className="flex justify-end mt-2">
              <button className="btn-ghost !py-1" onClick={() => setVideoOpen(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {selectedHere.length > 0 && (
        <div className="flex items-center gap-2 bg-accent/15 border border-accent/40 rounded-lg px-3 py-2 flex-wrap">
          <span className="text-xs font-medium text-accent-soft">
            {selectedHere.length} track{selectedHere.length === 1 ? "" : "s"} selected
          </span>
          <div className="ml-auto flex gap-1.5 flex-wrap">
            <button className="btn-primary !py-1 text-xs" onClick={playSelection}>
              <Play className="h-3.5 w-3.5" /> Play selection
            </button>
            <button className="btn-ghost !py-1 text-xs" onClick={addSelectionToPlaylist}>
              Playlist
            </button>
            <button className="btn-ghost !py-1 text-xs" onClick={() => clearSelection()}>
              Clear
            </button>
          </div>
        </div>
      )}

      <div className="bg-card rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-panel/60">
            <tr>
              <th className="th w-12" title="Play from here"></th>
              <th className="th w-10"></th>
              <SortHeader label="#" sort={sort} sortKey="tracknumber" onSort={(k) => setSort(toggleSort(sort, k))} className="w-14" />
              <th className="th w-10"></th>
              <SortHeader label="Title" sort={sort} sortKey="tags.TITLE" onSort={(k) => setSort(toggleSort(sort, k))} />
              <SortHeader label="Genre" sort={sort} sortKey="tags.GENRE" onSort={(k) => setSort(toggleSort(sort, k))} />
              <SortHeader label="Dur" sort={sort} sortKey="tech.length" onSort={(k) => setSort(toggleSort(sort, k))} />
              <SortHeader label="Bitrate" sort={sort} sortKey="tech.bitrate" onSort={(k) => setSort(toggleSort(sort, k))} />
            </tr>
          </thead>
          <tbody>
            {(() => {
              const groups = groupByDisc(tracks);
              const multiDisc = groups.length > 1;
              return groups.map((g) => (
                <Fragment key={g.disc ?? 0}>
                  {multiDisc && (
                    <tr className="bg-panel/60">
                      <td colSpan={8} className="td text-[10px] uppercase tracking-wider text-zinc-500">
                        Disc {g.disc ?? "?"}
                      </td>
                    </tr>
                  )}
                  {g.tracks.map((tr) => (
              <tr
                key={tr.path}
                className="table-row group cursor-pointer"
                title="Click to play"
                onClick={() =>
                  playNow(
                    data.tracks.map((t) => ({
                      path: t.path, file: t.file, albumPath: data.path,
                      artist: data.meta?.ALBUMARTIST ?? data.meta?.ARTIST ?? undefined,
                      album: data.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
                    })),
                    data.tracks.findIndex((t) => t.path === tr.path)
                  )
                }
              >
                <td className="td" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      className="btn-ghost !px-2 !py-1"
                      title="Play from here"
                      onClick={() =>
                        playNow(
                          data.tracks.map((t) => ({
                            path: t.path, file: t.file, albumPath: data.path,
                            artist: data.meta?.ALBUMARTIST ?? data.meta?.ARTIST ?? undefined,
                            album: data.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
                          })),
                          data.tracks.findIndex((t) => t.path === tr.path)
                        )
                      }
                    >
                      <Play className="h-3.5 w-3.5" />
                    </button>
                    {tr.file.toLowerCase().endsWith(".mp4") && (
                      <button
                        className="btn-ghost !px-2 !py-1"
                        title="Watch music video"
                        onClick={() => setVideoOpen(tr.path)}
                      >
                        <FileVideo className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </td>
                <td className="td pr-0" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selection.tracks.includes(tr.path)}
                    onChange={() => toggleTrack(tr.path)}
                  />
                </td>
                <td className="td text-zinc-500">
                  <div className="flex items-center gap-1.5">
                    <span className="tabular-nums">{tr.tracknumber ?? tr.tags.TRACKNUMBER ?? "—"}</span>
                    {multiDisc && (
                      <span className="text-[9px] text-zinc-600 uppercase tracking-wide">cd{g.disc ?? "?"}</span>
                    )}
                    {/* verdict dot — click for grading & audit details */}
                    <button
                      className={`h-2 w-2 rounded-full shrink-0 ${verdictTrack(tr) ? "bg-emerald-400/80" : "bg-red-500"}`}
                      title={verdictTrack(tr) ? "Pass" : "Fail — grading & audit details"}
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailTrack(tr);
                      }}
                    />
                  </div>
                </td>
                <td className="td pr-0">
                  {tr.cover_file && (
                    <CoverImg
                      albumPath={data.path}
                      coverFile={tr.cover_file}
                      wrapperClass="h-7 w-7 rounded bg-raise border border-border overflow-hidden shrink-0"
                    />
                  )}
                </td>
                <td className="td">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <Link
                      to={trackRef(tr)}
                      className="hover:text-accent-soft truncate inline-block max-w-full"
                      title="Click to play · Ctrl-click to open track page"
                      onClick={(e) => {
                        if (e.ctrlKey || e.metaKey || e.shiftKey) e.stopPropagation();
                        else e.preventDefault();
                      }}
                    >
                      {tr.tags.TITLE ?? tr.file}
                    </Link>
                    <span className="opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                      <FavHeart kind="track" id={tr.path} mbid={tr.tags.MUSICBRAINZ_TRACKID} iconClass="h-3.5 w-3.5" title={undefined} />
                    </span>
                    {!!tr.issues?.length && (
                      <span className="text-[9px] text-red-400 shrink-0" title={tr.issues.join("\n")}>
                        {tr.issues.length}✗
                      </span>
                    )}
                  </div>
                </td>
                <td className="td text-zinc-500 max-w-[180px] truncate">{tr.tags.GENRE ?? "—"}</td>
                <td className="td text-zinc-500">{fmtDuration(tr.tech.length)}</td>
                <td className="td text-zinc-500">
                  {tr.tech.bitrate ? `${(tr.tech as any).codec ? (tr.tech as any).codec + " · " : ""}${Math.round(tr.tech.bitrate / 1000)} kbps` : "—"}
                  {tr.tech.bits_per_sample ? ` · ${Math.round(tr.tech.bits_per_sample)} bit` : ""}
                  {tr.tech.sample_rate ? ` · ${(tr.tech.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz` : ""}
                </td>
              </tr>
                  ))}
                </Fragment>
              ));
            })()}
          </tbody>
        </table>
      </div>

      {coverSearchOpen && (
        <CoverSearchModal
          albumPath={data.path}
          artist={data.meta?.ALBUMARTIST ?? data.meta?.ARTIST ?? ""}
          album={data.meta?.ALBUM ?? ""}
          onClose={() => setCoverSearchOpen(false)}
          onApplied={() => {
            qc.invalidateQueries({ queryKey: ["library"] });
            qc.invalidateQueries({ queryKey: ["coverColor", decoded] });
            qc.invalidateQueries({ queryKey: ["album", decoded] });
          }}
        />
      )}
    </div>
  );
}