/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
import { startTransition, useEffect, useRef, useState, type ReactNode } from "react";

/** How close (px) a `whenNear` section must scroll before it's drawn: about a screen
 *  ahead, so it's ready by the time it's in view. */
const NEAR_PX = 900;

/** Draws a below-the-fold section just after the first paint, in its own short task
 *  (`order` staggers them), so heavy pages don't block the main thread. With `whenNear`
 *  it waits until the reader scrolls towards it (for the heaviest sections, e.g. a
 *  1,500-row leaderboard), and draws it anyway once the page has been idle a while. */
export function Later({
  order = 1,
  minHeight = 320,
  whenNear = false,
  children,
}: {
  order?: number;
  minHeight?: number;
  whenNear?: boolean;
  children: ReactNode;
}) {
  const [ready, setReady] = useState(false);
  const placeholder = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const show = () => startTransition(() => setReady(true));
    if (whenNear && typeof IntersectionObserver !== "undefined") {
      const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && show(), {
        rootMargin: `${NEAR_PX}px 0px`,
      });
      if (placeholder.current) io.observe(placeholder.current);
      const idle = setTimeout(show, 8000); // ready for Ctrl+F and printing without scrolling
      return () => {
        io.disconnect();
        clearTimeout(idle);
      };
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    const frame = requestAnimationFrame(() => {
      timer = setTimeout(show, order * 16);
    });
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
    };
  }, [order, whenNear]);
  if (!ready) return <div ref={placeholder} aria-hidden style={{ minHeight }} />;
  return <div className="later">{children}</div>;
}
