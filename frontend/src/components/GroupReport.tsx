/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 23 November 2026
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, groupsApi, type GroupContest, type GroupReport, type GroupStudent } from "../api";
import { fmtDate, fmtDecimal, fmtDuration, fmtInt, fmtPct } from "../format";
import { RowsSkeleton } from "./skeletons";
import { Card, CardHeader, Empty, ErrorBox, Input, LinkButton, Medal, ResultStatusBadge, Select, Stat, cx } from "./ui";

const DEFAULT = { key: "Group", value: "Top K" };
const WINDOWS = [5, 10, 20] as const;

/** Admin → Top K: a group of students (a sheet column's value, Group = Top K by default),
 *  contest by contest and ranked among themselves. */
export default function GroupReportCard() {
  const [group, setGroup] = useState(DEFAULT);
  const [last, setLast] = useState<number | null>(10);
  const [view, setView] = useState<string>("overall"); // "overall" or a contest slug
  const report = useQuery({
    queryKey: ["group-report", group.key, group.value, last],
    queryFn: () => groupsApi.report({ ...group, last }),
    placeholderData: keepPreviousData,
  });

  const data = report.data;
  const contest = data?.contests.find((c) => c.slug === view);
  const keys = data?.options ?? [];
  const values = keys.find((o) => o.key === group.key)?.values ?? [group.value];

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader
          title={`${group.value} students`}
          subtitle={`Students whose ${group.key} is "${group.value}": how they did in each contest, and their rank among themselves. Overall rank = most LeetCode contest points over the contests shown (ties: less total time), as in Analytics.`}
          actions={
            <>
              {keys.length > 0 && (
                <Select
                  label="Column"
                  value={group.key}
                  onChange={(e) => {
                    const key = e.target.value;
                    const first = keys.find((o) => o.key === key)?.values[0] ?? "";
                    setGroup({ key, value: key === DEFAULT.key ? DEFAULT.value : first });
                    setView("overall");
                  }}
                >
                  {keys.map((o) => (
                    <option key={o.key}>{o.key}</option>
                  ))}
                </Select>
              )}
              <Select
                label="Value"
                value={group.value}
                onChange={(e) => {
                  setGroup((g) => ({ ...g, value: e.target.value }));
                  setView("overall");
                }}
              >
                {values.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </Select>
              <Select label="Contests" value={last ?? ""} onChange={(e) => setLast(e.target.value ? Number(e.target.value) : null)}>
                {WINDOWS.map((n) => (
                  <option key={n} value={n}>
                    Last {n}
                  </option>
                ))}
                <option value="">All scanned</option>
              </Select>
            </>
          }
        />
        {report.isPending ? (
          <div className="px-5 pb-5">
            <RowsSkeleton rows={4} cols={4} label="Loading the group…" />
          </div>
        ) : report.isError ? (
          <div className="p-5">
            <ErrorBox error={report.error} onRetry={() => report.refetch()} />
          </div>
        ) : data && data.students.length === 0 ? (
          <Empty>
            No active student has {group.key} = "{group.value}". Add the column to the roster (Students → Upload Excel) to make a group.
          </Empty>
        ) : (
          data && <Summary data={data} loading={report.isPlaceholderData} />
        )}
      </Card>

      {data && data.students.length > 0 && (
        <>
          <ContestTable data={data} onPick={setView} picked={view} />
          <Card>
            <CardHeader
              title={contest ? `Ranking in ${contest.title}` : "Overall ranking"}
              subtitle={
                contest
                  ? `Rank = place among the ${group.value} students who took part, in the contest's order (portal rank underneath).`
                  : `Rank over the ${data.contests.length} contest${data.contests.length === 1 ? "" : "s"} shown; each contest column is the rank in the group that contest, with problems solved.`
              }
              actions={
                <Select label="Ranking" value={view} onChange={(e) => setView(e.target.value)}>
                  <option value="overall">Overall</option>
                  {data.contests.map((c) => (
                    <option key={c.slug} value={c.slug}>
                      {c.title}
                    </option>
                  ))}
                </Select>
              }
            />
            {contest ? <ContestRanking data={data} contest={contest} /> : <OverallRanking data={data} />}
          </Card>
        </>
      )}
    </div>
  );
}

function Summary({ data, loading }: { data: GroupReport; loading: boolean }) {
  const latest = data.contests[0];
  const ranked = data.students.filter((s) => s.rank != null).length;
  return (
    <div className={cx("kpi-row grid grid-cols-2 gap-2 px-5 pb-5 transition-opacity md:grid-cols-4", loading && "opacity-60")}>
      <Stat label="Students" value={fmtInt(data.students.length)} sub={`${fmtInt(ranked)} scored in these contests`} />
      <Stat
        label="Took part, latest"
        value={latest ? `${fmtInt(latest.participated)} / ${fmtInt(latest.students)}` : "—"}
        sub={latest ? `${fmtPct(latest.participation_rate)} · ${latest.title}` : "no contest scanned"}
      />
      <Stat
        label="Avg solved, latest"
        value={fmtDecimal(latest?.avg_solved) || "—"}
        sub={latest ? `of ${latest.questions} problems` : undefined}
      />
      <Stat label="Best profile rank, latest" value={fmtInt(latest?.best_global_rank) || "—"} sub={latest?.top[0]?.name} />
    </div>
  );
}

function ContestTable({ data, onPick, picked }: { data: GroupReport; onPick: (slug: string) => void; picked: string }) {
  return (
    <Card>
      <CardHeader
        title="Contest by contest"
        subtitle={`Newest first. Pick a contest to rank the group in it; the download is that contest's Excel for only these students, with their rank among themselves.`}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-ink-2">
            <tr className="border-b border-fg/5">
              <th className="px-5 py-2 font-medium">Contest</th>
              <th className="px-3 py-2 text-right font-medium">Took part</th>
              <th className="px-3 py-2 text-right font-medium">Avg solved</th>
              <th className="px-3 py-2 text-right font-medium">Solved all</th>
              <th className="px-3 py-2 text-right font-medium">Best profile rank</th>
              <th className="px-3 py-2 font-medium">Top 3 in the group</th>
              <th className="px-5 py-2 text-right font-medium">Download</th>
            </tr>
          </thead>
          <tbody>
            {data.contests.map((c) => (
              <tr key={c.slug} className={cx("border-b border-fg/5 last:border-0", picked === c.slug && "bg-accent-soft/50")}>
                <td className="px-5 py-2.5">
                  <button
                    type="button"
                    onClick={() => onPick(c.slug)}
                    className="text-left font-medium text-ink hover:text-accent-ink hover:underline"
                  >
                    {c.title}
                  </button>
                  <div className="text-xs text-ink-3">
                    {fmtDate(c.start_time)} ·{" "}
                    <Link to={`/contests/${c.slug}`} className="hover:text-ink hover:underline">
                      contest page
                    </Link>
                  </div>
                </td>
                <td className="tabular px-3 py-2.5 text-right">
                  {fmtInt(c.participated)} / {fmtInt(c.students)} <span className="text-ink-3">{fmtPct(c.participation_rate)}</span>
                </td>
                <td className="tabular px-3 py-2.5 text-right">{fmtDecimal(c.avg_solved) || "—"}</td>
                <td className="tabular px-3 py-2.5 text-right">{fmtInt(c.solved_all)}</td>
                <td className="tabular px-3 py-2.5 text-right">{fmtInt(c.best_global_rank) || "—"}</td>
                <td className="px-3 py-2.5">
                  {c.top.length ? (
                    <ol className="flex flex-col gap-0.5">
                      {c.top.map((t, i) => (
                        <li key={t.id} className="flex items-center gap-1.5 text-[13px]">
                          <Medal place={i + 1} size="sm" />
                          <Link to={`/students/${t.id}`} className="truncate hover:text-accent-ink hover:underline">
                            {t.name}
                          </Link>
                          <span className="tabular text-xs text-ink-3">
                            {t.solved}/{c.questions} · #{fmtInt(t.global_rank)}
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <span className="text-ink-3">nobody took part</span>
                  )}
                </td>
                <td className="px-5 py-2.5 text-right">
                  <LinkButton href={api.exportUrl(c.slug, "xlsx", { extra: { [data.key]: data.value } })} download>
                    Excel
                  </LinkButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function useSearch(students: GroupStudent[]) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const n = q.trim().toLowerCase();
    if (!n) return students;
    return students.filter((s) =>
      [s.name, s.roll_no, s.handle, s.college, ...Object.values(s.extra)].some((v) => (v ?? "").toLowerCase().includes(n)),
    );
  }, [students, q]);
  const box = (
    <div className="border-y border-fg/5 bg-fg/[0.015] px-5 py-2">
      <Input
        type="search"
        aria-label="Search"
        placeholder="Name, roll no, handle, section…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="w-full sm:max-w-xs"
      />
    </div>
  );
  return { shown, box };
}

/** The columns worth showing next to a name: Section and Hall (not the group column itself). */
function sideColumns(data: GroupReport): string[] {
  const keys = new Set(data.students.flatMap((s) => Object.keys(s.extra)));
  return ["Section", "Hall"].filter((k) => k !== data.key && keys.has(k));
}

function StudentCell({ s }: { s: GroupStudent }) {
  return (
    <div className="min-w-44">
      <Link to={`/students/${s.id}`} className="font-medium text-ink hover:text-accent-ink hover:underline">
        {s.name}
      </Link>
      <div className="text-xs text-ink-3">{[s.roll_no, s.handle].filter(Boolean).join(" · ")}</div>
    </div>
  );
}

function OverallRanking({ data }: { data: GroupReport }) {
  const { shown, box } = useSearch(data.students);
  const side = sideColumns(data);
  return (
    <>
      {box}
      {shown.length === 0 ? (
        <Empty>No students match.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-2">
              <tr className="border-b border-fg/5">
                <th className="px-5 py-2 text-right font-medium">Rank</th>
                <th className="px-3 py-2 font-medium">Student</th>
                <th className="px-3 py-2 font-medium">College</th>
                {side.map((k) => (
                  <th key={k} className="px-3 py-2 font-medium">
                    {k}
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-medium">Points</th>
                <th className="px-3 py-2 text-right font-medium">Attended</th>
                <th className="px-3 py-2 text-right font-medium">Avg solved</th>
                <th className="px-3 py-2 text-right font-medium">Avg group rank</th>
                <th className="px-3 py-2 text-right font-medium">Best profile rank</th>
                {data.contests.map((c) => (
                  <th key={c.slug} className="whitespace-nowrap px-3 py-2 text-right font-medium last:pr-5" title={c.title}>
                    {shortTitle(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((s) => (
                <tr key={s.id} className="border-b border-fg/5 last:border-0 hover:bg-surface-2/60">
                  <td className="px-5 py-2.5 text-right">
                    {s.rank != null && s.rank <= 3 ? (
                      <Medal place={s.rank} />
                    ) : (
                      <span className="tabular font-semibold">{s.rank ?? "—"}</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <StudentCell s={s} />
                  </td>
                  <td className="px-3 py-2.5 text-ink-2">{shortCollege(s.college)}</td>
                  {side.map((k) => (
                    <td key={k} className="whitespace-nowrap px-3 py-2.5 text-ink-2">
                      {s.extra[k] || "—"}
                    </td>
                  ))}
                  <td className="tabular px-3 py-2.5 text-right font-medium">{fmtInt(s.points)}</td>
                  <td className="tabular px-3 py-2.5 text-right">
                    {s.attended}
                    <span className="text-ink-3">/{data.contests.length}</span>
                  </td>
                  <td className="tabular px-3 py-2.5 text-right">{fmtDecimal(s.avg_solved) || "—"}</td>
                  <td className="tabular px-3 py-2.5 text-right">{fmtDecimal(s.avg_group_rank) || "—"}</td>
                  <td className="tabular px-3 py-2.5 text-right">{fmtInt(s.best_global_rank) || "—"}</td>
                  {data.contests.map((c) => {
                    const r = s.results[c.slug];
                    return (
                      <td key={c.slug} className="tabular whitespace-nowrap px-3 py-2.5 text-right last:pr-5">
                        {r?.rank != null ? (
                          <span
                            title={`${c.title}: #${r.rank} in the group, ${r.solved}/${c.questions} solved, profile rank ${fmtInt(r.global_rank)}`}
                          >
                            <span className="font-medium">#{r.rank}</span>
                            <span className="ml-1 text-xs text-ink-3">
                              {r.solved}/{c.questions}
                            </span>
                          </span>
                        ) : (
                          <span className="text-ink-3" title={r ? r.status.replace("_", " ") : "no result"}>
                            —
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function ContestRanking({ data, contest }: { data: GroupReport; contest: GroupContest }) {
  // the contest's order: ranked students first, then those who didn't take part
  const ordered = useMemo(
    () =>
      [...data.students].sort((a, b) => {
        const ra = a.results[contest.slug]?.rank ?? Infinity;
        const rb = b.results[contest.slug]?.rank ?? Infinity;
        return ra - rb || a.name.localeCompare(b.name);
      }),
    [data.students, contest.slug],
  );
  const { shown, box } = useSearch(ordered);
  const side = sideColumns(data);
  return (
    <>
      {box}
      {shown.length === 0 ? (
        <Empty>No students match.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-2">
              <tr className="border-b border-fg/5">
                <th className="px-5 py-2 text-right font-medium">Rank</th>
                <th className="px-3 py-2 font-medium">Student</th>
                <th className="px-3 py-2 font-medium">College</th>
                {side.map((k) => (
                  <th key={k} className="px-3 py-2 font-medium">
                    {k}
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-medium">Solved</th>
                <th className="px-3 py-2 text-right font-medium">Profile rank</th>
                <th className="px-3 py-2 text-right font-medium">Total time</th>
                <th className="px-5 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((s) => {
                const r = s.results[contest.slug];
                return (
                  <tr key={s.id} className="border-b border-fg/5 last:border-0 hover:bg-surface-2/60">
                    <td className="px-5 py-2.5 text-right">
                      {r?.rank != null ? (
                        <span className="inline-flex flex-col items-end">
                          {r.rank <= 3 ? <Medal place={r.rank} /> : <span className="tabular font-semibold">{r.rank}</span>}
                          {r.college_rank != null && (
                            <span
                              className="tabular whitespace-nowrap text-[10px] text-ink-3"
                              title="Rank among all students in the portal"
                            >
                              #{r.college_rank} portal
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-ink-3">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <StudentCell s={s} />
                    </td>
                    <td className="px-3 py-2.5 text-ink-2">{shortCollege(s.college)}</td>
                    {side.map((k) => (
                      <td key={k} className="whitespace-nowrap px-3 py-2.5 text-ink-2">
                        {s.extra[k] || "—"}
                      </td>
                    ))}
                    <td className="tabular px-3 py-2.5 text-right">
                      {r?.solved != null ? (
                        <>
                          {r.solved}
                          <span className="text-ink-3">/{contest.questions}</span>
                        </>
                      ) : (
                        <span className="text-ink-3">—</span>
                      )}
                    </td>
                    <td className="tabular px-3 py-2.5 text-right">{fmtInt(r?.global_rank) || "—"}</td>
                    <td className="tabular px-3 py-2.5 text-right">{r?.total_time_secs != null ? fmtDuration(r.total_time_secs) : "—"}</td>
                    <td className="px-5 py-2.5">
                      {r ? <ResultStatusBadge status={r.status} /> : <span className="text-xs text-ink-3">added after this contest</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/** "Weekly Contest 529" -> "W529", "Biweekly Contest 196" -> "BW196" (column headers). */
function shortTitle(c: GroupContest): string {
  const m = c.slug.match(/^(weekly|biweekly)-contest-(\d+)$/);
  return m ? `${m[1] === "weekly" ? "W" : "BW"}${m[2]}` : c.title;
}

/** "BITS — BITS Pilani (Hyderabad Campus)" -> "BITS" */
function shortCollege(name: string): string {
  return name.split(/\s+[—–-]\s+/)[0] || "—";
}
