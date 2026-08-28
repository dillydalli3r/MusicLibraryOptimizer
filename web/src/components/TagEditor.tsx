import { useEffect, useState } from "react";
import { useStore } from "../store";
const API="http://127.0.0.1:8000";

export default function TagEditor(){
  const {selected} = useStore();
  const [tags, setTags] = useState<any>(null);
  const [ed, setEd] = useState<Record<string,string>>({});
  const target = selected.find(s=>s.toLowerCase().endsWith(".flac")||s.toLowerCase().endsWith(".mp3")||s.endsWith(".m4a")) || null;
  useEffect(()=>{
    if(!target) { setTags(null); return;}
    fetch(`${API}/api/tags?path=${encodeURIComponent(target)}`).then(r=>r.json()).then(j=>{ setTags(j); setEd(j.tags||{})}).catch(()=>setTags(null));
  },[target]);

  const save = async()=>{
    if(!target) return;
    await fetch(`${API}/api/tags`,{method:"POST",headers:{"Content-Type":"application/json"},body: JSON.stringify({path: target, tags: ed})});
    alert("tags saved");
  };

  const runForSelected = async (ids:number[], label:string)=>{
    if(!selected.length) return alert("Select Tracks/Albums/Artists first");
    await fetch(`${API}/api/run`,{method:"POST",headers:{"Content-Type":"application/json"},body: JSON.stringify({ids, targets: selected})});
    const lib = await fetch(`${API}/api/library`).then(r=>r.json());
    useStore.getState().setLibrary(lib);
    alert(label+" done for selected");
  };

  if(!selected.length) return <div className="p-4 text-sm text-gray-400">Select a Track/Album/Artist (left) to grade/audit/tag. Select multiple or an artist folder to operate on Everything at once. Drag a cover onto an album to replace cover.*</div>;

  return <div className="p-3 space-y-3">
    <div className="text-xs text-gray-400">Selected {selected.length}: <span className="text-white break-all">{selected.slice(0,3).join(", ")}{selected.length>3?" …":""}</span></div>
    <div className="grid grid-cols-2 gap-2">
      <button onClick={()=>runForSelected([4],"Grade")} className="py-1.5 bg-zinc-800 rounded text-sm">Grade selected</button>
      <button onClick={()=>runForSelected([6],"Audit")} className="py-1.5 bg-zinc-800 rounded text-sm">Audit selected</button>
      <button onClick={()=>runForSelected([1],"Lyrics")} className="py-1.5 bg-zinc-800 rounded text-sm">Lyrics</button>
      <button onClick={()=>runForSelected([2],"CUEs")} className="py-1.5 bg-zinc-800 rounded text-sm">CUEs</button>
      <button onClick={()=>runForSelected([8],"AutoTag")} className="py-1.5 bg-zinc-800 rounded text-sm">AutoTag</button>
      <button onClick={()=>runForSelected([3],"FLAC")} className="py-1.5 bg-zinc-800 rounded text-sm">FLAC</button>
      <button onClick={()=>runForSelected([5],"Images")} className="py-1.5 bg-zinc-800 rounded text-sm">Images</button>
      <button onClick={()=>runForSelected([9],"AccurateRip")} className="py-1.5 bg-zinc-800 rounded text-sm">AccurateRip</button>
      <button onClick={()=>runForSelected([7],"DR/RG")} className="py-1.5 bg-zinc-800 rounded text-sm">DR+RG</button>
      <button onClick={()=>runForSelected([10],"FormatAll")} className="py-1.5 bg-white text-black rounded text-sm">Format All</button>
    </div>

    {!target ? <div className="text-xs text-gray-500">Select a single track to edit tags (bulk tag + BPM/KEY + Picard naming in next phase).</div> : !tags ? <div className="text-xs text-gray-400">Loading tags…</div> : (
      <div className="space-y-2">
        <div className="text-sm font-semibold truncate">{target.split("/").pop()}</div>
        <div className="max-h-[50vh] overflow-auto space-y-2 pr-1">
          {Object.entries(ed).map(([k,v])=>(
            <label key={k} className="block">
              <span className="text-xs text-gray-400">{k}</span>
              <input value={String(v??"")} onChange={e=>setEd(s=>({...s,[k]:e.target.value}))} className="w-full bg-zinc-900 border border-border rounded px-2 py-1 text-sm" />
            </label>
          ))}
          <label className="block"><span className="text-xs text-gray-400">Add tag (KEY)</span><input id="newk" placeholder="TITLE / ARTIST / GENRE …" className="w-full bg-zinc-900 border border-border rounded px-2 py-1 text-sm" /></label>
        </div>
        <button onClick={save} className="w-full py-2 bg-white text-black rounded font-semibold">Save tags</button>
        <details className="text-xs text-gray-400"><summary>Raw + lyrics</summary><pre className="whitespace-pre-wrap bg-zinc-900 p-2 rounded">{JSON.stringify(tags,null,2)}</pre></details>
      </div>
    )}
  </div>;
}
