/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { analyticsApi, type StudentAnalytics } from "../api";
import { fmtDate, fmtDecimal, fmtDuration, fmtInt, fmtIso, fmtPct } from "../format";
import { ChartTable, ColumnChart, LineChart, Meter, shortContest } from "./charts";
import { ConsistencyBadge, Definitions, TrendBadge, fmtTopPct } from "./metrics";
import { Card, CardHeader, ErrorBox, Stat } from "./ui";
import { studentAnalyticsQuery } from "../queries";
import { StudentAnalyticsSkeleton } from "./skeletons";

export default function StudentAnalyticsSection({ id }: { id: number }) {
  const qc = useQueryClient();
  const q = useQuery(studentAnalyticsQuery(id));
  // opening a student asks LeetCode for their current rating
  const live = useMutation({
    mutationFn: () => analyticsApi.refreshRating(id),
    onSuccess: (r) => {
      if (r.fetched_now) {
        qc.invalidateQueries({ queryKey: ["student-analytics", id] });
        qc.invalidateQueries({ queryKey: ["students"] });
      }
    },
  });
  const { mutate } = live;
  useEffect(() => mutate(), [id, mutate]);
  if (q.isPending) return <StudentAnalyticsSkeleton />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const a = q.data;
  return (
    <>
      <Tiles a={a} live={live.isPending ? "checking" : live.isError ? "failed" : live.isSuccess ? "live" : null} />
      <Definitions />
      <QuestionBreakdown a={a} />
      <Charts a={a} />
    </>
  );
}

function Tiles({ a, live }: { a: StudentAnalytics; live: "checking" | "live" | "failed" | null }) {
  const r = a.rating;
  return (
    <div className="kpi-row grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
      <Stat
        label="Attendance"
        value={`${a.contests_attended} / ${a.contests_scanned}`}
        sub={
          a.absent_streak > 0
            ? `missed the last ${a.absent_streak}`
            : a.current_streak > 1
              ? `${a.current_streak} in a row (best ${a.longest_streak})`
              : `${fmtPct(a.attendance_rate) || "0%"} of contests`
        }
      />
      <Stat label="Consistency" value={a.consistency ?? "—"} sub={a.consistency_label ?? "needs 3+ contests"} />
      <Stat
        label="Avg problems solved"
        value={fmtDecimal(a.avg_solved) || "—"}
        sub={<TrendBadge label={a.trend_label} delta={a.trend} />}
      />
      <Stat label="Avg global position" value={fmtTopPct(a.avg_top_pct) || "—"} sub={a.best_global_rank ? `best profile rank ${fmtInt(a.best_global_rank)}` : undefined} />
      <Stat label="Best college rank" value={a.best_college_rank ?? "—"} sub="among portal students" />
      <Stat
        label="LeetCode rating"
        value={r.current ? fmtInt(r.current) : "—"}
        sub={
          <span className="flex flex-col gap-0.5">
            <span>{r.top_percentage != null ? `top ${r.top_percentage}% · ${fmtInt(r.contests_attended)} contests` : r.synced_at ? "no rated contests" : "not synced yet"}</span>
            <span className="inline-flex items-center gap-1.5" title={r.synced_at ? `Last fetched from LeetCode ${fmtIso(r.synced_at)}` : undefined}>
              {live === "checking" ? (
                <>
                  <span className="live-dot h-1.5 w-1.5 rounded-full bg-accent" /> checking LeetCode…
                </>
              ) : live === "live" ? (
                <>
                  <span className="h-1.5 w-1.5 rounded-full bg-good" /> live from LeetCode
                </>
              ) : live === "failed" ? (
                <>LeetCode didn't answer{r.synced_at ? ` · as of ${fmtIso(r.synced_at)}` : ""}</>
              ) : null}
            </span>
          </span>
        }
      />
    </div>
  );
}

function QuestionBreakdown({ a }: { a: StudentAnalytics }) {
  return (
    <Card>
      <CardHeader
        title="Question by question"
        subtitle="How often this student solved each question when they took part, compared with all students (white tick / grey text)."
        actions={<ConsistencyBadge score={a.consistency} label={a.consistency_label} />}
      />
      {a.contests_attended === 0 ? (
        <p className="px-5 py-6 text-[13px] text-ink-2">Hasn't taken part in a scanned contest yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-2">
              <tr className="border-b border-fg/5">
                <th className="px-5 py-2 font-medium">Question</th>
                <th className="w-1/3 px-3 py-2 font-medium">Solved</th>
                <th className="px-3 py-2 text-right font-medium">Median time</th>
                <th className="px-3 py-2 text-right font-medium">Fastest</th>
                <th className="px-3 py-2 text-right font-medium">Wrong submissions</th>
                <th className="px-5 py-2 text-right font-medium">Wrong / solve</th>
              </tr>
            </thead>
            <tbody>
              {a.labels.map((label) => {
                const q = a.questions[label];
                if (!q) return null;
                return (
                  <tr key={label} className="border-b border-fg/5 last:border-0">
                    <td className="px-5 py-2.5 font-semibold">{label}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-3">
                        <Meter
                          value={q.solve_rate}
                          compare={q.cohort_solve_rate}
                          label={`${label}: solved ${q.solved} of ${q.attempted_contests} contests (${fmtPct(q.solve_rate)}); all students ${fmtPct(q.cohort_solve_rate)}`}
                        />
                        <span className="tabular w-44 shrink-0 text-right">
                          <span className="font-semibold">{q.solved}</span> of {q.attempted_contests}{" "}
                          <span className="text-ink-3">
                            ({fmtPct(q.solve_rate) || "0%"} · all {fmtPct(q.cohort_solve_rate) || "—"})
                          </span>
                        </span>
                      </div>
                    </td>
                    <td className="tabular px-3 py-2.5 text-right">
                      {fmtDuration(q.median_secs) || "—"}
                      {q.cohort_median_secs != null && <div className="text-xs text-ink-3">all {fmtDuration(q.cohort_median_secs)}</div>}
                    </td>
                    <td className="tabular px-3 py-2.5 text-right">{fmtDuration(q.best_secs) || "—"}</td>
                    <td className="tabular px-3 py-2.5 text-right">{q.wrong}</td>
                    <td className="tabular px-5 py-2.5 text-right">
                      {fmtDecimal(q.wrong_per_solve, 2) || "—"}
                      {q.cohort_wrong_per_solve != null && <div className="text-xs text-ink-3">all {fmtDecimal(q.cohort_wrong_per_solve, 2)}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Charts({ a }: { a: StudentAnalytics }) {
  const s = a.series;
  const maxQ = Math.max(4, ...s.map((x) => x.questions));
  const ratings = a.rating.history.slice(-30);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader title="Problems solved" subtitle="Per scanned contest (– = absent)." />
        <div className="px-5 pb-3 pt-2">
          <ColumnChart
            ariaLabel="Problems solved per contest"
            max={maxQ}
            format={(v) => String(Math.round(v))}
            columns={s.map((x) => ({
              label: x.title,
              tick: shortContest(x.title),
              value: x.solved,
              note: x.status === "solved" || x.status === "zero" ? `of ${x.questions} questions` : "absent",
            }))}
          />
          <ChartTable columns={["Contest", "Date", "Solved", "Status"]} rows={s.map((x) => [x.title, fmtDate(x.start_time), x.solved ?? "—", x.status])} />
        </div>
      </Card>
      <Card>
        <CardHeader title="Global position" subtitle="Top % of all participants (higher on the chart is better)." />
        <div className="px-5 pb-3 pt-2">
          <LineChart
            ariaLabel="Global position by contest"
            invert
            format={(v) => (v === 0 ? "0%" : `${v < 10 ? fmtDecimal(v) : Math.round(v)}%`)}
            points={s.map((x) => ({
              label: x.title,
              tick: shortContest(x.title),
              y: x.top_pct,
              note: x.global_rank ? `rank ${fmtInt(x.global_rank)} · college rank ${x.college_rank ?? "—"}` : "absent",
            }))}
            height={176}
          />
          <ChartTable
            columns={["Contest", "Global rank", "Top %", "College rank"]}
            rows={s.map((x) => [x.title, fmtInt(x.global_rank) || "—", fmtTopPct(x.top_pct) || "—", x.college_rank ?? "—"])}
          />
        </div>
      </Card>
      <Card>
        <CardHeader title="LeetCode rating" subtitle="After each rated contest (from LeetCode)." />
        <div className="px-5 pb-3 pt-2">
          {ratings.length === 0 ? (
            <p className="grid min-h-36 place-items-center rounded-md border border-dashed border-fg/10 px-4 text-center text-xs text-ink-3">{a.rating.synced_at ? "No rated contests yet." : "Ratings haven't been synced yet."}</p>
          ) : (
            <>
              <LineChart
                ariaLabel="LeetCode rating history"
                area={false}
                format={(v) => fmtInt(Math.round(v))}
                points={ratings.map((h) => ({
                  label: h.title,
                  tick: shortContest(h.title),
                  y: h.rating,
                  note: h.ranking ? `rank ${fmtInt(h.ranking)} · solved ${h.solved}/${h.total}` : undefined,
                }))}
                height={176}
              />
              <ChartTable
                columns={["Contest", "Rating", "Rank", "Solved"]}
                rows={ratings.map((h) => [h.title, h.rating, fmtInt(h.ranking) || "—", h.solved != null ? `${h.solved}/${h.total}` : "—"])}
              />
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
