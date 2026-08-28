import { useEffect, useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  UploadCloud, ExternalLink, Check, ChevronLeft, ChevronRight, Search, Wand2,
  ListMusic, Plus, Trash2, Disc3, FolderOpen,
} from "lucide-react";
import { api } from "../api";
import { toast } from "../store";
import LyricsViewer, { parseLrc } from "../components/LyricsViewer";
import type { MBRelease, MatchSuggestion } from "../types";

const STEPS = ["Select & separate", "Links", "Match", "Genres", "Lyrics", "Advisory", "Finish"];

// Everything the importer accepts: audio, all common image formats, and the
// sidecars the optimizer understands (.lrc, .cue, .log, .accurip).
const ALLOWED = /\.(flac|mp3|m4a|mp4|ogg|opus|wav|aac|wv|ape|alac|aiff|aif|dsf|dff|mka)$|\.(jpg|jpeg|png|webp|bmp|gif|tiff|tif|avif|heic|heif|jxl|svg)$|\.(lrc|cue|log|accurip)$/i;
const AUDIO_RE = /\.(flac|mp3|m4a|mp4|ogg|opus|wav|aac|wv|ape|alac|aiff|aif|dsf|dff|mka)$/i;
const DISC_RE = /^(cd|disc|disk)\s*\d+$/i;

interface ImportFile {
  file: File | null; // null = native pick (already on disk)
  relPath: string;
}

interface AlbumGroup {
  name: string;
  root: string; // rel path of the album dir under the drop/native root ("" = root itself)
  files: ImportFile[];
}

function dirOf(relPath: string): string {
  const i = relPath.lastIndexOf("/");
  return i === -1 ? "" : relPath.slice(0, i);
}

function baseName(p: string): string {
  const parts = p.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

/** Extract a MusicBrainz ID from an ID or a musicbrainz.org URL. */
function extractMbid(value: string): string | null {
  const m = value.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  return m ? m[0].toLowerCase() : null;
}

/** Detect album boundaries inside an import set.
 *  An album = any dir with immediate audio children (disc-like dirs such as
 *  CD1/Disc 2 merge into their parent). Group names fall back to
 *  "Parent - Album" when albums sit inside artist folders. */
function detectAlbums(imports: ImportFile[], fallbackName: string): AlbumGroup[] {
  const audio = imports.filter((f) => AUDIO_RE.test(f.relPath));
  if (!audio.length) {
    return [{ name: fallbackName || "New Album", root: "", files: [...imports] }];
  }
  const dirsWithAudio = new Set(audio.map((f) => dirOf(f.relPath)));

  const isDiscDir = (d: string) => d !== "" && DISC_RE.test(baseName(d));
  const roots = new Set<string>();
  for (const d of dirsWithAudio) {
    if (!d) {
      roots.add("");
      continue;
    }
    if (isDiscDir(d)) {
      const parent = dirOf(d);
      const siblings = [...dirsWithAudio].filter((x) => x && dirOf(x) === parent);
      if (siblings.length && siblings.every((s) => isDiscDir(s))) {
        roots.add(parent || "");
      } else {
        roots.add(d);
      }
    } else {
      roots.add(d);
    }
  }
  if (!roots.size) roots.add("");

  const ordered = [...roots].sort((a, b) => {
    const da = a ? a.split("/").length : 0;
    const db = b ? b.split("/").length : 0;
    return da - db || a.localeCompare(b);
  });

  // The wrapper folder the user dropped/picked (e.g. "Rips/"). Albums sitting
  // directly inside it are named by their own folder only.
  const firstSeg = imports[0]?.relPath.split("/")[0] ?? "";
  const allShare = imports.every((f) => f.relPath.split("/")[0] === firstSeg);
  const dropRoot = firstSeg && allShare ? firstSeg : "";

  const nameFor = (d: string): string => {
    if (!d) return fallbackName || "New Album";
    const parent = dirOf(d);
    const base = baseName(d);
    if (!parent || parent === dropRoot) return base;
    return `${baseName(parent)} - ${base}`;
  };

  const groups = new Map<string, ImportFile[]>();
  const rootsDeep = [...roots].sort((a, b) => b.split("/").length - a.split("/").length);
  for (const f of imports) {
    const fd = dirOf(f.relPath);
    const root = rootsDeep.find((r) => r === "" || fd === r || fd.startsWith(`${r}/`)) ?? ordered[0];
    if (!groups.has(root)) groups.set(root, []);
    groups.get(root)!.push(f);
  }

  return ordered.map((r) => ({
    name: nameFor(r),
    root: r,
    files: groups.get(r) ?? [],
  }));
}

export default function ImportWizard() {
  const [params, setParams] = useSearchParams();
  const albumParam = params.get("album");
  const initialAlbum = albumParam ?? null;
  const [step, setStep] = useState(initialAlbum ? 1 : 0);

  const [albumPath, setAlbumPath] = useState<string | null>(initialAlbum);
  const [albumName, setAlbumName] = useState("");
  const [source, setSource] = useState<"web" | "native">("web");
  const [nativeRoot, setNativeRoot] = useState<string | null>(null);
  const [albums, setAlbums] = useState<AlbumGroup[]>([]);
  const [uploaded, setUploaded] = useState<{ name: string; path: string }[]>([]);
  const [albumIndex, setAlbumIndex] = useState(0);
  const [uploading, setUploading] = useState(false);

  const [mbLink, setMbLink] = useState("");
  const [rymLink, setRymLink] = useState("");
  const [rymValid, setRymValid] = useState<boolean | null>(null);
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

  // Auto-recognize a pasted MusicBrainz release URL/ID.
  useEffect(() => {
    const id = extractMbid(mbLink);
    if (id && id !== releaseId) setReleaseId(id);
  }, [mbLink, releaseId]);

  // Debounced RYM link validation.
  useEffect(() => {
    if (!rymLink.trim()) {
      setRymValid(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = await api.rymValidate(rymLink.trim());
        setRymValid(r.valid);
      } catch {
        setRymValid(false);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [rymLink]);

  const defaultTrackName = (p: string) => {
    const base = p.split("/").pop() ?? "";
    return base.replace(/^\d+\s*[-._]\s*/, "").replace(/\.[^.]+$/, "").trim();
  };

  const currentAlbumName = uploaded[albumIndex]?.name ?? albumPath?.split("/").pop() ?? "";

  // ---------------- Step 0: selection + separation ----------------
  const adoptImports = (list: ImportFile[], fallback: string) => {
    if (list.length && fallback && !albumName) setAlbumName(fallback);
    setAlbums(detectAlbums(list, fallback || albumName || "New Album"));
  };

  const handleFiles = (list: FileList | File[]) => {
    const arr: ImportFile[] = [];
    for (const f of Array.from(list)) {
      const rel = (f as any).webkitRelativePath
        ? (f as any).webkitRelativePath.replace(/\\/g, "/")
        : f.name.replace(/\\/g, "/");
      if (ALLOWED.test(rel)) arr.push({ file: f, relPath: rel });
    }
    adoptImports(arr, arr[0]?.relPath.split("/")[0] ?? "");
  };

  const walkEntry = async (entry: any, prefix: string, out: ImportFile[]) => {
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

  const handleDrop = async (items: DataTransferItemList) => {
    const out: ImportFile[] = [];
    const roots: any[] = [];
    for (const item of Array.from(items)) {
      const entry = item.webkitGetAsEntry?.();
      if (entry) roots.push(entry);
    }
    if (roots.some((r) => r.isDirectory)) {
      for (const root of roots) {
        await walkEntry(root, root.isDirectory ? root.name : "", out);
      }
      adoptImports(out.filter((o) => ALLOWED.test(o.relPath)), roots.find((r) => r.isDirectory)?.name ?? "");
    } else {
      const files = roots.filter((r) => r.isFile).map((r) => r.file) as File[];
      handleFiles(files);
    }
  };

  const pickFolderBrowser = async () => {
    try {
      // Preferred: File System Access API (Chromium/Edge).
      const picker = (window as any).showDirectoryPicker;
      if (picker) {
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
        adoptImports(out.filter((o) => ALLOWED.test(o.relPath)), dir.name || "");
        return;
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") toast(String(e));
      return;
    }
    // Fallback: webkitdirectory input (Chrome/Edge/Firefox/WebView2).
    document.getElementById("import-folder")?.click();
  };

  const pickFolderNative = async () => {
    const inTauri = !!(window as any).__TAURI_INTERNALS__;
    if (!inTauri) {
      toast("The native picker is only available in the desktop app — use 'Pick folder' instead");
      return;
    }
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const picked = await invoke<string | null>("pick_folder");
      if (!picked) return;
      const scan = await api.importScan(picked);
      setSource("native");
      setNativeRoot(picked);
      const list: ImportFile[] = scan.files
        .filter((f) => ALLOWED.test(f.relPath))
        .map((f) => ({ file: null, relPath: f.relPath }));
      adoptImports(list, picked.split(/[\\/]/).pop() ?? "");
    } catch (e) {
      toast(String(e));
    }
  };

  const renameGroup = (i: number, name: string) =>
    setAlbums((gs) => gs.map((g, j) => (j === i ? { ...g, name } : g)));

  const moveFile = (from: number, to: number, f: ImportFile) => {
    if (from === to) return;
    setAlbums((gs) =>
      gs.map((g, i) => {
        if (i === from) return { ...g, files: g.files.filter((x) => x !== f) };
        if (i === to) return { ...g, files: [...g.files, f] };
        return g;
      })
    );
  };

  const addAlbum = () =>
    setAlbums((gs) => [...gs, { name: `Album ${gs.length + 1}`, root: "", files: [] }]);

  const removeAlbum = (i: number) => {
    setAlbums((gs) => {
      if (gs.length <= 1) return gs;
      const removed = gs[i];
      const rest = gs.filter((_, j) => j !== i);
      if (removed.files.length) {
        rest[0] = { ...rest[0], files: [...removed.files, ...rest[0].files] };
      }
      return rest;
    });
  };

  const doImport = async () => {
    const groups = albums.filter((g) => g.name.trim() && g.files.length);
    if (!groups.length) {
      toast("Nothing to import — add files first");
      return;
    }
    setUploading(true);
    try {
      const results: { name: string; path: string }[] = [];
      for (const g of groups) {
        const name = g.name.trim();
        if (source === "web") {
          const filesToSend = g.files.filter((f) => f.file) as { file: File; relPath: string }[];
          if (!filesToSend.length) continue;
          const res = await api.importUpload(name, filesToSend);
          results.push({ name, path: res.album_path });
        } else {
          const src = nativeRoot ? (g.root ? `${nativeRoot}/${g.root}` : nativeRoot) : "";
          if (!src) continue;
          const res = await api.importIngest(src, name);
          results.push({ name, path: res.path });
        }
      }
      if (!results.length) {
        toast("Nothing to import");
        return;
      }
      setUploaded(results);
      setAlbumIndex(0);
      setAlbumPath(results[0].path);
      setStep(1);
      qc.invalidateQueries({ queryKey: ["library"] });
      toast(`Imported ${results.length} album${results.length > 1 ? "s" : ""}`);
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
    const rid = releaseId || extractMbid(mbLink) || "";
    if (!albumPath || !rid) {
      toast("Enter a valid MusicBrainz release URL or ID first");
      return;
    }
    setBusy(true);
    try {
      await api.importCommit(currentAlbumName, mbLink || `https://musicbrainz.org/release/${rid}`, rymValid ? rymLink : undefined);
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
  const trackAlbum = trackList[0]?.tags.ALBUM ?? currentAlbumName;

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
    toast(uploaded.length > 1 ? `Imported ${uploaded.length} albums — enrich each from its album page` : "Import complete — album graded");
  };

  const switchAlbum = (i: number) => {
    setAlbumIndex(i);
    setAlbumPath(uploaded[i].path);
    setRelease(null);
    setReleaseId("");
    setSuggestions([]);
    setGenres({});
    setMbLink("");
    setRymLink("");
    setSearchHits([]);
  };

  const totalFiles = albums.reduce((n, g) => n + g.files.length, 0);
  const canNext =
    step === 0
      ? totalFiles > 0 && albums.length > 0 && albums.every((g) => g.name.trim() || g.files.length === 0)
      : step === 1
        ? !!(releaseId || extractMbid(mbLink))
        : true;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <UploadCloud className="h-6 w-6 text-accent" /> Import
        </h1>
        {uploaded.length > 1 && (
          <select className="input !w-auto text-sm" value={albumIndex} onChange={(e) => switchAlbum(Number(e.target.value))}>
            {uploaded.map((a, i) => (
              <option key={a.path} value={i}>{a.name}</option>
            ))}
          </select>
        )}
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

      {/* ---------------- Step 0: select & separate ---------------- */}
      {step === 0 && (
        <div className="space-y-4">
          <div
            className="rounded-xl border-2 border-dashed border-border bg-card p-10 text-center hover:border-accent/60 transition-colors cursor-pointer"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              handleDrop(e.dataTransfer.items);
            }}
            onClick={() => pickFolderBrowser()}
          >
            <UploadCloud className="h-10 w-10 text-zinc-600 mx-auto mb-3" />
            <div className="font-medium text-zinc-300">Drop albums or files here</div>
            <div className="text-xs text-zinc-600 mt-1">
              drop one or more folders (even from different artists) — they are separated into albums below ·
              multi-disc folders (<b className="text-zinc-500">CD1/</b>, <b className="text-zinc-500">Disc 2/</b>) merge
              into one album
            </div>
            <div className="text-[11px] text-zinc-600 mt-1">
              audio (flac, mp3, m4a, ogg, opus, wav, …) · images (jpg, png, webp, tiff, avif, heic, …) · .lrc .cue .log .accurip
            </div>
            <div className="text-xs text-zinc-600 mt-2">
              click to <b className="text-zinc-400">pick a folder</b> · or{" "}
              <span
                className="text-accent-soft underline underline-offset-2 cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation();
                  document.getElementById("import-files")?.click();
                }}
              >
                browse individual files
              </span>
            </div>
            <input id="import-files" type="file" multiple className="hidden" onChange={(e) => e.target.files && handleFiles(e.target.files)} />
            <input
              id="import-folder"
              type="file"
              multiple
              className="hidden"
              ref={(el) => {
                if (el) {
                  el.setAttribute("webkitdirectory", "");
                  el.setAttribute("directory", "");
                }
              }}
              onChange={(e) => e.target.files && handleFiles(e.target.files)}
            />
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button className="btn-ghost" onClick={pickFolderBrowser}>
              <FolderOpen className="h-4 w-4" /> Pick folder…
            </button>
            <button className="btn-ghost" onClick={pickFolderNative}>
              <ListMusic className="h-4 w-4" /> Pick folder (native)…
            </button>
            <input
              className="input max-w-xs"
              placeholder="Default album name"
              value={albumName}
              onChange={(e) => setAlbumName(e.target.value)}
            />
            {source === "native" && (
              <span className="text-xs text-zinc-500">importing from disk — files move into your library</span>
            )}
          </div>

          {totalFiles > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">Separate into albums</span>
                <span className="text-xs text-zinc-500">
                  {totalFiles} file(s) → {albums.length} album(s) — rename, or move files between albums with the dropdown
                </span>
                <button className="btn-ghost !py-1 text-xs ml-auto" onClick={addAlbum}>
                  <Plus className="h-3.5 w-3.5" /> Add album
                </button>
              </div>
              {albums.map((g, gi) => (
                <div key={gi} className="bg-card rounded-lg border border-border p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Disc3 className="h-4 w-4 text-zinc-500 shrink-0" />
                    <input
                      className="input !w-auto min-w-[200px] font-medium"
                      value={g.name}
                      placeholder="Album name"
                      onChange={(e) => renameGroup(gi, e.target.value)}
                    />
                    <span className="text-xs text-zinc-500">{g.files.length} file(s)</span>
                    <button className="btn-danger !px-2 !py-1 ml-auto" onClick={() => removeAlbum(gi)} disabled={albums.length <= 1} title="Remove (files move to first album)">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="max-h-52 overflow-auto space-y-1">
                    {g.files.length === 0 && <div className="text-xs text-zinc-600 px-2 py-1">Empty — move files here from other albums.</div>}
                    {g.files.map((f) => (
                      <div key={f.relPath} className="flex items-center gap-2 text-xs px-2">
                        <span className="flex-1 truncate text-zinc-400" title={f.relPath}>{f.relPath}</span>
                        <select
                          className="input !w-auto !py-0.5 text-[11px]"
                          value={gi}
                          onChange={(e) => moveFile(gi, Number(e.target.value), f)}
                        >
                          {albums.map((a, i) => (
                            <option key={i} value={i}>{a.name.trim() || `Album ${i + 1}`}</option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              <button
                className="btn-primary"
                onClick={doImport}
                disabled={uploading || !albums.some((g) => g.name.trim() && g.files.length)}
              >
                {uploading ? "Importing…" : `Import ${albums.filter((g) => g.files.length).length} album(s) into library`}
              </button>
            </div>
          )}
        </div>
      )}

      {/* ---------------- Step 1: links ---------------- */}
      {step === 1 && (
        <div className="space-y-4">
          <div className="bg-card rounded-lg border border-border p-4 space-y-3">
            <div className="text-sm font-semibold text-zinc-300">
              MusicBrainz release <span className="text-zinc-500 font-normal">— {currentAlbumName}</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                className={`input flex-1 ${releaseId ? "!border-emerald-700" : ""}`}
                placeholder="MusicBrainz release URL or ID (e.g. https://musicbrainz.org/release/…)"
                value={mbLink}
                onChange={(e) => setMbLink(e.target.value)}
              />
              {releaseId ? (
                <span className="chip bg-emerald-900/60 text-emerald-300 border border-emerald-800 shrink-0">
                  <Check className="h-3 w-3" /> recognized
                </span>
              ) : mbLink.trim() ? (
                <span className="chip bg-amber-900/50 text-amber-300 border border-amber-900 shrink-0">no MBID found</span>
              ) : null}
            </div>
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
            <div className="flex items-center gap-2">
              <input
                className={`input flex-1 ${rymValid === true ? "!border-emerald-700" : rymValid === false ? "!border-red-800" : ""}`}
                placeholder="https://rateyourmusic.com/release/…"
                value={rymLink}
                onChange={(e) => setRymLink(e.target.value)}
              />
              {rymValid === true && (
                <span className="chip bg-emerald-900/60 text-emerald-300 border border-emerald-800 shrink-0">
                  <Check className="h-3 w-3" /> valid
                </span>
              )}
              {rymValid === false && (
                <span className="chip bg-red-900/50 text-red-300 border border-red-900 shrink-0">not a RYM URL</span>
              )}
            </div>
          </div>
          <button className="btn-primary" onClick={() => pickRelease(releaseId || mbLink)} disabled={!mbLink || busy}>
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
            {uploaded.length > 1
              ? `${uploaded.length} albums were added to your library. Use the dropdown above to finish linking, matching and tagging each one.`
              : "Links, MBIDs, genres, lyrics and advisory ratings are written to the files. Run grading on the album to verify a perfect score."}
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