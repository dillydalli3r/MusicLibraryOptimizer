import { useEffect, useState } from "react";
import { useStore } from "./store";
import Library from "./components/Library";
import TagEditor from "./components/TagEditor";
import Player from "./components/Player";
import LyricsEditor from "./components/LyricsEditor";

const API = "http://127.0.0.1:8000";

export default function App() {
  const { library, setLibrary, progress, setProgress, selected } = useStore();
  const [tab, setTab] = useState<"library" | "lyrics">("library");
  const [config, setConfig] = useState<any>(null);

  useEffect(() => {
    fetch(`${API}/api/library`).then(r=>r.json()).then(setLibrary).catch(()=>{});
    fetch(`${API}/api/config`).then(r=>r.json()).then(setConfig).catch(()=>{});
    const ws = new WebSocket("ws://127.0.0.1:8000/ws/progress");
    ws.onmessage = e => { try{ setProgress(JSON.parse(e.data)); }catch{} };
    return () => ws.close();
  }, []);

  const run = async (ids: number[], title: string) => {
    const targets = selected.length ? selected : undefined;
    await fetch(`${API}/api/run`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ids, targets})});
    // refresh
    const lib = await fetch(`${API}/api/library`).then(r=>r.json());
    setLibrary(lib);
    alert(`${title} done`);
  };

  return (
    <div className="min-h-screen bg-bg text-white flex flex-col">
      <header className="h-14 bg-panel border-b border-border flex items-center px-4 gap-3 sticky top-0 z-20">
        <span className="font-bold tracking-wide">MusicLibraryOptimizer</span>
        <span className="text-xs text-gray-400">{config?.music_folder || library?.folder}</span>
        <div className="ml-auto flex gap-2">
          <button onClick={()=>run([1,2,8,3,5,9,6,4,7,10],"RUN ALL")} className="px-3 py-1.5 bg-white text-black rounded text-sm font-semibold">Run All</button>
          <button onClick={()=>run([4],"Grade")} className="px-3 py-1.5 bg-zinc-800 rounded text-sm">Grade</button>
          <button onClick={()=>run([6],"Audit")} className="px-3 py-1.5 bg-zinc-800 rounded text-sm">Audit</button>
        </div>
      </header>

      {progress && <div className="h-1 bg-zinc-900"><div className="h-1 bg-white transition-all" style={{width: `${progress.total? Math.min(100, progress.done/progress.total*100):0}%`}} /><div className="text-[10px] text-gray-400 px-4 py-0.5">{progress.desc} {progress.done}/{progress.total}</div></div>}

      <div className="flex gap-2 px-4 py-2 bg-panel border-b border-border">
        <button onClick={()=>setTab("library")} className={`px-3 py-1 rounded text-sm ${tab==="library"?"bg-white text-black":"bg-zinc-800"}`}>Library</button>
        <button onClick={()=>setTab("lyrics")} className={`px-3 py-1 rounded text-sm ${tab==="lyrics"?"bg-white text-black":"bg-zinc-800"}`}>Lyrics editor</button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 overflow-auto">
          {tab==="library" ? <Library /> : <LyricsEditor />}
        </div>
        <div className="w-[380px] border-l border-border bg-card overflow-auto">
          <TagEditor />
        </div>
      </div>

      <Player />
    </div>
  );
}
