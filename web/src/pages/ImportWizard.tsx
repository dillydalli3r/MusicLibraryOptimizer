import { useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  UploadCloud, ExternalLink, Check, ChevronLeft, ChevronRight, Search, Wand2, ListMusic,
} from "lucide-react";
import { api } from "../api";
import { toast } from "../store";
import LyricsViewer, { parseLrc } from "../components/LyricsViewer";
import type { MBRelease, MatchSuggestion } from "../types";

const STEPS = ["Upload", "Links", "Match", "Genres", "Lyrics", "Advisory", "Finish"];

export default function ImportWizard() {
  const [params, setParams] = useSearchParams();
  const albumParam = params.get("album");
  const initialAlbum = albumParam ?? null;
  const [step, setStep] = useState(initialAlbum ? 1 : 0);

  const [albumPath, setAlbumPath] = useState<string | null>(initialAlbum);
  const [albumName, setAlbumName] = useState("");
  const [files, setFiles] = useState<{ file: File; relPath: string }[]>([]);
  const [uploading, setUploading] = useState(false);

  const [mbLink, setMbLink] = useState("");
  const [rymLink, setRymLink] = useState("");
  const [mbSearch, setMbSearch] = useState("");
  const [searchHits, setSearchHits] = useState<any[]>([]);
  const [release, setRelease] = useState<MBRelease | null>(null);
  const [releaseId, setReleaseId] = useState("");
  const [suggestions, setSuggestions] = useState<MatchSuggestion[]>([]);
  const [genres, setGenres] = useState<Record<string, string>>({});
  const [genreSource, setGenreSource] = useState<string | null>(null);
  const [advisory, setAdvisory] = useState<Record<string, string>>({});
  const [instrumental, setInstrumental] = useState<Record<string, string>>({});
  const [lyricsDrafts, setLyricsDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();

  const { data: lib } = useQuery({ queryKey: ["library"], queryFn: api.library });

  const trackList = useMemo(() => {
    if (!albumPath || !lib) return [];
    for (const a of lib.artists)
      for (const al of a.albums)
        if (al.path === albumPath) return al.tracks;
    return [];
  }, [albumPath, lib]);

  const defaultTrackName = (p: string) => {
    const base = p.split("/").pop() ?? "";
    return base.replace(/^\d+\s*[-._]\s*/, "").replace(/\.[^.]+$/, "").trim();
  };

  // ---------------- Step 0: upload ----------------
  interface ImportFile {
    file: File;
    relPath: string;
  }

  const ALLOWED = /\.(flac|mp3|m4a|mp4|ogg|opus|wav|aac|cue|log|jpg|jpeg|png|webp|jxl|bmp)$/i;

  const handleFiles = (list: FileList | File[], baseDir = "") => {
    const arr: ImportFile[] = [];
    for (const f of Array.from(list)) {
      const rel = (f as any).webkitRelativePath
        ? (f as any).webkitRelativePath.replace(/\\/g, "/")
        : f.name.replace(/\\/g, "/");
      const full = baseDir ? `${baseDir}/${rel}` : rel;
      if (ALLOWED.test(f.name)) arr.push({ file: f, relPath: full });
    }
    setFiles(arr);
  };

  /** Recursively walk dropped entries (webkitGetAsEntry) to support
   *  dropping a whole album folder, preserving its internal structure. */
  const handleDrop = async (items: DataTransferItemList) => {
    const out: { file: File; relPath: string }[] = [];
    const roots: any[] = [];
    for (const item of Array.from(items)) {
      const entry = item.webkitGetAsEntry?.();
      if (entry) roots.push(entry);
    }
    if (roots.some((r) => r.isDirectory)) {
      for (const root of roots) {
        await walkEntry(root, root.isDirectory ? root.name : "", out);
      }
      const folderName = roots.find((r) => r.isDirectory)?.name;
      if (folderName && !albumName) setAlbumName(folderName);
    } else {
      handleFiles(roots.map((r) => r.file ? r : null).filter(Boolean) as File[], "");
      return;
    }
    setFiles(out.filter((o) => ALLOWED.test(o.file.name)));
  };

  const walkEntry = async (entry: any, prefix: string, out: { file: File; relPath: string }[]) => {
    if (entry.isFile) {
      const f = await new Promise<File>((resolve, reject) => entry.file(resolve, reject));
      out.push({ file: f, relPath: prefix ? `${prefix}/${f.name}` : f.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const entries: any[] = await new Promise((resolve, reject) => {
        const all: any[] = [];
        const readBatch = () =>
          reader.readEntries((batch: any[]) => {
            if (!batch.length) return resolve(all);
            all.push(...batch);
            readBatch();
          }, reject);
        readBatch();
      });
      for (const e of entries) await walkEntry(e, prefix ? `${prefix}/${entry.name}` : entry.name, out);
    }
  };

  const pickFolder = async () => {
    try {
      const inTauri = !!(window as any).__TAURI_INTERNALS__;
      if (inTauri) {
        const { invoke } = await import("@tauri-apps/api/core");
        const picked = await invoke<string | null>("pick_folder");
        if (picked) {
          const dirName = picked.split(/[\\/]/).pop() ?? "Album";
          setAlbumName(dirName);
          setAlbumPath(picked);
          setStep(1);
        }
        return;
      }
      const picker = (window as any).showDirectoryPicker;
      if (!picker) {
        toast("Folder picker unsupported — use the file input or drag & drop");
        return;
      }
      const dir = await picker({ mode: "read" });
      const out: ImportFile[] = [];
      const walk = async (entry: any, prefix: string) => {
        for await (const e of entry.values()) {
          if (e.kind === "file") {
            const f = await e.getFile();
            out.push({ file: f, relPath: prefix ? `${prefix}/${f.name}` : f.name });
          } else if (e.kind === "directory") {
            await walk(e, prefix ? `${prefix}/${e.name}` : e.name);
          }
        }
      };
      await walk(dir, "");
      setAlbumName(dir.name);
      setFiles(out.filter((o) => ALLOWED.test(o.file.name)));
    } catch (e) {
      if ((e as Error).name !== "AbortError") toast(String(e));
    }
  };

  const upload = async () => {
    if (!files.length) return;
    setUploading(true);
    try {
      const res = await api.importUpload(albumName || "New Album", files);
      setAlbumPath(res.album_path);
      setStep(1);
      qc.invalidateQueries({ queryKey: ["library"] });
      toast(`Uploaded ${res.saved.length} file(s)`);
    } catch (e) {
      toast(String(e));
    } finally {
      setUploading(false);
    }
  };

  // ---------------- Step 1: links ----------------
  const doSearch = async () => {
    if (!mbSearch.trim()) return;
    setBusy(true);
    try {
      setSearchHits(await api.mbSearchReleases(mbSearch.trim()));
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const pickRelease = async (id: string) => {
    setBusy(true);
    try {
      const rel = await api.mbRelease(id);
      setRelease(rel);
      setReleaseId(id);
      const matched = await api.mbMatch(albumPath!, id);
      setSuggestions(matched.suggestions);
      const cascade = await api.mbGenres(id);
      const g: Record<string, string> = {};
      const byPos = new Map(cascade.per_track.map((t) => [`${t.disc}-${t.position}`, t.genres.join("; ")]));
      for (const s of matched.suggestions) {
        const m = s.release_track;
        const key = m ? `${m.disc}-${m.position}` : "";
        const found = byPos.get(key) ?? cascade.per_track.find((t) => t.title === m?.title)?.genres.join("; ");
        g[s.local] = found ?? "";
        const src = cascade.per_track.find((t) => t.title === m?.title)?.source;
        if (src) setGenreSource(src);
      }
      setGenres(g);
      toast(`Matched ${matched.suggestions.filter((s) => s.matched).length}/${matched.suggestions.length} tracks`);
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const nextFromLinks = async () => {
    if (!albumPath || !releaseId) {
      toast("Pick a MusicBrainz release first");
      return;
    }
    setBusy(true);
    try {
      await api.importCommit(albumPath.split("/").pop()!, mbLink || `https://musicbrainz.org/release/${releaseId}`, rymLink || undefined);
      toast("Links saved to album");
      setStep(2);
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  // ---------------- Step 2: matching ----------------
  const setSuggestion = (path: string, disc: number, position: number) => {
    const m = release?.media.find((x) => x.disc === disc && x.position === position);
    setSuggestions((ss) => ss.map((s) => (s.local === path ? { ...s, matched: !!m, confidence: 1, release_track: m ?? null } : s)));
  };

  const confirmMatch = async () => {
    setBusy(true);
    try {
      const writes: Record<string, Record<string, string | null>> = {};
      for (const s of suggestions) {
        const t = s.release_track;
        writes[s.local] = {
          MUSICBRAINZ_TRACKID: t?.recording_mbid ?? null,
          MUSICBRAINZ_ARTISTID: t?.artist_mbids?.[0] ?? null,
          TRACKNUMBER: t ? String(t.position).padStart(2, "0") : null,
          DISCNUMBER: t ? String(t.disc) : null,
        };
      }
      await api.mbAssign(writes);
      toast("Track matching saved (MBIDs + track/disc numbers)");
      setStep(3);
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  // ---------------- Step 3: genres ----------------
  const saveGenres = async () => {
    setBusy(true);
    try {
      const writes: Record<string, Record<string, string | null>> = {};
      for (const [p, g] of Object.entries(genres)) writes[p] = { GENRE: g || null };
      await api.mbAssign(writes);
      toast("Genres saved");
      setStep(4);
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  // ---------------- Step 4: lyrics ----------------
  const trackArtist = (p: string) => {
    const t = trackList.find((x) => x.path === p);
    return t?.tags.ARTIST ?? "";
  };
  const trackTitle = (p: string) => {
    const t = trackList.find((x) => x.path === p);
    return t?.tags.TITLE ?? defaultTrackName(p);
  };
  const trackAlbum = trackList[0]?.tags.ALBUM ?? albumName;

  const importLyricsForAll = async () => {
    setBusy(true);
    let done = 0;
    try {
      for (const t of trackList) {
        if (instrumental[t.path] === "1") continue;
        try {
          const res = await api.lyricsGet(trackArtist(t.path), trackTitle(t.path), trackAlbum);
          const lrc = res?.syncedLyrics ?? res?.plainLyrics;
          if (lrc) {
            setLyricsDrafts((d) => ({ ...d, [t.path]: lrc }));
            done++;
          }
        } catch {
          /* per-track skip */
        }
      }
      toast(`Imported lyrics for ${done} track(s)`);
    } finally {
      setBusy(false);
    }
  };

  const saveLyricsStep = async () => {
    setBusy(true);
    try {
      const writes: Record<string, Record<string, string | null>> = {};
      for (const t of trackList) {
        const inst = instrumental[t.path] ?? (t.tags.INSTRUMENTAL === "1" ? "1" : "0");
        writes[t.path] = { INSTRUMENTAL: inst };
        if (inst === "1") continue;
        const lrc = lyricsDrafts[t.path];
        if (lrc && parseLrc(lrc).length) {
          await api.lyricsWrite(t.path, lrc);
        }
      }
      await api.mbAssign(writes);
      toast("Lyrics + INSTRUMENTAL saved");
      setStep(5);
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  // ---------------- Step 5: advisory ----------------
  const saveAdvisory = async () => {
    setBusy(true);
    try {
      const writes: Record<string, Record<string, string | null>> = {};
      for (const t of trackList) {
        writes[t.path] = { ITUNESADVISORY: advisory[t.path] ?? null };
      }
      await api.mbAssign(writes);
      toast("Advisory ratings saved");
      setStep(6);
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const finish = () => {
    qc.invalidateQueries({ queryKey: ["library"] });
    setParams({});
    toast("Import complete — album graded");
  };

  const canNext = step === 0 ? files.length > 0 : step === 1 ? !!releaseId : true;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <UploadCloud className="h-6 w-6 text-accent" /> Import album
        </h1>
        {albumPath && (
          <span className="text-xs text-zinc-500 truncate">
            <Link to={`/album/${encodeURIComponent(albumPath)}`} className="hover:text-accent-soft">
              {albumPath.split("/").pop()}
            </Link>
          </span>
        )}
      </div>

      {/* step indicator */}
      <div className="flex items-center gap-1.5 overflow-x-auto">
        {STEPS.map((s, i) => (
          <div key={s} className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => i < step && setStep(i)}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition-colors ${
                i === step
                  ? "bg-accent text-white"
                  : i < step
                    ? "bg-violet-900/40 text-violet-300 hover:bg-violet-900/60"
                    : "bg-raise text-zinc-500 border border-border"
              }`}
            >
              {i < step ? <Check className="h-3 w-3" /> : <span>{i + 1}</span>}
              {s}
            </button>
            {i < STEPS.length - 1 && <div className="h-px w-3 bg-border" />}
          </div>
        ))}
      </div>

      {/* ---------------- Step 0: upload ---------------- */}
      {step === 0 && (
        <div className="space-y-4">
          <div
            className="rounded-xl border-2 border-dashed border-border bg-card p-12 text-center hover:border-accent/60 transition-colors cursor-pointer"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              handleDrop(e.dataTransfer.items);
            }}
            onClick={() => document.getElementById("import-files")?.click()}
          >
            <UploadCloud className="h-10 w-10 text-zinc-600 mx-auto mb-3" />
            <div className="font-medium text-zinc-300">Drop a whole album folder (or files) here</div>
            <div className="text-xs text-zinc-600 mt-1">
              drop a folder like <b className="text-zinc-500">2024 - Album Name/</b> — cover, .cue, .log and
              multi-disc subfolders are kept · or click to browse
            </div>
            <input id="import-files" type="file" multiple className="hidden" onChange={(e) => e.target.files && handleFiles(e.target.files)} />
          </div>
          <div className="flex items-center gap-3">
            <button className="btn-ghost" onClick={pickFolder}>
              <ListMusic className="h-4 w-4" /> Pick folder…
            </button>
            <input className="input max-w-xs" placeholder="Album folder name (e.g. 2020 - First Album)" value={albumName} onChange={(e) => setAlbumName(e.target.value)} />
          </div>
          {files.length > 0 && (
            <div className="bg-card rounded-lg border border-border p-3 text-sm">
              <div className="font-medium mb-2">{files.length} file(s)</div>
              <div className="max-h-40 overflow-auto text-xs text-zinc-500 grid grid-cols-2 gap-1">
                {files.slice(0, 60).map((f, i) => (
                  <span key={i} className="truncate">{f.relPath}</span>
                ))}
                {files.length > 60 && <span>…{files.length - 60} more</span>}
              </div>
              <button className="btn-primary mt-3" onClick={upload} disabled={uploading}>
                {uploading ? "Uploading…" : `Upload album → ${albumName || "New Album"}`}
              </button>
            </div>
          )}
        </div>
      )}

      {/* ---------------- Step 1: links ---------------- */}
      {step === 1 && (
        <div className="space-y-4">
          <div className="bg-card rounded-lg border border-border p-4 space-y-3">
            <div className="text-sm font-semibold text-zinc-300">MusicBrainz release</div>
            <input className="input" placeholder="MusicBrainz release URL or ID (e.g. https://musicbrainz.org/release/…)" value={mbLink} onChange={(e) => setMbLink(e.target.value)} />
            <div className="text-xs text-zinc-600">or search:</div>
            <div className="flex gap-2">
              <input className="input" placeholder="Search release (title + artist)…" value={mbSearch} onChange={(e) => setMbSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doSearch()} />
              <button className="btn-ghost" onClick={doSearch} disabled={busy}><Search className="h-4 w-4" /></button>
            </div>
            {searchHits.length > 0 && (
              <div className="max-h-48 overflow-auto space-y-1">
                {searchHits.map((h) => (
                  <button key={h.id} className="w-full text-left px-3 py-2 rounded bg-panel hover:bg-raise text-sm flex items-center gap-2"
                    onClick={() => { setMbLink(`https://musicbrainz.org/release/${h.id}`); setReleaseId(h.id); }}>
                    <span className="flex-1 truncate">
                      <span className="text-zinc-200">{h.title}</span>
                      <span className="text-zinc-500"> — {h.artist} ({h.date})</span>
                    </span>
                    {releaseId === h.id && <Check className="h-4 w-4 text-accent" />}
                  </button>
                ))}
              </div>
            )}
            {release && (
              <div className="text-xs text-zinc-400 pt-2 border-t border-border">
                <span className="font-semibold text-zinc-200">{release.title}</span> · {release.artists.map((a) => a.name).join(", ")} · {release.date} · {release.medium_count} disc(s) · {release.media.length} tracks
              </div>
            )}
            <div className="text-sm font-semibold text-zinc-300 pt-2">RateYourMusic album link (optional)</div>
            <input className="input" placeholder="https://rateyourmusic.com/release/…" value={rymLink} onChange={(e) => setRymLink(e.target.value)} />
          </div>
          <button className="btn-primary" onClick={() => pickRelease(releaseId)} disabled={!mbLink || busy}>
            <Wand2 className="h-4 w-4" /> Fetch release & auto-match
          </button>
        </div>
      )}

      {/* ---------------- Step 2: matching ---------------- */}
      {step === 2 && (
        <div className="space-y-3">
          <div className="text-sm text-zinc-400">
            Confirm each local track's MusicBrainz track/disc. Unmatched rows stay blank — you can also fix them manually later on the track page.
          </div>
          {suggestions.length === 0 && <div className="text-xs text-zinc-500">No data — go back and fetch the release.</div>}
          {suggestions.map((s) => (
            <div key={s.local} className="flex items-center gap-3 bg-card rounded-lg border border-border px-3 py-2">
              <span className="text-xs text-zinc-600 w-8">{s.file.split("/").pop()?.slice(0, 2)}</span>
              <span className="flex-1 truncate text-sm">{s.file.split("/").pop()}</span>
              <span className="text-xs text-zinc-500">
                {s.matched ? `${s.release_track!.disc}.${s.release_track!.position} ${s.release_track!.title}` : "no match"}
              </span>
              <select
                className="input !w-auto text-xs"
                value={s.release_track ? `${s.release_track.disc}-${s.release_track.position}` : ""}
                onChange={(e) => {
                  const [d, p] = e.target.value.split("-").map(Number);
                  setSuggestion(s.local, d, p);
                }}
              >
                <option value="">— none —</option>
                {release?.media.map((m) => (
                  <option key={`${m.disc}-${m.position}`} value={`${m.disc}-${m.position}`}>
                    {m.disc}.{m.position} {m.title}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <div className="flex justify-end">
            <button className="btn-primary" onClick={confirmMatch} disabled={busy}>
              Save matching
            </button>
          </div>
        </div>
      )}

      {/* ---------------- Step 3: genres ---------------- */}
      {step === 3 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            Genres auto-imported from {genreSource ?? "MusicBrainz"} (track → release → release-group → artist fallback).
            Edit freely — imported genres stay editable.
          </div>
          {trackList.map((t) => (
            <div key={t.path} className="flex items-center gap-3 bg-card rounded-lg border border-border px-3 py-2">
              <span className="flex-1 truncate text-sm">{t.tags.TITLE ?? defaultTrackName(t.path)}</span>
              <input className="input max-w-sm" placeholder="Genre (semicolon separated)" value={genres[t.path] ?? ""} onChange={(e) => setGenres((g) => ({ ...g, [t.path]: e.target.value }))} />
            </div>
          ))}
          <div className="flex justify-end">
            <button className="btn-primary" onClick={saveGenres} disabled={busy}>Save genres</button>
          </div>
        </div>
      )}

      {/* ---------------- Step 4: lyrics ---------------- */}
      {step === 4 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <button className="btn-primary text-xs" onClick={importLyricsForAll} disabled={busy}>
              <CloudDownloadIcon /> Auto-import from LRCLIB
            </button>
            <span className="text-xs text-zinc-500">Review below — Space stamps time while previewing; INSTRUMENTAL=1 skips lyrics.</span>
          </div>
          {trackList.map((t) => {
            const inst = instrumental[t.path] ?? t.tags.INSTRUMENTAL;
            return (
              <details key={t.path} className="bg-card rounded-lg border border-border open:pb-3">
                <summary className="px-3 py-2 text-sm font-medium cursor-pointer flex items-center gap-2">
                  <span className="flex-1 truncate">{t.tags.TITLE ?? defaultTrackName(t.path)}</span>
                  <label className="flex items-center gap-1.5 text-xs text-zinc-400 select-none" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={inst === "1"}
                      onChange={(e) => setInstrumental((m) => ({ ...m, [t.path]: e.target.checked ? "1" : "0" }))}
                      className="accent-violet-500"
                    />
                    INSTRUMENTAL
                  </label>
                </summary>
                {inst !== "1" ? (
                  <div className="px-3">
                    <LyricsViewer
                      path={t.path}
                      initialLyrics={lyricsDrafts[t.path] ?? ""}
                      onChange={(lrc) => setLyricsDrafts((d) => ({ ...d, [t.path]: lrc }))}
                      artist={trackArtist(t.path)}
                      track={trackTitle(t.path)}
                      album={trackAlbum}
                    />
                  </div>
                ) : (
                  <div className="px-3 text-xs text-zinc-500">Marked instrumental — lyrics skipped.</div>
                )}
              </details>
            );
          })}
          <div className="flex justify-end">
            <button className="btn-primary" onClick={saveLyricsStep} disabled={busy}>Save lyrics & instrumental</button>
          </div>
        </div>
      )}

      {/* ---------------- Step 5: advisory ---------------- */}
      {step === 5 && (
        <div className="space-y-3">
          <div className="text-sm text-zinc-400">Set iTunes advisory per track: <b className="text-zinc-200">0</b> unrated/clean, <b className="text-zinc-200">1</b> explicit, <b className="text-zinc-200">2</b> safe edited version.</div>
          {trackList.map((t) => (
            <div key={t.path} className="flex items-center gap-3 bg-card rounded-lg border border-border px-3 py-2">
              <span className="flex-1 truncate text-sm">{t.tags.TITLE ?? defaultTrackName(t.path)}</span>
              <div className="flex gap-1">
                {["0", "1", "2"].map((v) => (
                  <button
                    key={v}
                    onClick={() => setAdvisory((a) => ({ ...a, [t.path]: v }))}
                    className={`px-3 py-1 rounded text-xs border ${
                      (advisory[t.path] ?? t.tags.ITUNESADVISORY) === v
                        ? "bg-accent text-white border-accent"
                        : "bg-panel text-zinc-400 border-border hover:border-accent/50"
                    }`}
                  >
                    {v === "0" ? "0 · clean" : v === "1" ? "1 · explicit" : "2 · safe"}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <div className="flex justify-end">
            <button className="btn-primary" onClick={saveAdvisory} disabled={busy}>Save advisory</button>
          </div>
        </div>
      )}

      {/* ---------------- Step 6: finish ---------------- */}
      {step === 6 && (
        <div className="bg-card rounded-lg border border-border p-6 text-center">
          <Check className="h-10 w-10 text-emerald-400 mx-auto mb-3" />
          <div className="font-semibold text-lg">Import complete</div>
          <div className="text-sm text-zinc-500 mt-1">
            Links, MBIDs, genres, lyrics and advisory ratings are written to the files.
            Run grading on the album to verify a perfect score.
          </div>
          <div className="flex justify-center gap-2 mt-5">
            {albumPath && (
              <Link to={`/album/${encodeURIComponent(albumPath)}`} className="btn-ghost" onClick={finish}>
                Open album
              </Link>
            )}
            <button className="btn-primary" onClick={finish}>Done</button>
          </div>
        </div>
      )}

      {/* nav buttons */}
      {step > 0 && step < 6 && (
        <div className="flex justify-between pt-2">
          <button className="btn-ghost" onClick={() => setStep(step - 1)}>
            <ChevronLeft className="h-4 w-4" /> Back
          </button>
          <button
            className="btn-primary"
            disabled={!canNext || busy}
            onClick={() => (step === 1 ? nextFromLinks() : step === 2 ? confirmMatch() : step === 3 ? saveGenres() : step === 4 ? saveLyricsStep() : saveAdvisory())}
          >
            {step === 5 ? "Save & finish" : "Continue"} <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}

function CloudDownloadIcon() {
  return <ExternalLink className="h-3.5 w-3.5" />;
}