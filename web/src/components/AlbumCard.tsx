import { Link } from "react-router-dom";
import { Play } from "lucide-react";
import { useStore } from "../store";
import { statusFor } from "../lib/status";
import { mediaShort } from "./Badges";
import CoverImg from "./CoverImg";
import FavHeart from "./FavHeart";
import { albumRef } from "../lib/refs";
import type { Album } from "../types";

/** The library's album grid card, shared by the Library and Favorites pages
 * so favorites render with exactly the same layout. The library payload
 * enriches albums with an `artist` display name; elsewhere it falls back to
 * the album-artist tag. */
export default function AlbumCard({ al, artistName, selectable, selected, onSelect }: {
  al: Album & { artist?: string };
  artistName?: string;
  selectable?: boolean;
  selected?: boolean;
  onSelect?: (path: string) => void;
}) {
  const st = statusFor(!!al.pass, al.audit_summary);
  const artist = artistName ?? al.artist ?? al.album_artist ?? al.path.split(/[\\/]/).slice(0, -1).pop() ?? "";
  const ms = mediaShort(al.media || al.meta?.MEDIA);
  return (
    <div className={`group relative rounded-xl p-2 transition-all hover:-translate-y-0.5 hover:bg-panel/70 ${selected ? "bg-accent/10 ring-1 ring-accent/30" : ""}`}>
      <div className="relative">
        <Link to={albumRef(al)} title="Open album page" className="block">
          <CoverImg
            albumPath={al.path}
            coverFile={al.cover_file}
            wrapperClass="aspect-square w-full rounded-xl shadow-lg ring-1 ring-black/40 overflow-hidden"
          />
        </Link>
        {selectable && (
          <div
            className="absolute top-2 left-2 opacity-0 group-hover:opacity-100 transition-opacity bg-black/60 rounded-md px-1 py-0.5"
            onClick={(e) => e.stopPropagation()}
          >
            <input type="checkbox" checked={!!selected} onChange={() => onSelect?.(al.path)} title="Select album" />
          </div>
        )}
        {ms ? (
          <span
            className="absolute bottom-1.5 right-1.5 bg-black/65 text-zinc-200 text-[9px] font-semibold tracking-wide rounded px-1 py-0.5 border border-white/10"
            title={`Media: ${al.media || al.meta?.MEDIA}`}
          >
            {ms}
          </span>
        ) : null}
        <div className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <FavHeart kind="album" id={al.path} mbid={al.meta?.MUSICBRAINZ_ALBUMID} className="!p-1.5 bg-black/60" iconClass="h-4 w-4" />
        </div>
        <button
          className="btn-primary absolute left-2 bottom-3 !rounded-lg !p-3 opacity-0 translate-y-1 group-hover:opacity-100 group-hover:translate-y-0 transition-all shadow-2xl"
          title="Play album"
          onClick={() =>
            useStore.getState().playNow(
              (al.tracks ?? []).map((t) => ({
                path: t.path, file: t.file, albumPath: al.path,
                artist, album: al.meta?.ALBUM ?? undefined, title: t.tags.TITLE || undefined,
              }))
            )
          }
        >
          <Play className="h-4 w-4 fill-current" />
        </button>
      </div>
      <div className="mt-2 px-0.5">
        <Link
          to={albumRef(al)}
          className="text-sm font-medium truncate block hover:text-accent-soft"
          title={al.meta?.ALBUM ?? al.path}
        >
          {al.meta?.ALBUM ?? al.path.split("/").pop()}
        </Link>
        <div className="text-[11px] text-zinc-500 truncate flex items-center gap-1.5 mt-0.5">
          <span className={`h-1.5 w-1.5 rounded-full ${st.edge} inline-block shrink-0`} title={st.label} />
          <span className="truncate">
            {artist}
            {al.meta?.DATE ? ` · ${String(al.meta.DATE).slice(0, 4)}` : ""}
            {al.meta?.ORIGINALDATE && String(al.meta.ORIGINALDATE).slice(0, 4) !== String(al.meta?.DATE ?? "").slice(0, 4)
              ? ` (orig. ${String(al.meta.ORIGINALDATE).slice(0, 4)})` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}
