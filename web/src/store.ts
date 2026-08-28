import { create } from "zustand";

type Library = {
  folder: string;
  artists: {
    path: string;
    name: string;
    albums: any[];
  }[];
};

type Store = {
  library: Library | null;
  setLibrary: (l: Library | null) => void;
  selected: string[]; // paths of selected tracks/albums/artists
  setSelected: (s: string[]) => void;
  playing: string | null;
  setPlaying: (p: string | null) => void;
  query: string;
  setQuery: (q: string) => void;
  progress: { done: number; total: number; desc: string } | null;
  setProgress: (p: any) => void;
};

export const useStore = create<Store>((set) => ({
  library: null,
  setLibrary: (library) => set({ library }),
  selected: [],
  setSelected: (selected) => set({ selected }),
  playing: null,
  setPlaying: (playing) => set({ playing }),
  query: "",
  setQuery: (query) => set({ query }),
  progress: null,
  setProgress: (progress) => set({ progress }),
}));
