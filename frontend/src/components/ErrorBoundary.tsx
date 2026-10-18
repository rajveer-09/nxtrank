/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "./ui";

/** Catches a page that throws while rendering, so one broken page shows a calm message
 *  with Reload / Back instead of a blank screen. Keyed by path in Layout: opening
 *  another page starts fresh. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("page crashed", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    // after a new release, an open tab can ask for page code that no longer exists
    const stale = /dynamically imported module|Importing a module script failed|Failed to fetch/i.test(error.message);
    return (
      <div role="alert" className="rise mx-auto flex max-w-md flex-col items-center gap-4 py-16 text-center">
        <div>
          <h1 className="text-[15px] font-semibold text-ink">{stale ? "A newer version is available" : "This page hit a problem"}</h1>
          <p className="mt-1 text-[13px] text-ink-2">
            {stale
              ? "NxtRank was updated since this tab opened. Reload to get the latest version."
              : "Something on this page didn't load properly. Reloading usually fixes it; your data is safe."}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => window.location.reload()}>Reload</Button>
          {!stale && <Button onClick={() => window.history.back()}>Back</Button>}
        </div>
      </div>
    );
  }
}
