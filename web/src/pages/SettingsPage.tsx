import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Save, RotateCcw, Check } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";
import { applyAccent } from "../App";

const DEFAULT_NAMING_SCRIPT =
  "%albumartist% [%musicbrainz_albumartistid%]/$if(%releasetype%,[%releasetype%] ,)$if(%originaldate%,%originaldate% - ,)$if(%date%,%date% - ,)%album% {$if(%releasecountry%,%releasecountry% - )%media%$if(%catalognumber%, - %catalognumber%)}/%discnumber%-$num(%tracknumber%,2) %title%";

const ACCENT_OPTIONS: { id: string; name: string; color: string }[] = [
  { id: "violet", name: "Violet", color: "#8b5cf6" },
  { id: "pink", name: "Pink", color: "#ec4899" },
  { id: "emerald", name: "Emerald", color: "#10b981" },
  { id: "sky", name: "Sky", color: "#0ea5e9" },
  { id: "amber", name: "Amber", color: "#f59e0b" },
  { id: "red", name: "Red", color: "#ef4444" },
];

export default function SettingsPage() {
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config });
  const qc = useQueryClient();
  const [musicFolder, setMusicFolder] = useState("");
  const [lyricsFormat, setLyricsFormat] = useState("EMBEDDED");
  const [workerLimit, setWorkerLimit] = useState(0);
  const [namingScript, setNamingScript] = useState(DEFAULT_NAMING_SCRIPT);
  const [shortFolderNames, setShortFolderNames] = useState(false);
  const [accent, setAccent] = useState<string>(() => localStorage.getItem("mlo.accent") ?? "violet");
  const [defaultView, setDefaultView] = useState<string>(() => localStorage.getItem("mlo.defaultView") ?? "albums");
  const [loaded, setLoaded] = useState(false);

  // ---- script options (persisted to config; /api/run uses them as defaults) ----
  const [forceFlac, setForceFlac] = useState(false);
  const [forceImages, setForceImages] = useState(false);
  const [forceAudit, setForceAudit] = useState(false);
  const [forceLyrics, setForceLyrics] = useState(false);
  const [forceCue, setForceCue] = useState(false);
  const [forceDr, setForceDr] = useState(false);
  const [forceAutotag, setForceAutotag] = useState(false);
  const [forceAccurip, setForceAccurip] = useState(false);
  const [renameCovers, setRenameCovers] = useState(true);
  const [reencodeToJxl, setReencodeToJxl] = useState(true);
  const [removeAlpha, setRemoveAlpha] = useState(true);
  const [jpegProgressive, setJpegProgressive] = useState(true);
  const [coverResize, setCoverResize] = useState(false);
  const [coverTargetSize, setCoverTargetSize] = useState(0);
  const [coverCrop, setCoverCrop] = useState(false);
  const [coverJpegQuality, setCoverJpegQuality] = useState(95);
  const [jpegxlEffort, setJpegxlEffort] = useState(10);
  const [pngLevel, setPngLevel] = useState(6);

  useEffect(() => {
    if (!config || loaded) return;
    setMusicFolder(String(config.music_folder ?? ""));
    setLyricsFormat(String(config.lyrics_format ?? "EMBEDDED"));
    setWorkerLimit(Number(config.worker_limit ?? 0));
    setNamingScript(String(config.naming_script ?? "") || DEFAULT_NAMING_SCRIPT);
    setShortFolderNames(!!config.short_folder_names);
    setForceFlac(!!config.force_reencode_flac);
    setForceImages(!!config.force_reencode_images);
    setForceAudit(!!config.force_audit);
    setForceLyrics(!!config.force_lyrics);
    setForceCue(!!config.force_cue);
    setForceDr(!!config.force_dr_replaygain);
    setForceAutotag(!!config.force_auto_tag);
    setForceAccurip(!!config.force_accurip);
    setRenameCovers(config.rename_to_cover !== false);
    setReencodeToJxl(config.reencode_to_jxl !== false);
    setRemoveAlpha(config.remove_alpha !== false);
    setJpegProgressive(config.jpeg_progressive !== false);
    setCoverResize(!!config.cover_resize_enabled);
    setCoverTargetSize(Number(config.cover_target_size ?? 0));
    setCoverCrop(!!config.cover_crop_enabled);
    setCoverJpegQuality(Number(config.cover_jpeg_quality ?? 95));
    setJpegxlEffort(Number(config.jpegxl_effort ?? 10));
    setPngLevel(Number(config.png_optimization_level ?? 6));
    setLoaded(true);
  }, [config, loaded]);

  const pickAccent = (id: string) => {
    setAccent(id);
    localStorage.setItem("mlo.accent", id);
    applyAccent(id);
  };

  const pickDefaultView = (v: string) => {
    setDefaultView(v);
    localStorage.setItem("mlo.defaultView", v);
  };

  const pickNative = async () => {
    if (!(window as any).__TAURI_INTERNALS__) {
      toast("Native picker is only available in the desktop app");
      return;
    }
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const picked = await invoke<string | null>("pick_folder");
      if (picked) setMusicFolder(picked);
    } catch (e) {
      toast(String(e));
    }
  };

  const save = async () => {
    try {
      await api.saveConfig({
        ...config,
        music_folder: musicFolder,
        lyrics_format: lyricsFormat,
        worker_limit: workerLimit,
        naming_script: namingScript,
        short_folder_names: shortFolderNames,
        force_reencode_flac: forceFlac,
        force_reencode_images: forceImages,
        force_audit: forceAudit,
        force_lyrics: forceLyrics,
        force_cue: forceCue,
        force_dr_replaygain: forceDr,
        force_auto_tag: forceAutotag,
        force_accurip: forceAccurip,
        rename_to_cover: renameCovers,
        reencode_to_jxl: reencodeToJxl,
        remove_alpha: removeAlpha,
        jpeg_progressive: jpegProgressive,
        cover_resize_enabled: coverResize,
        cover_target_size: coverTargetSize,
        cover_crop_enabled: coverCrop,
        cover_jpeg_quality: coverJpegQuality,
        jpegxl_effort: jpegxlEffort,
        png_optimization_level: pngLevel,
      });
      toast("Config saved");
      qc.invalidateQueries({ queryKey: ["config"] });
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    }
  };

  return (
    <div className="p-6 max-w-3xl space-y-5">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>

      <div className="bg-card rounded-lg border border-border p-4 space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Appearance</div>
        <div>
          <span className="text-xs text-zinc-500 uppercase">Accent color</span>
          <div className="flex gap-2 mt-1.5">
            {ACCENT_OPTIONS.map((a) => (
              <button
                key={a.id}
                title={a.name}
                onClick={() => pickAccent(a.id)}
                className="h-8 w-8 rounded-full border-2 flex items-center justify-center transition-transform hover:scale-110"
                style={{
                  backgroundColor: a.color,
                  borderColor: accent === a.id ? "#fff" : "transparent",
                }}
              >
                {accent === a.id && <Check className="h-4 w-4 text-black" />}
              </button>
            ))}
          </div>
        </div>
        <label className="block">
          <span className="text-xs text-zinc-500 uppercase">Default library view</span>
          <select className="input mt-1" value={defaultView} onChange={(e) => pickDefaultView(e.target.value)}>
            <option value="albums">Albums</option>
            <option value="artists">Artists</option>
            <option value="tracks">Tracks</option>
          </select>
        </label>
      </div>

      <div className="bg-card rounded-lg border border-border p-4 space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Library</div>
        <label className="block">
          <span className="text-xs text-zinc-500 uppercase">Music folder</span>
          <div className="flex gap-2 mt-1">
            <input className="input" value={musicFolder} onChange={(e) => setMusicFolder(e.target.value)} placeholder="F:\Music" />
            <button className="btn-ghost" onClick={pickNative} title="Native folder picker (desktop)">
              <FolderOpen className="h-4 w-4" />
            </button>
          </div>
        </label>
        <label className="block">
          <span className="text-xs text-zinc-500 uppercase">Lyrics format</span>
          <select className="input mt-1" value={lyricsFormat} onChange={(e) => setLyricsFormat(e.target.value)}>
            <option value="EMBEDDED">Embedded</option>
            <option value="LRC">LRC sidecar</option>
            <option value="BOTH">Both</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-zinc-500 uppercase">Worker limit (0 = auto)</span>
          <input className="input mt-1" type="number" min={0} value={workerLimit} onChange={(e) => setWorkerLimit(Number(e.target.value))} />
        </label>
      </div>

      <div className="bg-card rounded-lg border border-border p-4 space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">File naming (Picard-style script)</div>
        <textarea
          className="input font-mono text-xs min-h-[110px]"
          value={namingScript}
          onChange={(e) => setNamingScript(e.target.value)}
          spellCheck={false}
        />
        <div className="text-[11px] text-zinc-600 leading-relaxed">
          Variables: <code>%albumartist% %musicbrainz_albumartistid% %releasetype% %originaldate% %date% %album% %releasecountry% %media% %catalognumber% %discnumber% %tracknumber% %title%</code> ·
          Functions: <code>$if(a,b,c) $left(s,n) $num(s,n) $lower $upper $replace</code> · <code>/</code> creates folders.
          Applied from the album page or the bulk selection toolbar.
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={shortFolderNames}
              onChange={(e) => setShortFolderNames(e.target.checked)}
              className=""
            />
            Shorter folder names (truncate MusicBrainz IDs to 8 chars)
          </label>
          <button className="btn-ghost !py-1 text-xs" onClick={() => setNamingScript(DEFAULT_NAMING_SCRIPT)}>
            <RotateCcw className="h-3.5 w-3.5" /> Reset to default
          </button>
        </div>
      </div>

      <button className="btn-primary" onClick={save}>
        <Save className="h-4 w-4" /> Save
      </button>

      <div className="bg-card rounded-lg border border-border p-4 space-y-4">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Scripts</div>

        <div>
          <div className="text-xs text-zinc-500 uppercase mb-1.5">Force re-run (ignore existing results)</div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5">
            {[
              { label: "Lyrics (format + fetch)", v: forceLyrics, s: setForceLyrics },
              { label: "CUEs", v: forceCue, s: setForceCue },
              { label: "FLACs (re-encode)", v: forceFlac, s: setForceFlac },
              { label: "Images", v: forceImages, s: setForceImages },
              { label: "Audit", v: forceAudit, s: setForceAudit },
              { label: "DR / ReplayGain", v: forceDr, s: setForceDr },
              { label: "AutoTag", v: forceAutotag, s: setForceAutotag },
              { label: "AccurateRip", v: forceAccurip, s: setForceAccurip },
            ].map((o) => (
              <label key={o.label} className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
                <input type="checkbox" checked={o.v} onChange={(e) => o.s(e.target.checked)} />
                {o.label}
              </label>
            ))}
          </div>
        </div>

        <div>
          <div className="text-xs text-zinc-500 uppercase mb-1.5">Images</div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5">
            <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
              <input type="checkbox" checked={renameCovers} onChange={(e) => setRenameCovers(e.target.checked)} />
              Rename album art to cover.*
            </label>
            <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
              <input type="checkbox" checked={reencodeToJxl} onChange={(e) => setReencodeToJxl(e.target.checked)} />
              Convert images to JPEG XL
            </label>
            <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
              <input type="checkbox" checked={removeAlpha} onChange={(e) => setRemoveAlpha(e.target.checked)} />
              Remove PNG alpha
            </label>
            <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
              <input type="checkbox" checked={jpegProgressive} onChange={(e) => setJpegProgressive(e.target.checked)} />
              Progressive JPEG
            </label>
            <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
              <input type="checkbox" checked={coverResize} onChange={(e) => setCoverResize(e.target.checked)} />
              Resize covers
            </label>
            <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
              <input type="checkbox" checked={coverCrop} onChange={(e) => setCoverCrop(e.target.checked)} />
              Crop covers to square
            </label>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
            <label className="block">
              <span className="text-[10px] text-zinc-500 uppercase">Cover target size (px, 0 = off)</span>
              <input className="input mt-0.5" type="number" min={0} max={4000} value={coverTargetSize} onChange={(e) => setCoverTargetSize(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="text-[10px] text-zinc-500 uppercase">Cover JPEG quality (70–100)</span>
              <input className="input mt-0.5" type="number" min={70} max={100} value={coverJpegQuality} onChange={(e) => setCoverJpegQuality(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="text-[10px] text-zinc-500 uppercase">JPEG XL effort (1–10)</span>
              <input className="input mt-0.5" type="number" min={1} max={10} value={jpegxlEffort} onChange={(e) => setJpegxlEffort(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="text-[10px] text-zinc-500 uppercase">PNG optimization level</span>
              <input className="input mt-0.5" type="number" min={0} max={6} value={pngLevel} onChange={(e) => setPngLevel(Number(e.target.value))} />
            </label>
          </div>
        </div>
      </div>

      <details className="bg-card rounded-lg border border-border p-4">
        <summary className="text-sm font-semibold cursor-pointer">Raw config (advanced)</summary>
        <pre className="mt-2 text-xs text-zinc-400 overflow-auto max-h-80">{JSON.stringify(config, null, 2)}</pre>
      </details>
    </div>
  );
}