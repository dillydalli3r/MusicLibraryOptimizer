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
  /** Bring `el`'s vertical middle to the scroller's middle. `snap` jumps
   * immediately (seeks, track changes); default glides from here. */
  center(el: HTMLElement, snap?: boolean): void;
  /** Stop gliding and adopt the current position as resting (user took
   * over the pane with the wheel / touch). */
  stop(): void;
}

export function createLyricsGlider(c: HTMLElement): LyricsGlider {
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
      target = Math.min(maxTop, Math.max(0, top - (c.clientHeight - el.offsetHeight) / 2));
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
