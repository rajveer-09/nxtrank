/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 18 October 2026
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { topicsApi, type TagState, type TagsStatus } from "../api";
import { useMe } from "../auth";
import { fmtInt, fmtIso } from "../format";
import { ScansOffNote } from "./ContestStatus";
import { RowsSkeleton } from "./skeletons";
import { QuestionChips, TopicLegend } from "./Topics";
import { Button, Card, CardHeader, Empty, ErrorBox, Select, cx } from "./ui";

const STATES: { key: TagState; label: string; hint: string }[] = [
  { key: "official", label: "Official", hint: "LeetCode's own tags" },
  { key: "provisional", label: "Provisional", hint: "from community solutions" },
  { key: "insufficient", label: "Not enough data", hint: "left out of topic stats" },
  { key: "pending", label: "Pending", hint: "not checked yet" },
];

/** Admin → Topics: the nightly tag refresh, and each question's tags. */
export default function TagsCard() {
  const qc = useQueryClient();
  const scansOff = useMe().data?.scans_enabled === false;
  const status = useQuery({
    queryKey: ["tags-status"],
    queryFn: topicsApi.status,
    refetchInterval: (q) => (q.state.data?.refresh_requested ? 10_000 : false),
  });
  const refresh = useMutation({ mutationFn: topicsApi.refresh, onSuccess: () => qc.invalidateQueries({ queryKey: ["tags-status"] }) });
  const [show, setShow] = useState<TagState | "">("");

  return (
    <Card>
      <CardHeader
        title="Topics"
        subtitle="The worker refreshes topic tags every night at 00:00 IST for the last 45 days' questions, official tags for every question on the 1st of each month, and right after each scan."
      />
      <div className="flex flex-col gap-4 border-t border-fg/5 px-5 py-4">
        {status.isPending ? (
          <RowsSkeleton rows={4} cols={4} />
        ) : status.isError ? (
          <ErrorBox error={status.error} onRetry={() => status.refetch()} />
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="text-[13px]">
                <div className="font-medium text-ink">Last refresh</div>
                <div className="text-ink-2">
                  {status.data.last_run
                    ? `${fmtIso(status.data.last_run.at)} · ${status.data.last_run.line.replace(/^tags: /, "")}`
                    : "Not run yet."}
                </div>
              </div>
              {scansOff ? (
                <ScansOffNote />
              ) : (
                <div className="flex flex-col items-end gap-1">
                  <Button variant="primary" onClick={() => refresh.mutate()} disabled={refresh.isPending || status.data.refresh_requested}>
                    {status.data.refresh_requested ? "Waiting for the worker…" : "Refresh tags"}
                  </Button>
                  <span className="text-xs text-ink-3">The worker picks it up within a minute.</span>
                </div>
              )}
            </div>
            {refresh.isError && <ErrorBox error={refresh.error} />}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {STATES.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setShow(show === s.key ? "" : s.key)}
                  className={cx(
                    "rounded-lg px-3 py-2 text-left ring-1 ring-inset",
                    show === s.key ? "bg-accent-soft ring-accent/30" : "bg-fg/[0.025] ring-fg/[0.06] hover:bg-fg/[0.04]",
                  )}
                >
                  <div className="tabular text-lg font-semibold text-ink">{fmtInt(status.data.counts[s.key])}</div>
                  <div className="text-xs text-ink-2">
                    {s.label} · {s.hint}
                  </div>
                </button>
              ))}
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <CoverageChart questions={status.data.questions} />
              <TopTopicsChart questions={status.data.questions} />
            </div>
            <TopicLegend />
          </>
        )}
      </div>
      {status.data && <QuestionList questions={status.data.questions} show={show} setShow={setShow} />}
    </Card>
  );
}

function QuestionList({
  questions,
  show,
  setShow,
}: {
  questions: TagsStatus["questions"];
  show: TagState | "";
  setShow: (s: TagState | "") => void;
}) {
  const [limit, setLimit] = useState(40);
  const rows = questions.filter((q) => !show || q.state === show);
  return (
    <div className="border-t border-fg/5">
      <div className="flex items-center gap-3 px-5 py-2">
        <Select label="Show" hideLabel value={show} onChange={(e) => setShow(e.target.value as TagState | "")}>
          <option value="">Every question</option>
          {STATES.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </Select>
        <span className="text-xs text-ink-3">{fmtInt(rows.length)} questions, newest contests first</span>
      </div>
      {rows.length === 0 ? (
        <Empty>No questions here.</Empty>
      ) : (
        <ul className="divide-y divide-fg/5">
          {rows.slice(0, limit).map((q) => (
            <li key={`${q.contest}/${q.label}`} className="flex flex-col gap-1 px-5 py-2 sm:flex-row sm:items-center sm:gap-4">
              <div className="min-w-0 sm:w-80">
                <div className="truncate text-[13px] text-ink">
                  <span className="mr-1.5 font-semibold">{q.label}</span>
                  {q.title ?? q.slug}
                </div>
                <div className="truncate text-xs text-ink-3">{q.contest_title}</div>
              </div>
              <div className="min-w-0 flex-1">
                <QuestionChips t={{ state: q.state, tags: q.tags, mentions: q.mentions, fetched_at: q.fetched_at }} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {rows.length > limit && (
        <div className="border-t border-fg/5 px-5 py-2">
          <Button variant="ghost" size="sm" onClick={() => setLimit(limit + 80)}>
            Show more
          </Button>
        </div>
      )}
    </div>
  );
}

// tag states are states, so they wear the status colours, always with a label
const STATE_COLOR: Record<TagState, string> = {
  official: "var(--good)",
  provisional: "var(--info)",
  insufficient: "var(--warning)",
  pending: "var(--neutral)",
};
const STATE_LABEL: Record<TagState, string> = {
  official: "Official",
  provisional: "Provisional",
  insufficient: "Not enough data",
  pending: "Pending",
};
const ORDER: TagState[] = ["official", "provisional", "insufficient", "pending"];
const RECENT_CONTESTS = 12;

const shortName = (title: string) => title.replace(/^Weekly Contest /, "W").replace(/^Biweekly Contest /, "B");

/** Recent contests, oldest to newest: each question coloured by its tag state. Official
 *  tags arriving over the weeks show as the green moving right. */
function CoverageChart({ questions }: { questions: TagsStatus["questions"] }) {
  const [active, setActive] = useState<string | null>(null);
  const contests: { slug: string; title: string; qs: TagsStatus["questions"] }[] = [];
  for (const q of questions) {
    let c = contests.find((x) => x.slug === q.contest);
    if (!c) contests.push((c = { slug: q.contest, title: q.contest_title, qs: [] }));
    c.qs.push(q);
  }
  const shown = contests.slice(0, RECENT_CONTESTS).reverse(); // the API lists newest first
  if (!shown.length) return null;
  const tallest = Math.max(...shown.map((c) => c.qs.length));
  const hovered = shown.find((c) => c.slug === active);
  return (
    <figure className="flex min-w-0 flex-col gap-3">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="font-medium text-ink">Tag coverage, last {shown.length} contests</span>
        <span className="flex flex-wrap gap-3 text-ink-2" aria-hidden>
          {ORDER.map((s) => (
            <span key={s} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: STATE_COLOR[s] }} />
              {STATE_LABEL[s]}
            </span>
          ))}
        </span>
      </figcaption>
      <div
        role="img"
        aria-label={`Tag coverage by contest: ${shown.map((c) => `${c.title}: ${ORDER.map((s) => `${c.qs.filter((q) => q.state === s).length} ${STATE_LABEL[s].toLowerCase()}`).join(", ")}`).join("; ")}`}
        className="relative"
      >
        <div aria-hidden className="flex h-36 items-end gap-1.5">
          {shown.map((c) => (
            <div
              key={c.slug}
              className={cx(
                "flex h-full min-w-0 flex-1 flex-col justify-end rounded-sm px-0.5 transition-colors",
                active === c.slug && "bg-fg/[0.04]",
              )}
              onPointerEnter={() => setActive(c.slug)}
              onPointerLeave={() => setActive(null)}
              onClick={() => setActive(active === c.slug ? null : c.slug)}
            >
              <div className="flex flex-col-reverse gap-0.5" style={{ height: `${(c.qs.length / tallest) * 100}%` }}>
                {ORDER.flatMap((s) => c.qs.filter((q) => q.state === s)).map((q) => (
                  <span key={q.label} className="min-h-1 flex-1 rounded-[3px]" style={{ background: STATE_COLOR[q.state] }} />
                ))}
              </div>
            </div>
          ))}
        </div>
        <div aria-hidden className="mt-1.5 flex gap-1.5">
          {shown.map((c) => (
            <span key={c.slug} className="tabular min-w-0 flex-1 truncate text-center text-[10px] text-ink-3">
              {shortName(c.title)}
            </span>
          ))}
        </div>
        {hovered && (
          <div
            role="tooltip"
            className="pointer-events-none absolute left-0 top-0 z-10 rounded-md bg-surface-2 px-2.5 py-1.5 text-[11px] leading-snug text-ink shadow-(--shadow-pop) ring-1 ring-inset ring-fg/10"
          >
            <b>{hovered.title}</b>
            {hovered.qs.map((q) => (
              <div key={q.label}>
                {q.label}: {STATE_LABEL[q.state].toLowerCase()}
                {q.tags.length ? ` · ${q.tags.map((t) => t.name).join(", ")}` : ""}
              </div>
            ))}
          </div>
        )}
      </div>
    </figure>
  );
}

/** The topics on the most questions, official and provisional parts. */
function TopTopicsChart({ questions }: { questions: TagsStatus["questions"] }) {
  const counts = new Map<string, { name: string; official: number; provisional: number }>();
  for (const q of questions)
    for (const t of q.tags) {
      const c = counts.get(t.slug) ?? { name: t.name, official: 0, provisional: 0 };
      if (t.source === "official") c.official++;
      else c.provisional++;
      counts.set(t.slug, c);
    }
  const rows = [...counts.values()]
    .sort((a, b) => b.official + b.provisional - (a.official + a.provisional) || a.name.localeCompare(b.name))
    .slice(0, 8);
  if (!rows.length) return null;
  const most = rows[0].official + rows[0].provisional;
  return (
    <figure className="flex min-w-0 flex-col gap-3">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="font-medium text-ink">Most common topics</span>
        <span className="flex gap-3 text-ink-2" aria-hidden>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-[2px] bg-[var(--series-1)]" />
            Official
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-[2px] border border-dashed border-[var(--series-1)]" />
            Provisional
          </span>
        </span>
      </figcaption>
      <div role="img" aria-label={`Most common topics: ${rows.map((r) => `${r.name} ${r.official + r.provisional} questions`).join(", ")}`}>
        <ul aria-hidden className="flex flex-col gap-1.5">
          {rows.map((r) => (
            <li
              key={r.name}
              title={`${r.name}: ${r.official} official, ${r.provisional} provisional`}
              className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)_2.5rem] items-center gap-3"
            >
              <span className="truncate text-xs text-ink-2">{r.name}</span>
              <span className="flex h-2.5 gap-0.5">
                {r.official > 0 && (
                  <span className="rounded-full bg-[var(--series-1)]" style={{ width: `${(r.official / most) * 100}%` }} />
                )}
                {r.provisional > 0 && (
                  <span
                    className="rounded-full border border-dashed border-[var(--series-1)] bg-[color-mix(in_srgb,var(--series-1)_18%,transparent)]"
                    style={{ width: `${(r.provisional / most) * 100}%` }}
                  />
                )}
              </span>
              <span className="tabular text-right text-xs font-medium text-ink">{r.official + r.provisional}</span>
            </li>
          ))}
        </ul>
      </div>
    </figure>
  );
}
