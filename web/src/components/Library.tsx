import { useMemo, useState } from "react";
import { useStore } from "../store";

const API = "http://127.0.0.1:8000";

export default function Library() {
  const { library, selected, setSelected, query, setQuery } = useStore();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const toggle = (k: string) => setExpanded(s => ({...s, [k]: !s[k]}));

  const filtered = useMemo(() => {
    if (!library) return null;
    if (!query) return library;
    const q = query.toLowerCase();
    return {
      ...library,
      artists: library.artists.map(a => ({
        ...a,
        albums: a.albums.filter(alb => {
          const hay = `${a.name} ${alb.path} ${alb.tracks?.map((t:any)=>t.file).join(" ")}`.toLowerCase();
          return hay.includes(q);
        })
      })).filter(a=>a.albums.length)
    };
  }, [library, query]);

  if (!library) return <div className="p-8 text-gray-400">Loading library… set music_folder in config if empty. Backend http://127.0.0.1:8000 must be running.</div>;
  if (!filtered) return null;

  const sel = new Set(selected);
  const toggleSel = (path: string) => {
    const next = sel.has(path) ? [...selected.filter(p=>p!==path)] : [...selected, path];
    setSelected(next);
  };

  return (
    <div className="p-3">
      <div className="flex gap-2 mb-3">
        <input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search artists / albums / tracks (grade/audit/media)…" className="flex-1 bg-zinc-900 border border-border rounded px-3 py-2 text-sm outline-none" />
        <span className="text-xs text-gray-400 py-2">{selected.length ? `${selected.length} selected` : "Click rows to select Tracks/Albums/Artists/All"}</span>
        <button onClick={()=>setSelected([])} className="text-xs px-2 py-1 bg-zinc-800 rounded">Clear</button>
      </div>

      <div className="space-y-3">
        {filtered.artists.map(artist => (
          <div key={artist.path} className="bg-card rounded border border-border">
            <div onClick={()=>toggleSel(artist.path)} className={`flex items-center px-3 py-2 cursor-pointer ${sel.has(artist.path)?"bg-zinc-800":""}`}>
              <button onClick={e=>{e.stopPropagation(); toggle(artist.path);}} className="mr-2 text-gray-400">{expanded[artist.path]?"▾":"▸"}</button>
              <span className="font-semibold">{artist.name}</span>
              <span className="ml-2 text-xs text-gray-400">{artist.albums.length} albums</span>
              <span className="ml-auto text-xs text-gray-500">{artist.path}</span>
            </div>

            {(expanded[artist.path] ?? true) && artist.albums.map(alb => (
              <div key={alb.path} className="border-t border-border">
                <div onClick={()=>toggleSel(alb.path)} className={`flex items-center px-3 py-2 bg-panel cursor-pointer text-sm ${sel.has(alb.path)?"bg-zinc-800":""}`}>
                  <button onClick={e=>{e.stopPropagation(); toggle(alb.path);}} className="mr-2">{expanded[alb.path]?"▾":"▸"}</button>
                  <span className="truncate">{alb.path.split("/").pop()}</span>
                  <span className={`ml-2 px-1.5 py-0.5 rounded text-xs ${alb.pass_count===alb.total_checks?"bg-green-900 text-green-200":"bg-red-900 text-red-200"}`}>{alb.pass_count}/{alb.total_checks} {alb.pass_count===alb.total_checks?"PASS":"FAIL"}</span>
                  <span className={`ml-2 text-xs ${alb.audit_summary==="REAL"?"text-green-400": alb.audit_summary==="FAKE"?"text-red-400":"text-yellow-400"}`}>AUDIT {alb.audit_summary||"—"} | AR {alb.accuraterip_status} | CS {alb.checksum_status}</span>
                  <span className="ml-auto text-xs text-gray-500">{alb.track_count} tr</span>
                </div>

                {(expanded[alb.path] ?? false) && (
                  <div className="overflow-auto">
                    <table className="w-full text-xs">
                      <thead className="text-gray-400">
                        <tr><th className="text-left px-3 py-1">Track</th><th>GRADE</th><th>AUDIT</th><th>AR</th><th>CS</th><th>MEDIA</th><th>COVER</th><th>FAILED</th></tr>
                      </thead>
                      <tbody>
                        {alb.tracks?.map((tr:any)=>(
                          <tr key={tr.file} onClick={()=>toggleSel(tr._full)} className={`border-t border-zinc-900 cursor-pointer hover:bg-zinc-900 ${sel.has(tr._full)?"bg-zinc-800":""}`}>
                            <td className="px-3 py-1 truncate max-w-[260px]">{tr.file}</td>
                            <td className="text-center">{tr.issues?.length?"FAIL":"PASS"}</td>
                            <td className={`text-center ${tr.audit==="REAL"?"text-green-400": tr.audit==="FAKE"?"text-red-400":"text-gray-400"}`}>{tr.audit||"—"}</td>
                            <td className={`text-center ${tr.accuraterip_status==="REAL"?"text-green-400": tr.accuraterip_status==="FAKE"?"text-red-400":"text-gray-500"}`}>{tr.accuraterip_status||"—"}</td>
                            <td className={`text-center ${tr.checksum_status==="REAL"?"text-green-400": tr.checksum_status==="FAKE"?"text-red-400":"text-gray-500"}`}>{tr.checksum_status||"—"}</td>
                            <td className="text-center">{tr.values?.MEDIA||""}</td>
                            <td className="text-center">{alb.cover_file||""}</td>
                            <td className="px-2 truncate max-w-[260px] text-red-300">{tr.issues?.join(", ")}</td>
                          </tr>
                        ))}
                        {/* sidecars */}
                        {alb.path && (
                          <tr><td colSpan={8} className="px-3 py-1 text-gray-500">Sidecars: {(alb as any).has_log?"CD-1.log ":""}{(alb as any).has_cue?"CD-1.cue ":""}{alb.cover_file?"cover.*":""}</td></tr>
                        )}
                      </tbody>
                    </table>
                    <div className="flex gap-2 p-2">
                      <button onClick={()=>playAlbum(alb)} className="px-2 py-1 bg-zinc-800 rounded text-xs">Play album</button>
                      <button onDragOver={e=>e.preventDefault()} onDrop={e=>handleCoverDrop(e, alb.path)} className="px-2 py-1 bg-zinc-800 rounded text-xs">Drop cover here</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );

  function playAlbum(alb:any){
    const first = alb.tracks?.[0]?._full;
    if(first) useStore.getState().setPlaying(first);
  }
  async function handleCoverDrop(e:React.DragEvent, albumPath:string){
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if(!f) return;
    const fd = new FormData(); fd.append("file", f);
    await fetch(`${API}/api/cover?album=${encodeURIComponent(albumPath)}`, {method:"POST", body: fd});
    const lib = await fetch(`${API}/api/library`).then(r=>r.json());
    useStore.getState().setLibrary(lib);
  }
}
