/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useSyncExternalStore } from "react";
import { flushSync } from "react-dom";

export type Theme = "dark" | "light";

const KEY = "theme";
const listeners = new Set<() => void>();

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function apply(next: Theme) {
  document.documentElement.dataset.theme = next;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "light" ? "#ffffff" : "#17191c");
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* private mode: theme just won't persist */
  }
  listeners.forEach((l) => l());
}

type ViewTransitionDoc = Document & { startViewTransition?: (update: () => void) => unknown };

/** Switch theme: the whole page cross-fades at once, quickly (View Transitions), so
 *  gradients, shadows and charts change together. Without View Transitions (or with
 *  reduced motion) it switches at once. */
export function setTheme(next: Theme) {
  if (next === currentTheme()) return;
  const doc = document as ViewTransitionDoc;
  if (!doc.startViewTransition || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    apply(next);
    return;
  }
  doc.startViewTransition(() => flushSync(() => apply(next)));
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

/** Shared theme state (every toggle stays in sync). The initial value is applied in
 *  index.html before first paint. */
export function useTheme(): [Theme, () => void, (t: Theme) => void] {
  const theme = useSyncExternalStore(subscribe, currentTheme);
  return [theme, () => setTheme(theme === "dark" ? "light" : "dark"), setTheme];
}
