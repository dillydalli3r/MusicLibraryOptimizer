import { useEffect } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Library, ListMusic, Import, Settings as SettingsIcon, RefreshCw, Play } from "lucide-react";
import { api } from "./api";
import { useStore } from "./store";
import LibraryPage from "./pages/LibraryPage";
import ArtistPage from "./pages/ArtistPage";
import AlbumPage from "./pages/AlbumPage";
import TrackPage from "./pages/TrackPage";
import PlaylistsPage from "./pages/PlaylistsPage";
import SettingsPage from "./pages/SettingsPage";
import PlayerBar from "./components/PlayerBar";
import ImportWizard from "./pages/ImportWizard";
import { ProgressBar } from "./components/ProgressBar";

const NAV = [
  { to: "/", label: "Library", icon: Library, end: true },
  { to: "/playlists", label: "Playlists", icon: ListMusic, end: false },
  { to: "/import", label: "Import", icon: Import, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

export default function App() {
  const { progress, setProgress, toast: toastMsg } = useStore();
  const qc = useQueryClient();

  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config });

  useEffect(() => {
    const ws = new WebSocket(
      `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/progress`
    );
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
    await api.run([1, 2, 8, 3, 5, 9, 6, 4, 7, 10]);
    qc.invalidateQueries({ queryKey: ["library"] });
  };

  return (
    <div className="min-h-screen bg-bg text-zinc-100 flex flex-col">
      <header className="h-14 shrink-0 border-b border-border bg-panel flex items-center gap-3 px-4 sticky top-0 z-30">
        <div className="flex items-center gap-2">
          <span className="h-7 w-7 rounded-md bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
            <Play className="h-3.5 w-3.5 text-white fill-white" />
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
                `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-raise text-white border border-border"
                    : "text-zinc-400 hover:text-white hover:bg-panel"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
          <div className="mt-auto text-[10px] text-zinc-600 px-3 py-2">
            Grading · Auditing · Tagging
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
            <Route path="/import" element={<ImportWizard />} />
            <Route path="/settings" element={<SettingsPage />} />
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