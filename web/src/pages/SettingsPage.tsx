import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Save } from "lucide-react";
import { api } from "../api";
import { toast } from "../store";

export default function SettingsPage() {
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config });
  const qc = useQueryClient();
  const [musicFolder, setMusicFolder] = useState("");
  const [lyricsFormat, setLyricsFormat] = useState("EMBEDDED");
  const [workerLimit, setWorkerLimit] = useState(0);

  const apply = () => {
    if (config) {
      setMusicFolder(String(config.music_folder ?? ""));
      setLyricsFormat(String(config.lyrics_format ?? "EMBEDDED"));
      setWorkerLimit(Number(config.worker_limit ?? 0));
    }
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
      await api.saveConfig({ ...config, music_folder: musicFolder, lyrics_format: lyricsFormat, worker_limit: workerLimit });
      toast("Config saved");
      qc.invalidateQueries({ queryKey: ["config"] });
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      toast(String(e));
    }
  };

  return (
    <div className="p-6 max-w-2xl space-y-5">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>

      {!config ? (
        <button className="btn-primary" onClick={apply}>Load config</button>
      ) : (
        <>
          <div className="bg-card rounded-lg border border-border p-4 space-y-3">
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
            <button className="btn-primary" onClick={save}>
              <Save className="h-4 w-4" /> Save
            </button>
          </div>

          <details className="bg-card rounded-lg border border-border p-4">
            <summary className="text-sm font-semibold cursor-pointer">Raw config (advanced)</summary>
            <pre className="mt-2 text-xs text-zinc-400 overflow-auto max-h-80">{JSON.stringify(config, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}