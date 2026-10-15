/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
import type { ReactNode } from "react";
import { cx } from "./ui";

/** Loading states shaped like the pages they stand in for, so nothing jumps when the
 *  data arrives. Each is announced once to screen readers ("Loading …"). */

function Bar({ className }: { className?: string }) {
  return <span aria-hidden className={cx("skeleton h-3", className)} />;
}

function Loading({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cx("flex flex-col gap-6", className)}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

function CardShell({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <div aria-hidden className={cx("overflow-hidden rounded-lg bg-surface shadow-card ring-1 ring-inset ring-(--card-ring)", className)}>
      {children}
    </div>
  );
}

function PageTitle({ back = false, meta = true }: { back?: boolean; meta?: boolean }) {
  return (
    <div aria-hidden className="flex flex-col gap-2">
      {back && <Bar className="h-3 w-20" />}
      <Bar className="h-5 w-56" />
      {meta && <Bar className="w-80 max-w-full" />}
    </div>
  );
}

function Stats({ n, cols }: { n: number; cols: string }) {
  return (
    <div aria-hidden className={cx("grid grid-cols-2 gap-2", cols)}>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="flex h-[86px] flex-col gap-2 rounded-md bg-surface px-4 py-3 shadow-card ring-1 ring-inset ring-(--card-ring)">
          <Bar className="h-2.5 w-20" />
          <Bar className="h-5 w-16" />
          <Bar className="h-2.5 w-24" />
        </div>
      ))}
    </div>
  );
}

/** Table rows: a first column with two lines (name / detail), then short cells. */
function Rows({ rows, cols }: { rows: number; cols: number }) {
  return (
    <div aria-hidden className="divide-y divide-fg/5 border-t border-fg/5">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex items-center gap-6 px-5 py-3">
          <div className="flex w-48 shrink-0 flex-col gap-1.5">
            <Bar className={r % 3 === 1 ? "w-32" : "w-40"} />
            <Bar className="h-2.5 w-24" />
          </div>
          {Array.from({ length: cols - 1 }, (_, c) => (
            <Bar key={c} className={cx("hidden flex-1 sm:block", c % 2 ? "max-w-16" : "max-w-24")} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Rows inside a card that is already on screen (a section's list loading). */
export function RowsSkeleton({ rows = 6, cols = 5, label = "Loading…" }: { rows?: number; cols?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Rows rows={rows} cols={cols} />
    </div>
  );
}

function TableCard({ rows = 8, cols = 5, filters = true }: { rows?: number; cols?: number; filters?: boolean }) {
  return (
    <CardShell>
      <div className="flex flex-col gap-2 px-5 pb-3 pt-4">
        <Bar className="w-28" />
        <Bar className="h-2.5 w-64 max-w-full" />
      </div>
      {filters && (
        <div className="flex gap-2 border-t border-fg/5 bg-fg/[0.015] px-5 py-2">
          <Bar className="h-8 w-64 rounded-md" />
          <Bar className="h-8 w-32 rounded-md" />
        </div>
      )}
      <Rows rows={rows} cols={cols} />
    </CardShell>
  );
}

export function ContestsSkeleton() {
  return (
    <Loading label="Loading contests…">
      <PageTitle />
      <div aria-hidden className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <CardShell key={i} className="flex h-[188px] flex-col gap-3 p-4">
            <Bar className="h-2.5 w-16" />
            <Bar className="h-4 w-40" />
            <Bar className="h-2.5 w-32" />
            <div className="mt-1 flex gap-1.5">
              {[0, 1, 2, 3].map((j) => <Bar key={j} className="h-11 w-11 rounded-md" />)}
            </div>
          </CardShell>
        ))}
      </div>
      <TableCard rows={8} cols={6} />
    </Loading>
  );
}

export function ContestSkeleton() {
  return (
    <Loading label="Loading the contest…">
      <PageTitle back />
      <Stats n={5} cols="md:grid-cols-3 xl:grid-cols-5" />
      <TableCard rows={10} cols={7} />
    </Loading>
  );
}

export function StudentSkeleton() {
  return (
    <Loading label="Loading the student…">
      <PageTitle back />
      <Stats n={6} cols="md:grid-cols-3 xl:grid-cols-6" />
      <TableCard rows={4} cols={6} filters={false} />
    </Loading>
  );
}

/** The student page's analytics section (below the name). */
export function StudentAnalyticsSkeleton() {
  return (
    <Loading label="Loading analytics…">
      <Stats n={6} cols="md:grid-cols-3 xl:grid-cols-6" />
      <TableCard rows={4} cols={6} filters={false} />
    </Loading>
  );
}

/** Everything below the analytics filters. */
export function AnalyticsSkeleton() {
  return (
    <Loading label="Loading analytics…">
      <Stats n={5} cols="md:grid-cols-3 xl:grid-cols-5" />
      <div aria-hidden className="grid gap-4 lg:grid-cols-2">
        <CardShell className="h-64" />
        <CardShell className="h-64" />
      </div>
      <TableCard rows={8} cols={7} />
    </Loading>
  );
}

export function StudentsSkeleton() {
  return (
    <Loading label="Loading students…">
      <PageTitle />
      <TableCard rows={12} cols={7} />
    </Loading>
  );
}

/** While a page's code loads (first visit to it). */
export function PageSkeleton() {
  return (
    <Loading label="Loading…">
      <PageTitle />
      <TableCard rows={6} cols={5} />
    </Loading>
  );
}
