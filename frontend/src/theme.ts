/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";

const KEY = "theme";
const listeners = new Set<() => void>();

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function setTheme(next: Theme) {
  if (next === currentTheme()) return;
  const root = document.documentElement;
  root.classList.add("theme-transition"); // cross-fade colours, then remove
  root.dataset.theme = next;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "light" ? "#ffffff" : "#17191c");
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* private mode: theme just won't persist */
  }
  window.setTimeout(() => root.classList.remove("theme-transition"), 320);
  listeners.forEach((l) => l());
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
