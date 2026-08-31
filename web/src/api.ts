// In the Tauri desktop shell the frontend is served from tauri://localhost,
// so relative /api paths cannot reach the Python backend — use absolute.
const IN_TAURI = !!(window as any).__TAURI_INTERNALS__;
const BASE = IN_TAURI ? "http://127.0.0.1:8000" : "";
const API = `${BASE}/api`;

async function json<T>(url: string, init?: RequestInit, timeoutMs = 20000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let r: Response;
  try {
    r = await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = j.detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => json<{ status: string; version: string }>(`${API}/health`),
  config: () => json<Record<string, unknown>>(`${API}/config`),
  saveConfig: (cfg: Record<string, unknown>) =>
    json<Record<string, unknown>>(`${API}/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    }),

  library: () => json<import("./types").Library>(`${API}/library`),
  album: (path: string) => json<import("./types").Album>(`${API}/album?path=${encodeURIComponent(path)}`),
  artist: (path: string) => json<import("./types").Artist>(`${API}/artist?path=${encodeURIComponent(path)}`),
  removeAlbum: (path: string) =>
    json<{ ok: boolean; trash: string }>(`${API}/album/remove`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  mbDetect: (path: string) =>
    json<{ mbid: string | null; key?: string; track?: string }>(
      `${API}/album/mbdetect?path=${encodeURIComponent(path)}`,
      undefined,
      8000
    ),
  scanTracks: (path: string) =>
    json<{ path: string; tracks: any[] }>(
      `${API}/album/scan-tracks?path=${encodeURIComponent(path)}`,
      undefined,
      30000
    ),
  organize: (paths: string[], dryRun = false) =>
    json<{ results: any[] }>(`${API}/organize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths, dry_run: dryRun }),
    }),

  streamUrl: (path: string) => `${API}/stream?path=${encodeURIComponent(path)}`,
  tags: (path: string) => json<any>(`${API}/tags?path=${encodeURIComponent(path)}`),
  setTags: (path: string, tags: Record<string, string | null>) =>
    json<{ ok: boolean }>(`${API}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, tags }),
    }),
  setTagsBatch: (tracks: Record<string, Record<string, string | null>>) =>
    json<{ ok: boolean; changed: number }>(`${API}/tags/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: tracks }),
    }),

  run: (ids: number[], targets?: string[], force?: Record<string, boolean>) =>
    json<{ results: any[] }>(`${API}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, targets, force }),
    }),

  // playlists
  playlists: () => json<import("./types").Playlist[]>(`${API}/playlists`),
  playlist: (id: number) => json<import("./types").Playlist>(`${API}/playlists/${id}`),
  createPlaylist: (name: string, kind: "manual" | "smart", filter?: unknown) =>
    json<import("./types").Playlist>(`${API}/playlists`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, kind, filter }),
    }),
  renamePlaylist: (id: number, name: string) =>
    json<import("./types").Playlist>(`${API}/playlists/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  deletePlaylist: (id: number) => json<{ ok: boolean }>(`${API}/playlists/${id}`, { method: "DELETE" }),
  playlistAdd: (id: number, paths: string[], position?: number) =>
    json<{ added: number }>(`${API}/playlists/${id}/tracks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths, position }),
    }),
  playlistOrder: (id: number, paths: string[]) =>
    json<{ ok: boolean }>(`${API}/playlists/${id}/tracks`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    }),
  playlistRemove: (id: number, paths: string[]) =>
    json<{ ok: boolean }>(`${API}/playlists/${id}/tracks`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    }),
  playlistFilter: (id: number, filter: unknown) =>
    json<import("./types").Playlist>(`${API}/playlists/${id}/filter`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filter }),
    }),
  playlistEvaluate: (id: number) => json<{ paths: string[] }>(`${API}/playlists/${id}/evaluate`, { method: "POST" }),
  playlistExportUrl: (id: number) => `${API}/playlists/${id}/export`,
  playlistImport: (name: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return json<import("./types").Playlist>(`${API}/playlists/import?name=${encodeURIComponent(name)}`, {
      method: "POST",
      body: fd,
    });
  },

  // integrations
  mbRelease: (id: string) => json<import("./types").MBRelease>(`${API}/mb/release?mbid=${encodeURIComponent(id)}`),
  mbGenres: (id: string, limit?: number) =>
    json<import("./types").GenreCascade>(
      `${API}/mb/release-genres?mbid=${encodeURIComponent(id)}${limit ? `&limit=${limit}` : ""}`
    ),
  mbSearchReleases: (q: string, mode: "release" | "track" | "catno" | "barcode" = "release") =>
    json<any[]>(`${API}/mb/search/releases?q=${encodeURIComponent(q)}&mode=${mode}`),
  mbSearchArtists: (q: string) => json<any[]>(`${API}/mb/search/artists?q=${encodeURIComponent(q)}`),
  mbMatch: (albumPath: string, releaseId: string) =>
    json<{ release: import("./types").MBRelease; suggestions: import("./types").MatchSuggestion[] }>(
      `${API}/mb/match`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ album_path: albumPath, release_id: releaseId }),
      }
    ),
  mbAssign: (tracks: Record<string, Record<string, string | null>>) =>
    json<{ ok: boolean; changed: number }>(`${API}/mb/assign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tracks }),
    }),

  lyricsSearch: (artist: string, track: string, album?: string) =>
    json<any[]>(`${API}/lyrics/search?artist=${encodeURIComponent(artist)}&track=${encodeURIComponent(track)}${album ? `&album=${encodeURIComponent(album)}` : ""}`),
  lyricsGet: (artist: string, track: string, album?: string, duration?: number) =>
    json<any>(
      `${API}/lyrics/get?artist=${encodeURIComponent(artist)}&track=${encodeURIComponent(track)}${album ? `&album=${encodeURIComponent(album)}` : ""}${duration ? `&duration=${duration}` : ""}`
    ),
  lyricsWrite: (path: string, lrc: string) =>
    json<{ ok: boolean; lrc: string }>(`${API}/lyrics/write`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, lrc }),
    }),

  rymValidate: (url: string) => json<{ valid: boolean }>(`${API}/rym/validate?url=${encodeURIComponent(url)}`),

  coverUrl: (albumPath: string, coverFile?: string | null) =>
    `${API}/cover?album=${encodeURIComponent(albumPath)}${coverFile ? `&file=${encodeURIComponent(coverFile)}` : ""}`,
  coverColor: (albumPath: string) =>
    json<{ color: string; album: string }>(
      `${API}/cover?album=${encodeURIComponent(albumPath)}&color=1`,
      undefined,
      8000
    ),

  importUpload: (targetDir: string, files: { file: File; relPath: string }[]) => {
    const fd = new FormData();
    for (const { file, relPath } of files) fd.append("files", file, relPath);
    return json<{ ok: boolean; saved: string[]; album_path: string }>(
      `${API}/import/upload?target_dir=${encodeURIComponent(targetDir)}`,
      { method: "POST", body: fd }
    );
  },
  importScan: (path: string) =>
    json<{ root: string; files: { relPath: string; size: number }[] }>(
      `${API}/import/scan?path=${encodeURIComponent(path)}`,
      { method: "POST" }
    ),
  importIngest: (source: string, target: string) =>
    json<{ ok: boolean; path: string }>(
      `${API}/import/ingest?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}`,
      { method: "POST" }
    ),
  importCommit: (targetDir: string, mbLink?: string, rymLink?: string) =>
    json<{ ok: boolean; changed: number }>(`${API}/import/commit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_dir: targetDir, mb_link: mbLink || null, rym_link: rymLink || null }),
    }),

  namingPreview: (script: string, shortFolderNames: boolean, sample?: Record<string, string>) =>
    json<{ path: string | null; ok: boolean; error?: string }>(`${API}/naming/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script, short_folder_names: shortFolderNames, sample }),
    }),

  openFolder: (path: string) =>
    json<{ ok: boolean }>(`${API}/open-folder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),

  dependencies: () =>
    json<{ deps_dir: string; tools: { key: string; name: string; installed_version?: string; latest_version?: string; detected_version?: string; path?: string | null; state: string }[] }>(
      `${API}/dependencies`
    ),
  installDependencies: (keys?: string[]) =>
    json<{ results: { key: string; name: string; ok: boolean; error?: string }[] }>(
      `${API}/dependencies/install`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keys: keys ?? null }),
      },
      900000
    ),

  cover: (albumPath: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return json<{ ok: boolean; path: string }>(
      `${API}/cover?album=${encodeURIComponent(albumPath)}`,
      { method: "POST", body: fd }
    );
  },
};