import { useState } from "react";
import { Disc3 } from "lucide-react";
import { api } from "../api";

/** Cover thumbnail with a graceful fallback when the art is missing or
 * fails to load. `wrapperClass` sizes the box; the image fills it. */
export default function CoverImg({
  albumPath,
  coverFile,
  wrapperClass = "h-9 w-9 rounded bg-raise border border-border overflow-hidden shrink-0",
}: {
  albumPath: string;
  coverFile?: string | null;
  wrapperClass?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (!coverFile || failed) {
    return (
      <div className={`${wrapperClass} flex items-center justify-center text-zinc-700`}>
        <Disc3 className="h-1/2 w-1/2 max-h-5 max-w-5" />
      </div>
    );
  }
  return (
    <div className={wrapperClass}>
      <img
        src={api.coverUrl(albumPath, coverFile)}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className="h-full w-full object-cover"
      />
    </div>
  );
}