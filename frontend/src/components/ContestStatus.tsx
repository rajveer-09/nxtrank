/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useMe } from "../auth";
import { api, type ContestStatus, type WorkerStatus } from "../api";
import { fmtIso, fmtPct, fmtWhen } from "../format";
import { Button, ContestStateBadge, Dialog, ErrorBox, Spinner, cx } from "./ui";

export function useGetResults(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.getResults(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contests"] });
      qc.invalidateQueries({ queryKey: ["contest", slug] });
    },
  });
}

/** Button to queue a scan, after a confirmation pop-up. Admins and viewers can fetch a
 *  contest without results; rescans are admin-only; instructors are read-only. */
export function GetResultsButton({ slug, status, isAdmin, compact, title }: { slug: string; status: ContestStatus; isAdmin: boolean; compact?: boolean; title?: string }) {
  const me = useMe().data;
  const m = useGetResults(slug);
  const [open, setOpen] = useState(false);
  const label = status.state === "failed" ? "Try again" : status.has_data ? "Rescan" : "Get results";
  const allowed = me?.role !== "instructor" && (status.has_data ? isAdmin : true);
  const busy = status.state === "scanning" || status.state === "queued";
  if (!allowed || busy || ["upcoming", "live", "scheduled"].includes(status.state)) return null;
  return (
    <>
      <Button
        variant={status.has_data ? "ghost" : "primary"}
        size={compact ? "sm" : "md"}
        onClick={() => {
          m.reset();
          setOpen(true);
        }}
        title={status.has_data ? "Scan this contest again" : "Fetch this contest's results for all students"}
      >
        {label}
      </Button>
      <ScanConfirm
        slug={slug}
        title={title}
        open={open}
        rescan={status.has_data}
        pending={m.isPending}
        error={m.error}
        onClose={() => setOpen(false)}
        onConfirm={() => m.mutate(undefined, { onSuccess: () => setOpen(false) })}
      />
    </>
  );
}

const titleOf = (slug: string) => slug.split("-").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");

/** "Rescan Weekly Contest 519?" — what will happen, then Confirm starts it. */
export function ScanConfirm({
  slug,
  title,
  open,
  rescan,
  pending,
  error,
  onClose,
  onConfirm,
}: {
  slug: string;
  title?: string;
  open: boolean;
  rescan?: boolean;
  pending: boolean;
  error: unknown;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const preview = useQuery({ queryKey: ["scan-preview", slug], queryFn: () => api.scanPreview(slug), enabled: open, staleTime: 0, gcTime: 0, retry: false });
  const p = preview.data;
  const name = p?.title ?? title ?? titleOf(slug);
  const isRescan = p ? p.has_data : !!rescan;
  const minutes = p ? Math.max(1, Math.round(p.typical_scan_secs / 60)) : 10;
  const blocked = !!p && (!!p.already || !p.can_request);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={pending}
      title={isRescan ? `Rescan ${name}?` : `Get results for ${name}?`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirm} disabled={pending || preview.isPending || preview.isError || blocked} autoFocus>
            {pending ? "Starting…" : isRescan ? "Yes, rescan" : "Yes, get results"}
          </Button>
        </>
      }
    >
      {preview.isPending ? (
        <Spinner label="Checking…" />
      ) : preview.isError ? (
        <ErrorBox error={preview.error} />
      ) : (
        <div className="flex flex-col gap-3">
          <p>
            {isRescan
              ? "The whole LeetCode leaderboard is read again and every student's result is replaced. The current results stay visible until the new scan finishes; removed students' past results are kept."
              : "The whole LeetCode leaderboard is read to find every student's result."}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-lg bg-fg/[0.03] px-4 py-3 ring-1 ring-inset ring-fg/[0.06]">
            <dt className="text-ink-3">Results</dt>
            <dd>
              {p!.kind === "final" ? (
                <>
                  <ContestStateBadge state="final" /> <span className="ml-1 text-ink-3">LeetCode has finalised this contest</span>
                </>
              ) : p!.kind === "provisional" ? (
                <>
                  <ContestStateBadge state="provisional" />
                  <div className="mt-1 text-xs text-ink-3">
                    {p!.final_ready_at ? `Final results by ${fmtWhen(p!.final_ready_at)}, collected automatically.` : "Final results are collected automatically later."}
                  </div>
                </>
              ) : (
                <span>Early or final, from the contest's date</span>
              )}
            </dd>
            <dt className="text-ink-3">Students</dt>
            <dd className="text-ink">{p!.students.toLocaleString()} active students are matched</dd>
            <dt className="text-ink-3">Takes</dt>
            <dd className="text-ink">
              About {minutes} minutes{p!.ahead > 0 ? `, after ${p!.ahead} ${p!.ahead === 1 ? "scan" : "scans"} ahead of it` : ""}
              <div className="text-xs text-ink-3">Ready around {fmtIso(p!.ready_at)}</div>
            </dd>
          </dl>
          {p!.already && <ErrorBox error={p!.already === "scanning" ? "This contest is being scanned right now." : "This contest is already in the scan queue."} />}
          {!p!.can_request && <ErrorBox error="Only admins can rescan a contest that already has results." />}
          {!p!.worker.alive && <ErrorBox error="The background worker isn't running, so the scan won't start until it does." />}
          {error != null && <ErrorBox error={error} />}
        </div>
      )}
    </Dialog>
  );
}

/** Who may cancel: admins, or the person who requested the scan. Automatic scans
 *  (no requester) can only be stopped by admins. */
export function useCanCancel(requestedBy: string | null | undefined) {
  const me = useMe().data;
  if (!me || me.role === "instructor") return false; // instructors are read-only
  return me.role === "admin" || (!!requestedBy && requestedBy === me.username);
}

export function useCancelScan(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelScan(slug),
    onSuccess: () => {
      for (const key of ["contests", "contest", "scan-status", "scan-requests", "scan-runs"]) qc.invalidateQueries({ queryKey: [key] });
    },
  });
}

/** Cancel a queued scan (one click) or stop a running one (click, then confirm). */
export function CancelScanButton({
  slug,
  running = false,
  requestedBy,
  cancelRequested = false,
  size = "sm",
}: {
  slug: string;
  running?: boolean;
  requestedBy?: string | null;
  cancelRequested?: boolean;
  size?: "sm" | "md";
}) {
  const allowed = useCanCancel(requestedBy);
  const m = useCancelScan(slug);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    if (!confirm) return;
    const id = window.setTimeout(() => setConfirm(false), 4000);
    return () => window.clearTimeout(id);
  }, [confirm]);

  if (!allowed) return null;
  if (cancelRequested || (running && m.isSuccess))
    return <span className="inline-flex items-center gap-1.5 text-xs text-ink-3"><span className="live-dot h-1.5 w-1.5 rounded-full bg-critical" />Stopping…</span>;

  const onClick = () => {
    if (running && !confirm) return setConfirm(true);
    setConfirm(false);
    m.mutate();
  };
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button
        variant="ghost"
        size={size}
        disabled={m.isPending}
        onClick={onClick}
        title={running ? "Stop this scan (results so far are discarded)" : "Remove this scan from the queue"}
        className={cx(
          "gap-1 text-ink-3 hover:bg-critical/10 hover:text-critical-ink",
          confirm && "bg-critical/10 text-critical-ink ring-1 ring-inset ring-critical/30",
        )}
      >
        <svg aria-hidden viewBox="0 0 12 12" className="h-3 w-3">
          {running ? (
            <rect x="3" y="3" width="6" height="6" rx="1" fill="currentColor" />
          ) : (
            <path d="m3.5 3.5 5 5m0-5-5 5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          )}
        </svg>
        {m.isPending ? "Cancelling…" : confirm ? "Stop scan?" : running ? "Stop" : "Cancel"}
      </Button>
      {m.isError && <span className="text-xs text-critical">{(m.error as Error).message}</span>}
    </span>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-bar-track" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div className="progress-fill relative h-full overflow-hidden rounded-full bg-accent transition-[width] duration-700 ease-out" style={{ width: `${Math.max(value * 100, 2)}%` }} />
    </div>
  );
}

const etaTime = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const etaDay = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" });

/** "Ready by" as a compact chip: clock · time · relative ("in 8 min"); a pulsing dot when
 *  it's due any moment. */
export function Eta({ iso, label }: { iso: string; label?: string }) {
  const t = new Date(iso);
  const now = Date.now();
  const mins = Math.round((t.getTime() - now) / 60_000);
  const sameDay = new Date(now).toDateString() === t.toDateString();
  const soon = mins <= 1;
  const rel = soon ? "finishing up" : mins < 60 ? `in ${mins} min` : mins < 24 * 60 && sameDay ? `in ${Math.round(mins / 60)} hr` : etaDay.format(t);
  return (
    <span
      className="eta-chip inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded-full pl-1.5 pr-2 text-[11px] leading-none"
      title={`${label ?? "Ready"} by ${t.toLocaleString()}`}
    >
      {soon ? (
        <span aria-hidden className="grid h-3.5 w-3.5 place-items-center">
          <span className="live-dot h-1.5 w-1.5 rounded-full bg-accent" />
        </span>
      ) : (
        <svg aria-hidden viewBox="0 0 14 14" className="h-3.5 w-3.5 text-ink-3">
          <circle cx="7" cy="7" r="5.6" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M7 4.3V7l1.8 1.1" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      )}
      {label && <span className="text-ink-3">{label}</span>}
      <span className="tabular font-semibold text-ink">{etaTime.format(t)}</span>
      <span className="text-ink-3">· {rel}</span>
    </span>
  );
}

/** One-line description of where a contest stands, with ETA. */
export function StatusDetail({ status, worker }: { status: ContestStatus; worker?: WorkerStatus }) {
  const waiting = worker && !worker.alive;
  switch (status.state) {
    case "scanning":
      return (
        <div className="flex min-w-52 flex-col gap-1.5">
          <ProgressBar value={status.progress ?? 0} label="Scan progress" />
          <div className="flex items-center gap-2">
            <span className="tabular text-xs font-semibold text-ink">{fmtPct(status.progress ?? 0)}</span>
            {status.ready_at && <Eta iso={status.ready_at} />}
          </div>
        </div>
      );
    case "queued":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <span className="tabular rounded-md bg-fg/[0.05] px-1.5 py-0.5 text-[11px] font-semibold text-ink-2">#{status.position} in queue</span>
          {waiting || !status.ready_at ? <span className="text-xs text-ink-3">starts when the worker runs</span> : <Eta iso={status.ready_at} />}
        </div>
      );
    case "scheduled":
    case "upcoming":
    case "live":
      return status.ready_at ? (
        <Eta iso={status.ready_at} label="Results" />
      ) : (
        <span className="text-xs text-ink-3">scanned automatically once the worker runs</span>
      );
    case "failed":
      return <span className="line-clamp-2 max-w-xs text-xs text-ink-2" title={status.error ?? ""}>{status.error}</span>;
    case "provisional":
      return (
        <div className="flex flex-col gap-0.5 text-xs text-ink-3">
          {status.scanned_at && <span>collected {fmtIso(status.scanned_at)}</span>}
          {status.final_at && (
            <span className="inline-flex items-center gap-1 text-info-ink" title="Final results are collected automatically at 11 pm on the 5th working day after the contest, once LeetCode has settled ranks and ratings.">
              <svg aria-hidden viewBox="0 0 12 12" className="h-3 w-3">
                <path d="M6 3.2V6l1.8 1.1M11 6A5 5 0 1 1 1 6a5 5 0 0 1 10 0Z" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
              Final results by {fmtWhen(status.final_at)}
            </span>
          )}
        </div>
      );
    case "final":
      return status.scanned_at ? <span className="text-xs text-ink-3">collected {fmtIso(status.scanned_at)}</span> : null;
    default:
      return null;
  }
}

/** Big panel for a contest page that has no results yet. */
export function NoResultsPanel({ slug, status, isAdmin, worker }: { slug: string; status: ContestStatus; isAdmin: boolean; worker?: WorkerStatus }) {
  const readOnly = useMe().data?.role === "instructor";
  const titles: Partial<Record<ContestStatus["state"], string>> = {
    scanning: "Collecting results…",
    queued: "Waiting in the scan queue",
    scheduled: "Results will be collected automatically",
    upcoming: "This contest hasn't started yet",
    live: "This contest is running now",
    failed: "The last scan failed",
    not_scanned: "No results for this contest yet",
  };
  const help: Partial<Record<ContestStatus["state"], string>> = {
    scanning: "The whole LeetCode leaderboard is being read to find every student. This page updates by itself.",
    queued: "Other contests are being scanned first. This page updates by itself.",
    scheduled: "The worker scans contests 30 minutes after they end.",
    not_scanned: readOnly
      ? "An admin can fetch this contest's results."
      : "Fetch the leaderboard to see how every student did. It takes about 10 minutes for a recent contest, less for older ones.",
    failed: readOnly ? "An admin can try again." : "You can try again. If it keeps failing, LeetCode may be blocking the server (see the Admin page).",
  };
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-border bg-surface px-6 py-8">
      <div className="flex items-center gap-2">
        <ContestStateBadge state={status.state} />
        <h2 className="text-lg font-semibold">{titles[status.state] ?? "No results yet"}</h2>
      </div>
      {help[status.state] && <p className="max-w-2xl text-[13px] text-ink-2">{help[status.state]}</p>}
      <div className="w-full max-w-md">
        <StatusDetail status={status} worker={worker} />
      </div>
      {worker && !worker.alive && (status.state === "queued" || status.state === "scheduled") && (
        <ErrorBox error="The background worker isn't running, so nothing will be scanned until it starts (python -m app.cli worker)." />
      )}
      <div className="flex items-center gap-2">
        <GetResultsButton slug={slug} status={status} isAdmin={isAdmin} />
        {(status.state === "queued" || status.state === "scanning") && (
          <CancelScanButton
            slug={slug}
            running={status.state === "scanning"}
            requestedBy={status.requested_by}
            cancelRequested={status.cancel_requested}
            size="md"
          />
        )}
      </div>
    </div>
  );
}
