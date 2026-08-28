import { useEffect, useRef } from "react";
import { useStore } from "../store";
const API="http://127.0.0.1:8000";
export default function Player(){
  const {playing, setPlaying} = useStore();
  const ref = useRef<HTMLAudioElement>(null);
  useEffect(()=>{ if(ref.current && playing){ ref.current.src=`${API}/api/stream?path=${encodeURIComponent(playing)}`; ref.current.play().catch(()=>{});} },[playing]);
  if(!playing) return <div className="h-14 bg-panel border-t border-border flex items-center px-4 text-xs text-gray-400">No track — click a track to play. Listening uses /api/stream (Range).</div>;
  return <div className="h-14 bg-panel border-t border-border flex items-center px-3 gap-3">
    <button onClick={()=>setPlaying(null)} className="px-2 py-1 bg-zinc-800 rounded text-xs">■</button>
    <span className="text-xs truncate flex-1">{playing.split("/").pop()}</span>
    <audio ref={ref} controls className="h-8 w-[360px]" />
  </div>;
}
