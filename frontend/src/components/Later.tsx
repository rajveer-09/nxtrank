/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
import { startTransition, useEffect, useState, type ReactNode } from "react";

/** Draws a below-the-fold section just after the first paint, in its own short task
 *  (`order` staggers them), so heavy pages don't block the main thread. */
export function Later({ order = 1, minHeight = 320, children }: { order?: number; minHeight?: number; children: ReactNode }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const frame = requestAnimationFrame(() => {
      timer = setTimeout(() => startTransition(() => setReady(true)), order * 16);
    });
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
    };
  }, [order]);
  if (!ready) return <div aria-hidden style={{ minHeight }} />;
  return <div className="later">{children}</div>;
}
