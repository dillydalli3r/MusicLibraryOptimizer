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

  useEffect(() => {
    if (!config || loaded) return;
    setMusicFolder(String(config.music_folder ?? ""));
    setLyricsFormat(String(config.lyrics_format ?? "EMBEDDED"));
    setWorkerLimit(Number(config.worker_limit ?? 0));
    setNamingScript(String(config.naming_script ?? "") || DEFAULT_NAMING_SCRIPT);
    setShortFolderNames(!!config.short_folder_names);
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

      <details className="bg-card rounded-lg border border-border p-4">
        <summary className="text-sm font-semibold cursor-pointer">Raw config (advanced)</summary>
        <pre className="mt-2 text-xs text-zinc-400 overflow-auto max-h-80">{JSON.stringify(config, null, 2)}</pre>
      </details>
    </div>
  );
}