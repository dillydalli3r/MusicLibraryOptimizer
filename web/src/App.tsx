import { useEffect } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Library, ListMusic, Import, Settings as SettingsIcon, RefreshCw, Play, ArrowDownUp } from "lucide-react";
import { api } from "./api";
import { useStore } from "./store";
import LibraryPage from "./pages/LibraryPage";
import ArtistPage from "./pages/ArtistPage";
import AlbumPage from "./pages/AlbumPage";
import TrackPage from "./pages/TrackPage";
import PlaylistsPage from "./pages/PlaylistsPage";
import SettingsPage from "./pages/SettingsPage";
import SetupPage from "./pages/SetupPage";
import SoulseekPage from "./pages/SoulseekPage";
import PlayerBar from "./components/PlayerBar";
import ImportWizard from "./pages/ImportWizard";
import { ProgressBar } from "./components/ProgressBar";

const NAV = [
  { to: "/", label: "Library", icon: Library, end: true },
  { to: "/playlists", label: "Playlists", icon: ListMusic, end: false },
  { to: "/import", label: "Import", icon: Import, end: false },
  { to: "/soulseek", label: "Soulseek", icon: ArrowDownUp, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

const ACCENTS: Record<string, [string, string, string]> = {
  violet: ["139 92 246", "167 139 250", "255 255 255"],
  pink: ["236 72 153", "249 168 212", "255 255 255"],
  emerald: ["16 185 129", "110 231 183", "255 255 255"],
  sky: ["14 165 233", "125 211 252", "255 255 255"],
  amber: ["245 158 11", "252 211 77", "24 24 27"],
  red: ["239 68 68", "252 165 165", "255 255 255"],
  mono: ["255 255 255", "212 212 216", "9 9 11"],
};

export function applyAccent(name: string | null) {
  const [accent, soft, fg] = ACCENTS[name ?? "mono"] ?? ACCENTS.mono;
  document.documentElement.style.setProperty("--accent", accent);
  document.documentElement.style.setProperty("--accent-soft", soft);
  document.documentElement.style.setProperty("--accent-fg", fg);
}

export default function App() {
  const { progress, setProgress, toast: toastMsg, setToast } = useStore();
  const qc = useQueryClient();

  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config });

  useEffect(() => {
    applyAccent(localStorage.getItem("mlo.accent"));
  }, []);

  useEffect(() => {
    const inTauri = !!(window as any).__TAURI_INTERNALS__;
    const wsBase = inTauri ? "ws://127.0.0.1:8000" : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
    const ws = new WebSocket(`${wsBase}/ws/progress`);
    ws.onmessage = (e) => {
      try {
        setProgress(JSON.parse(e.data));
      } catch {
        /* ignore */
      }
    };
    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runAll = async () => {
    setToast("Running all scripts…");
    try {
      const order = Array.isArray(config?.run_all_order)
        ? config.run_all_order.filter((n) => n >= 1 && n <= 11)
        : [11, 1, 2, 8, 3, 5, 9, 6, 4, 7, 10];
      const res = await api.run(order.length ? order : [1, 2, 8, 3, 5, 9, 6, 4, 7, 10]);
      const failed = (res.results ?? []).filter((r) => r.error);
      setToast(
        failed.length
          ? `${failed.length} script(s) failed — see console`
          : "Run All finished"
      );
    } catch (e) {
      setToast(String(e));
    } finally {
      qc.invalidateQueries({ queryKey: ["library"] });
    }
  };

  // First-run gate: no music folder (or setup not completed) → setup wizard.
  if (config && (!String(config.music_folder ?? "").trim() || !config.first_run_done)) {
    return (
      <Routes>
        <Route path="/setup" element={<SetupPage />} />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
    );
  }

  return (
    <div className="min-h-screen bg-bg text-zinc-100 flex flex-col">
      <header className="h-14 shrink-0 border-b border-border bg-panel flex items-center gap-3 px-4 sticky top-0 z-30">
        <div className="flex items-center gap-2">
          <span className="h-7 w-7 rounded-md bg-white text-black flex items-center justify-center shadow-sm">
            <Play className="h-3.5 w-3.5 fill-current" />
          </span>
          <span className="font-bold tracking-wide">MusicLibraryOptimizer</span>
          <span className="chip bg-raise border border-border text-zinc-400">v2</span>
        </div>
        <span className="hidden md:block text-xs text-zinc-500 truncate">
          {config?.music_folder ? String(config.music_folder) : "music folder not set"}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button className="btn-ghost text-xs" onClick={() => qc.invalidateQueries({ queryKey: ["library"] })}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
          <button className="btn-primary text-xs" onClick={runAll}>
            <Play className="h-3.5 w-3.5" /> Run All
          </button>
        </div>
      </header>

      <ProgressBar progress={progress} />

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-48 shrink-0 border-r border-border bg-panel p-3 flex flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors border ${
                  isActive
                    ? "bg-raise text-white border-accent/40"
                    : "text-zinc-400 hover:text-white hover:bg-panel border-transparent"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
          <div className="mt-auto text-[10px] text-zinc-600 px-3 py-2">
            Grading · Auditing · Optimization
            <br />
            MusicBrainz · LRCLIB · RYM
          </div>
        </aside>

        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<LibraryPage />} />
            <Route path="/artist/:path" element={<ArtistPage />} />
            <Route path="/album/:path" element={<AlbumPage />} />
            <Route path="/track/:path" element={<TrackPage />} />
            <Route path="/playlists" element={<PlaylistsPage />} />
            <Route path="/soulseek" element={<SoulseekPage />} />
            <Route path="/import" element={<ImportWizard />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/setup" element={<Navigate to="/" replace />} />
            <Route
              path="*"
              element={
                <div className="p-10 text-center text-sm text-zinc-500">
                  Page not found —{" "}
                  <NavLink to="/" className="text-accent-soft hover:underline">
                    back to the library
                  </NavLink>
                </div>
              }
            />
          </Routes>
        </main>
      </div>

      <PlayerBar />

      {toastMsg && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 rounded-lg border border-accent/40 bg-panel px-4 py-2 text-sm shadow-xl">
          {toastMsg}
        </div>
      )}
    </div>
  );
}