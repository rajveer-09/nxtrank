/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, type Me } from "./api";

export function useMe() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.me();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 5 * 60_000,
  });
}

/** Why the login screen is showing, told once to the login page. */
export type SignOutReason = "signed_out" | "expired";
let reason: SignOutReason | null = null;

export function markSessionExpired() {
  reason = "expired";
}

export function takeSignOutReason(): SignOutReason | null {
  const r = reason;
  reason = null;
  return r;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Sign out with a short fade, back to the home address (so the next person doesn't
 *  land on this person's last page). Local state is cleared even if the server is unreachable. */
export function useLogout() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [leaving, setLeaving] = useState(false);
  async function logout() {
    if (leaving) return;
    setLeaving(true);
    const root = document.documentElement;
    root.classList.add("app-leaving");
    await Promise.allSettled([api.logout(), wait(reduceMotion() ? 0 : 260)]);
    reason = "signed_out";
    // sign out first (the app is watching "me"), then drop everyone else's cached data;
    // clearing the whole cache first would leave the app holding the old "me"
    qc.setQueryData(["me"], null);
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    navigate("/", { replace: true });
    root.classList.remove("app-leaving");
  }
  return { logout, leaving };
}
