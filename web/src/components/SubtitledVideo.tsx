import { useEffect, useState } from "react";
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
  onError,
  controls = true,
}: {
  path: string;
  muted?: boolean;
  videoRef?: React.RefObject<HTMLVideoElement | null>;
  className?: string;
  onClick?: () => void;
  onError?: () => void;
  controls?: boolean;
}) {
  const tracks = useSubtitleTracks(path);
  // Codecs the browser can't decode (MPEG-2 VOB/MPG/M2TS, VC-1, ...) fail
  // on the direct stream — retry once through the server's live H.264
  // transcode before reporting an error.
  const [transcoded, setTranscoded] = useState(false);
  useEffect(() => setTranscoded(false), [path]);
  return (
    <video
      key={`${path}|${transcoded ? "x" : "direct"}`}
      ref={videoRef}
      src={api.videoStreamUrl(path, transcoded)}
      controls={controls}
      autoPlay
      muted={muted}
      playsInline
      preload="auto"
      onClick={onClick}
      onError={() => {
        if (!transcoded) setTranscoded(true);
        else onError?.();
      }}
      className={className}
    >
      {tracks.map((t) => (
        <track key={t.key} kind="subtitles" src={t.src} label={t.label} default={t.default} />
      ))}
    </video>
  );
}
