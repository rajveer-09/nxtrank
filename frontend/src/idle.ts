/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 18 October 2026
 */
// Background work (other pages' code, likely next pages' data) waits until the page
// you're on has its own data, then for an idle moment, so it never queues ahead of what
// you're waiting for on a slow connection.

let busy: () => boolean = () => false;
const MAX_WAIT_MS = 8000; // don't hold background work back for ever

/** Set once at start-up: whether the page is still loading its own data. */
export function setBusyCheck(check: () => boolean) {
  busy = check;
}

type IdleWindow = Window & {
  requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
  cancelIdleCallback?: (id: number) => void;
};

/** Run `fn` once the page's own requests are done and the browser is idle. Returns a cancel. */
export function whenIdle(fn: () => void, timeout = 3000): () => void {
  const w = window as IdleWindow;
  const started = Date.now();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let idle: number | undefined;
  let cancelled = false;
  const attempt = () => {
    if (cancelled) return;
    if (busy() && Date.now() - started < MAX_WAIT_MS) {
      timer = setTimeout(attempt, 150);
      return;
    }
    if (w.requestIdleCallback) idle = w.requestIdleCallback(() => !cancelled && fn(), { timeout });
    else timer = setTimeout(() => !cancelled && fn(), 300);
  };
  attempt();
  return () => {
    cancelled = true;
    clearTimeout(timer);
    if (idle != null) w.cancelIdleCallback?.(idle);
  };
}
