/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 18 October 2026
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { analyticsApi, api, instructorsApi, topicsApi, type Instructor } from "../api";
import { useViewAs } from "../auth";
import { AuditLine } from "../components/Roster";
import { PageSkeleton, RowsSkeleton } from "../components/skeletons";
import { Badge, Button, Card, CardHeader, Empty, ErrorBox, Input, cx } from "../components/ui";
import { fmtDateTime, fmtInt } from "../format";
import { AnalyticsView } from "./Analytics";

const TABS = [
  { key: "overview", label: "Students and analytics" },
  { key: "contests", label: "Contests" },
] as const;
type Tab = (typeof TABS)[number]["key"];

/** Admin → Instructors → one instructor: who they follow, how those students are doing,
 *  each contest limited to them, and "View as" to see exactly their dashboard. */
export default function InstructorDetail() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "contests" ? "contests" : "overview";
  const list = useQuery({ queryKey: ["instructors"], queryFn: instructorsApi.list });
  const i = list.data?.instructors.find((x) => x.id === id);

  if (list.isPending) return <PageSkeleton />;
  if (list.isError) return <ErrorBox error={list.error} onRetry={() => list.refetch()} />;
  if (!i)
    return (
      <Card>
        <Empty>
          This instructor doesn't exist (any more). <Link to="/admin/instructors" className="text-accent-ink">Back to instructors</Link>
        </Empty>
      </Card>
    );

  return (
    <div className="flex flex-col gap-5">
      <Header i={i} />
      <div role="tablist" aria-label="Sections" className="flex gap-1 border-b border-fg/[0.08]">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setParams(t.key === "overview" ? {} : { tab: t.key }, { replace: true })}
            className={cx(
              "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium",
              tab === t.key ? "border-accent text-ink" : "border-transparent text-ink-2 hover:text-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "overview" ? (
        <AnalyticsView
          key={i.id}
          title={`${i.name}'s students`}
          subtitle={`What ${i.name} sees on their “My students” page · ${fmtInt(i.students)} students. Click a student to open their page.`}
          queryKey={["instructor-analytics", i.id]}
          fetch={(f) => analyticsApi.instructor(f, i.id)}
          fetchStudents={(f, page) => analyticsApi.instructorStudents(f, page, i.id)}
          fetchTopics={(f) => topicsApi.instructor(f, i.id)}
        />
      ) : (
        <Contests i={i} />
      )}
    </div>
  );
}

function Header({ i }: { i: Instructor }) {
  const { start, pending, error } = useViewAs();
  return (
    <Card>
      <div className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-start">
        <div className="min-w-0 flex-1">
          <Link to="/admin/instructors" className="text-xs text-ink-2 hover:text-ink">
            ← Instructors
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight text-ink">{i.name}</h2>
            {i.active ? <Badge tone="good" icon="check">Active</Badge> : <Badge tone="neutral" icon="dash">Deactivated</Badge>}
          </div>
          <div className="text-xs text-ink-3">{i.email}</div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
            <span className="font-medium text-ink">{fmtInt(i.students)} students</span>
            {i.colleges.map((c) => (
              <span key={c} className="rounded-full bg-fg/[0.05] px-2 py-0.5 ring-1 ring-inset ring-fg/[0.06]">
                {c}
              </span>
            ))}
            {i.roll_nos.length > 0 && (
              <span className="rounded-full bg-fg/[0.05] px-2 py-0.5 ring-1 ring-inset ring-fg/[0.06]" title={i.roll_nos.join(", ")}>
                +{i.roll_nos.length} by roll no
              </span>
            )}
          </div>
          <AuditLine a={i} className="mt-2" />
        </div>
        <div className="flex shrink-0 flex-col items-start gap-1 sm:items-end">
          <Button variant="primary" onClick={() => start(i.id)} disabled={pending || !i.active} title="See the dashboard exactly as this instructor does (read-only, up to an hour)">
            {pending ? "Switching…" : "View as"}
          </Button>
          {!i.active && <span className="text-xs text-ink-3">Activate the login to view as them</span>}
          {error != null && <div className="max-w-64"><ErrorBox error={error} /></div>}
        </div>
      </div>
    </Card>
  );
}

function Contests({ i }: { i: Instructor }) {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const contests = useQuery({
    queryKey: ["contests", "with_data", q, page],
    queryFn: () => api.contests({ show: "with_data", q, page, per_page: 20 }),
    placeholderData: keepPreviousData,
  });
  const pages = contests.data ? Math.max(1, Math.ceil(contests.data.total / contests.data.per_page)) : 1;
  return (
    <Card>
      <CardHeader title="Contests" subtitle={`Each contest's results, limited to ${i.name}'s students.`} />
      <div className="border-y border-fg/5 bg-fg/[0.015] px-5 py-2">
        <Input type="search" placeholder="Search contests" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="w-full sm:w-72" />
      </div>
      {contests.isPending ? (
        <div className="px-5"><RowsSkeleton rows={8} cols={3} /></div>
      ) : contests.isError ? (
        <div className="p-5"><ErrorBox error={contests.error} onRetry={() => contests.refetch()} /></div>
      ) : contests.data.items.length === 0 ? (
        <Empty>No scanned contests{q ? " match this search" : " yet"}.</Empty>
      ) : (
        <ul className={cx("divide-y divide-fg/5", contests.isPlaceholderData && "opacity-60")}>
          {contests.data.items.map((c) => (
            <li key={c.slug}>
              <Link to={`/contests/${c.slug}?instructor=${i.id}`} className="flex items-center gap-4 px-5 py-2.5 hover:bg-fg/[0.025]">
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">{c.title}</span>
                <span className="tabular text-xs text-ink-3">{fmtDateTime(c.start_time)}</span>
                <span aria-hidden className="text-ink-3">→</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 border-t border-fg/5 px-5 py-2 text-xs text-ink-2">
          <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span className="tabular">Page {page} of {pages}</span>
          <Button variant="ghost" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </Card>
  );
}
