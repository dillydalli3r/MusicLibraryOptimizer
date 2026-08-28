import { create } from "zustand";

export interface QueueTrack {
  path: string;
  file: string;
  albumPath: string;
  artist?: string;
}

interface Store {
  folder: string | null;
  setFolder: (f: string | null) => void;
  config: Record<string, unknown> | null;
  setConfig: (c: Record<string, unknown> | null) => void;
  progress: { done: number; total: number; desc: string } | null;
  setProgress: (p: { done: number; total: number; desc: string } | null) => void;
  playing: string | null;
  setPlaying: (p: string | null) => void;
  queue: QueueTrack[];
  setQueue: (q: QueueTrack[]) => void;
  index: number;
  setIndex: (i: number) => void;
  playNow: (q: QueueTrack[], i?: number) => void;
  selected: string[];
  setSelected: (s: string[]) => void;
  selectionAlbum: string | null;
  setSelectionAlbum: (p: string | null) => void;
  query: string;
  setQuery: (q: string) => void;
  sort: { key: string; dir: 1 | -1 } | null;
  setSort: (s: { key: string; dir: 1 | -1 } | null) => void;
  filter: Record<string, unknown>;
  setFilter: (f: Record<string, unknown>) => void;
  toast: string | null;
  setToast: (t: string | null) => void;
}

export const useStore = create<Store>((set) => ({
  folder: null,
  setFolder: (folder) => set({ folder }),
  config: null,
  setConfig: (config) => set({ config }),
  progress: null,
  setProgress: (progress) => set({ progress }),
  playing: null,
  setPlaying: (playing) => set({ playing }),
  queue: [],
  setQueue: (queue) => set({ queue }),
  index: 0,
  setIndex: (index) => set({ index }),
  playNow: (queue, index = 0) =>
    set({ queue, index, playing: queue[index]?.path ?? null }),
  selected: [],
  setSelected: (selected) => set({ selected }),
  selectionAlbum: null,
  setSelectionAlbum: (selectionAlbum) => set({ selectionAlbum }),
  query: "",
  setQuery: (query) => set({ query }),
  sort: null,
  setSort: (sort) => set({ sort }),
  filter: {},
  setFilter: (filter) => set({ filter }),
  toast: null,
  setToast: (toast) => set({ toast }),
}));

export function toast(msg: string) {
  useStore.getState().setToast(msg);
  setTimeout(() => useStore.getState().setToast(null), 3000);
}