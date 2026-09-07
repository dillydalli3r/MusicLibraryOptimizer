/** Library scripts (numbers match the runner registry in server/main.py and
 * mlo/cliapp.py). Shared by the library selection menus and the Optimization
 * page so every surface offers the same set. */
export const SCRIPTS: { ids: number[]; label: string }[] = [
  { ids: [1], label: "Format lyrics" },
  { ids: [2], label: "Format CUEs" },
  { ids: [3], label: "Optimize FLACs" },
  { ids: [5], label: "Process images" },
  { ids: [6], label: "Audit library" },
  { ids: [7], label: "DR & ReplayGain" },
  { ids: [8], label: "Auto tagging" },
  { ids: [13], label: "Fetch lyrics" },
  { ids: [15], label: "Lyrics xlit / translate (AI)" },
  { ids: [11], label: "Remux videos (MKV)" },
  { ids: [12], label: "Key & BPM" },
  { ids: [9], label: "AccurateRip" },
  { ids: [10], label: "Format all" },
  { ids: [4], label: "Grade" },
];

/** Default Run All order: videos first (slow, bit-exact), grading last. */
export const DEFAULT_RUN_ALL = [11, 14, 1, 2, 8, 13, 15, 12, 3, 5, 9, 6, 4, 7, 10];
