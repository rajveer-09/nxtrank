/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { Role } from "./api";
import { prefetchPath } from "./queries";

const HOVER_INTENT_MS = 65; // a pointer that rests this long on a link is heading for it

/** Prefetches the code and data behind any in-app link on hover intent, focus or touch
 *  (one document listener; off when the browser asks to save data). */
export function useIntentPrefetch(role: Role | undefined) {
  const qc = useQueryClient();
  useEffect(() => {
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    if (connection?.saveData) return;

    let timer: ReturnType<typeof setTimeout> | undefined;
    let current: HTMLAnchorElement | null = null;
    const linkOf = (target: EventTarget | null) =>
      target instanceof Element ? (target.closest("a[href]") as HTMLAnchorElement | null) : null;
    const usable = (a: HTMLAnchorElement | null): a is HTMLAnchorElement =>
      !!a && !a.target && !a.hasAttribute("download") && a.origin === window.location.origin &&
      a.pathname + a.search !== window.location.pathname + window.location.search;
    const prefetch = (a: HTMLAnchorElement) => prefetchPath(qc, a.href, role);

    const onOver = (e: PointerEvent) => {
      const a = linkOf(e.target);
      if (a === current) return; // still on the same link
      clearTimeout(timer);
      current = a;
      if (usable(a)) timer = setTimeout(() => prefetch(a), HOVER_INTENT_MS);
    };
    const onNow = (e: Event) => {
      const a = linkOf(e.target);
      if (usable(a)) prefetch(a);
    };

    document.addEventListener("pointerover", onOver);
    document.addEventListener("focusin", onNow);
    document.addEventListener("touchstart", onNow, { passive: true });
    return () => {
      clearTimeout(timer);
      document.removeEventListener("pointerover", onOver);
      document.removeEventListener("focusin", onNow);
      document.removeEventListener("touchstart", onNow);
    };
  }, [qc, role]);
}

/** Run `fn` when the browser has nothing else to do; returns a cancel function. */
export { whenIdle } from "./idle";
