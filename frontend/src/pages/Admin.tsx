/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { adminsApi, api, collegesApi, instructorsApi, rosterApi } from "../api";
import AdminsCard from "../components/Admins";
import CollegesCard from "../components/Colleges";
import GroupReportCard from "../components/GroupReport";
import { Badge, Button, Card, CardHeader, Empty, ErrorBox, Input, cx } from "../components/ui";
import { fmtIso, fmtInt } from "../format";
import { CancelScanButton, ScanConfirm, ScansOffNote } from "../components/ContestStatus";
import { useMe } from "../auth";
import InstructorsCard from "../components/Instructors";
import TagsCard from "../components/TagsAdmin";
import InstructorDetail from "./InstructorDetail";
import RosterCard from "../components/Roster";
import { RowsSkeleton } from "../components/skeletons";

const slugTitle = (slug: string) => slug.split("-").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
const kindLabel = (kind: string) => (kind === "final" ? "Final" : kind === "auto" ? "Early or final, by date" : "Early");

const RUN_STATUS = {
  complete: ["good", "check", "Complete"],
  failed: ["critical", "cross", "Failed"],
  cancelled: ["neutral", "dash", "Cancelled"],
  running: ["accent", "spin", "Running"],
  review: ["info", "clock", "Awaiting review"],
  discarded: ["neutral", "dash", "Discarded"],
} as const;

/** Admin: a settings-style page with a section menu; each section has its own URL. */
export default function Admin() {
  const { pathname } = useLocation();
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">Admin</h1>
        <p className="mt-1 text-[13px] text-ink-2">Manage students and instructors, run scans on demand, and follow the Top K group.</p>
      </div>
      <div className="grid items-start gap-6 lg:grid-cols-[256px_minmax(0,1fr)]">
        <AdminNav />
        <div key={pathname} className="page-enter min-w-0">
          <Routes>
            <Route index element={<Navigate to="/admin/students" replace />} />
            <Route path="students" element={<RosterCard />} />
            <Route path="instructors" element={<InstructorsCard />} />
            <Route path="instructors/:id" element={<InstructorDetail />} />
            <Route path="admins" element={<AdminsCard />} />
            <Route path="colleges" element={<CollegesCard />} />
            <Route path="scans" element={<ScanCard />} />
            <Route path="topics" element={<TagsCard />} />
            <Route path="top-k" element={<GroupReportCard />} />
            <Route path="*" element={<Navigate to="/admin/students" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}

const ICONS: Record<string, ReactNode> = {
  students: (
    <path d="M8 8.5a2.75 2.75 0 1 0 0-5.5 2.75 2.75 0 0 0 0 5.5ZM2.75 14c.4-2.6 2.6-4 5.25-4s4.85 1.4 5.25 4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  ),
  instructors: (
    <path d="M8 2 14.5 5 8 8 1.5 5 8 2Zm-4 4.4v3.1C4 11 5.8 12.5 8 12.5s4-1.5 4-3V6.4M14.5 5v4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  ),
  admins: (
    <path d="M8 1.75 13 3.6v3.6c0 3-2.1 5.4-5 6.6-2.9-1.2-5-3.6-5-6.6V3.6L8 1.75ZM6 7.75l1.4 1.4L10.25 6.3" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  ),
  colleges: (
    <path d="M2 6.5 8 3l6 3.5M3.5 7v5M6.5 7v5M9.5 7v5M12.5 7v5M2 13.5h12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  ),
  topics: (
    <path d="M2.5 3.5h5l6 6-4 4-6-6v-4ZM5.25 6.25h.01" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  ),
  "top-k": (
    <path d="M5 2.5h6v3.25a3 3 0 0 1-6 0V2.5ZM5 3.75H3v1a2 2 0 0 0 2 2M11 3.75h2v1a2 2 0 0 1-2 2M8 8.75v2.5M5.5 13.5h5M6.25 13.5l.5-2.25h2.5l.5 2.25" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  ),
  scans: (
    <path d="M2.5 8a5.5 5.5 0 1 0 1.6-3.9M2.5 2.5v2.6h2.6M8 5v3l2 1.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  ),
};

function AdminNav() {
  // counts reuse the sections' own queries (same keys), so they're shared, not refetched
  const roster = useQuery({
    queryKey: ["roster", "count"],
    queryFn: () => rosterApi.list({ q: "", show: "active", offset: 0, limit: 1 }),
  });
  const instructors = useQuery({ queryKey: ["instructors"], queryFn: instructorsApi.list });
  const admins = useQuery({ queryKey: ["admins"], queryFn: adminsApi.list });
  const colleges = useQuery({ queryKey: ["colleges"], queryFn: collegesApi.list });
  const requests = useQuery({ queryKey: ["scan-requests"], queryFn: api.scanRequests, refetchInterval: 15_000 });
  const runs = useQuery({ queryKey: ["scan-runs"], queryFn: api.scanRuns, refetchInterval: 15_000 });
  const busy = (requests.data?.filter((r) => !r.handled_at).length ?? 0) + (runs.data?.some((r) => r.status === "running") ? 1 : 0);

  const groups: { title: string; items: { to: string; label: string; hint: string; count?: ReactNode }[] }[] = [
    {
      title: "People",
      items: [
        { to: "students", label: "Students", hint: "Roster, Excel upload", count: roster.data && fmtInt(roster.data.active) },
        { to: "instructors", label: "Instructors", hint: "Logins, assigned students", count: instructors.data && fmtInt(instructors.data.instructors.filter((i) => i.active).length) },
        { to: "admins", label: "Admins", hint: "Who manages the portal", count: admins.data && fmtInt(admins.data.filter((a) => a.active).length) },
      ],
    },
    {
      title: "Organisation",
      items: [{ to: "colleges", label: "Colleges", hint: "Managed by the super admin", count: colleges.data && fmtInt(colleges.data.colleges.length) }],
    },
    {
      title: "Contests",
      items: [
        {
          to: "scans",
          label: "Scans",
          hint: "Queue and history",
          count: busy ? (
            <span className="inline-flex items-center gap-1 text-accent-ink">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-accent" />
              {busy}
            </span>
          ) : undefined,
        },
        { to: "topics", label: "Topics", hint: "Question tags, nightly refresh" },
        { to: "top-k", label: "Top K students", hint: "Contest-wise, ranked among themselves" },
      ],
    },
  ];

  return (
    <nav aria-label="Admin sections" className="min-w-0 lg:sticky lg:top-24">
      {/* phones and tablets: every section visible at once, two (or three) to a row */}
      <div className="grid grid-cols-2 gap-1 rounded-xl bg-fg/[0.03] p-1 ring-1 ring-inset ring-fg/[0.06] sm:grid-cols-3 lg:hidden">
        {groups.flatMap((g) => g.items).map((it) => (
          <NavLink
            key={it.to}
            to={`/admin/${it.to}`}
            className={({ isActive }) =>
              cx(
                "ripple flex min-h-10 min-w-0 items-center gap-2 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors",
                isActive ? "bg-surface text-ink shadow-sm ring-1 ring-inset ring-fg/[0.08]" : "text-ink-2 hover:text-ink",
              )
            }
          >
            <svg aria-hidden viewBox="0 0 16 16" className="h-4 w-4">
              {ICONS[it.to]}
            </svg>
            <span className="truncate">{it.label}</span>
            {it.count != null && <span className="tabular ml-auto text-xs text-ink-3">{it.count}</span>}
          </NavLink>
        ))}
      </div>
      {/* desktop: a settings-style side menu on its own panel */}
      <div className="admin-menu hidden flex-col gap-1 rounded-2xl bg-surface p-2 ring-1 ring-inset ring-fg/[0.07] lg:flex">
        {groups.map((g, gi) => (
          <div key={g.title} className={cx(gi > 0 && "border-t border-fg/[0.06] pt-1")}>
            <div className="px-2.5 pb-1 pt-2.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink-3">{g.title}</div>
            <ul className="flex flex-col gap-0.5 pb-1">
              {g.items.map((it) => (
                <li key={it.to}>
                  <NavLink
                    to={`/admin/${it.to}`}
                    className={({ isActive }) =>
                      cx(
                        "ripple group relative flex items-center gap-3 rounded-xl px-2 py-1.5 transition-colors duration-150",
                        isActive ? "bg-accent-soft text-ink" : "text-ink-2 hover:bg-fg/[0.04] hover:text-ink",
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <span
                          className={cx(
                            "grid h-8 w-8 shrink-0 place-items-center rounded-lg transition-colors duration-150",
                            isActive ? "bg-btn-primary text-white shadow-[0_1px_2px_rgb(0_0_0/0.15)]" : "bg-fg/[0.05] text-ink-2 ring-1 ring-inset ring-fg/[0.05] group-hover:text-ink",
                          )}
                        >
                          <svg aria-hidden viewBox="0 0 16 16" className="h-4 w-4">
                            {ICONS[it.to]}
                          </svg>
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className={cx("block text-[13px]", isActive ? "font-semibold" : "font-medium")}>{it.label}</span>
                          <span className="block truncate text-[11.5px] text-ink-3">{it.hint}</span>
                        </span>
                        {it.count != null && (
                          <span
                            className={cx(
                              "tabular shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                              isActive ? "bg-surface text-accent-ink ring-1 ring-inset ring-accent/20" : "bg-fg/[0.05] text-ink-2",
                            )}
                          >
                            {it.count}
                          </span>
                        )}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}

function ScanCard() {
  const qc = useQueryClient();
  const runs = useQuery({ queryKey: ["scan-runs"], queryFn: api.scanRuns, refetchInterval: 15_000 });
  const requests = useQuery({ queryKey: ["scan-requests"], queryFn: api.scanRequests, refetchInterval: 15_000 });
  const [slug, setSlug] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const request = useMutation({
    mutationFn: (s: string) => api.requestScan(s),
    onSuccess: () => {
      setSlug("");
      setConfirming(null);
      qc.invalidateQueries({ queryKey: ["scan-requests"] });
      qc.invalidateQueries({ queryKey: ["contests"] });
    },
  });
  const pending = (requests.data ?? []).filter((r) => !r.handled_at);
  const scansOff = useMe().data?.scans_enabled === false;

  function submit(e: FormEvent) {
    e.preventDefault();
    request.reset();
    setConfirming(slug.trim().toLowerCase());
  }

  return (
    <Card>
      <CardHeader title="Scans" subtitle="A full scan takes about 10 minutes. The worker must be running to process requests." />
      {confirming && (
        <ScanConfirm
          slug={confirming}
          open
          pending={request.isPending}
          error={request.error}
          onClose={() => setConfirming(null)}
          onConfirm={() => request.mutate(confirming)}
        />
      )}
      {scansOff ? (
        <div className="border-y border-fg/5 px-5 py-3">
          <ScansOffNote />
        </div>
      ) : (
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3 border-y border-fg/5 bg-fg/[0.015] px-5 py-3">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Contest</span>
          <Input placeholder="weekly-contest-519" value={slug} onChange={(e) => setSlug(e.target.value)} required pattern="(weekly|biweekly)-contest-\d+" className="w-60" />
        </label>
        <Button type="submit" variant="primary" disabled={request.isPending}>
          Queue scan
        </Button>
        <p className="w-full text-xs text-ink-3">
          Use this to load past contests (backfill) or to re-run a failed scan. Contests past their final-scan time (11 pm on the 5th working day after the contest) give final results; newer ones give early results.
        </p>
        {request.isError && (
          <div className="w-full">
            <ErrorBox error={request.error} />
          </div>
        )}
      </form>
      )}

      {pending.length > 0 && (
        <div className="border-b border-fg/5 bg-accent-soft/40 px-5 py-2 text-xs text-ink-2">
          <span className="font-medium text-ink">Queued: </span>
          {pending.map((r) => (
            <span key={r.id} className="ml-2 inline-flex items-center gap-1 rounded-full bg-surface py-0.5 pl-2.5 pr-0.5 ring-1 ring-inset ring-fg/[0.08]">
              {slugTitle(r.contest_slug)}
              <span className="text-ink-3">
                ({kindLabel(r.kind)}, by {r.requested_by})
              </span>
              {runs.data?.some((x) => x.status === "running" && x.contest_slug === r.contest_slug) ? (
                <span className="px-1.5 text-ink-3">scanning</span>
              ) : (
                <CancelScanButton slug={r.contest_slug} requestedBy={r.requested_by} />
              )}
            </span>
          ))}
        </div>
      )}

      {runs.isPending ? (
        <div className="px-5">
          <RowsSkeleton />
        </div>
      ) : runs.isError ? (
        <div className="p-5">
          <ErrorBox error={runs.error} onRetry={() => runs.refetch()} />
        </div>
      ) : runs.data.length === 0 ? (
        <Empty>No scans yet.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="stack-table w-full text-sm">
            <thead className="text-left text-xs text-ink-2">
              <tr className="border-b border-fg/5">
                <th className="px-5 py-2 font-medium">Contest</th>
                <th className="px-3 py-2 font-medium">Kind</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Started</th>
                <th className="px-3 py-2 text-right font-medium">Participants</th>
                <th className="px-5 py-2 text-right font-medium">Students</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.id} className="border-b border-fg/5 align-top last:border-0">
                  <td className="stack-full px-5 py-2.5 font-medium">{slugTitle(r.contest_slug)}</td>
                  <td data-label="Kind" className="px-3 py-2.5 text-ink-2">{kindLabel(r.kind)}</td>
                  <td data-label="Status" className="px-3 py-2.5">
                    <Badge tone={RUN_STATUS[r.status][0]} icon={RUN_STATUS[r.status][1]}>
                      {RUN_STATUS[r.status][2]}
                    </Badge>
                    {r.error && <div className="mt-1 max-w-md text-xs text-ink-2">{r.error}</div>}
                    {r.status === "review" && (
                      <div className="mt-1 text-xs">
                        <Link to={`/contests/${r.contest_slug}`} className="text-accent-ink hover:underline">
                          {r.review_decision === "outdated" ? "Outdated: discard on the contest page" : "Review on the contest page"}
                        </Link>
                      </div>
                    )}
                    {r.review_decision && r.status !== "review" && r.review_decision !== "published" && (
                      <div className="mt-1 text-xs text-ink-3">{r.review_decision}{r.reviewed_by ? ` by ${r.reviewed_by}` : ""}</div>
                    )}
                    {r.review_decision === "published" && (
                      <div className="mt-1 text-xs text-ink-3">reviewed and added{r.reviewed_by ? ` by ${r.reviewed_by}` : ""}</div>
                    )}
                    {r.status === "running" && (
                      <div className="mt-1">
                        <CancelScanButton slug={r.contest_slug} running />
                      </div>
                    )}
                  </td>
                  <td data-label="Started" className="whitespace-nowrap px-3 py-2.5 text-ink-2">{fmtIso(r.started_at)}</td>
                  <td data-label="Participants" className="tabular px-3 py-2.5 text-right">{fmtInt(r.participants)}</td>
                  <td data-label="Students" className="tabular px-5 py-2.5 text-right">{fmtInt(r.students)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
