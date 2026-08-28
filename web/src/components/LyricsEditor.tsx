import { useState } from "react";
import { useStore } from "../store";
const API="http://127.0.0.1:8000";
export default function LyricsEditor(){
  const {selected} = useStore();
  const [text, setText] = useState("");
  const [tr, setTr] = useState("");
  const target = selected.find(s=>s.match(/\.(flac|mp3|m4a|mp4|ogg|opus)$/i));
  const searchLRClib = async()=>{
    if(!target) return alert("Select a track first");
    const tags = await fetch(`${API}/api/tags?path=${encodeURIComponent(target)}`).then(r=>r.json());
    const artist = tags.tags?.ARTIST || tags.tags?.ALBUMARTIST || "";
    const title = tags.tags?.TITLE || target.split("/").pop()?.replace(/\.[^.]+$/, "").replace(/^\d+[-\s]+/,"") || "";
    const album = tags.tags?.ALBUM || "";
    // try get exact
    let r = await fetch(`${API}/api/lyrics/get?artist=${encodeURIComponent(artist)}&track=${encodeURIComponent(title)}&album=${encodeURIComponent(album)}`);
    if(r.ok){ const j=await r.json(); if(j.syncedLyrics){ setText(j.syncedLyrics); return; } if(j.plainLyrics) setText(j.plainLyrics); return; }
    r = await fetch(`${API}/api/lyrics/search?artist=${encodeURIComponent(artist)}&track=${encodeURIComponent(title)}&album=${encodeURIComponent(album)}`);
    if(r.ok){ const arr=await r.json(); const best = arr?.[0]; if(best?.syncedLyrics) setText(best.syncedLyrics); else if(best?.plainLyrics) setText(best.plainLyrics); else alert("No LRClib result"); }
  };
  const save = async()=>{
    if(!target) return;
    await fetch(`${API}/api/lyrics/write?path=${encodeURIComponent(target)}`,{method:"POST",headers:{"Content-Type":"application/json"},body: JSON.stringify({lrc: text})});
    alert("wrote .lrc (not to tag)");
  };
  // Word-level helper: Enhanced LRC <mm:ss.xx> preserved; translation sidecar only (ask: don’t write to tags, just helper)
  const saveTranslation = async()=>{
    if(!target) return;
    const path = target.replace(/\.[^.]+$/, ".lrc.translation");
    await fetch(`${API}/api/lyrics/write?path=${encodeURIComponent(path)}`,{method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({lrc: tr})});
    alert("saved translation sidecar .lrc.translation (helper only)");
  };
  return <div className="p-4 space-y-3">
    <div className="text-sm font-semibold">Built-in lyrics editor — Enhanced LRC + translation/transliteration helper (never writes to tags)</div>
    <div className="text-xs text-gray-400">Selected: {target || "— select a track left"} • Source: LRClib • Target .lrc sidecar</div>
    <div className="flex gap-2">
      <button onClick={searchLRClib} className="px-3 py-1.5 bg-white text-black rounded text-sm">Auto-fetch LRClib</button>
      <button onClick={save} className="px-3 py-1.5 bg-zinc-800 rounded text-sm">Save .lrc</button>
    </div>
    <div className="grid grid-cols-2 gap-3">
      <div>
        <div className="text-xs text-gray-400 mb-1">LRC (Enhanced &lt;mm:ss.xx&gt; supported, idempotent via mlo/lyrics.py)</div>
        <textarea value={text} onChange={e=>setText(e.target.value)} rows={20} className="w-full bg-zinc-900 border border-border rounded p-2 text-sm font-mono" placeholder="[00:12.34] line&#10;[00:15.00] <00:15.00> word <00:15.40> level" />
      </div>
      <div>
        <div className="text-xs text-gray-400 mb-1">Translation / transliteration (helper, .lrc.translation sidecar)</div>
        <textarea value={tr} onChange={e=>setTr(e.target.value)} rows={20} className="w-full bg-zinc-900 border border-border rounded p-2 text-sm" placeholder="Paste translation; not written to LYRICS tag" />
        <button onClick={saveTranslation} className="mt-2 px-3 py-1 bg-zinc-800 rounded text-sm">Save translation sidecar</button>
      </div>
    </div>
  </div>;
}
