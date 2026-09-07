import { useEffect, useRef, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownUp, ChevronLeft, ChevronRight, Gauge, HardDriveDownload, Heart, Import,
  Library, ListMusic, Music4, PanelLeftClose, PanelLeftOpen, Search,
  Settings as SettingsIcon, Wrench,
} from "lucide-react";
import { api } from "./api";
import { useStore } from "./store";
import LibraryPage from "./pages/LibraryPage";
import ArtistPage from "./pages/ArtistPage";
import AlbumPage from "./pages/AlbumPage";
import TrackPage from "./pages/TrackPage";
import PlaylistsPage from "./pages/PlaylistsPage";
import FavoritesPage from "./pages/FavoritesPage";
import SettingsPage from "./pages/SettingsPage";
import SetupPage from "./pages/SetupPage";
import SoulseekPage from "./pages/SoulseekPage";
import ExportPage from "./pages/ExportPage";
import OptimizationPage from "./pages/OptimizationPage";
import DependenciesPage from "./pages/DependenciesPage";
import {
  MBSearchPage, MBArtistPage, MBReleaseGroupPage, MBReleasePage, MBRecordingPage,
} from "./pages/MusicBrainzPage";
import PlayerBar from "./components/PlayerBar";
import ImportWizard from "./pages/ImportWizard";
import { ProgressInline } from "./components/ProgressBar";

const NAV = [
  { to: "/", label: "Library", icon: Library, end: true },
  { to: "/playlists", label: "Playlists", icon: ListMusic, end: false },
  { to: "/favorites", label: "Favorites", icon: Heart, end: false },
  { to: "/import", label: "Import", icon: Import, end: false },
  { to: "/soulseek", label: "Soulseek", icon: ArrowDownUp, end: false },
  { to: "/export", label: "Export", icon: HardDriveDownload, end: false },
  { to: "/optimize", label: "Optimization", icon: Gauge, end: false },
  { to: "/dependencies", label: "Dependencies", icon: Wrench, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

const COLLAPSE_KEY = "mlo.sidebar.collapsed";

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
  const { progress, setProgress, toast: toastMsg, query, setQuery } = useStore();
  const progressClear = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config });

  // ---- navigation history (top-bar back / forward) ------------------------
  const location = useLocation();
  const navigate = useNavigate();
  // The stack itself lives in a ref (mutations shouldn't re-render), but the
  // position is STATE: a ref-only position never triggers a re-render, so
  // the Back/Forward buttons would render with a stale `disabled` flag.
  const stackRef = useRef<string[]>([location.pathname]);
  const [pos, setPos] = useState(0);
  useEffect(() => {
    // Record navigations into the history stack. Back/forward moves update
    // pos BEFORE navigating, and the router update can land in a separate
    // commit from the setPos — so each pass below reconciles towards the
    // observed path instead of assuming a fresh navigation.
    const stack = stackRef.current;
    if (stack[pos] === location.pathname) return; // already in place
    // the router landed on the entry just behind / ahead of us → that was a
    // back / forward move, just adopt its position
    if (pos > 0 && stack[pos - 1] === location.pathname) {
      setPos(pos - 1);
      return;
    }
    if (pos < stack.length - 1 && stack[pos + 1] === location.pathname) {
      setPos(pos + 1);
      return;
    }
    // otherwise it's a new jump: drop the forward entries and append
    stack.splice(pos + 1);
    stack.push(location.pathname);
    setPos(stack.length - 1);
  }, [location.pathname, pos]);
  const goBack = () => {
    if (pos > 0) {
      setPos(pos - 1);
      navigate(stackRef.current[pos - 1]);
    }
  };
  const goForward = () => {
    if (pos < stackRef.current.length - 1) {
      setPos(pos + 1);
      navigate(stackRef.current[pos + 1]);
    }
  };

  // Global search lives in the top bar and drives the library filter from
  // anywhere — typing on another page jumps to the library. The dropdown
  // below the input offers the MusicBrainz browser (and recognizes pasted
  // musicbrainz.org links).
  const [searchOpen, setSearchOpen] = useState(false);
  const onSearch = (q: string) => {
    setQuery(q);
    if (location.pathname !== "/") navigate("/");
  };
  const goMbSearch = () => {
    setSearchOpen(false);
    navigate(`/mb/search?q=${encodeURIComponent(query.trim())}`);
  };
  const mbLink = /^(?:https?:\/\/)?(?:www\.)?musicbrainz\.org\/(artist|release-group|release|recording)\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i.exec(
    query.trim()
  );

  // ---- collapsible sidebar (icons-only rail) ------------------------------
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const toggleCollapse = () => {
    const v = !collapsed;
    setCollapsed(v);
    localStorage.setItem(COLLAPSE_KEY, v ? "1" : "0");
  };

  useEffect(() => {
    applyAccent(localStorage.getItem("mlo.accent"));
  }, []);

  useEffect(() => {
    const inTauri = !!(window as any).__TAURI_INTERNALS__;
    // window.location (not the router's location object) — this is a URL.
    const wsBase = inTauri ? "ws://127.0.0.1:8000" : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
    const ws = new WebSocket(`${wsBase}/ws/progress`);
    ws.onmessage = (e) => {
      try {
        const p = JSON.parse(e.data);
        if (typeof p?.done !== "number") return; // ping / non-progress frame
        setProgress(p);
        // The relay never sends an explicit "finished" frame — clear the
        // indicator shortly after the bar completes.
        if (progressClear.current) clearTimeout(progressClear.current);
        if (p.total && p.done >= p.total) {
          progressClear.current = setTimeout(() => setProgress(null), 2500);
        }
      } catch {
        /* ignore */
      }
    };
    return () => {
      ws.close();
      if (progressClear.current) clearTimeout(progressClear.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    // The sidebar owns the entire left edge, top to bottom (brand header, nav,
    // footer); the top bar, content and player bar all live in the column to
    // its right.
    <div className="h-screen overflow-hidden bg-bg text-zinc-100 flex">
      <aside
        className={`${collapsed ? "w-14" : "w-48"} h-full shrink-0 border-r border-border bg-panel p-2 flex flex-col gap-1 overflow-y-auto transition-[width] duration-150`}
      >
        {/* sidebar header: brand + collapse toggle, split from the nav by a
            hairline. Collapses to a stacked icon rail. */}
        <div
          className={`flex items-center gap-2 border-b border-border pb-2 mb-1 shrink-0 ${
            collapsed ? "flex-col pt-1 gap-1.5" : "px-1"
          }`}
        >
          <img
            src="/icon.png"
            alt="la musica"
            className="h-7 w-7 rounded-md object-cover ring-1 ring-border shadow-sm shrink-0"
          />
          {!collapsed && <span className="flex-1 font-bold tracking-tight text-sm truncate">la musica</span>}
          <button
            className="p-1.5 rounded-lg text-zinc-500 hover:text-white hover:bg-raise transition-colors"
            onClick={toggleCollapse}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              // Monochrome-style: the active entry is a solid accent block
              // with contrast text; inactive ones stay quiet.
              `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors border ${
                isActive
                  ? "bg-accent on-accent font-semibold border-transparent shadow-sm"
                  : "text-zinc-400 hover:text-white hover:bg-raise border-transparent"
              } ${collapsed ? "justify-center px-0" : ""}`
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && label}
          </NavLink>
        ))}
        {!collapsed && (
          <div className="mt-auto text-[10px] text-zinc-600 px-3 pb-2">
            Grading · Auditing · Optimization
            <br />
            MusicBrainz · LRCLIB · RYM
          </div>
        )}
      </aside>

      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* top bar (right of the sidebar): back / forward immediately left of
            the global search, live progress on the right. */}
        <header className="h-12 shrink-0 bg-bg flex items-center gap-3 px-4 z-30 relative">
          <div className="flex items-center gap-1 shrink-0">
            <button
              className="p-1.5 rounded-lg text-zinc-300 hover:bg-raise hover:text-white disabled:opacity-30 disabled:pointer-events-none transition-colors"
              onClick={goBack}
              disabled={pos === 0}
              title="Back"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              className="p-1.5 rounded-lg text-zinc-300 hover:bg-raise hover:text-white disabled:opacity-30 disabled:pointer-events-none transition-colors"
              onClick={goForward}
              disabled={pos >= stackRef.current.length - 1}
              title="Forward"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          {/* the search input spans the rest of the bar */}
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
            <input
              className="input !py-2 !pl-10 text-xs w-full"
              placeholder="Search for tracks, artists, albums…"
              value={query}
              onChange={(e) => onSearch(e.target.value)}
              onFocus={() => setSearchOpen(true)}
              onBlur={() => setTimeout(() => setSearchOpen(false), 150)}
            />
            {searchOpen && query.trim() && (
              <div className="absolute left-0 right-0 top-full mt-1 z-40 rounded-lg border border-border bg-zinc-950/95 backdrop-blur shadow-xl overflow-hidden">
                {mbLink ? (
                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs text-zinc-200 hover:bg-raise transition-colors text-left"
                    onClick={() => {
                      setSearchOpen(false);
                      navigate(`/mb/${mbLink[1] === "release-group" ? "rg" : mbLink[1]}/${mbLink[2]}`);
                    }}
                  >
                    <Music4 className="h-4 w-4 text-accent-soft shrink-0" />
                    Open this MusicBrainz {mbLink[1].replace("-", " ")} in the browser
                  </button>
                ) : (
                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs text-zinc-200 hover:bg-raise transition-colors text-left"
                    onClick={goMbSearch}
                  >
                    <Music4 className="h-4 w-4 text-accent-soft shrink-0" />
                    Search MusicBrainz for “{query.trim()}”
                  </button>
                )}
              </div>
            )}
          </div>
          {/* live script progress floats below the bar so the search keeps
              the full width */}
          {progress && (
            <div className="absolute right-4 top-full mt-1 z-40">
              <ProgressInline progress={progress} />
            </div>
          )}
        </header>

        <main className="flex-1 overflow-auto min-w-0">
          {/* keyed by pathname so each navigation eases the new page in */}
          <div key={location.pathname} className="page-enter">
            <Routes>
            <Route path="/" element={<LibraryPage />} />
            <Route path="/artist/:path" element={<ArtistPage />} />
            <Route path="/album/:path" element={<AlbumPage />} />
            <Route path="/track/:path" element={<TrackPage />} />
            <Route path="/playlists" element={<PlaylistsPage />} />
            <Route path="/favorites" element={<Navigate to="/favorites/tracks" replace />} />
            <Route path="/favorites/:kind" element={<FavoritesPage />} />
            <Route path="/soulseek" element={<SoulseekPage />} />
            <Route path="/export" element={<ExportPage />} />
            <Route path="/optimize" element={<OptimizationPage />} />
            <Route path="/dependencies" element={<DependenciesPage />} />
            {/* MusicBrainz browser */}
            <Route path="/mb" element={<Navigate to="/mb/search" replace />} />
            <Route path="/mb/search" element={<MBSearchPage />} />
            <Route path="/mb/artist/:id" element={<MBArtistPage />} />
            <Route path="/mb/rg/:id" element={<MBReleaseGroupPage />} />
            <Route path="/mb/release/:id" element={<MBReleasePage />} />
            <Route path="/mb/recording/:id" element={<MBRecordingPage />} />
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
          </div>
        </main>

        <PlayerBar />
      </div>

      {toastMsg && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 rounded-lg border border-accent/40 bg-panel px-4 py-2 text-sm shadow-xl">
          {toastMsg}
        </div>
      )}
    </div>
  );
}
