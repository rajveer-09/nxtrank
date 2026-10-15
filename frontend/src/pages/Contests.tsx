/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { type ContestListItem, type ContestPage, type ContestQuery } from "../api";
import { CancelScanButton, Eta, GetResultsButton, ProgressBar, StatusDetail } from "../components/ContestStatus";
import { Button, Card, CardHeader, ContestStateBadge, Empty, ErrorBox, Input, Select, cx } from "../components/ui";
import { fmtDateTime, fmtDecimal, fmtInt, fmtPct } from "../format";
import { useMe } from "../auth";
import { whenIdle } from "../prefetch";
import { contestsQuery, prefetchPath } from "../queries";
import { ContestsSkeleton } from "../components/skeletons";

const SHOW: { value: NonNullable<ContestQuery["show"]>; label: string }[] = [
  { value: "all", label: "All" },
  { value: "with_data", label: "With results" },
  { value: "without_data", label: "Not scanned yet" },
];

export default function Contests({ isAdmin }: { isAdmin: boolean }) {
  const [show, setShow] = useState<NonNullable<ContestQuery["show"]>>("all");
  const [type, setType] = useState<ContestQuery["type"]>("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const query: ContestQuery = { show, type, q: q.trim(), page, per_page: 25 };
  const contests = useQuery({
    ...contestsQuery(query),
    placeholderData: keepPreviousData,
    // poll quickly while something is being scanned
    refetchInterval: (qq) => (qq.state.data && (qq.state.data.running || qq.state.data.queue.length) ? 5_000 : 60_000),
  });
  // the most likely next click: the newest contest with results. Fetch it while idle.
  const qc = useQueryClient();
  const role = useMe().data?.role;
  const likely = contests.data?.items.find((c) => c.has_data)?.slug;
  useEffect(() => {
    if (likely) return whenIdle(() => prefetchPath(qc, `/contests/${likely}`, role));
  }, [likely, qc, role]);

  if (contests.isPending) return <ContestsSkeleton />;
  if (contests.isError) return <ErrorBox error={contests.error} />;
  const d = contests.data;
  const pages = Math.max(1, Math.ceil(d.total / d.per_page));

  return (
    <div className="relative flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">Contests</h1>
        <p className="mt-1 text-[13px] text-ink-2">
          New contests are collected automatically 30 minutes after they end. For any past contest, click{" "}
          <span className="font-medium text-ink">Get results</span> to fetch it.
        </p>
      </div>

      <ScanActivity d={d} />

      {d.upcoming.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {d.upcoming.map((c, i) => (
            <UpcomingCard key={c.slug} c={c} next={i === 0} delay={i * 70} />
          ))}
        </div>
      )}

      <Card>
        <CardHeader title="Past contests" subtitle={`${fmtInt(d.with_data)} with results. Click a contest to see every student's result.`} />
        <div className="flex flex-wrap items-center gap-2 border-y border-fg/5 bg-fg/[0.015] px-5 py-2 [&_label>span:first-child]:sr-only">
          <div role="radiogroup" aria-label="Show" className="flex rounded-md bg-fg/[0.04] p-0.5 ring-1 ring-inset ring-fg/5">
            {SHOW.map((o) => (
              <button
                key={o.value}
                role="radio"
                aria-checked={show === o.value}
                onClick={() => { setShow(o.value); setPage(1); }}
                className={cx("ripple rounded-[5px] px-2.5 py-1 text-xs font-medium", show === o.value ? "bg-surface-2 text-ink ring-1 ring-inset ring-fg/5" : "text-ink-3 hover:text-ink")}
              >
                {o.label}
              </button>
            ))}
          </div>
          <Select label="Type" value={type} onChange={(e) => { setType(e.target.value as ContestQuery["type"]); setPage(1); }}>
            <option value="">Weekly & biweekly</option>
            <option value="weekly">Weekly</option>
            <option value="biweekly">Biweekly</option>
          </Select>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Search</span>
            <Input type="search" placeholder="Contest number" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="w-40" />
          </label>
        </div>
        {d.items.length === 0 ? (
          <Empty>{d.total === 0 && show === "all" && !q ? "The contest list hasn't been loaded yet. The worker fetches it from LeetCode when it starts." : "No contests match."}</Empty>
        ) : (
          <div className={cx("overflow-x-auto transition-opacity", contests.isPlaceholderData && "opacity-60")}>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-ink-2">
                <tr className="border-b border-fg/5">
                  <th className="px-5 py-2 font-medium">Contest</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Participated</th>
                  <th className="px-3 py-2 text-right font-medium">Solved ≥ 1</th>
                  <th className="px-3 py-2 text-right font-medium">Avg solved</th>
                  <th className="px-3 py-2 text-right font-medium">Best rank</th>
                  <th className="px-5 py-2" />
                </tr>
              </thead>
              <tbody>
                {d.items.map((c) => (
                  <ContestRow key={c.slug} c={c} isAdmin={isAdmin} d={d} latest={d.latest_slugs.includes(c.slug)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-border px-5 py-3 text-[13px] text-ink-2">
          <span className="tabular">
            Page {d.page} of {pages} · {fmtInt(d.total)} contests
          </span>
          <div className="flex gap-2">
            <Button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Newer
            </Button>
            <Button disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Older
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

const slugTitle = (slug: string) => slug.split("-").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");

function ScanActivity({ d }: { d: ContestPage }) {
  if (!d.running && d.queue.length === 0) return null;
  const r = d.running;
  return (
    <Card>
      {!d.worker.alive && (
        <div className="px-5 pt-4">
          <ErrorBox error="The background worker isn't running, so queued scans won't start until it does (python -m app.cli worker)." />
        </div>
      )}
      {r && (
        <div className="grid items-center gap-x-8 gap-y-3 px-5 py-4 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-accent-ink">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-accent" />
              Scanning now
            </div>
            <Link to={`/contests/${r.slug}`} className="mt-1 block truncate text-[15px] font-semibold tracking-tight text-ink hover:text-accent-ink">
              {slugTitle(r.slug)}
            </Link>
          </div>
          <div className="min-w-0">
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-xs">
              <span className="tabular text-base font-semibold text-ink">{fmtPct(r.progress)}</span>
              {r.pages_total ? (
                <span className="tabular text-ink-3">
                  {fmtInt(r.pages_done)} / {fmtInt(r.pages_total)} pages
                </span>
              ) : null}
            </div>
            <ProgressBar value={r.progress} label="Scan progress" />
          </div>
          <div className="md:text-right">
            <div className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Ready by</div>
            <div className="mt-1 flex items-center gap-2 md:justify-end">
              {r.ready_at ? <Eta iso={r.ready_at} /> : <span className="text-xs text-ink-3">calculating…</span>}
              <CancelScanButton slug={r.slug} running requestedBy={r.requested_by} cancelRequested={r.cancel_requested} />
            </div>
          </div>
        </div>
      )}
      {d.queue.length > 0 && (
        <div className={cx("flex flex-wrap items-center gap-2 px-5 py-3", r && "border-t border-fg/[0.06]")}>
          <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Queued</span>
          {d.queue.map((x) => (
            <span
              key={x.slug}
              className="inline-flex items-center gap-1 rounded-full bg-fg/[0.04] py-0.5 pl-2.5 pr-0.5 text-xs text-ink ring-1 ring-inset ring-fg/[0.06]"
            >
              <Link to={`/contests/${x.slug}`} className="inline-flex items-center gap-2 hover:text-accent-ink">
                <span className="tabular text-ink-3">#{x.position}</span>
                {slugTitle(x.slug)}
                {x.ready_at ? <Eta iso={x.ready_at} /> : <span className="text-ink-3">waiting</span>}
              </Link>
              <CancelScanButton slug={x.slug} requestedBy={x.requested_by} />
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

function ContestRow({ c, isAdmin, d, latest }: { c: ContestListItem; isAdmin: boolean; d: ContestPage; latest: boolean }) {
  const s = c.summary;
  return (
    <tr className={cx("border-b border-fg/5 align-middle last:border-0 even:bg-fg/[0.022] hover:bg-fg/[0.05]", latest && "latest-row")}>
      <td className="px-5 py-2.5">
        <div className="flex items-center gap-2">
          <Link to={`/contests/${c.slug}`} className={cx("text-[13px] font-medium hover:underline", c.has_data || latest ? "text-ink hover:text-accent-ink" : "text-ink-2 hover:text-ink")}>
            {c.title}
          </Link>
          {latest && (
            <span className="rounded-full bg-accent px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-white">Latest</span>
          )}
        </div>
        <div className="text-xs text-ink-3">{fmtDateTime(c.start_time)}</div>
      </td>
      <td className="px-3 py-2.5">
        <div className="flex flex-col items-start gap-1">
          <ContestStateBadge state={c.state} />
          <StatusDetail status={c} worker={d.worker} />
        </div>
      </td>
      <td className="tabular px-3 py-2.5 text-right">
        {s && (
          <>
            {fmtInt(s.participated)} / {fmtInt(s.students)}
            <span className="ml-1.5 text-ink-3">{fmtPct(s.participation_rate)}</span>
          </>
        )}
      </td>
      <td className="tabular px-3 py-2.5 text-right">{s && fmtInt(s.solved_any)}</td>
      <td className="tabular px-3 py-2.5 text-right">{s && fmtDecimal(s.avg_solved)}</td>
      <td className="tabular px-3 py-2.5 text-right">{s && fmtInt(s.best_global_rank)}</td>
      <td className="px-5 py-2.5 text-right">
        {c.state === "queued" || c.state === "scanning" ? (
          <CancelScanButton slug={c.slug} running={c.state === "scanning"} requestedBy={c.requested_by} cancelRequested={c.cancel_requested} />
        ) : (
          <GetResultsButton slug={c.slug} status={c} isAdmin={isAdmin} compact title={c.title} />
        )}
      </td>
    </tr>
  );
}

// ---- upcoming contests: live countdown ---------------------------------------------

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

function splitDuration(ms: number) {
  const t = Math.max(0, Math.floor(ms / 1000));
  return { d: Math.floor(t / 86400), h: Math.floor((t % 86400) / 3600), m: Math.floor((t % 3600) / 60), s: t % 60 };
}

function CountUnit({ value, unit, animate }: { value: number; unit: string; animate?: boolean }) {
  return (
    <div className="flex min-w-11 flex-col items-center rounded-md bg-fg/[0.04] px-2 py-1.5 ring-1 ring-inset ring-fg/[0.05]">
      <span key={animate ? value : undefined} className={cx("tabular text-lg font-semibold leading-none text-ink", animate && "count-unit-value")}>
        {String(value).padStart(2, "0")}
      </span>
      <span className="mt-1 text-[10px] font-medium uppercase tracking-wide text-ink-3">{unit}</span>
    </div>
  );
}

function UpcomingCard({ c, next, delay }: { c: ContestListItem; next: boolean; delay: number }) {
  const now = useNow();
  const start = c.start_time * 1000;
  const end = start + c.duration * 1000;
  const live = now >= start && now < end;
  const t = splitDuration(live ? end - now : start - now);
  return (
    <div className="rise" style={{ animationDelay: `${delay}ms` }}>
      <Card className={cx("h-full px-4 py-3.5", next && "next-up")}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">
            {live ? "Happening now" : next ? "Next up" : c.contest_type === "biweekly" ? "Biweekly" : "Weekly"}
          </span>
          {live ? (
            <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-critical-ink">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-critical" />
              LIVE
            </span>
          ) : (
            <ContestStateBadge state={c.state} />
          )}
        </div>
        <div className="mt-1.5 text-[15px] font-semibold tracking-tight text-ink">{c.title}</div>
        <div className="tabular text-xs text-ink-2">{fmtDateTime(c.start_time)}</div>
        <div className="mt-3 flex items-center gap-1.5" aria-label={live ? "Time until it ends" : "Time until it starts"}>
          {t.d > 0 && <CountUnit value={t.d} unit="days" />}
          <CountUnit value={t.h} unit="hrs" />
          <CountUnit value={t.m} unit="mins" />
          <CountUnit value={t.s} unit="secs" animate />
          <span className="ml-1 text-xs text-ink-3">{live ? "left" : "to go"}</span>
        </div>
        {c.ready_at && (
          <div className="mt-3">
            <Eta iso={c.ready_at} label="Results" />
          </div>
        )}
      </Card>
    </div>
  );
}
