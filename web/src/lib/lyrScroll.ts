/** Shared lyrics-pane scrolling for the sidebar and the fullscreen player.

 * Centering uses ONLY offset layout values (offsetTop / offsetHeight /
 * clientHeight) — never getBoundingClientRect. The fullscreen pane scales
 * its content with CSS `zoom`, and inactive lines carry a transform scale;
 * gBCR reports visual pixels while scrollTop is written in layout units, so
 * mixing the two landed every scroll target off by the zoom factor. Offset
 * math is blind to both, which also makes the centering independent of
 * screen / pane size.

 * The glide is a retargetable rAF ease instead of scrollTo({smooth}): a
 * native smooth scroll interrupted by the next line change restarts its
 * animation and reads as a jerk; this loop simply re-aims each frame, so
 * any number of rapid retargets stays one continuous motion. */

export interface LyricsGlider {
  /** Bring `el` to the pane's lyric anchor line. `snap` jumps immediately
   * (seeks, track changes); default glides from here. */
  center(el: HTMLElement, snap?: boolean): void;
  /** Stop gliding and adopt the current position as resting (user took
   * over the pane with the wheel / touch). */
  stop(): void;
}

/** Where the currently-sung line sits vertically, as a fraction of the
 * pane height: the upper third — ahead of the reader's eye, with the
 * upcoming lines filling the space below. */
export const LYRICS_ANCHOR = 0.33;

export function createLyricsGlider(c: HTMLElement, anchor: number = LYRICS_ANCHOR): LyricsGlider {
  let target = c.scrollTop;
  let raf = 0;
  let active = false;
  const step = () => {
    const diff = target - c.scrollTop;
    if (Math.abs(diff) < 0.5) {
      c.scrollTop = target;
      active = false;
      return;
    }
    c.scrollTop += diff * 0.16;
    raf = requestAnimationFrame(step);
  };
  return {
    center(el, snap = false) {
      // Walk the offsetParent chain up to the scroller (it is the nearest
      // positioned ancestor — both panes mark it `relative`).
      let top = 0;
      let n: HTMLElement | null = el;
      while (n && n !== c) {
        top += n.offsetTop;
        n = n.offsetParent as HTMLElement | null;
      }
      if (n !== c) return; // el is not inside the scroller — refuse to guess
      const maxTop = Math.max(0, c.scrollHeight - c.clientHeight);
      // Anchor: the line's vertical middle lands at `anchor` × height
      // (the upper third) instead of the pane's exact middle.
      target = Math.min(maxTop, Math.max(0, top + el.offsetHeight / 2 - c.clientHeight * anchor));
      cancelAnimationFrame(raf);
      if (snap) {
        c.scrollTop = target;
        active = false;
        return;
      }
      if (!active) {
        active = true;
        raf = requestAnimationFrame(step);
      }
    },
    stop() {
      cancelAnimationFrame(raf);
      active = false;
      target = c.scrollTop;
    },
  };
}
