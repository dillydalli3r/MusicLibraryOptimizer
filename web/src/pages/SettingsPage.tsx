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
  { id: "mono", name: "Black & white", color: "#ffffff" },
];

export default function SettingsPage() {
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config });
  const qc = useQueryClient();
  const [musicFolder, setMusicFolder] = useState("");
  const [lyricsFormat, setLyricsFormat] = useState("EMBEDDED");
  const [workerLimit, setWorkerLimit] = useState(0);
  const [namingScript, setNamingScript] = useState(DEFAULT_NAMING_SCRIPT);
  const [shortFolderNames, setShortFolderNames] = useState(false);
  const [accent, setAccent] = useState<string>(() => localStorage.getItem("mlo.accent") ?? "mono");
  const [defaultView, setDefaultView] = useState<string>(() => localStorage.getItem("mlo.defaultView") ?? "albums");
  const [loaded, setLoaded] = useState(false);

  // ---- script options (persisted to config; /api/run uses them as defaults) ----
  type CfgField =
    | { k: string; label: string; type: "bool" }
    | { k: string; label: string; type: "number"; min?: number; max?: number; step?: number }
    | { k: string; label: string; type: "select"; options: [string, string][] }
    | { k: string; label: string; type: "text" };
  interface CfgGroup {
    title: string;
    blurb?: string;
    fields: CfgField[];
  }
  const CFG_GROUPS: CfgGroup[] = [
    {
      title: "FLACs (script 3)",
      fields: [
        { k: "flac_level", label: "Compression level", type: "number", min: 0, max: 8 },
        { k: "add_seektables", label: "Add seektables", type: "bool" },
        { k: "flac_preserve_picture", label: "Preserve embedded picture", type: "bool" },
        { k: "flac_no_padding", label: "No padding", type: "bool" },
        { k: "force_reencode_flac", label: "Force re-encode", type: "bool" },
      ],
    },
    {
      title: "Images (script 5)",
      blurb: "Requires libjxl in .dependencies for JPEG XL conversion.",
      fields: [
        { k: "rename_to_cover", label: "Rename album art to cover.*", type: "bool" },
        { k: "reencode_to_jxl", label: "Convert images to JPEG XL", type: "bool" },
        { k: "convert_jxl_back", label: "Convert JXL back to original", type: "bool" },
        { k: "images_convert_to_jpeg", label: "Convert other formats to JPEG", type: "bool" },
        { k: "images_convert_lossless_to_png", label: "Convert lossless to PNG", type: "bool" },
        { k: "remove_alpha", label: "Remove PNG alpha", type: "bool" },
        { k: "jpeg_progressive", label: "Progressive JPEG", type: "bool" },
        { k: "jpegxl_effort", label: "JPEG XL effort", type: "number", min: 1, max: 10 },
        { k: "jpegxl_distance", label: "JPEG XL distance (0 = lossless)", type: "number", min: 0, max: 2, step: 0.1 },
        { k: "images_jpeg_quality", label: "JPEG quality", type: "number", min: 70, max: 100 },
        { k: "png_optimization_level", label: "PNG optimization level", type: "number", min: 0, max: 6 },
        { k: "cover_jpeg_quality", label: "Cover JPEG quality", type: "number", min: 70, max: 100 },
        { k: "cover_resize_enabled", label: "Resize covers", type: "bool" },
        { k: "cover_target_size", label: "Cover target size (px)", type: "number", min: 0, max: 4000 },
        { k: "cover_crop_enabled", label: "Crop covers to square", type: "bool" },
        { k: "cover_crop_threshold", label: "Crop threshold (aspect deviation)", type: "number", min: 0, max: 0.5, step: 0.05 },
        { k: "cover_force_exact_size", label: "Force exact target size", type: "bool" },
        { k: "cover_enforce_size", label: "Enforce size in grading", type: "bool" },
        { k: "cover_enforce_square", label: "Enforce square in grading", type: "bool" },
        { k: "cover_jpeg_enabled", label: "Process JPEG covers", type: "bool" },
        { k: "cover_png_enabled", label: "Process PNG covers", type: "bool" },
        { k: "cover_jxl_enabled", label: "Process JXL covers", type: "bool" },
        { k: "cover_jpeg_target_size", label: "JPEG cover size override (0 = global)", type: "number", min: 0, max: 4000 },
        { k: "cover_png_target_size", label: "PNG cover size override (0 = global)", type: "number", min: 0, max: 4000 },
        { k: "cover_jxl_target_size", label: "JXL cover size override (0 = global)", type: "number", min: 0, max: 4000 },
        { k: "force_reencode_images", label: "Force re-process", type: "bool" },
      ],
    },
    {
      title: "Lyrics & CUEs (scripts 1 & 2)",
      fields: [
        { k: "optimize_lrc", label: "Optimize .lrc sidecars", type: "bool" },
        { k: "optimize_embedded_lyrics", label: "Optimize embedded lyrics", type: "bool" },
        { k: "lrc_timestamp_precision", label: "Timestamp precision (decimals)", type: "number", min: 2, max: 3 },
        { k: "lrc_strip_metadata", label: "Strip metadata tags ([ti:], [ar:])", type: "bool" },
        { k: "lrc_collapse_blank_lines", label: "Collapse blank lines", type: "bool" },
        { k: "lrc_enhanced_enabled", label: "Enhanced LRC (word timestamps)", type: "bool" },
        { k: "lrc_enhanced_word_sync", label: "Enhanced LRC word sync", type: "bool" },
        { k: "lrc_extended_enabled", label: "Extended LRC (E-LRC)", type: "bool" },
        { k: "lrc_add_zero_timestamp", label: "Add [00:00.00] opening line", type: "bool" },
        { k: "lrc_zero_timestamp_target", label: "Zero timestamp target", type: "select", options: [["EMBEDDED", "Embedded"], ["LRC", "LRC sidecar"], ["BOTH", "Both"]] },
        { k: "append_final_newline", label: "Append final newline", type: "bool" },
        { k: "keep_empty_cue_lines", label: "Keep empty CUE lines", type: "bool" },
        { k: "keep_other_cue_lines", label: "Keep non-track CUE lines", type: "bool" },
        { k: "keep_empty_accurip_lines", label: "Keep empty .accurip lines", type: "bool" },
        { k: "cue_file_type", label: "CUE file type", type: "select", options: [["WAVE", "WAVE"], ["MP3", "MP3"]] },
        { k: "force_lyrics", label: "Force lyrics re-format", type: "bool" },
        { k: "force_cue", label: "Force CUE re-format", type: "bool" },
      ],
    },
    {
      title: "DR / ReplayGain (script 7)",
      fields: [
        { k: "dr_replaygain_enabled", label: "Enabled", type: "bool" },
        { k: "replaygain_skip_existing", label: "Skip files that already have RG tags", type: "bool" },
        { k: "force_dr_replaygain", label: "Force re-run", type: "bool" },
      ],
    },
    {
      title: "Audit (script 6)",
      blurb: "AudioAuditor verdict + CD rip verification (REAL/FAKE).",
      fields: [
        { k: "audit_thorough", label: "Thorough mode (full-track detectors)", type: "bool" },
        { k: "audit_cutoff_allow", label: "Frequency cutoff allowance (Hz, 0 = default)", type: "number", min: 0, max: 24000 },
        { k: "audit_verify_cd_checksums", label: "Verify CD .log CRC checksums", type: "bool" },
        { k: "audit_cd_require_both", label: "Require log CRC AND auditor for REAL", type: "bool" },
        { k: "audit_integrity", label: "Write integrity tags (AUDIO_MD5)", type: "bool" },
        { k: "audit_fail_on_unscorable_log", label: "Fail on unscorable .log", type: "bool" },
        { k: "audit_verify_log_checksum", label: "Verify .log checksum", type: "bool" },
        { k: "audit_require_accuraterip", label: "Require AccurateRip data", type: "bool" },
        { k: "audit_log_score_threshold", label: "Log score threshold", type: "number", min: 0, max: 100 },
        { k: "audit_batch_size", label: "Batch size", type: "number", min: 50, max: 500 },
        { k: "audit_batch_timeout_s", label: "Batch timeout (s)", type: "number", min: 10, max: 120 },
        { k: "audit_per_file_timeout_s", label: "Per-file timeout (s)", type: "number", min: 10, max: 60 },
        { k: "audit_clipping", label: "Detect clipping", type: "bool" },
        { k: "audit_scaled_clipping", label: "Detect scaled clipping", type: "bool" },
        { k: "audit_mqa", label: "Detect MQA", type: "bool" },
        { k: "audit_ai", label: "Detect AI-upscaled audio", type: "bool" },
        { k: "audit_fake_stereo", label: "Detect fake stereo", type: "bool" },
        { k: "audit_silence", label: "Detect silence", type: "bool" },
        { k: "audit_dynamic_range", label: "Measure dynamic range", type: "bool" },
        { k: "audit_true_peak", label: "Measure true peak", type: "bool" },
        { k: "audit_lufs", label: "Measure LUFS", type: "bool" },
        { k: "audit_bpm", label: "Measure BPM", type: "bool" },
        { k: "force_audit", label: "Force re-audit", type: "bool" },
      ],
    },
    {
      title: "AutoTag (script 8)",
      fields: [
        { k: "auto_advisory", label: "Set advisory automatically", type: "bool" },
        { k: "auto_instrumental", label: "Set INSTRUMENTAL automatically", type: "bool" },
        { k: "auto_zero_advisory_for_instrumental", label: "Zero advisory on instrumentals", type: "bool" },
        { k: "fix_instrumental_from_lyrics", label: "Fix INSTRUMENTAL from lyrics", type: "bool" },
        { k: "force_auto_tag", label: "Force re-tag", type: "bool" },
      ],
    },
    {
      title: "AccurateRip (script 9)",
      fields: [
        { k: "write_accurip_files", label: "Write .accurip files", type: "bool" },
        { k: "force_accurip", label: "Force re-generate", type: "bool" },
      ],
    },
    {
      title: "Tag writes (global switches)",
      blurb: "Which tag families may be written at all. Per-filetype overrides live in the raw config (audio_tag_writes).",
      fields: [
        { k: "write_audit_tag", label: "Write AUDIT verdicts", type: "bool" },
        { k: "write_log_grade", label: "Write LOG_GRADE scores", type: "bool" },
        { k: "write_replaygain_tags", label: "Write ReplayGain tags", type: "bool" },
        { k: "write_dynamic_range_tags", label: "Write DR tags", type: "bool" },
        { k: "normalize_media_source", label: "Normalize MEDIA / SOURCE", type: "bool" },
        { k: "strip_source_on_cd", label: "Strip SOURCE on CD rips", type: "bool" },
        { k: "fill_empty_source", label: "Fill empty SOURCE on digital", type: "bool" },
        { k: "digital_media_source_value", label: "Digital SOURCE value", type: "text" },
      ],
    },
    {
      title: "Grading (script 4)",
      blurb: "Which file types are allowed in an album and which checks count as failures.",
      fields: [
        { k: "grade_include_music", label: "Allow audio files", type: "bool" },
        { k: "grade_include_cover", label: "Allow cover images", type: "bool" },
        { k: "grade_include_cue", label: "Allow CUE files", type: "bool" },
        { k: "grade_include_log", label: "Allow LOG files", type: "bool" },
        { k: "grade_include_lrc", label: "Allow LRC files", type: "bool" },
        { k: "grade_include_accurip", label: "Allow .accurip files", type: "bool" },
        { k: "grade_include_other", label: "Allow other files", type: "bool" },
        { k: "grade_log_score_threshold", label: "Log score threshold", type: "number", min: 0, max: 100 },
        { k: "grade_check_log_checksum", label: "Check log checksum", type: "bool" },
        { k: "grade_check_accuraterip", label: "Check AccurateRip", type: "bool" },
        { k: "grader_cover_size_tolerance_px", label: "Cover size tolerance (px)", type: "number", min: 0, max: 5 },
        { k: "grader_strict_square_threshold", label: "Strict square threshold", type: "number", min: 0, max: 0.05, step: 0.005 },
      ],
    },
  ];
  const GRADE_CHECK_KEYS: CfgField[] = [
    { k: "grade_check_tag_spaces", label: "Tag spaces", type: "bool" },
    { k: "grade_check_lyrics_spaces", label: "Lyrics spaces", type: "bool" },
    { k: "grade_check_cue_spaces", label: "CUE spaces", type: "bool" },
    { k: "grade_check_cover_crop", label: "Cover crop", type: "bool" },
    { k: "grade_check_lyrics_zero", label: "Lyrics zero timestamp", type: "bool" },
    { k: "grade_check_tag_blank_lines", label: "Tag blank lines", type: "bool" },
    { k: "grade_check_lyrics_blank_lines", label: "Lyrics blank lines", type: "bool" },
    { k: "grade_check_cue_blank_lines", label: "CUE blank lines", type: "bool" },
    { k: "grade_check_unreadable", label: "Unreadable files", type: "bool" },
    { k: "grade_check_missing_tags", label: "Missing tags", type: "bool" },
    { k: "grade_check_encoder", label: "Encoder markers", type: "bool" },
    { k: "grade_check_audit", label: "AUDIT present", type: "bool" },
    { k: "grade_check_instrumental", label: "INSTRUMENTAL", type: "bool" },
    { k: "grade_check_lyrics", label: "Lyrics present", type: "bool" },
    { k: "grade_check_lyrics_format", label: "Lyrics format", type: "bool" },
    { k: "grade_check_sidecar_cover", label: "Sidecar cover", type: "bool" },
    { k: "grade_check_media", label: "MEDIA tag", type: "bool" },
    { k: "grade_check_source", label: "SOURCE tag", type: "bool" },
    { k: "grade_check_album_tags", label: "Album-level tags", type: "bool" },
    { k: "grade_check_cd_log", label: "CD log", type: "bool" },
    { k: "grade_check_cd_cue", label: "CD cue", type: "bool" },
    { k: "grade_check_disc_naming", label: "Disc naming", type: "bool" },
    { k: "grade_check_log_grade", label: "Log grade", type: "bool" },
    { k: "grade_check_crc", label: "CRC", type: "bool" },
    { k: "grade_check_cd_format", label: "CD format", type: "bool" },
    { k: "grade_check_cover", label: "Cover present", type: "bool" },
    { k: "grade_check_cue_format", label: "CUE format", type: "bool" },
    { k: "grade_check_disallowed", label: "Disallowed files", type: "bool" },
  ];
  const ALL_CFG_KEYS = [...CFG_GROUPS.flatMap((g) => g.fields), ...GRADE_CHECK_KEYS].map((f) => f.k);
  const [scriptCfg, setScriptCfg] = useState<Record<string, unknown>>({});
  const setCfg = (k: string, v: unknown) => setScriptCfg((c) => ({ ...c, [k]: v }));
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const runPreview = async () => {
    setPreviewing(true);
    setPreviewError(null);
    try {
      const r = await api.namingPreview(namingScript, shortFolderNames);
      if (r.ok && r.path) {
        setPreviewPath(r.path);
      } else {
        setPreviewError(r.error || "Script produced an empty path");
        setPreviewPath(null);
      }
    } catch (e) {
      setPreviewError(String(e));
      setPreviewPath(null);
    } finally {
      setPreviewing(false);
    }
  };

  useEffect(() => {
    if (!config || loaded) return;
    setMusicFolder(String(config.music_folder ?? ""));
    setLyricsFormat(String(config.lyrics_format ?? "EMBEDDED"));
    setWorkerLimit(Number(config.worker_limit ?? 0));
    setNamingScript(String(config.naming_script ?? "") || DEFAULT_NAMING_SCRIPT);
    setShortFolderNames(!!config.short_folder_names);
    setScriptCfg(Object.fromEntries(ALL_CFG_KEYS.map((k) => [k, config[k]])));
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
        ...scriptCfg,
        music_folder: musicFolder,
        lyrics_format: lyricsFormat,
        worker_limit: workerLimit,
        naming_script: namingScript,
        short_folder_names: shortFolderNames,
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
                  borderColor: accent === a.id ? "#fff" : "#3f3f46",
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
          <button className="btn-ghost !py-1 text-xs" onClick={runPreview} disabled={previewing}>
            Preview
          </button>
        </div>
        {previewPath && (
          <div className="rounded-md border border-border bg-panel px-3 py-2 font-mono text-xs text-accent-soft break-all">
            <span className="text-zinc-500">sample album → </span>
            {previewPath}
          </div>
        )}
        {previewError && (
          <div className="rounded-md border border-red-900 bg-red-950/40 px-3 py-2 font-mono text-xs text-red-300 break-all">
            {previewError}
          </div>
        )}
      </div>

      <div className="bg-card rounded-lg border border-border p-4 space-y-5">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Scripts — in-depth configuration</div>

        {CFG_GROUPS.map((g) => (
          <div key={g.title}>
            <div className="text-xs font-bold text-zinc-300">{g.title}</div>
            {g.blurb && <div className="text-[10px] text-zinc-600 mb-1">{g.blurb}</div>}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5 mt-1.5">
              {g.fields.map((f) => (
                <label key={f.k} className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
                  {f.type === "bool" ? (
                    <>
                      <input type="checkbox" checked={!!scriptCfg[f.k]} onChange={(e) => setCfg(f.k, e.target.checked)} />
                      {f.label}
                    </>
                  ) : f.type === "select" ? (
                    <div className="flex items-center gap-2 w-full">
                      <span className="flex-1 min-w-0 truncate">{f.label}</span>
                      <select
                        className="input !w-32 !py-0.5 text-[11px] shrink-0"
                        value={String(scriptCfg[f.k] ?? "")}
                        onChange={(e) => setCfg(f.k, e.target.value)}
                      >
                        {f.options.map(([v, l]) => (
                          <option key={v} value={v}>{l}</option>
                        ))}
                      </select>
                    </div>
                  ) : f.type === "text" ? (
                    <div className="flex items-center gap-2 w-full">
                      <span className="flex-1 min-w-0 truncate">{f.label}</span>
                      <input
                        className="input !w-32 !py-0.5 text-[11px] shrink-0"
                        value={String(scriptCfg[f.k] ?? "")}
                        onChange={(e) => setCfg(f.k, e.target.value)}
                      />
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 w-full">
                      <span className="flex-1 min-w-0 truncate">{f.label}</span>
                      <input
                        className="input !w-20 !py-0.5 text-[11px] shrink-0 text-right"
                        type="number"
                        min={f.min}
                        max={f.max}
                        step={f.step ?? 1}
                        value={String(scriptCfg[f.k] ?? "")}
                        onChange={(e) => setCfg(f.k, Number(e.target.value))}
                      />
                    </div>
                  )}
                </label>
              ))}
            </div>
          </div>
        ))}

        <details className="rounded-md border border-border bg-panel/40 p-3">
          <summary className="text-xs font-semibold text-zinc-400 cursor-pointer select-none">
            Grading — individual checks ({GRADE_CHECK_KEYS.length})
          </summary>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5 mt-2">
            {GRADE_CHECK_KEYS.map((f) => (
              <label key={f.k} className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
                <input type="checkbox" checked={!!scriptCfg[f.k]} onChange={(e) => setCfg(f.k, e.target.checked)} />
                {f.label}
              </label>
            ))}
          </div>
        </details>
      </div>

      <button className="btn-primary" onClick={save}>
        <Save className="h-4 w-4" /> Save all settings
      </button>

      <details className="bg-card rounded-lg border border-border p-4">
        <summary className="text-sm font-semibold cursor-pointer">Raw config (advanced)</summary>
        <pre className="mt-2 text-xs text-zinc-400 overflow-auto max-h-80">{JSON.stringify(config, null, 2)}</pre>
      </details>
    </div>
  );
}