import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";

export type FavKind = "album" | "artist" | "playlist";

export interface Favorites {
  albums: string[];
  artists: string[];
  playlists: string[];
}

/** API payloads use plural keys; the heart kind is singular. */
const PLURAL: Record<FavKind, keyof Favorites> = {
  album: "albums",
  artist: "artists",
  playlist: "playlists",
};

export function useFavorites() {
  return useQuery({ queryKey: ["favorites"], queryFn: api.favorites, staleTime: 30_000 });
}

export function useTrackLikes() {
  return useQuery({ queryKey: ["likes"], queryFn: api.likes, staleTime: 30_000 });
}

/** Shared heart state for one entity. `kind: "track"` uses the backend's
 * liked-tracks store; the rest use the favorites table. Passing the
 * entity's MusicBrainz ID lets the backend keep the entry alive across
 * file moves. */
export function useFav(kind: FavKind | "track", id: string | undefined | null, mbid?: string | null) {
  const qc = useQueryClient();
  const favs = useFavorites();
  const likes = useTrackLikes();
  const isTrack = kind === "track";
  const fav = isTrack
    ? !!id && (likes.data?.paths ?? []).includes(id)
    : !!id && !!favs.data && ((favs.data[PLURAL[kind]] ?? []) as string[]).includes(id);
  const mutation = useMutation({
    mutationFn: async () => {
      if (!id) throw new Error("nothing to favorite");
      return isTrack ? api.likeToggle(id, mbid ?? undefined) : api.favoriteToggle(kind as FavKind, id, mbid ?? undefined);
    },
    onSuccess: (r) => {
      const on = "liked" in r ? r.liked : r.fav;
      // Optimistic single-entity update; the invalidation re-syncs lists.
      qc.setQueryData(["likes"], (old: { paths: string[] } | undefined) =>
        !isTrack || !old ? old : { paths: on ? [id!, ...old.paths] : old.paths.filter((p) => p !== id) }
      );
      qc.setQueryData(["favorites"], (old: Favorites | undefined) => {
        if (isTrack || !old) return old;
        const key = PLURAL[kind];
        const list: string[] = old[key] ?? [];
        return { ...old, [key]: on ? [id!, ...list] : list.filter((k) => k !== id) } as Favorites;
      });
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["likes"] });
      qc.invalidateQueries({ queryKey: ["favorites"] });
    },
  });
  return { fav, toggle: () => id && mutation.mutate(), pending: mutation.isPending };
}
