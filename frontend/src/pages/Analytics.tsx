/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  topicsApi,
  type TopicsData,
  analyticsApi,
  type AnalyticsFilters,
  type AnalyticsOverview,
  type LeaderRow,
  type StudentAnalyticsRow,
  type StudentsPage,
  type StudentsPageQuery,
  type Topper,
} from "../api";
import { ChartTable, LineChart, Meter, shortContest } from "../components/charts";
import { ConsistencyBadge, Definitions, TrendBadge, downloadCsv, fmtTopPct } from "../components/metrics";
import { Button, Card, CardHeader, Empty, ErrorBox, Input, Medal, Select, Stat, cx, scrollToTopOf } from "../components/ui";
import { fmtDecimal, fmtDuration, fmtInt, fmtPct } from "../format";
import { SETTLED } from "../queries";
import { useDebounced } from "../useDebounced";
import { AnalyticsSkeleton } from "../components/skeletons";
import { Later } from "../components/Later";
import { TopicsCard } from "../components/Topics";

const WINDOWS = [
  { value: 5, label: "Last 5 contests" },
  { value: 10, label: "Last 10 contests" },
  { value: 20, label: "Last 20 contests" },
  { value: 0, label: "All contests" },
];

export default function Analytics() {
  return (
    <AnalyticsView
      title="Analytics"
      subtitle="How students perform across contests: toppers, attendance, consistency, question by question."
      queryKey={["analytics"]}
      fetch={analyticsApi.overview}
      fetchStudents={analyticsApi.students}
      fetchTopics={topicsApi.cohort}
    />
  );
}

/** The analytics page for any set of students: the whole portal, or an instructor's. */
export function AnalyticsView({
  title,
  subtitle,
  queryKey,
  fetch,
  fetchStudents,
  fetchTopics,
  actions,
}: {
  title: ReactNode;
  subtitle: ReactNode;
  queryKey: unknown[];
  fetch: (f: AnalyticsFilters) => Promise<AnalyticsOverview>;
  /** The "All students" table, a page at a time. */
  fetchStudents: (f: AnalyticsFilters, page: StudentsPageQuery) => Promise<StudentsPage>;
  /** Topic-wise stats for the same students (period and college filters apply). */
  fetchTopics?: (f: AnalyticsFilters) => Promise<TopicsData>;
  actions?: ReactNode;
}) {
  const [last, setLast] = useState(10);
  const [college, setCollege] = useState("");
  const [extra, setExtra] = useState<Record<string, string>>({});
  const filters: AnalyticsFilters = { last: last || undefined, college: college || undefined, extra };
  const q = useQuery({
    queryKey: [...queryKey, filters],
    queryFn: () => fetch(filters),
    placeholderData: keepPreviousData,
    staleTime: SETTLED,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          <p className="mt-1 text-[13px] text-ink-2">{subtitle}</p>
        </div>
        {actions}
      </div>

      {/* filters scope everything below */}
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Period" value={last} onChange={(e) => setLast(Number(e.target.value))}>
          {WINDOWS.map((w) => (
            <option key={w.value} value={w.value}>
              {w.label}
            </option>
          ))}
        </Select>
        {q.data && q.data.filters.colleges.length > 1 && (
          <Select label="College" value={college} onChange={(e) => setCollege(e.target.value)}>
            <option value="">Any college</option>
            {q.data.filters.colleges.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        )}
        {q.data &&
          Object.entries(q.data.filters.extras).map(([key, values]) => (
            <Select key={key} label={key} value={extra[key] ?? ""} onChange={(e) => setExtra((x) => ({ ...x, [key]: e.target.value }))}>
              <option value="">Any {key.toLowerCase()}</option>
              {values.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </Select>
          ))}
        {(college || Object.values(extra).some(Boolean)) && (
          <Button variant="ghost" onClick={() => { setCollege(""); setExtra({}); }}>
            Clear filters
          </Button>
        )}
        {q.data?.window.contests ? (
          <span className="pb-2 text-xs text-ink-3">
            {q.data.window.first} → {q.data.window.last}
          </span>
        ) : null}
      </div>

      {q.isPending ? (
        <AnalyticsSkeleton />
      ) : q.isError ? (
        <ErrorBox error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.window.contests === 0 || q.data.summary.students === 0 ? (
        <Card>
          <Empty>{q.data.summary.students === 0 ? "No students here yet." : "No contests have been scanned yet."}</Empty>
        </Card>
      ) : (
        <div className={cx("flex flex-col gap-6 transition-opacity", q.isPlaceholderData && "opacity-60")}>
          <Overview
            data={q.data}
            students={{ queryKey, filters, fetch: fetchStudents }}
            topics={
              fetchTopics && (
                <Later order={5} minHeight={360} whenNear>
                  <TopicsCard
                    group
                    queryKey={[...queryKey, filters.last ?? 0, filters.college ?? ""]}
                    fetch={() => fetchTopics(filters)}
                    subtitle="Each topic across these students' contests; weakest topics (lowest solve rate, seen 10+ times) first. Period and college filters apply."
                  />
                </Later>
              )
            }
          />
        </div>
      )}
    </div>
  );
}

interface StudentsSource {
  queryKey: unknown[];
  filters: AnalyticsFilters;
  fetch: (f: AnalyticsFilters, page: StudentsPageQuery) => Promise<StudentsPage>;
}

function Overview({ data, students, topics }: { data: AnalyticsOverview; students: StudentsSource; topics?: ReactNode }) {
  const s = data.summary;
  return (
    <>
      <div className="kpi-row grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
        <Stat label="Students" value={fmtInt(s.students)} sub={`${fmtInt(s.active_participants)} took part at least once`} />
        <Stat label="Attendance" value={fmtPct(s.participation_rate) || "—"} sub="of student-contests" />
        <Stat label="Avg problems solved" value={fmtDecimal(s.avg_solved) || "—"} sub="per attended contest" />
        <Stat label="Avg LeetCode rating" value={s.avg_rating ? fmtInt(s.avg_rating) : "—"} sub={`${fmtInt(s.rated_students)} rated students`} />
        <Stat label="Needs attention" value={fmtInt(s.needs_attention)} sub="absent 3+ in a row or declining" />
      </div>
      <Definitions />
      <Toppers data={data} />
      {/* below the first screen: drawn right after it, one section at a time */}
      <Later order={1} minHeight={360}>
        <CollegeRanking data={data} />
      </Later>
      <Later order={2} minHeight={420}>
        <Trends data={data} />
      </Later>
      <Later order={3} minHeight={360}>
        <Questions data={data} />
      </Later>
      <Later order={4} minHeight={360}>
        <Colleges data={data} />
      </Later>
      <Later order={5} minHeight={520}>
        <Leaders data={data} />
      </Later>
      {topics /* topic-wise analytics, right above the student list */}
      <Later order={6} minHeight={900}>
        <StudentsTable data={data} source={students} />
      </Later>
    </>
  );
}

const PODIUM = ["podium-gold", "podium-silver", "podium-bronze"];
const PODIUM_LABEL = ["Topper", "Second", "Third"];

const PAGE = 10;

/** Search + "show more" for long college lists (there can be 40-50 colleges). */
function usePaged<T>(rows: T[], text: (r: T) => string) {
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? rows.filter((r) => text(r).toLowerCase().includes(q)) : rows;
  }, [rows, query, text]);
  return {
    query,
    setQuery: (q: string) => {
      setQuery(q);
      setShown(PAGE);
    },
    visible: filtered.slice(0, shown),
    total: filtered.length,
    more: Math.min(PAGE, filtered.length - shown),
    showMore: () => setShown((n) => n + PAGE),
    showAll: () => setShown(filtered.length),
    collapse: () => setShown(PAGE),
    expanded: shown > PAGE,
  };
}

function PagerFooter({ p, noun }: { p: ReturnType<typeof usePaged<unknown>>; noun: string }) {
  if (p.total <= PAGE) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-2.5 text-[13px]">
      <span className="tabular text-xs text-ink-3">
        Showing {p.visible.length} of {p.total} {noun}
      </span>
      <div className="flex items-center gap-1">
        {p.more > 0 && (
          <>
            <Button variant="ghost" size="sm" onClick={p.showMore}>
              Show {p.more} more
            </Button>
            <Button variant="ghost" size="sm" onClick={p.showAll}>
              Show all
            </Button>
          </>
        )}
        {p.more <= 0 && p.expanded && (
          <Button variant="ghost" size="sm" onClick={p.collapse}>
            Show fewer
          </Button>
        )}
      </div>
    </div>
  );
}

function TopperCell({ t, place }: { t: Topper | undefined; place: number }) {
  if (!t) return <span className="text-ink-3">—</span>;
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <Medal place={place} size="sm" />
      <div className="min-w-0">
        <Link to={`/students/${t.id}`} className="block max-w-44 truncate text-[13px] font-medium hover:text-accent-ink hover:underline" title={t.name}>
          {t.name}
        </Link>
        <div className="tabular text-[11px] text-ink-3" title={`#${t.portal_rank} in the portal`}>
          {fmtInt(t.points)} pts · #{t.portal_rank}
        </div>
      </div>
    </div>
  );
}

type CollegeToppers = AnalyticsOverview["toppers"]["colleges"][number];
const collegeName = (c: { college: string }) => c.college;

function Toppers({ data }: { data: AnalyticsOverview }) {
  const { overall, colleges } = data.toppers;
  const withToppers = useMemo(() => colleges.filter((c) => c.toppers.length > 0), [colleges]);
  const p = usePaged<CollegeToppers>(withToppers, collegeName);
  if (overall.length === 0) return null;
  return (
    <Card>
      <CardHeader
        title="Toppers"
        subtitle="Most LeetCode contest points over the selected contests; ties go to less total time. For a single contest this is LeetCode's own order."
      />
      <div className="grid gap-3 px-5 pb-5 sm:grid-cols-3">
        {overall.map((t, i) => (
          <div key={t.id} className={cx("flex min-w-0 flex-col gap-3 rounded-xl bg-surface-2/60 p-4", PODIUM[i])}>
            <div className="flex items-center justify-between">
              <Medal place={i + 1} size="lg" />
              <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">{PODIUM_LABEL[i]}</span>
            </div>
            <div className="min-w-0">
              <Link to={`/students/${t.id}`} className="block truncate text-[15px] font-semibold text-ink hover:text-accent-ink hover:underline">
                {t.name}
              </Link>
              <div className="truncate text-xs text-ink-3">{[t.roll_no, t.college].filter(Boolean).join(" · ")}</div>
            </div>
            <div className="flex items-end justify-between gap-2">
              <div>
                <div className="tabular text-xl font-semibold text-ink">{fmtInt(t.points)}</div>
                <div className="text-[11px] text-ink-3">points</div>
              </div>
              <div className="text-right text-xs text-ink-2">
                <div className="tabular">
                  {t.contests_attended} {t.contests_attended === 1 ? "contest" : "contests"} · {fmtDecimal(t.avg_solved) || "0"} solved avg
                </div>
                {t.best_global_rank != null && <div className="tabular text-ink-3">best profile rank {fmtInt(t.best_global_rank)}</div>}
              </div>
            </div>
          </div>
        ))}
      </div>
      {withToppers.length > 1 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3">
            <div>
              <h3 className="text-[13px] font-semibold text-ink">College toppers</h3>
              <p className="text-xs text-ink-3">Top three of each college; colleges with the best-placed students first.</p>
            </div>
            {withToppers.length > PAGE && (
              <Input type="search" placeholder="Find a college" value={p.query} onChange={(e) => p.setQuery(e.target.value)} className="w-full sm:w-56" />
            )}
          </div>
          {p.total === 0 ? (
            <Empty>No college matches.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-ink-2">
                  <tr className="border-y border-fg/5">
                    <th className="px-5 py-2 font-medium">College</th>
                    <th className="px-3 py-2 font-medium">Gold</th>
                    <th className="px-3 py-2 font-medium">Silver</th>
                    <th className="px-5 py-2 font-medium">Bronze</th>
                  </tr>
                </thead>
                <tbody>
                  {p.visible.map((c) => (
                    <tr key={c.college} className="border-b border-fg/5 last:border-0 hover:bg-fg/[0.025]">
                      <td className="px-5 py-2.5">
                        <div className="max-w-60 truncate font-medium text-ink" title={c.college}>
                          {c.college}
                        </div>
                        <div className="tabular text-[11px] text-ink-3">{fmtInt(c.students)} students</div>
                      </td>
                      {[0, 1, 2].map((i) => (
                        <td key={i} className="px-3 py-2.5 last:pr-5">
                          <TopperCell t={c.toppers[i]} place={i + 1} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <PagerFooter p={p as ReturnType<typeof usePaged<unknown>>} noun="colleges" />
        </>
      )}
    </Card>
  );
}

type RankingRow = AnalyticsOverview["college_ranking"][number];

function CollegeRanking({ data }: { data: AnalyticsOverview }) {
  const rows = data.college_ranking;
  const p = usePaged<RankingRow>(rows, collegeName);
  if (rows.length < 2 || !rows.some((c) => c.in_top > 0)) return null;
  const max = Math.max(...rows.map((c) => c.in_top), 1);
  return (
    <Card>
      <CardHeader
        title={`College ranking · top ${data.top_n}`}
        subtitle={`Colleges ranked by how many of their students are in the portal's top ${data.top_n} by points over the selected contests. Ties: more in the top 10, then the best-placed student.`}
        actions={
          rows.length > PAGE && <Input type="search" placeholder="Find a college" value={p.query} onChange={(e) => p.setQuery(e.target.value)} className="w-full sm:w-56" />
        }
      />
      {p.total === 0 ? (
        <Empty>No college matches.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-2">
              <tr className="border-b border-fg/5">
                <th className="w-16 px-5 py-2 font-medium">Rank</th>
                <th className="px-3 py-2 font-medium">College</th>
                <th className="w-1/3 px-3 py-2 font-medium">In top {data.top_n}</th>
                <th className="px-3 py-2 text-right font-medium">In top 10</th>
                <th className="px-3 py-2 text-right font-medium">Best placed</th>
                <th className="px-5 py-2 text-right font-medium">Students</th>
              </tr>
            </thead>
            <tbody>
              {p.visible.map((c) => (
                <tr key={c.college} className="border-b border-fg/5 last:border-0 hover:bg-fg/[0.025]">
                  <td className="px-5 py-2.5">
                    <Medal place={c.rank} size="sm" />
                  </td>
                  <td className="px-3 py-2.5 font-medium">{c.college}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-3">
                      <Meter value={c.in_top / max} label={`${c.college}: ${c.in_top} students in the top ${data.top_n}`} />
                      <span className="tabular w-8 shrink-0 text-right font-semibold">{c.in_top}</span>
                    </div>
                  </td>
                  <td className="tabular px-3 py-2.5 text-right">{c.in_top_10}</td>
                  <td className="tabular px-3 py-2.5 text-right">{c.best_portal_rank ? `#${c.best_portal_rank}` : "—"}</td>
                  <td className="tabular px-5 py-2.5 text-right text-ink-2">{fmtInt(c.students)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <PagerFooter p={p as ReturnType<typeof usePaged<unknown>>} noun="colleges" />
    </Card>
  );
}

function Trends({ data }: { data: AnalyticsOverview }) {
  const pts = data.trend;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Attendance by contest" subtitle="Share of students on the leaderboard." />
        <div className="px-5 pb-3 pt-2">
          <LineChart
            ariaLabel="Attendance by contest"
            domain={[0, 1]}
            format={(v) => fmtPct(v)}
            points={pts.map((p) => ({ label: p.title, tick: shortContest(p.title), y: p.participation_rate, note: `${p.participated} of ${p.students} students` }))}
          />
          <ChartTable
            columns={["Contest", "Participated", "Students", "Attendance"]}
            rows={pts.map((p) => [p.title, p.participated, p.students, fmtPct(p.participation_rate)])}
          />
        </div>
      </Card>
      <Card>
        <CardHeader title="Average problems solved" subtitle="Among students who took part." />
        <div className="px-5 pb-3 pt-2">
          <LineChart
            ariaLabel="Average problems solved by contest"
            domain={[0, Math.max(4, ...data.labels.map((_, i) => i + 1))]}
            format={(v) => fmtDecimal(v)}
            points={pts.map((p) => ({ label: p.title, tick: shortContest(p.title), y: p.avg_solved, note: p.median_top_pct != null ? `median ${fmtTopPct(p.median_top_pct)}` : undefined }))}
          />
          <ChartTable
            columns={["Contest", "Avg solved", "Median top %", "Best profile rank"]}
            rows={pts.map((p) => [p.title, fmtDecimal(p.avg_solved), fmtTopPct(p.median_top_pct), fmtInt(p.best_global_rank)])}
          />
        </div>
      </Card>
    </div>
  );
}

function Questions({ data }: { data: AnalyticsOverview }) {
  return (
    <Card>
      <CardHeader
        title="Question by question"
        subtitle="Across the selected contests: how often students who took part solved Q1, Q2, …, how long it took, and wrong submissions."
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-ink-2">
            <tr className="border-b border-fg/5">
              <th className="px-5 py-2 font-medium">Question</th>
              <th className="w-1/3 px-3 py-2 font-medium">Solved</th>
              <th className="px-3 py-2 text-right font-medium">Median time</th>
              <th className="px-3 py-2 text-right font-medium">Middle half took</th>
              <th className="px-3 py-2 text-right font-medium">Wrong / solve</th>
              <th className="px-5 py-2 text-right font-medium">Wrong submissions</th>
            </tr>
          </thead>
          <tbody>
            {data.questions.map((q) => (
              <tr key={q.label} className="border-b border-fg/5 last:border-0">
                <td className="px-5 py-2.5 font-semibold">{q.label}</td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-3">
                    <Meter value={q.solve_rate} label={`${q.label}: solved ${q.solved} of ${q.attempts} times (${fmtPct(q.solve_rate)})`} />
                    <span className="tabular w-36 shrink-0 text-right">
                      {fmtInt(q.solved)} / {fmtInt(q.attempts)} <span className="text-ink-3">({fmtPct(q.solve_rate) || "0%"})</span>
                    </span>
                  </div>
                </td>
                <td className="tabular px-3 py-2.5 text-right">{fmtDuration(q.median_secs) || "—"}</td>
                <td className="tabular px-3 py-2.5 text-right text-ink-2">
                  {q.p25_secs != null ? `${fmtDuration(Math.round(q.p25_secs))} – ${fmtDuration(Math.round(q.p75_secs!))}` : "—"}
                </td>
                <td className="tabular px-3 py-2.5 text-right">{fmtDecimal(q.wrong_per_solve, 2) || "—"}</td>
                <td className="tabular px-5 py-2.5 text-right">{fmtInt(q.wrong)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* small multiples: one panel per question, one hue */}
      <div className="grid gap-4 border-t border-border px-5 py-4 sm:grid-cols-2 xl:grid-cols-4">
        {data.labels.map((label) => (
          <div key={label}>
            <div className="mb-1 text-xs font-medium text-ink-2">{label} solve rate by contest</div>
            <LineChart
              ariaLabel={`${label} solve rate by contest`}
              height={140}
              domain={[0, 1]}
              format={(v) => fmtPct(v)}
              points={data.trend.map((p) => {
                const t = p.questions[label];
                return {
                  label: p.title,
                  tick: shortContest(p.title),
                  y: t?.solve_rate ?? null,
                  note: t ? `${t.solved} solved · median ${fmtDuration(t.median_secs) || "—"} · ${fmtDecimal(t.wrong_per_solver, 2) || "0"} wrong/solver` : undefined,
                };
              })}
            />
          </div>
        ))}
      </div>
    </Card>
  );
}

function Colleges({ data }: { data: AnalyticsOverview }) {
  if (data.colleges.length < 2) return null;
  const rows = [...data.colleges].sort((a, b) => (b.participation_rate ?? 0) - (a.participation_rate ?? 0));
  return (
    <Card>
      <CardHeader title="Colleges" subtitle="Compared over the selected contests." />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-ink-2">
            <tr className="border-b border-fg/5">
              <th className="px-5 py-2 font-medium">College</th>
              <th className="px-3 py-2 text-right font-medium">Students</th>
              <th className="w-1/4 px-3 py-2 font-medium">Attendance</th>
              <th className="px-3 py-2 text-right font-medium">Avg solved</th>
              <th className="px-3 py-2 text-right font-medium">Median position</th>
              <th className="px-3 py-2 text-right font-medium">Best rank</th>
              <th className="px-3 py-2 text-right font-medium">Avg consistency</th>
              <th className="px-5 py-2 text-right font-medium">Avg rating</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.college} className="border-b border-fg/5 last:border-0">
                <td className="px-5 py-2.5 font-medium">{c.college}</td>
                <td className="tabular px-3 py-2.5 text-right">{fmtInt(c.students)}</td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-3">
                    <Meter value={c.participation_rate} label={`${c.college}: attendance ${fmtPct(c.participation_rate)}`} />
                    <span className="tabular w-10 shrink-0 text-right">{fmtPct(c.participation_rate)}</span>
                  </div>
                </td>
                <td className="tabular px-3 py-2.5 text-right">{fmtDecimal(c.avg_solved) || "—"}</td>
                <td className="tabular px-3 py-2.5 text-right">{fmtTopPct(c.median_top_pct) || "—"}</td>
                <td className="tabular px-3 py-2.5 text-right">{fmtInt(c.best_global_rank) || "—"}</td>
                <td className="tabular px-3 py-2.5 text-right">{c.avg_consistency ?? "—"}</td>
                <td className="tabular px-5 py-2.5 text-right">{c.avg_rating ? fmtInt(c.avg_rating) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function LeaderList({ title, subtitle, rows, render, empty }: { title: string; subtitle: string; rows: LeaderRow[]; render: (r: LeaderRow) => ReactNode; empty: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, 10);
  return (
    <Card>
      <CardHeader title={title} subtitle={subtitle} />
      {rows.length === 0 ? (
        <Empty>{empty}</Empty>
      ) : (
        <ol className="divide-y divide-fg/5">
          {shown.map((r, i) => (
            <li key={r.id} className="flex items-center gap-3 px-5 py-2 text-[13px] transition-colors duration-150 hover:bg-fg/[0.025]">
              <span className={cx("tabular w-5 text-right text-xs", i < 3 ? "font-semibold text-accent-ink" : "text-ink-3")}>{i + 1}</span>
              <div className="min-w-0 flex-1">
                <Link to={`/students/${r.id}`} className="-my-1 inline-block py-1 font-medium hover:text-accent-ink hover:underline">
                  {r.name}
                </Link>
                <div className="truncate text-xs text-ink-3">{[r.roll_no, r.college].filter(Boolean).join(" · ")}</div>
              </div>
              <div className="shrink-0 text-right">{render(r)}</div>
            </li>
          ))}
        </ol>
      )}
      {rows.length > 10 && (
        <div className="border-t border-border px-5 py-2.5">
          <button className="text-[13px] font-medium text-accent-ink hover:underline" onClick={() => setAll((x) => !x)}>
            {all ? "Show fewer" : `Show all ${rows.length}`}
          </button>
        </div>
      )}
    </Card>
  );
}

function Leaders({ data }: { data: AnalyticsOverview }) {
  const l = data.leaders;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <LeaderList
        title="Most consistent"
        subtitle="Attend regularly and solve a steady number of problems."
        rows={l.consistent}
        empty="Needs at least 3 scanned contests."
        render={(r) => <ConsistencyBadge score={r.consistency} label={r.consistency_label} />}
      />
      <LeaderList
        title="Top performers"
        subtitle="Best average global position (attended 3+ contests)."
        rows={l.top_performers}
        empty="Nobody has attended enough contests yet."
        render={(r) => (
          <span className="tabular text-[13px]">
            {fmtTopPct(r.avg_top_pct)} <span className="text-ink-3">· {fmtDecimal(r.avg_solved)} solved</span>
          </span>
        )}
      />
      <LeaderList
        title="Most improved"
        subtitle="Solving more problems lately than before."
        rows={l.improved}
        empty="No clear improvers in this period."
        render={(r) => <TrendBadge label={r.trend_label} delta={r.trend} />}
      />
      <LeaderList
        title="Needs attention"
        subtitle="Missed the last 3+ contests, or solving fewer problems lately."
        rows={l.attention}
        empty="Nobody right now."
        render={(r) => <span className="text-xs text-ink-2">{r.reasons?.join("; ")}</span>}
      />
    </div>
  );
}

const PAGE_SIZE = 50;

/** Every student, searched, sorted and paged by the server: the browser gets 50 rows,
 *  not the whole cohort. The next page is fetched ahead, so "Next" is instant. */
function StudentsTable({ data, source }: { data: AnalyticsOverview; source: StudentsSource }) {
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim(), 250);
  const [sorting, setSorting] = useState<SortingState>([{ id: "portal_rank", desc: false }]);
  const sort = sorting[0] ?? { id: "portal_rank", desc: false };
  // a new search, sort or filter starts again at the first page
  const resetKey = JSON.stringify([search, sort, source.filters]);
  const [page, setPage] = useState({ key: resetKey, index: 0 });
  const pageIndex = page.key === resetKey ? page.index : 0;
  const card = useRef<HTMLDivElement>(null);
  const goTo = (index: number) => {
    setPage({ key: resetKey, index });
    scrollToTopOf(card.current); // the new page starts at its first row
  };

  const pageQuery = (index: number): StudentsPageQuery => ({
    q: search, sort: sort.id, desc: sort.desc, offset: index * PAGE_SIZE, limit: PAGE_SIZE,
  });
  const keyFor = (pq: StudentsPageQuery) => [...source.queryKey, "students", source.filters, pq];
  const q = useQuery({
    queryKey: keyFor(pageQuery(pageIndex)),
    queryFn: () => source.fetch(source.filters, pageQuery(pageIndex)),
    placeholderData: keepPreviousData,
    staleTime: SETTLED,
  });
  const total = q.data?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);
  useEffect(() => {
    if (pageIndex + 1 < pageCount) {
      const next = pageQuery(pageIndex + 1);
      void qc.prefetchQuery({ queryKey: keyFor(next), queryFn: () => source.fetch(source.filters, next), staleTime: SETTLED });
    }
  }, [resetKey, pageIndex, pageCount]); // eslint-disable-line react-hooks/exhaustive-deps -- the rest derive from these
  const rows = q.data?.rows ?? [];

  const columns = useMemo<ColumnDef<StudentAnalyticsRow>[]>(
    () => [
      {
        id: "name",
        header: "Student",
        accessorFn: (r) => r.name.toLowerCase(),
        cell: ({ row: { original: r } }) => (
          <div className="min-w-44 max-w-64">
            <Link to={`/students/${r.id}`} className="-my-1 inline-block py-1 font-medium hover:text-accent-ink hover:underline">
              {r.name}
            </Link>
            <div className="truncate text-xs text-ink-3">{[r.roll_no, r.college].filter(Boolean).join(" · ")}</div>
          </div>
        ),
      },
      {
        id: "portal_rank",
        header: "Portal rank",
        accessorFn: (r) => r.portal_rank ?? undefined,
        sortUndefined: "last",
        cell: ({ row: { original: r } }) =>
          r.portal_rank ? (
            <span className="inline-flex items-center justify-end gap-2" title={`#${r.portal_rank} in the portal · ${fmtInt(r.points)} points over the selected contests`}>
              {r.portal_rank <= 3 ? <Medal place={r.portal_rank} size="sm" /> : <span className="tabular">#{r.portal_rank}</span>}
              <span className="tabular w-14 text-right text-xs text-ink-3">{fmtInt(r.points)} pts</span>
            </span>
          ) : (
            <span className="text-ink-3">—</span>
          ),
        meta: { align: "right" },
      },
      {
        id: "attendance",
        header: "Attended",
        accessorFn: (r) => r.attendance_rate ?? undefined,
        sortUndefined: "last",
        cell: ({ row: { original: r } }) => (
          <div
            className="ml-auto flex w-24 flex-col items-end gap-1"
            title={`Attended ${r.contests_attended} of ${r.contests_scanned} contests${r.absent_streak >= 3 ? `, missed the last ${r.absent_streak}` : ""}`}
          >
            <div className="flex items-center gap-1.5">
              {r.absent_streak >= 3 && (
                <span className="inline-flex h-[18px] items-center gap-0.5 rounded-full bg-critical/10 px-1.5 text-[10px] font-semibold text-critical-ink ring-1 ring-inset ring-critical/20">
                  <svg aria-hidden viewBox="0 0 10 10" className="h-2.5 w-2.5">
                    <path d="M5 2v6M2.5 5.5 5 8l2.5-2.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  {r.absent_streak} missed
                </span>
              )}
              <span className="tabular text-[13px] font-semibold text-ink">
                {r.contests_attended}
                <span className="font-normal text-ink-3">/{r.contests_scanned}</span>
              </span>
            </div>
            <span className="h-1 w-full overflow-hidden rounded-full bg-bar-track">
              <span
                className={cx(
                  "meter-fill block h-full rounded-full",
                  (r.attendance_rate ?? 0) >= 0.6 ? "bg-good" : (r.attendance_rate ?? 0) >= 0.3 ? "bg-warning" : "bg-critical",
                )}
                style={{ width: `${Math.max((r.attendance_rate ?? 0) * 100, r.contests_attended ? 4 : 0)}%` }}
              />
            </span>
          </div>
        ),
        meta: { align: "right" },
      },
      {
        id: "consistency",
        header: "Consistency",
        accessorFn: (r) => r.consistency ?? undefined,
        sortUndefined: "last",
        cell: ({ row: { original: r } }) => <ConsistencyBadge score={r.consistency} label={r.consistency_label} />,
      },
      {
        id: "avg_solved",
        header: "Avg solved",
        accessorFn: (r) => r.avg_solved ?? undefined,
        sortUndefined: "last",
        cell: ({ getValue }) => <span className="tabular">{fmtDecimal(getValue<number | undefined>()) || "—"}</span>,
        meta: { align: "right" },
      },
      ...data.labels.map<ColumnDef<StudentAnalyticsRow>>((label) => ({
        id: label,
        header: `${label} solved`,
        accessorFn: (r) => r.questions[label]?.solve_rate ?? undefined,
        sortUndefined: "last",
        cell: ({ row: { original: r } }) => {
          const q = r.questions[label];
          if (!q || q.attempted_contests === 0)
            return (
              <span className="inline-grid grid-cols-[2.75rem_3.25rem] gap-x-1.5 text-ink-3">
                <span className="text-right">—</span>
                <span />
              </span>
            );
          return (
            <span className="tabular whitespace-nowrap" title={`${label}: solved ${q.solved} of ${q.attempted_contests} attended contests · median ${fmtDuration(q.median_secs) || "—"} · ${q.wrong} wrong`}>
              <span className="inline-grid grid-cols-[2.75rem_3.25rem] items-baseline gap-x-1.5">
                <span className="text-right">
                  {q.solved}
                  <span className="text-ink-3">/{q.attempted_contests}</span>
                </span>
                <span className="text-left text-xs text-ink-3">{q.median_secs != null ? fmtDuration(q.median_secs) : ""}</span>
              </span>
            </span>
          );
        },
        meta: { align: "right" },
      })),
      {
        id: "wrong",
        header: "Wrong submissions",
        accessorFn: (r) => Object.values(r.questions).reduce((a, q) => a + q.wrong, 0),
        cell: ({ getValue }) => <span className="tabular">{getValue<number>()}</span>,
        meta: { align: "right" },
      },
      {
        id: "top_pct",
        header: "Avg position",
        accessorFn: (r) => r.avg_top_pct ?? undefined,
        sortUndefined: "last",
        cell: ({ getValue }) => <span className="tabular whitespace-nowrap">{fmtTopPct(getValue<number | undefined>()) || "—"}</span>,
        meta: { align: "right" },
      },
      {
        id: "rating",
        header: "Rating",
        accessorFn: (r) => r.rating ?? undefined,
        sortUndefined: "last",
        cell: ({ getValue }) => <span className="tabular">{fmtInt(getValue<number | undefined>()) || "—"}</span>,
        meta: { align: "right" },
      },
      {
        id: "trend",
        header: "Trend",
        accessorFn: (r) => r.trend ?? undefined,
        sortUndefined: "last",
        cell: ({ row: { original: r } }) => <TrendBadge label={r.trend_label} delta={r.trend} />,
      },
    ],
    [data.labels],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    manualSorting: true, // the server sorts
    getCoreRowModel: getCoreRowModel(),
  });

  const [exporting, setExporting] = useState(false);
  async function exportCsv() {
    setExporting(true);
    try {
      const all = await source.fetch(source.filters, { ...pageQuery(0), limit: 5000 });
      writeCsv(all.rows);
    } finally {
      setExporting(false);
    }
  }

  function writeCsv(students: StudentAnalyticsRow[]) {
    const header = ["Roll no", "Name", "College", "Portal rank", "Points", "Contests attended", "Contests scanned", "Attendance %", "Absent streak",
      "Consistency", "Consistency label", "Avg solved",
      ...data.labels.flatMap((l) => [`${l} solved`, `${l} attempted`, `${l} median time`, `${l} wrong`]),
      "Avg top %", "Best profile rank", "Rating", "Trend"];
    const out = students.map((r) => [
      r.roll_no, r.name, r.college, r.portal_rank ?? "", r.points, r.contests_attended, r.contests_scanned,
      r.attendance_rate != null ? Math.round(r.attendance_rate * 100) : "", r.absent_streak,
      r.consistency, r.consistency_label, r.avg_solved,
      ...data.labels.flatMap((l) => {
        const q = r.questions[l];
        return [q?.solved, q?.attempted_contests, fmtDuration(q?.median_secs ?? null), q?.wrong];
      }),
      r.avg_top_pct, r.best_global_rank, r.rating, r.trend_label,
    ]);
    downloadCsv("student-analytics.csv", header, out);
  }

  return (
    <div ref={card}>
    <Card>
      <CardHeader
        title="All students"
        subtitle="Portal rank is by contest points. Qn solved = times solved / contests attended (with median time). Sort by any column."
        actions={
          <Button onClick={exportCsv} disabled={exporting || total === 0}>
            {exporting ? "Preparing…" : "Download CSV"}
          </Button>
        }
      />
      <div className="border-y border-fg/5 bg-fg/[0.015] px-5 py-2">
        <Input type="search" placeholder="Search name or roll no" value={query} onChange={(e) => setQuery(e.target.value)} className="w-full sm:w-72" />
      </div>
      <div className={cx("sticky-first overflow-x-auto transition-opacity [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap",
        q.isPlaceholderData && "opacity-60")}>
        <table className="w-full text-sm">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-fg/5 text-xs text-ink-2">
                {hg.headers.map((h) => {
                  const right = (h.column.columnDef.meta as { align?: string } | undefined)?.align === "right";
                  const sorted = h.column.getIsSorted();
                  return (
                    <th key={h.id} className={cx("whitespace-nowrap px-3 py-2.5 font-medium first:pl-5 last:pr-5", right ? "text-right" : "text-left")}
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}>
                      <button type="button" onClick={h.column.getToggleSortingHandler()} className={cx("inline-flex items-center gap-1 hover:text-ink", sorted && "text-ink")}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        <span aria-hidden className="w-2 text-[10px]">{sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : ""}</span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {q.isError && (
              <tr>
                <td colSpan={columns.length} className="px-5 py-4">
                  <ErrorBox error={q.error} onRetry={() => q.refetch()} />
                </td>
              </tr>
            )}
            {q.isPending && (
              <tr>
                <td colSpan={columns.length} className="px-5 py-8 text-center text-ink-3">Loading students…</td>
              </tr>
            )}
            {q.isSuccess && rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-5 py-8 text-center text-ink-3">No students match “{search}”.</td>
              </tr>
            )}
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b border-fg/5 last:border-0 hover:bg-surface-2/60">
                {row.getVisibleCells().map((cell) => {
                  const right = (cell.column.columnDef.meta as { align?: string } | undefined)?.align === "right";
                  return (
                    <td key={cell.id} className={cx("px-3 py-2.5 first:pl-5 last:pr-5", right && "text-right")}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-border px-5 py-3 text-[13px] text-ink-2">
        <span className="tabular">
          {total === 0 ? 0 : pageIndex * PAGE_SIZE + 1}–{Math.min(total, (pageIndex + 1) * PAGE_SIZE)} of {fmtInt(total)}
        </span>
        <div className="flex gap-2">
          <Button onClick={() => goTo(pageIndex - 1)} disabled={pageIndex === 0}>Previous</Button>
          <Button onClick={() => goTo(pageIndex + 1)} disabled={pageIndex + 1 >= pageCount}>Next</Button>
        </div>
      </div>
    </Card>
    </div>
  );
}
