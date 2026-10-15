/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type ContestDetail, type ContestScope } from "../api";
import { useMe } from "../auth";
import { ChartTable, ColumnChart } from "../components/charts";
import { CancelScanButton, GetResultsButton, NoResultsPanel, StatusDetail } from "../components/ContestStatus";
import Leaderboard from "../components/Leaderboard";
import { Card, CardHeader, ErrorBox, ExternalLink, LinkButton, Select, Stat, cx } from "../components/ui";
import { fmtDateTime, fmtDecimal, fmtDuration, fmtInt, fmtIso, fmtPct, fmtWhen } from "../format";
import { contestQuery, resultsQuery } from "../queries";
import { ContestSkeleton, RowsSkeleton } from "../components/skeletons";
import { Later } from "../components/Later";

const ACTIVE = ["scanning", "queued", "scheduled"];

export default function ContestPage({ isAdmin }: { isAdmin: boolean }) {
  const { slug = "" } = useParams();
  const qc = useQueryClient();
  const me = useMe().data;
  // instructors start with their own students; everyone else with the whole portal
  const [scope, setScope] = useState<ContestScope>(me?.role === "instructor" ? "mine" : "all");
  const detail = useQuery({
    ...contestQuery(slug, scope),
    placeholderData: keepPreviousData,
    // refresh while a scan is pending; reload the leaderboard when results land
    refetchInterval: (q) => (q.state.data && ACTIVE.includes(q.state.data.status.state) ? 5_000 : false),
  });
  const hasData = detail.data?.status.has_data ?? false;
  const scannedAt = detail.data?.status.scanned_at;
  const results = useQuery({
    ...resultsQuery(slug, scannedAt, scope),
    enabled: hasData,
    placeholderData: keepPreviousData,
  });
  const scan = useQuery({ queryKey: ["scan-status"], queryFn: api.scanStatus, enabled: detail.isSuccess && !hasData, refetchInterval: 10_000 });
  useEffect(() => {
    if (scannedAt) qc.invalidateQueries({ queryKey: ["contests"] });
  }, [scannedAt, qc]);

  if (detail.isPending) return <ContestSkeleton />;
  if (detail.isError) return <ErrorBox error={detail.error} />;
  const c = detail.data;
  const s = c.summary;

  if (!c.status.has_data)
    return (
      <div className="flex flex-col gap-6">
        <div>
          <Link to="/" className="text-[13px] text-ink-2 hover:text-ink">
            ← Contests
          </Link>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-ink">{c.title}</h1>
          <p className="mt-1 text-[13px] text-ink-2">
            {fmtDateTime(c.start_time)} · <ExternalLink href={c.leetcode_url}>LeetCode page</ExternalLink>
          </p>
        </div>
        <NoResultsPanel slug={slug} status={c.status} isAdmin={isAdmin} worker={scan.data?.worker} />
      </div>
    );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/" className="text-[13px] text-ink-2 hover:text-ink">
            ← Contests
          </Link>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-ink">{c.title}</h1>
          <p className="mt-1 text-[13px] text-ink-2">
            {fmtDateTime(c.start_time)} · {fmtInt(c.participants_worldwide)} participants worldwide ·{" "}
            <ExternalLink href={c.leetcode_url}>LeetCode page</ExternalLink>
          </p>
          {c.scan && (
            <p className="mt-1 text-xs text-ink-3">
              {c.scan.kind === "final"
                ? `Final results${c.scan.finished_at ? `, collected ${fmtIso(c.scan.finished_at)}` : ""}.`
                : `Early results${c.scan.finished_at ? `, collected ${fmtIso(c.scan.finished_at)}` : ""}. Ranks can still shift slightly until LeetCode finalises the contest; final results by ${c.status.final_at ? fmtWhen(c.status.final_at) : "the 5th working day after it"}.`}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {c.status.state === "scanning" || c.status.state === "queued" ? (
            <span className="flex items-center gap-2 text-xs text-ink-2">
              Refreshing: <StatusDetail status={c.status} />
              <CancelScanButton
                slug={slug}
                running={c.status.state === "scanning"}
                requestedBy={c.status.requested_by}
                cancelRequested={c.status.cancel_requested}
              />
            </span>
          ) : (
            <GetResultsButton slug={slug} status={c.status} isAdmin={isAdmin} title={c.title} />
          )}
          <LinkButton href={api.exportUrl(slug, "xlsx")} download>
            Download Excel
          </LinkButton>
          <LinkButton href={api.exportUrl(slug, "csv")} download>
            Download CSV
          </LinkButton>
        </div>
      </div>

      <ScopeBar scope={scope} setScope={setScope} colleges={c.colleges} isInstructor={me?.role === "instructor"} loading={detail.isPlaceholderData} />

      <div className={cx("kpi-row grid grid-cols-2 gap-2 transition-opacity md:grid-cols-3 xl:grid-cols-6", detail.isPlaceholderData && "opacity-60")}>
        <Stat label="Participated" value={`${fmtInt(s.participated)} / ${fmtInt(s.students)}`} sub={`${fmtPct(s.participation_rate)} of students`} />
        <Stat label="Solved at least one" value={fmtInt(s.solved_any)} sub={`${fmtInt(s.zero)} took part but solved none`} />
        <Stat label="Avg problems solved" value={fmtDecimal(s.avg_solved)} sub="among participants" />
        <Stat label="Best profile rank" value={fmtInt(s.best_global_rank) || "—"} sub="highest-placed student" />
        <Stat label="Absent" value={fmtInt(s.absent)} sub="not on the leaderboard" />
        <Stat label="Handle problems" value={fmtInt(s.invalid_handle + s.no_handle)} sub="invalid or missing handle" />
      </div>

      <QuestionStats c={c} />
      {/* below the first screen: drawn right after it, one section at a time */}
      <Later order={1} minHeight={380}>
        <SolveTimes c={c} />
      </Later>
      <Later order={2} minHeight={300}>
        <CollegeBreakdown c={c} />
      </Later>

      <Later order={3} minHeight={900}>
      <Card>
        <CardHeader
          title="Students"
          subtitle={`${scope === "all" ? "College rank = rank among all students in the portal." : "Rank = rank among the students shown (portal-wide rank underneath)."} Profile rank is the rank on the student's LeetCode profile; click a leaderboard rank to open that page of the contest leaderboard.`}
        />
        {results.isPending ? (
          <div className="px-5">
            <RowsSkeleton rows={10} cols={7} label="Loading results…" />
          </div>
        ) : results.isError ? (
          <div className="p-5">
            <ErrorBox error={results.error} />
          </div>
        ) : (
          <Leaderboard data={results.data} scoped={scope !== "all"} />
        )}
      </Card>
      </Later>
    </div>
  );
}

function QuestionStats({ c }: { c: ContestDetail }) {
  const participants = c.summary.participated;
  return (
    <Card>
      <CardHeader title="Questions" subtitle="Share of participating students who solved each question." />
      <ul className="divide-y divide-border">
        {c.questions.map((q) => {
          const rate = q.solve_rate ?? 0;
          const tooltip = `${q.label}: ${q.solved} of ${participants} participants solved it (${fmtPct(q.solve_rate)})`;
          return (
            <li key={q.label} className="grid grid-cols-1 gap-2 px-5 py-3 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] md:items-center md:gap-6">
              <div className="min-w-0">
                <span className="mr-2 font-semibold">{q.label}</span>
                {q.url ? (
                  <ExternalLink href={q.url} className="truncate">
                    {q.title}
                  </ExternalLink>
                ) : (
                  q.title
                )}
                <span className="ml-2 text-xs text-ink-3">{q.credit} pts</span>
              </div>
              <div className="flex items-center gap-3" title={tooltip}>
                <div
                  className="h-2.5 flex-1 overflow-hidden rounded-full bg-bar-track"
                  role="img"
                  aria-label={tooltip}
                >
                  <div className="meter-fill h-full rounded-full bg-accent" style={{ width: `${Math.max(rate * 100, rate > 0 ? 1.5 : 0)}%` }} />
                </div>
                <span className="tabular w-28 text-right text-[13px]">
                  {fmtInt(q.solved)} <span className="text-ink-3">({fmtPct(q.solve_rate) || "0%"})</span>
                </span>
              </div>
              <div className="tabular text-xs text-ink-2 md:w-56 md:text-right">
                {q.median_solve_secs != null ? (
                  <>
                    median {fmtDuration(q.median_solve_secs)} · {fmtDecimal(q.avg_wrong)} wrong / solver
                  </>
                ) : (
                  "no solves"
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function SolveTimes({ c }: { c: ContestDetail }) {
  const d = c.distributions;
  const labels = c.questions.map((q) => q.label);
  const max = Math.max(1, ...labels.flatMap((l) => d.time_bins[l] ?? []));
  const binLabel = (i: number) => `${i * d.bin_minutes}–${(i + 1) * d.bin_minutes} min`;
  return (
    <Card>
      <CardHeader
        title="When students solved each question"
        subtitle={`Accepted submissions in ${d.bin_minutes}-minute steps from the start, and wrong attempts before acceptance.`}
      />
      <div className="grid gap-5 px-5 py-4 sm:grid-cols-2 xl:grid-cols-4">
        {labels.map((label) => {
          const bins = d.time_bins[label] ?? [];
          const w = d.wrong_distribution[label];
          const solvers = bins.reduce((x, y) => x + y, 0);
          return (
            <div key={label}>
              <div className="mb-1 flex items-baseline justify-between text-xs">
                <span className="font-medium text-ink">{label}</span>
                <span className="tabular text-ink-3">{solvers} solved</span>
              </div>
              <ColumnChart
                ariaLabel={`${label}: students solving it in each ${d.bin_minutes}-minute step`}
                height={130}
                max={max}
                format={(v) => String(Math.round(v))}
                columns={bins.map((n, i) => ({
                  label: `${label} · ${binLabel(i)}`,
                  tick: i % 3 === 0 ? `${i * d.bin_minutes}m` : "",
                  value: n,
                  note: n === 1 ? "student" : "students",
                }))}
              />
              {w && solvers > 0 && (
                <div className="tabular mt-2 flex flex-wrap gap-x-3 text-xs text-ink-2">
                  <span>wrong attempts:</span>
                  <span>none {w["0"]}</span>
                  <span>1: {w["1"]}</span>
                  <span>2: {w["2"]}</span>
                  <span>3+: {w["3+"]}</span>
                </div>
              )}
              <ChartTable columns={["Time", "Students"]} rows={bins.map((n, i) => [binLabel(i), n])} />
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function CollegeBreakdown({ c }: { c: ContestDetail }) {
  const rows = c.distributions.colleges;
  if (rows.length < 2) return null;
  return (
    <Card>
      <CardHeader title="By college" />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-ink-2">
            <tr className="border-b border-fg/5">
              <th className="px-5 py-2 font-medium">College</th>
              <th className="px-3 py-2 text-right font-medium">Participated</th>
              <th className="px-3 py-2 text-right font-medium">Avg solved</th>
              <th className="px-3 py-2 text-right font-medium">Solved all</th>
              <th className="px-3 py-2 text-right font-medium">Best profile rank</th>
              <th className="px-5 py-2 text-right font-medium">Best college rank</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.college} className="border-b border-fg/5 last:border-0">
                <td className="px-5 py-2.5 font-medium">{r.college}</td>
                <td className="tabular px-3 py-2.5 text-right">
                  {r.participated} / {r.students} <span className="text-ink-3">{fmtPct(r.participation_rate)}</span>
                </td>
                <td className="tabular px-3 py-2.5 text-right">{fmtDecimal(r.avg_solved) || "—"}</td>
                <td className="tabular px-3 py-2.5 text-right">{r.solved_all}</td>
                <td className="tabular px-3 py-2.5 text-right">{fmtInt(r.best_global_rank) || "—"}</td>
                <td className="tabular px-5 py-2.5 text-right">{r.best_college_rank ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ScopeBar({
  scope,
  setScope,
  colleges,
  isInstructor,
  loading,
}: {
  scope: ContestScope;
  setScope: (s: ContestScope) => void;
  colleges: string[];
  isInstructor: boolean;
  loading: boolean;
}) {
  if (!isInstructor && colleges.length < 2) return null;
  const label =
    scope === "mine" ? "your students" : scope.startsWith("college:") ? scope.slice("college:".length) : "every student in the portal";
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl bg-fg/[0.025] px-4 py-2.5 ring-1 ring-inset ring-fg/[0.06]">
      <Select label="Showing" hideLabel value={scope} onChange={(e) => setScope(e.target.value as ContestScope)}>
        {isInstructor && <option value="mine">My students</option>}
        <option value="all">All colleges</option>
        {colleges.map((c) => (
          <option key={c} value={`college:${c}`}>
            {c}
          </option>
        ))}
      </Select>
      <span className="text-xs text-ink-2">
        Stats, charts and the student list below are for <span className="font-medium text-ink">{label}</span>.
        {loading && <span className="ml-2 text-ink-3">Updating…</span>}
      </span>
    </div>
  );
}
