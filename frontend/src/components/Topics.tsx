/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 18 October 2026
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { QuestionTopics, TopicMetrics, TopicRow, TopicsData } from "../api";
import { fmtDuration, fmtInt, fmtIso, fmtPct } from "../format";
import { RowsSkeleton } from "./skeletons";
import { TopicBars, TopicDonut } from "./TopicCharts";
import { Card, CardHeader, Empty, ErrorBox, cx } from "./ui";

/** A topic tag. */
export function TagChip({ name, title }: { name: string; title?: string }) {
  return (
    <span title={title} className="inline-flex items-center gap-1 rounded-full bg-fg/[0.06] px-2 py-0.5 text-[11px] font-medium text-ink-2 ring-1 ring-inset ring-fg/[0.08]">
      {name}
    </span>
  );
}

/** A contest question's topics, or a note that they aren't known yet. */
export function QuestionChips({ t }: { t: QuestionTopics | undefined }) {
  if (!t || !t.tags.length)
    return (
      <span className="text-[11px] text-ink-3" title="Topics appear a few days after a contest">
        Topics pending
      </span>
    );
  const title = t.fetched_at ? `Topics · updated ${fmtIso(t.fetched_at)}` : undefined;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {t.tags.map((tag) => (
        <TagChip key={tag.slug} name={tag.name} title={title} />
      ))}
    </span>
  );
}

/** What the topic numbers rest on: which questions are left out until their topics are known. */
export function CoverageNote({ data }: { data: TopicsData }) {
  const c = data.coverage;
  if (!c.questions) return null;
  const parts: string[] = [];
  const out = c.insufficient + c.pending;
  if (out)
    parts.push(`${fmtInt(out)} ${out === 1 ? "question isn't" : "questions aren't"} counted yet: ${out === 1 ? "its" : "their"} topics aren't known yet.`);
  if (!parts.length) parts.push(`Every question in these ${fmtInt(c.contests)} contests has topics.`);
  return (
    <div className="rounded-md bg-info/[0.07] px-3 py-2 text-xs text-ink-2 ring-1 ring-inset ring-info/20">
      {parts.join(" ")}
      {c.last_refresh && <span className="text-ink-3"> Tags as of {fmtIso(c.last_refresh)}.</span>}
    </div>
  );
}

/** The topics table: appeared, solved, solve rate, accuracy and median time per topic. */
export function TopicsTable({ data, weakest = [], groupMedian = false }: { data: TopicsData; weakest?: string[]; groupMedian?: boolean }) {
  const rows = data.topics
    .map((r): { row: TopicRow; m: TopicMetrics } => ({ row: r, m: r }))
    .filter(({ m }) => m.appeared > 0)
    .sort((a, b) => {
      const wa = weakest.indexOf(a.row.slug), wb = weakest.indexOf(b.row.slug);
      if (wa !== wb) return (wa === -1 ? 99 : wa) - (wb === -1 ? 99 : wb);
      return b.m.appeared - a.m.appeared || a.row.name.localeCompare(b.row.name);
    });
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <CoverageNote data={data} />
      </div>
      {rows.length === 0 ? (
        <Empty>No tagged questions in these contests yet.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-[13px]">
            <thead className="text-left text-xs text-ink-2">
              <tr className="border-b border-fg/5">
                <th className="py-2 pr-3 font-medium">Topic</th>
                <th className="py-2 pr-3 text-right font-medium">Appeared</th>
                <th className="py-2 pr-3 text-right font-medium">Solved</th>
                <th className="py-2 pr-3 text-right font-medium">Solve rate</th>
                <th className="py-2 pr-3 text-right font-medium" title="Accepted ÷ (accepted + wrong submissions). LeetCode reports wrong tries only for solved problems.">Accuracy</th>
                <th className="py-2 text-right font-medium" title={groupMedian ? "Median of the solves, to the minute" : undefined}>Median time</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ row, m }) => (
                <tr key={row.slug} className="border-b border-fg/5 last:border-0">
                  <td className="py-2 pr-3">
                    <span className="font-medium text-ink">{row.name}</span>
                    {weakest.includes(row.slug) && <span className="ml-2 rounded-full bg-critical/10 px-1.5 py-0.5 text-[10px] font-medium text-critical-ink">weak</span>}
                  </td>
                  <td className="tabular py-2 pr-3 text-right">{fmtInt(m.appeared)}</td>
                  <td className="tabular py-2 pr-3 text-right">{fmtInt(m.solved)}</td>
                  <td className="tabular py-2 pr-3 text-right">{fmtPct(m.solve_rate) || "—"}</td>
                  <td className="tabular py-2 pr-3 text-right">{fmtPct(m.accuracy) || "—"}</td>
                  <td className="tabular py-2 text-right">{m.median_secs != null ? fmtDuration(m.median_secs) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** A "Topics" card that loads its own data (student, cohort, college or instructor). */
export function TopicsCard({ queryKey, fetch, subtitle, group = false, compare }: {
  queryKey: unknown[];
  fetch: () => Promise<TopicsData>;
  subtitle: string;
  group?: boolean;
  /** a group to compare against in the chart (e.g. every student, on a student's page) */
  compare?: { queryKey: unknown[]; fetch: () => Promise<TopicsData>; label: string };
}) {
  const q = useQuery({ queryKey: ["topics", ...queryKey], queryFn: fetch, placeholderData: keepPreviousData });
  const other = useQuery({ queryKey: ["topics", ...(compare?.queryKey ?? ["none"])], queryFn: compare?.fetch ?? (() => Promise.reject()), enabled: !!compare, staleTime: 5 * 60_000 });
  const rates = other.data
    ? new Map(other.data.topics.map((t) => [t.slug, t.solve_rate] as const))
    : undefined;
  return (
    <Card>
      <CardHeader title="Topics" subtitle={subtitle} />
      <div className={cx("px-5 pb-4", q.isPlaceholderData && "opacity-60")}>
        {q.isPending ? (
          <RowsSkeleton rows={6} cols={6} label="Loading topics…" />
        ) : q.isError ? (
          <ErrorBox error={q.error} onRetry={() => q.refetch()} />
        ) : (
          <div className="flex flex-col gap-5">
            {q.data.topics.length > 0 && (
              <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                <TopicBars rows={q.data.topics} officialOnly={false} compare={rates} compareLabel={compare?.label} />
                <TopicDonut rows={q.data.topics} officialOnly={false} />
              </div>
            )}
            <TopicsTable data={q.data} weakest={group ? q.data.weakest : []} groupMedian={group} />
          </div>
        )}
      </div>
    </Card>
  );
}
