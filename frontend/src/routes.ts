/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 15 October 2026
 */
import { whenIdle } from "./idle";
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

/** A lazily loaded page whose code can be fetched ahead of time (on hover, or when idle),
 *  so navigating to it is instant. */
export type Page<P> = LazyExoticComponent<ComponentType<P>> & { preload: () => Promise<unknown> };

function page<P>(load: () => Promise<{ default: ComponentType<P> }>): Page<P> {
  let pending: Promise<{ default: ComponentType<P> }> | null = null;
  const once = () => (pending ??= load());
  return Object.assign(lazy(once), { preload: once });
}

export const pages = {
  Login: page(() => import("./pages/Login")),
  Contests: page(() => import("./pages/Contests")),
  ContestPage: page(() => import("./pages/ContestPage")),
  Analytics: page(() => import("./pages/Analytics")),
  Students: page(() => import("./pages/Students")),
  StudentPage: page(() => import("./pages/StudentPage")),
  Admin: page(() => import("./pages/Admin")),
  MyStudents: page(() => import("./pages/MyStudents")),
  Guide: page(() => import("./pages/Guide")),
};

/** Once the first page has its data, fetch the other pages' code while the browser is
 *  idle, so later clicks don't wait on the network. */
export function preloadWhenIdle(list: (() => Promise<unknown>)[]) {
  const run = () => list.reduce<Promise<unknown>>((p, load) => p.then(() => load().catch(() => undefined)), Promise.resolve());
  whenIdle(() => void run(), 4000);
}
