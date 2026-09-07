import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

/** <track> elements for every subtitle source of a video: muxed streams and
 * external .srt/.vtt sidecars, all served as WebVTT by the backend. */
export default function useSubtitleTracks(videoPath: string | null | undefined) {
  const { data: subs } = useQuery({
    queryKey: ["subtitles", videoPath],
    queryFn: () => api.subtitles(videoPath!),
    enabled: !!videoPath,
    staleTime: 10 * 60 * 1000,
  });

  const tracks: { key: string; src: string; label: string; default: boolean }[] = [];
  (subs?.muxed ?? []).forEach((s) =>
    tracks.push({
      key: `muxed-${s.n}`,
      src: api.subtitleUrl(videoPath!, undefined, s.n),
      label: s.title,
      default: false,
    })
  );
  (subs?.sidecars ?? []).forEach((s, i) =>
    tracks.push({
      key: `side-${i}`,
      src: api.subtitleUrl(videoPath!, s.name),
      label: s.language ? `${s.name} (${s.language})` : s.name,
      default: (subs?.muxed?.length ?? 0) === 0 && i === 0, // sidecar wins when nothing is muxed in
    })
  );
  return tracks;
}

/** Video element with subtitle tracks wired in — shared by the track/album
 * modals and the fullscreen player. */
export function SubtitledVideo({
  path,
  muted,
  videoRef,
  className,
  onClick,
  controls = true,
}: {
  path: string;
  muted?: boolean;
  videoRef?: React.RefObject<HTMLVideoElement | null>;
  className?: string;
  onClick?: () => void;
  controls?: boolean;
}) {
  const tracks = useSubtitleTracks(path);
  return (
    <video
      ref={videoRef}
      src={api.streamUrl(path)}
      controls={controls}
      autoPlay
      muted={muted}
      playsInline
      onClick={onClick}
      className={className}
    >
      {tracks.map((t) => (
        <track key={t.key} kind="subtitles" src={t.src} label={t.label} default={t.default} />
      ))}
    </video>
  );
}
