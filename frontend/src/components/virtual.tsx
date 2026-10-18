/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
import { useVirtualizer, useWindowVirtualizer, type VirtualItem } from "@tanstack/react-virtual";
import { startTransition, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

/** Virtualised table rows: only rows near the screen are rendered; spacer rows keep the
 *  real <table> height, and aria-rowcount / aria-rowindex keep it accessible. */

export interface VirtualRows {
  items: VirtualItem[];
  /** height of the rows not rendered above / below the visible ones */
  before: number;
  after: number;
  measure: (el: Element | null) => void;
}

function spacers(items: VirtualItem[], total: number, offset: number) {
  if (!items.length) return { before: 0, after: 0 };
  return { before: items[0].start - offset, after: total - (items[items.length - 1].end - offset) };
}

/** Rows of a table that scrolls with the page. Attach `anchor` to the <tbody>. */
export function useWindowRows(count: number, estimate: number, enabled = true): VirtualRows & { anchor: RefObject<HTMLTableSectionElement | null> } {
  const anchor = useRef<HTMLTableSectionElement>(null);
  const [margin, setMargin] = useState(0);
  // every render, on purpose: filters above can wrap and move where the rows start;
  // the 1px guard below stops it from updating in a loop
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    // where the rows start on the page
    const top = anchor.current ? anchor.current.getBoundingClientRect().top + window.scrollY : 0;
    if (Math.abs(top - margin) > 1) setMargin(top);
  });
  const v = useWindowVirtualizer({ count, estimateSize: () => estimate, overscan: 8, scrollMargin: margin, enabled });
  const items = v.getVirtualItems();
  return { anchor, items, ...spacers(items, v.getTotalSize(), margin), measure: v.measureElement };
}

/** Rows of a table inside its own scrolling box. Attach `box` to that element. */
export function useBoxRows(count: number, estimate: number): VirtualRows & { box: RefObject<HTMLDivElement | null>; toTop: () => void } {
  const box = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count, getScrollElement: () => box.current, estimateSize: () => estimate, overscan: 10 });
  const items = v.getVirtualItems();
  return { box, items, ...spacers(items, v.getTotalSize(), 0), measure: v.measureElement, toTop: () => v.scrollToOffset(0) };
}

export function Spacer({ height, cols }: { height: number; cols: number }) {
  if (height <= 0) return null;
  return (
    <tr aria-hidden>
      <td colSpan={cols} style={{ height, padding: 0, border: 0 }} />
    </tr>
  );
}

/** How many of `count` rows to draw: `step` at first, then `step` more each frame,
 *  so a long table appears over a few short tasks instead of one long one. Starts
 *  again when `resetKey` changes (a new page or sort). */
export function useReveal(count: number, step = 12, resetKey: unknown = null): number {
  const [state, setState] = useState({ key: resetKey, shown: step });
  const shown = state.key === resetKey ? state.shown : step;
  useEffect(() => {
    if (shown >= count) return;
    const frame = requestAnimationFrame(() =>
      startTransition(() => setState({ key: resetKey, shown: shown + step })));
    return () => cancelAnimationFrame(frame);
  }, [shown, count, step, resetKey]);
  return Math.min(shown, count);
}
