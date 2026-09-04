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

const ENCODER_FORMATS = ["flac", "jpeg", "png", "jxl"] as const;
const ENCODER_FIELDS = ["ENCODER_PROGRAM", "ENCODER_QUALITY", "ENCODER_VERSION"] as const;
const AUDIO_TYPES = ["flac", "mp3", "mp4", "ogg", "opus", "aac"] as const;
const TAG_FAMILIES = ["AUDIT", "LOG_GRADE", "REPLAYGAIN", "DYNAMIC_RANGE", "MEDIA_SOURCE", "INSTRUMENTAL", "ADVISORY", "LYRICS"] as const;

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
        { k: "reencode_images", label: "Re-encode images (master switch)", type: "bool" },
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
        { k: "lrc_zero_timestamp_blank", label: "Zero timestamp is blank line", type: "bool" },
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
        { k: "audit_check_cd_format", label: "Verify CD format (16/44.1)", type: "bool" },
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
      blurb: "Which tag families may be written at all. Per-filetype overrides and encoder marker tags are below.",
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
      title: "CD Rips (scripts 2/6/9/10)",
      blurb: "Deterministic CD-N renaming of .log/.cue/.accurip and conservative CUE FILE-name fixes.",
      fields: [
        { k: "discs_rename_enabled", label: "Auto-rename disc sheets to CD-{n}", type: "bool" },
        { k: "discs_rename_single_fallback", label: "Rename lone sheet in single-disc album", type: "bool" },
        { k: "discs_rename_pattern", label: "Rename pattern (must contain {n})", type: "text" },
        { k: "discs_toc_tolerance_s", label: "TOC tolerance (s)", type: "number", min: 0.5, max: 10, step: 0.5 },
        { k: "discs_toc_unique_margin_s", label: "TOC unique margin (s)", type: "number", min: 0.5, max: 10, step: 0.5 },
        { k: "cue_fix_filenames", label: "Fix CUE FILE lines to real files", type: "bool" },
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
    {
      title: "Videos (script 11)",
      blurb: "Lossless remux: any video container → MP4. Video stream is copied when MP4-compatible (h264/hevc/mpeg4/av1/vp9); all audio streams are re-encoded to FLAC (lossless).",
      fields: [
        { k: "video_reencode_incompatible", label: "Re-encode incompatible video to H.264", type: "bool" },
        { k: "video_crf", label: "H.264 CRF (lower = better)", type: "number", min: 0, max: 51 },
        { k: "video_preset", label: "H.264 preset", type: "select", options: [["ultrafast","ultrafast"],["superfast","superfast"],["veryfast","veryfast"],["faster","faster"],["fast","fast"],["medium","medium"],["slow","slow"],["slower","slower"],["veryslow","veryslow"]] },
        { k: "video_flac_level", label: "FLAC compression (0-8)", type: "number", min: 0, max: 8 },
        { k: "video_remove_original", label: "Remove original after verified remux", type: "bool" },
        { k: "video_process_mp4", label: "Also normalize MP4s without FLAC audio", type: "bool" },
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
  const [rawConfig, setRawConfig] = useState("{}");
  const [tab, setTab] = useState("general");
  const [runAll, setRunAll] = useState<number[]>([11, 1, 2, 8, 3, 5, 9, 6, 4, 7, 10]);

  const RUN_ALL_SCRIPTS: { id: number; label: string }[] = [
    { id: 11, label: "Video Remux" },
    { id: 1, label: "Lyrics" },
    { id: 2, label: "CUEs" },
    { id: 8, label: "AutoTag" },
    { id: 3, label: "FLACs" },
    { id: 5, label: "Images" },
    { id: 9, label: "AccurateRip" },
    { id: 6, label: "Audit" },
    { id: 4, label: "Grade" },
    { id: 7, label: "DR / ReplayGain" },
    { id: 10, label: "Format All" },
  ];

  const NAV: { id: string; label: string; section?: string }[] = [
    { id: "general", label: "General" },
    { id: "appearance", label: "Appearance" },
    { id: "naming", label: "File naming" },
    { id: "deps", label: "Dependencies" },
    { id: "flac", label: "FLACs", section: "Scripts" },
    { id: "images", label: "Images", section: "Scripts" },
    { id: "lyrics", label: "Lyrics & CUEs", section: "Scripts" },
    { id: "dr", label: "DR / ReplayGain", section: "Scripts" },
    { id: "audit", label: "Audit", section: "Scripts" },
    { id: "autotag", label: "AutoTag", section: "Scripts" },
    { id: "accurip", label: "AccurateRip", section: "Scripts" },
    { id: "cdrips", label: "CD Rips", section: "Scripts" },
    { id: "videos", label: "Videos", section: "Scripts" },
    { id: "tagwrites", label: "Tag writes", section: "Scripts" },
    { id: "grading", label: "Grading", section: "Scripts" },
  ];

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
    const enc = (config.encoder_tags ?? {}) as Record<string, Record<string, boolean>>;
    const aw = (config.audio_tag_writes ?? {}) as Record<string, Record<string, boolean>>;
    setEncoderTags(
      Object.fromEntries(
        ENCODER_FORMATS.map((fmt) => [fmt, Object.fromEntries(ENCODER_FIELDS.map((f) => [f, !!enc[fmt]?.[f]]))])
      )
    );
    setAudioTagWrites(
      Object.fromEntries(
        AUDIO_TYPES.map((t) => [t, Object.fromEntries(TAG_FAMILIES.map((fam) => [fam, aw[t]?.[fam] ?? true]))])
      )
    );
    setRawConfig(JSON.stringify(config, null, 2));
    setRunAll(Array.isArray(config.run_all_order) ? config.run_all_order.map(Number).filter((n) => n >= 1 && n <= 11) : [11, 1, 2, 8, 3, 5, 9, 6, 4, 7, 10]);
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
        encoder_tags: encoderTags,
        audio_tag_writes: audioTagWrites,
        music_folder: musicFolder,
        lyrics_format: lyricsFormat,
        worker_limit: workerLimit,
        naming_script: namingScript,
        short_folder_names: shortFolderNames,
        run_all_order: runAll,
      });
      toast("Config saved");
      qc.invalidateQueries({ queryKey: ["config"] });
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    }
  };

  const applyRaw = () => {
    try {
      const parsed = JSON.parse(rawConfig) as Record<string, unknown>;
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("expected an object");
      const enc = (parsed.encoder_tags ?? {}) as Record<string, Record<string, boolean>>;
      const aw = (parsed.audio_tag_writes ?? {}) as Record<string, Record<string, boolean>>;
      setScriptCfg(Object.fromEntries(ALL_CFG_KEYS.map((k) => [k, parsed[k]])));
      setEncoderTags(
        Object.fromEntries(
          ENCODER_FORMATS.map((fmt) => [fmt, Object.fromEntries(ENCODER_FIELDS.map((f) => [f, !!enc[fmt]?.[f]]))])
        )
      );
      setAudioTagWrites(
        Object.fromEntries(
          AUDIO_TYPES.map((t) => [t, Object.fromEntries(TAG_FAMILIES.map((fam) => [fam, aw[t]?.[fam] ?? true]))])
        )
      );
      setMusicFolder(String(parsed.music_folder ?? musicFolder));
      setLyricsFormat(String(parsed.lyrics_format ?? lyricsFormat));
      setWorkerLimit(Number(parsed.worker_limit ?? workerLimit));
      setNamingScript(String(parsed.naming_script ?? "") || namingScript);
      setShortFolderNames(!!parsed.short_folder_names);
      setRunAll(Array.isArray(parsed.run_all_order) ? parsed.run_all_order.map(Number).filter((n: number) => n >= 1 && n <= 11) : runAll);
      toast("Raw config applied — click Save all settings to persist");
    } catch (e) {
      toast("Invalid JSON: " + String(e));
    }
  };

  const GROUP_BY_TAB: Record<string, CfgGroup> = {
    flac: CFG_GROUPS[0], images: CFG_GROUPS[1], lyrics: CFG_GROUPS[2],
    dr: CFG_GROUPS[3], audit: CFG_GROUPS[4], autotag: CFG_GROUPS[5],
    accurip: CFG_GROUPS[6], tagwrites: CFG_GROUPS[7], grading: CFG_GROUPS[8],
    cdrips: CFG_GROUPS[9], videos: CFG_GROUPS[10],
  };

  const [encoderTags, setEncoderTags] = useState<Record<string, Record<string, boolean>>>({});
  const toggleEncoder = (fmt: string, field: string, on: boolean) =>
    setEncoderTags((e) => ({ ...e, [fmt]: { ...e[fmt], [field]: on } }));

  const [audioTagWrites, setAudioTagWrites] = useState<Record<string, Record<string, boolean>>>({});
  const toggleTagWrite = (ftype: string, fam: string, on: boolean) =>
    setAudioTagWrites((a) => ({ ...a, [ftype]: { ...a[ftype], [fam]: on } }));

  const { data: deps, refetch: refetchDeps } = useQuery({
    queryKey: ["dependencies"],
    queryFn: api.dependencies,
    retry: false,
  });
  const [depsBusy, setDepsBusy] = useState(false);

  const installDeps = async (keys?: string[]) => {
    setDepsBusy(true);
    try {
      const r = await api.installDependencies(keys);
      const failed = r.results.filter((x) => !x.ok);
      toast(failed.length ? "Install finished with " + failed.length + " failure(s)" : "Dependencies installed / updated");
      refetchDeps();
    } catch (e) {
      toast(String(e));
    } finally {
      setDepsBusy(false);
    }
  };

  const renderFields = (fields: CfgField[]) => (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5 mt-1.5">
      {fields.map((f) => (
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
  );

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>

      <div className="flex gap-6 mt-4">
        <nav className="w-44 shrink-0 space-y-0.5 sticky top-20 self-start max-h-[calc(100vh-120px)] overflow-auto pr-1">
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => setTab(n.id)}
              className={`w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors ${
                tab === n.id ? "bg-raise text-white border border-accent/40" : "text-zinc-400 hover:text-white hover:bg-panel border border-transparent"
              }`}
            >
              {n.label}
            </button>
          ))}
        </nav>

        <div className="flex-1 min-w-0 space-y-5 pb-10">
          {tab === "general" && (
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
              <div className="flex flex-wrap gap-x-6 gap-y-1.5">
                <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
                  <input type="checkbox" checked={!!scriptCfg.auto_advance} onChange={(e) => setCfg("auto_advance", e.target.checked)} />
                  Auto-advance between Run All scripts
                </label>
                <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
                  <input type="checkbox" checked={!!scriptCfg.show_sidecar_files} onChange={(e) => setCfg("show_sidecar_files", e.target.checked)} />
                  Show sidecar files (cue/log/lrc/accurip) in library
                </label>
              </div>
              <div>
                <span className="text-xs text-zinc-500 uppercase">Run All — scripts in order</span>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5 mt-1.5">
                  {RUN_ALL_SCRIPTS.map((s) => (
                    <label key={s.id} className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={runAll.includes(s.id)}
                        onChange={(e) =>
                          setRunAll((ids) => (e.target.checked ? [...ids, s.id] : ids.filter((i) => i !== s.id)))
                        }
                      />
                      <span className="text-zinc-600 w-4">{s.id}</span>
                      {s.label}
                    </label>
                  ))}
                </div>
                <div className="text-[10px] text-zinc-600 mt-1">The Run All button executes them in this order.</div>
              </div>
            </div>
          )}

          {tab === "appearance" && (
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
          )}

          {tab === "naming" && (
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
                Functions: <code>$if(a,b,c) $left(s,n) $num(s,n) $lower $upper $replace $ne $right</code> · <code>/</code> creates folders.
                Applied from the album page or the bulk selection toolbar.
              </div>
              <div className="flex items-center gap-4 flex-wrap">
                <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none">
                  <input type="checkbox" checked={shortFolderNames} onChange={(e) => setShortFolderNames(e.target.checked)} />
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
          )}

          {tab === "deps" && (
            <div className="bg-card rounded-lg border border-border p-4 space-y-3">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Dependencies</div>
                  <div className="text-[11px] text-zinc-600 mt-0.5">
                    Tools the scripts need. Installed from <code className="font-mono">{deps?.deps_dir ?? ".dependencies"}</code> or found on PATH.
                  </div>
                </div>
                <div className="flex gap-2">
                  <button className="btn-ghost !py-1 text-xs" onClick={() => refetchDeps()} disabled={depsBusy}>
                    Refresh
                  </button>
                  <button
                    className="btn-ghost !py-1 text-xs"
                    onClick={() => installDeps(deps?.tools.filter((t) => t.state === "missing").map((t) => t.key))}
                    disabled={depsBusy}
                  >
                    Install missing
                  </button>
                  <button className="btn-primary !py-1 text-xs" onClick={() => installDeps()} disabled={depsBusy}>
                    {depsBusy ? "Installing…" : "Install / update all"}
                  </button>
                </div>
              </div>
              <div className="rounded-md border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-panel/60">
                    <tr>
                      <th className="th">Tool</th>
                      <th className="th">Status</th>
                      <th className="th">Installed</th>
                      <th className="th">Latest</th>
                      <th className="th">Path</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(deps?.tools ?? []).map((t) => (
                      <tr key={t.key} className="table-row cursor-default">
                        <td className="td font-medium">{t.name}</td>
                        <td className="td">
                          {t.state === "ok" && <span className="chip bg-emerald-900/50 text-emerald-300 border border-emerald-800">ready</span>}
                          {t.state === "update" && <span className="chip bg-amber-900/50 text-amber-300 border border-amber-900">update</span>}
                          {t.state === "missing" && <span className="chip bg-red-900/50 text-red-300 border border-red-900">missing</span>}
                        </td>
                        <td className="td text-zinc-500">{t.installed_version ?? t.detected_version ?? "—"}</td>
                        <td className="td text-zinc-500">{t.latest_version ?? "—"}</td>
                        <td className="td text-zinc-500 truncate max-w-[280px]">{t.path ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="text-[10px] text-zinc-600">
                Install downloads the pinned release from GitHub into the dependencies folder; PATH-installed tools (scoop etc.) are shown as ready.
              </div>
            </div>
          )}

          {GROUP_BY_TAB[tab] && (
            <div className="bg-card rounded-lg border border-border p-4 space-y-3">
              <div className="text-xs font-bold text-zinc-300">{GROUP_BY_TAB[tab].title}</div>
              {GROUP_BY_TAB[tab].blurb && <div className="text-[10px] text-zinc-600">{GROUP_BY_TAB[tab].blurb}</div>}
              {renderFields(GROUP_BY_TAB[tab].fields)}
              {tab === "tagwrites" && (
                <>
                  <div className="pt-2 border-t border-border">
                    <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Per-filetype tag writes</div>
                    <div className="text-[10px] text-zinc-600 mt-0.5 mb-1.5">
                      Which tag families each audio container receives (ANDed with the global switches above).
                    </div>
                    <table className="w-full text-xs">
                      <thead>
                        <tr>
                          <th className="text-left text-zinc-500 font-medium py-1">Type</th>
                          {TAG_FAMILIES.map((fam) => (
                            <th key={fam} className="text-zinc-500 font-medium py-1">{fam}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {AUDIO_TYPES.map((t) => (
                          <tr key={t}>
                            <td className="py-0.5 text-zinc-300">{t}</td>
                            {TAG_FAMILIES.map((fam) => (
                              <td key={fam} className="py-0.5">
                                <input
                                  type="checkbox"
                                  className="accent-[var(--accent)]"
                                  checked={!!audioTagWrites[t]?.[fam]}
                                  onChange={(e) => toggleTagWrite(t, fam, e.target.checked)}
                                />
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="pt-2 border-t border-border">
                    <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Encoder marker tags</div>
                    <div className="text-[10px] text-zinc-600 mt-0.5 mb-1.5">
                      Written to files when re-encoded. QUALITY/VERSION gate re-optimization; PROGRAM is informational.
                    </div>
                    <table className="w-full text-xs">
                      <thead>
                        <tr>
                          <th className="text-left text-zinc-500 font-medium py-1">Format</th>
                          {ENCODER_FIELDS.map((f) => (
                            <th key={f} className="text-zinc-500 font-medium py-1">{f}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {ENCODER_FORMATS.map((fmt) => (
                          <tr key={fmt}>
                            <td className="py-0.5 text-zinc-300">{fmt}</td>
                            {ENCODER_FIELDS.map((f) => (
                              <td key={f} className="py-0.5">
                                <input
                                  type="checkbox"
                                  className="accent-[var(--accent)]"
                                  checked={!!encoderTags[fmt]?.[f]}
                                  onChange={(e) => toggleEncoder(fmt, f, e.target.checked)}
                                />
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}

          {tab === "grading" && (
            <details className="bg-card rounded-lg border border-border p-4" open>
              <summary className="text-sm font-semibold cursor-pointer">Individual grading checks ({GRADE_CHECK_KEYS.length})</summary>
              <div className="mt-2">{renderFields(GRADE_CHECK_KEYS)}</div>
            </details>
          )}

          <button className="btn-primary" onClick={save}>
            <Save className="h-4 w-4" /> Save all settings
          </button>

          <details className="bg-card rounded-lg border border-border p-4">
            <summary className="text-sm font-semibold cursor-pointer">Raw config (advanced)</summary>
            <textarea
              className="input font-mono text-[11px] min-h-[220px] mt-2"
              value={rawConfig}
              onChange={(e) => setRawConfig(e.target.value)}
              spellCheck={false}
            />
            <div className="flex items-center gap-2 mt-2">
              <button className="btn-ghost !py-1 text-xs" onClick={applyRaw}>
                Apply to form
              </button>
              <span className="text-[10px] text-zinc-600">
                Edits the form fields (then click Save all settings). Invalid JSON is rejected.
              </span>
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}