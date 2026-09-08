import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Disc3, Heart, ListMusic, Mic2, Play } from "lucide-react";import { api } from "../api";
import { useStore } from "../store";
import { useFavorites, useTrackLikes } from "../lib/favs";
import { EmptyState } from "../components/Badges";
import { TrackCover } from "../components/CoverImg";
import AlbumCard from "../components/AlbumCard";
import FavHeart from "../components/FavHeart";
import { fmtDuration } from "./LibraryPage";
import { artistRef, artistMbid } from "../lib/refs";
import type { Album, Artist, Playlist, Track } from "../types";

const TABS = [
  { id: "tracks", label: "Liked tracks", icon: Heart },
  { id: "albums", label: "Albums", icon: Disc3 },
  { id: "artists", label: "Artists", icon: Mic2 },
  { id: "playlists", label: "Playlists", icon: ListMusic },
] as const;

type Kind = (typeof TABS)[number]["id"];

export default function FavoritesPage() {
  const { kind: raw } = useParams();
  const kind: Kind = (TABS.some((t) => t.id === raw) ? raw : "tracks") as Kind;

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <Heart className="h-6 w-6 text-accent fill-current" /> Favorites
        </h1>
        <div className="flex rounded-md border border-border overflow-hidden ml-2">
          {TABS.map((t) => (
            <Link
              key={t.id}
              to={`/favorites/${t.id}`}
              className={`px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-colors ${
                kind === t.id ? "bg-accent on-accent" : "bg-panel text-zinc-400 hover:text-white"
              }`}
            >
              <t.icon className="h-3.5 w-3.5" /> {t.label}
            </Link>
          ))}
        </div>
      </div>
      {kind === "tracks" && <LikedTracks />}
      {kind === "albums" && <FavAlbums />}
      {kind === "artists" && <FavArtists />}
      {kind === "playlists" && <FavPlaylists />}
    </div>
  );
}

/** Flat library lookups shared by every tab. */
function useLibraryMaps() {
  const { data: lib } = useQuery({ queryKey: ["library"], queryFn: api.library });
  return useMemo(() => {
    const tracks = new Map<string, { track: Track; album: Album; artist: Artist }>();
    const albums = new Map<string, { album: Album; artist: Artist }>();
    const artists = new Map<string, Artist>();
    for (const a of lib?.artists ?? []) {
      artists.set(a.path, a);
      for (const al of a.albums) {
        albums.set(al.path, { album: al, artist: a });
        for (const t of al.tracks) tracks.set(t.path, { track: t, album: al, artist: a });
      }
    }
    return { lib, tracks, albums, artists };
  }, [lib]);
}

function displayArtist(al: Album, a: Artist) {
  return al.album_artist || a.name;
}

// ------------------------------------------------------------------------ //
// Liked tracks
// ------------------------------------------------------------------------ //
function LikedTracks() {
  const { data: likes, isLoading } = useTrackLikes();
  const { tracks } = useLibraryMaps();
  const playNow = useStore((s) => s.playNow);
  const navigate = useNavigate();

  const rows = useMemo(() => {
    const paths = likes?.paths ?? [];
    return paths.map((p) => {
      const hit = tracks.get(p);
      if (hit) {
        const { track, album, artist } = hit;
        return {
          path: p,
          missing: false,
          mbid: track.tags.MUSICBRAINZ_TRACKID ?? undefined,
          title: track.tags.TITLE ?? track.file,
          sub: `${displayArtist(album, artist)} · ${album.meta?.ALBUM ?? album.path.split("/").pop()}`,
          albumPath: album.path,
          trackPath: track.path,
          dur: track.tech?.length,
          coverFile: track.cover_file ?? null,
          albumCover: album.cover_file ?? null,
          queue: {
            path: track.path,
            file: track.file,
            albumPath: album.path,
            artist: displayArtist(album, artist),
            album: album.meta?.ALBUM ?? undefined,
            title: track.tags.TITLE || undefined,
            coverFile: track.cover_file ?? null,
            albumCover: album.cover_file ?? null,
          },
        };
      }
      return {
        path: p,
        missing: true,
        mbid: undefined,
        title: p.split("/").pop() ?? p,
        sub: "not in library",
        albumPath: p.split("/").slice(0, -1).join("/"),
        trackPath: p,
        dur: undefined,
        queue: { path: p, file: p.split("/").pop() ?? p, albumPath: p.split("/").slice(0, -1).join("/") },
      };
    });
  }, [likes, tracks]);

  const play = (i: number) => {
    const playable = rows.filter((r) => !r.missing).map((r) => r.queue);
    if (playable.length) playNow(playable, Math.min(i, playable.length - 1));
  };

  if (isLoading) return <div className="text-sm text-zinc-500">Loading…</div>;
  if (!rows.length)
    return (
      <EmptyState
        title="No liked tracks yet"
        hint="Use the heart in the player bar or on any track row — liked tracks show up here."
      />
    );

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border">
        <span className="text-xs text-zinc-500">
          {rows.length} liked track{rows.length === 1 ? "" : "s"}
        </span>
        <button className="btn-primary !py-1 text-xs ml-auto" onClick={() => play(0)}>
          <Play className="h-3.5 w-3.5" /> Play all
        </button>
      </div>
      {/* Same row language as the library tables: click plays, ctrl/shift-click opens */}
      <table className="w-full text-sm">
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={r.path}
              className="table-row group cursor-pointer"
              title="Click to play · Ctrl-click to open track page"
              onClick={(e) => {
                if (!r.missing && (e.ctrlKey || e.metaKey || e.shiftKey)) {
                  navigate(`/track/${encodeURIComponent(r.trackPath)}`);
                } else if (!r.missing) {
                  play(i);
                }
              }}
            >
              <td className="td text-zinc-600 w-12 tabular-nums cell-nowrap">{i + 1}</td>
              <td className="td cell-cover pr-0">
                {"coverFile" in r && !r.missing ? (
                  <TrackCover
                    albumPath={r.albumPath}
                    trackCover={(r as { coverFile?: string | null }).coverFile}
                    albumCover={(r as { albumCover?: string | null }).albumCover}
                    wrapperClass="h-9 w-9 rounded bg-raise border border-border overflow-hidden shrink-0"
                  />
                ) : null}
              </td>
              <td className="td">
                <span className={`block break-words ${r.missing ? "text-zinc-500" : ""}`} title={r.missing ? r.path : r.title}>
                  {r.title}
                </span>
              </td>
              <td className="td text-xs text-zinc-500 break-words">{r.sub}</td>
              <td className="td text-xs text-zinc-600 font-mono w-16 pr-3 text-right">{fmtDuration(r.dur)}</td>
              <td className="td w-10 pr-0" onClick={(e) => e.stopPropagation()}>
                <FavHeart kind="track" id={r.path} mbid={r.mbid} iconClass="h-3.5 w-3.5" title="Unlike" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------------ //
// Favorite albums
// ------------------------------------------------------------------------ //
function FavAlbums() {
  const { data: favs, isLoading } = useFavorites();
  const { albums } = useLibraryMaps();

  const rows = useMemo(
    () =>
      (favs?.albums ?? [])
        .map((p) => albums.get(p))
        .filter((x): x is NonNullable<typeof x> => !!x),
    [favs, albums]
  );

  if (isLoading) return <div className="text-sm text-zinc-500">Loading…</div>;
  if (!rows.length)
    return <EmptyState title="No favorite albums yet" hint="Heart an album on its page or in the library grid." />;

  // Same card layout as the library grid (shared AlbumCard).
  return (
    <div
      className="grid gap-x-4 gap-y-5"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(164px, 1fr))" }}
    >
      {rows.map(({ album: al, artist: a }) => (
        <AlbumCard key={al.path} al={al} artistName={displayArtist(al, a)} />
      ))}
    </div>
  );
}

// ------------------------------------------------------------------------ //
// Favorite artists
// ------------------------------------------------------------------------ //
function FavArtists() {
  const { data: favs, isLoading } = useFavorites();
  const { artists } = useLibraryMaps();
  const playNow = useStore((s) => s.playNow);

  const rows = useMemo(
    () =>
      (favs?.artists ?? [])
        .map((p) => artists.get(p))
        .filter((x): x is Artist => !!x),
    [favs, artists]
  );

  if (isLoading) return <div className="text-sm text-zinc-500">Loading…</div>;
  if (!rows.length) return <EmptyState title="No favorite artists yet" hint="Heart an artist on their page." />;

  return (
    <div className="bg-card rounded-lg border border-border p-2">
      <div className="space-y-1">
      {rows.map((a) => {
        const displayName =
          a.display_name ||
          a.albums.find((al) => al.album_artist)?.album_artist ||
          a.name.replace(/\s*\[[0-9a-f-]{8,}\]\s*$/, "");
        const q = a.albums.flatMap((al) =>
          al.tracks.map((t) => ({
            path: t.path, file: t.file, albumPath: al.path,
            artist: displayArtist(al, a), album: al.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
            coverFile: t.cover_file ?? null, albumCover: al.cover_file ?? null,
          }))
        );
        return (
          <div key={a.path} className="group flex items-center gap-3 rounded-lg border border-transparent hover:border-border hover:bg-white/[0.04] px-3 py-1.5 transition-colors">
            <button className="btn-ghost !px-1.5 !py-1 shrink-0 opacity-0 group-hover:opacity-100 transition-colors" title="Play all" onClick={() => q.length && playNow(q)}>
              <Play className="h-3.5 w-3.5" />
            </button>
            <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-accent/40 to-indigo-700/40 border border-border flex items-center justify-center shrink-0">
              <Mic2 className="h-5 w-5 text-zinc-300" />
            </div>
            <Link to={artistRef(a)} className="text-sm font-medium truncate hover:text-accent-soft min-w-0">
              {displayName}
            </Link>
            <span className="text-xs text-zinc-500 ml-auto shrink-0">
              {a.aggregate.album_count} albums · {a.aggregate.track_count} tracks
            </span>
            <FavHeart kind="artist" id={a.path} mbid={artistMbid(a)} iconClass="h-3.5 w-3.5" />
          </div>
        );
      })}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------ //
// Favorite playlists
// ------------------------------------------------------------------------ //
function FavPlaylists() {
  const { data: favs, isLoading } = useFavorites();
  const { data: playlists } = useQuery({ queryKey: ["playlists"], queryFn: api.playlists });
  const { tracks } = useLibraryMaps();
  const playNow = useStore((s) => s.playNow);
  const navigate = useNavigate();

  const rows = useMemo(() => {
    const byId = new Map<string, Playlist>((playlists ?? []).map((p) => [String(p.id), p]));
    return (favs?.playlists ?? [])
      .map((id) => byId.get(id))
      .filter((x): x is Playlist => !!x);
  }, [favs, playlists]);

  const play = async (p: Playlist) => {
    try {
      const detail = await api.playlist(p.id);
      const q = (detail.tracks ?? []).map((path) => {
        const hit = tracks.get(path);
        return hit
          ? {
              path,
              file: hit.track.file,
              albumPath: hit.album.path,
              artist: displayArtist(hit.album, hit.artist),
              album: hit.album.meta?.ALBUM ?? undefined,
              title: hit.track.tags.TITLE || undefined,
              coverFile: hit.track.cover_file ?? null,
              albumCover: hit.album.cover_file ?? null,
            }
          : { path, file: path.split("/").pop() ?? path, albumPath: path.split("/").slice(0, -1).join("/") };
      });
      if (q.length) playNow(q);
    } catch (e) {
      useStore.getState().setToast(String(e));
    }
  };

  if (isLoading) return <div className="text-sm text-zinc-500">Loading…</div>;
  if (!rows.length) return <EmptyState title="No favorite playlists yet" hint="Heart a playlist on the Playlists page." />;

  return (
    <div className="bg-card rounded-lg border border-border p-2">
      <div className="space-y-1">
      {rows.map((p) => (
        <div key={p.id} className="group flex items-center gap-3 rounded-lg border border-transparent hover:border-border hover:bg-white/[0.04] px-3 py-1.5 transition-colors">
          <button className="btn-ghost !px-1.5 !py-1 shrink-0 opacity-0 group-hover:opacity-100 transition-colors" title="Play playlist" onClick={() => play(p)}>
            <Play className="h-3.5 w-3.5" />
          </button>
          <ListMusic className="h-4 w-4 text-accent shrink-0" />
          <button className="text-sm font-medium truncate hover:text-accent-soft min-w-0" onClick={() => navigate("/playlists")} title="Open the Playlists page">
            {p.name}
          </button>
          {p.kind === "smart" && <span className="chip bg-accent/10 text-accent-soft border border-accent/25 text-[10px]">SMART</span>}
          <span className="text-xs text-zinc-500 ml-auto shrink-0">{p.track_count} tracks</span>
          <FavHeart kind="playlist" id={String(p.id)} iconClass="h-3.5 w-3.5" />
        </div>
      ))}
      <div className="text-[11px] text-zinc-600 px-1 pt-1">
        Playlists are managed on the <Link to="/playlists" className="text-accent-soft hover:underline">Playlists page</Link>.
      </div>
      </div>
    </div>
  );
}
