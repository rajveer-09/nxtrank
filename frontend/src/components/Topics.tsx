/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 18 October 2026
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { QuestionTopics, TopicMetrics, TopicRow, TopicsData } from "../api";
import { fmtDuration, fmtInt, fmtIso, fmtPct } from "../format";
import { RowsSkeleton } from "./skeletons";
import { TopicBars, TopicDonut } from "./TopicCharts";
import { Card, CardHeader, Empty, ErrorBox, cx } from "./ui";

/** Topic tags: official ones solid, provisional (from community solutions) dashed. */
export function TagChip({ name, provisional, title }: { name: string; provisional?: boolean; title?: string }) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        provisional ? "border border-dashed border-info/50 text-info-ink" : "bg-fg/[0.06] text-ink-2 ring-1 ring-inset ring-fg/[0.08]",
      )}
    >
      {name}
      {provisional && <span className="text-[10px] uppercase tracking-wide opacity-80">Provisional</span>}
    </span>
  );
}

/** A contest question's tags, or why it has none yet. */
export function QuestionChips({ t }: { t: QuestionTopics | undefined }) {
  if (!t || t.state === "pending") return <span className="text-[11px] text-ink-3">Topics pending</span>;
  if (t.state === "insufficient") return <span className="text-[11px] text-ink-3">Not enough community data yet</span>;
  const provisional = t.state === "provisional";
  const title = provisional
    ? `From ${t.mentions ?? 0} community solution topic mentions · fetched ${fmtIso(t.fetched_at)} · replaced automatically when LeetCode publishes official tags`
    : `LeetCode's official tags · checked ${fmtIso(t.fetched_at)}`;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {t.tags.map((tag) => (
        <TagChip key={tag.slug} name={tag.name} provisional={provisional} title={title} />
      ))}
    </span>
  );
}

export function TopicLegend() {
  return (
    <p className="text-xs text-ink-3">
      Solid chips are LeetCode's official tags. <span className="rounded-full border border-dashed border-info/50 px-1.5 text-info-ink">Dashed</span> chips
      are provisional, from the topics community solutions use, until LeetCode publishes official ones (usually 1–4 weeks after a contest).
    </p>
  );
}

/** What the topic numbers rest on: how many contests use provisional tags, and what's left out. */
export function CoverageNote({ data }: { data: TopicsData }) {
  const c = data.coverage;
  if (!c.questions) return null;
  const parts: string[] = [];
  if (c.contests_provisional)
    parts.push(
      `Topic stats include provisional tags for ${fmtInt(c.contests_provisional)} ${c.contests_provisional === 1 ? "contest" : "contests"} (${fmtInt(c.provisional)} ${c.provisional === 1 ? "question" : "questions"}).`,
    );
  const out = c.insufficient + c.pending;
  if (out)
    parts.push(`${fmtInt(out)} ${out === 1 ? "question isn't" : "questions aren't"} counted yet (${[
      c.insufficient ? `${c.insufficient} with too little community data` : "",
      c.pending ? `${c.pending} not checked yet` : "",
    ].filter(Boolean).join(", ")}).`);
  if (c.contests_provisional) parts.push("Official tags replace these automatically.");
  if (!parts.length) parts.push(`Every question in these ${fmtInt(c.contests)} contests has official tags.`);
  return (
    <div className="rounded-md bg-info/[0.07] px-3 py-2 text-xs text-ink-2 ring-1 ring-inset ring-info/20">
      {parts.join(" ")}
      {c.last_refresh && <span className="text-ink-3"> Tags as of {fmtIso(c.last_refresh)}.</span>}
    </div>
  );
}

function pick(row: TopicRow, officialOnly: boolean): TopicMetrics {
  return officialOnly ? row.official : row;
}

/** The topics table: appeared, solved, solve rate, accuracy and median time per topic. */
export function TopicsTable({ data, weakest = [], groupMedian = false, officialOnly: controlled, setOfficialOnly: setControlled }: {
  data: TopicsData;
  weakest?: string[];
  groupMedian?: boolean;
  officialOnly?: boolean;
  setOfficialOnly?: (v: boolean) => void;
}) {
  const [own, setOwn] = useState(false);
  const officialOnly = controlled ?? own;
  const setOfficialOnly = setControlled ?? setOwn;
  const rows = data.topics
    .map((r) => ({ row: r, m: pick(r, officialOnly) }))
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
        <label className="flex shrink-0 items-center gap-2 text-xs text-ink-2">
          <input type="checkbox" checked={officialOnly} onChange={(e) => setOfficialOnly(e.target.checked)} className="accent-[var(--accent)]" />
          Official tags only
        </label>
      </div>
      {rows.length === 0 ? (
        <Empty>{officialOnly ? "No questions here have official tags yet." : "No tagged questions in these contests yet."}</Empty>
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
                    {!officialOnly && row.provisional_appeared > 0 && (
                      <span className="ml-2 text-[11px] text-info-ink" title={`${row.provisional_questions} provisional ${row.provisional_questions === 1 ? "question" : "questions"} count here`}>
                        ⓟ {fmtInt(row.provisional_appeared)} of {fmtInt(row.appeared)} provisional
                      </span>
                    )}
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
      <TopicLegend />
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
  const [officialOnly, setOfficialOnly] = useState(false);
  const rates = other.data
    ? new Map(other.data.topics.map((t) => [t.slug, (officialOnly ? t.official : t).solve_rate] as const))
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
                <TopicBars rows={q.data.topics} officialOnly={officialOnly} compare={rates} compareLabel={compare?.label} />
                <TopicDonut rows={q.data.topics} officialOnly={officialOnly} />
              </div>
            )}
            <TopicsTable data={q.data} weakest={group ? q.data.weakest : []} groupMedian={group} officialOnly={officialOnly} setOfficialOnly={setOfficialOnly} />
          </div>
        )}
      </div>
    </Card>
  );
}
