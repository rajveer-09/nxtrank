/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import StudentAnalyticsSection from "../components/StudentAnalytics";
import { Card, CardHeader, Empty, ErrorBox, ExternalLink, HandleStatusBadge, LeaderboardRank, ProfileRank, ResultStatusBadge } from "../components/ui";
import { fmtDate, fmtDuration } from "../format";
import { studentQuery } from "../queries";
import { StudentSkeleton } from "../components/skeletons";

export default function StudentPage() {
  const id = Number(useParams().id);
  const student = useQuery({ ...studentQuery(id), enabled: Number.isFinite(id) });

  if (student.isPending) return <StudentSkeleton />;
  if (student.isError) return <ErrorBox error={student.error} onRetry={() => student.refetch()} />;
  const s = student.data;
  const labels = [...new Set(s.history.flatMap((h) => h.questions))].sort();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/students" className="text-[13px] text-ink-2 hover:text-ink">
          ← Students
        </Link>
        <h1 className="mt-1 text-xl font-semibold tracking-tight text-ink">
          {s.name}
          {!s.active && <span className="ml-2 align-middle text-[13px] font-normal text-ink-3">(removed from the sheet)</span>}
        </h1>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-ink-2">
          <span>Roll no {s.roll_no}</span>
          {s.college && <span>{s.college}</span>}
          {Object.entries(s.extra)
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <span key={k}>
                {k}: {v}
              </span>
            ))}
          <span className="inline-flex items-center gap-2">
            {s.leetcode_url ? <ExternalLink href={s.leetcode_url}>{s.leetcode_handle}</ExternalLink> : s.leetcode_handle || "no handle"}
            <HandleStatusBadge status={s.handle_status} />
          </span>
        </div>
      </div>

      <StudentAnalyticsSection id={s.id} />

      <Card>
        <CardHeader title="Contest history" subtitle="Newest first. Profile rank is the rank on the student's LeetCode profile; click a leaderboard rank to open that page of the contest leaderboard." />
        {s.history.length === 0 ? (
          <Empty>No scanned contests yet.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-ink-2">
                <tr className="border-b border-fg/5">
                  <th className="px-5 py-2 text-left font-medium">Contest</th>
                  <th className="px-3 py-2 text-left font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium" title="Rank on the student's LeetCode profile">Profile rank</th>
                  <th className="px-3 py-2 text-right font-medium" title="Position on the contest's Global leaderboard">Leaderboard rank</th>
                  <th className="px-3 py-2 text-right font-medium">College rank</th>
                  <th className="px-3 py-2 text-right font-medium">Solved</th>
                  {labels.map((l) => (
                    <th key={l} className="px-3 py-2 text-right font-medium">
                      {l}
                    </th>
                  ))}
                  <th className="px-5 py-2 text-right font-medium">Total time</th>
                </tr>
              </thead>
              <tbody>
                {s.history.map((h) => (
                  <tr key={h.contest_slug} className="border-b border-fg/5 last:border-0 hover:bg-surface-2/60">
                    <td className="px-5 py-2.5">
                      <Link to={`/contests/${h.contest_slug}`} className="font-medium hover:text-accent-ink hover:underline">
                        {h.contest_title}
                      </Link>
                      <div className="text-xs text-ink-3">{fmtDate(h.start_time)}</div>
                    </td>
                    <td className="px-3 py-2.5">
                      <ResultStatusBadge status={h.status} />
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <ProfileRank rank={h.global_rank} official={h.rank_official} />
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <LeaderboardRank rank={h.leaderboard_rank} url={h.ranking_url} />
                    </td>
                    <td className="tabular px-3 py-2.5 text-right font-semibold">{h.college_rank ?? <span className="font-normal text-ink-3">—</span>}</td>
                    <td className="tabular px-3 py-2.5 text-right">
                      {h.solved == null ? <span className="text-ink-3">—</span> : `${h.solved}/${h.questions.length}`}
                    </td>
                    {labels.map((l) => {
                      const p = h.problems[l];
                      return (
                        <td key={l} className="tabular whitespace-nowrap px-3 py-2.5 text-right">
                          {p ? (
                            <span className="inline-grid grid-cols-[auto_1.5rem] items-baseline gap-x-1">
                              <span className="text-right">{fmtDuration(p.solve_secs)}</span>
                              <span className="text-left text-xs text-ink-3">{p.fail_count > 0 ? `+${p.fail_count}` : ""}</span>
                            </span>
                          ) : (
                            <span className="inline-grid grid-cols-[auto_1.5rem] gap-x-1 text-ink-3">
                              <span className="text-right">—</span>
                              <span />
                            </span>
                          )}
                        </td>
                      );
                    })}
                    <td className="tabular px-5 py-2.5 text-right">{fmtDuration(h.total_time_secs) || <span className="text-ink-3">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
