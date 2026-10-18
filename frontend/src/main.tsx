/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ApiError } from "./api";
import { setBusyCheck } from "./idle";
import { markSessionExpired } from "./auth";
import "@fontsource-variable/inter"; // self-hosted, cached forever; only the Latin subset is downloaded
import App from "./App";
import "./index.css";

// Session expired (or signed out in another tab) while browsing: back to the login
// screen, which explains why; the address is kept, so signing in returns here.
function onAuthError(error: unknown) {
  if (!(error instanceof ApiError && error.status === 401)) return;
  if (queryClient.getQueryData(["me"])) markSessionExpired();
  queryClient.setQueryData(["me"], null);
}

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onAuthError }),
  mutationCache: new MutationCache({ onError: onAuthError }),
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      // retry server trouble and dropped connections (status 0), not a 4xx: asking again won't change it
      retry: (count, error) => !(error instanceof ApiError && error.status > 0 && error.status < 500) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
});
// background prefetching waits while the page is loading its own data (idle.ts)
setBusyCheck(() => queryClient.isFetching() > 0);

// Premium click feedback: a soft wave spreads from the pointer on elements with .ripple.
document.addEventListener(
  "pointerdown",
  (e) => {
    const el = (e.target as Element | null)?.closest<HTMLElement>(".ripple");
    if (!el || e.button !== 0 || el.matches(":disabled") || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const r = el.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 2.2;
    const wave = document.createElement("span");
    wave.className = "ripple-wave";
    wave.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
    el.appendChild(wave);
    wave.addEventListener("animationend", () => wave.remove());
  },
  { passive: true },
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
