/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { type HandleStatus, type StudentSort } from "../api";
import { Card, CardHeader, Empty, ErrorBox, ExternalLink, HandleStatusBadge, Input, Select, cx, handleStatusLabel } from "../components/ui";
import { fmtIso } from "../format";
import { studentListQuery } from "../queries";
import { useDebounced } from "../useDebounced";
import { StudentsSkeleton } from "../components/skeletons";

const PAGE = 100;
type Sort = StudentSort;

/** Filtering, sorting and paging happen on the server: the browser gets the rows it
 *  shows, not all 1,500 students. */
export default function Students() {
  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim(), 250);
  const [college, setCollege] = useState("");
  const [handle, setHandle] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [sort, setSort] = useState<Sort>("name");
  const [limit, setLimit] = useState(PAGE);
  const students = useQuery({
    ...studentListQuery({ q: search, college, handle, includeRemoved: showInactive, sort, limit }),
    placeholderData: keepPreviousData,
  });
  const toggleSort = (key: "rating" | "attended") => setSort((s) => (s === `${key}_desc` ? `${key}_asc` : `${key}_desc`));

  if (students.isPending) return <StudentsSkeleton />;
  if (students.isError) return <ErrorBox error={students.error} onRetry={() => students.refetch()} />;

  const { rows, total, colleges, active: activeCount, handle_problems: handleProblems } = students.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">Students</h1>
        <p className="mt-1 text-[13px] text-ink-2">
          {activeCount.toLocaleString()} active students. Admins add and edit them on the Admin page.
          {handleProblems > 0 && ` ${handleProblems} have an invalid or missing LeetCode handle.`}
        </p>
      </div>
      <Card>
        <CardHeader title="All students" />
        <div className="flex flex-wrap items-center gap-2 border-y border-fg/5 bg-fg/[0.015] px-5 py-2 [&_label>span:first-child]:sr-only">
          <label className="flex min-w-56 flex-1 flex-col gap-1 sm:max-w-xs">
            <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Search</span>
            <Input type="search" placeholder="Name, roll no or handle" value={query} onChange={(e) => { setQuery(e.target.value); setLimit(PAGE); }} />
          </label>
          {colleges.length > 1 && (
            <Select label="College" value={college} onChange={(e) => setCollege(e.target.value)}>
              <option value="">Any college</option>
              {colleges.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </Select>
          )}
          <Select label="LeetCode handle" value={handle} onChange={(e) => setHandle(e.target.value)}>
            <option value="">Any handle status</option>
            {(["valid", "invalid", "missing", "unchecked"] as HandleStatus[]).map((h) => (
              <option key={h} value={h}>
                {handleStatusLabel(h)}
              </option>
            ))}
          </Select>
          <Select label="Sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="name">Sort: name A–Z</option>
            <option value="rating_desc">Rating: high → low</option>
            <option value="rating_asc">Rating: low → high</option>
            <option value="attended_desc">Contests attended: most → fewest</option>
            <option value="attended_asc">Contests attended: fewest → most</option>
          </Select>
          <label className="flex h-8 items-center gap-2 text-[13px] text-ink-2">
            <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} className="accent-accent" />
            Include removed students
          </label>
        </div>
        {total === 0 ? (
          <Empty>No students match these filters.</Empty>
        ) : (
          <div className={cx("overflow-x-auto transition-opacity", students.isPlaceholderData && "opacity-60")}>
            <table className="stack-table w-full text-sm">
              <thead className="text-left text-xs text-ink-2">
                <tr className="border-b border-fg/5">
                  <th className="px-5 py-2 font-medium">Student</th>
                  <th className="px-3 py-2 font-medium">Roll no</th>
                  <th className="px-3 py-2 font-medium">College</th>
                  <th className="px-3 py-2 font-medium">LeetCode</th>
                  <th className="px-3 py-2 font-medium">Handle</th>
                  <th
                    className="px-3 py-2 text-right font-medium"
                    aria-sort={sortDir(sort, "rating")}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort("rating")}
                      title="LeetCode contest rating (refreshed daily, and live when you open a student). Click to sort."
                      className={cx("inline-flex items-center gap-1 hover:text-ink", sort.startsWith("rating") && "text-ink")}
                    >
                      Rating
                      <SortArrow dir={sortDir(sort, "rating")} />
                    </button>
                  </th>
                  <th className="px-5 py-2 text-right font-medium" aria-sort={sortDir(sort, "attended")}>
                    <button
                      type="button"
                      onClick={() => toggleSort("attended")}
                      title="Contests the student took part in, out of those scanned. Click to sort."
                      className={cx("inline-flex items-center gap-1 hover:text-ink", sort.startsWith("attended") && "text-ink")}
                    >
                      Contests attended
                      <SortArrow dir={sortDir(sort, "attended")} />
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className="border-b border-fg/5 last:border-0 hover:bg-surface-2/60">
                    <td className="stack-full px-5 py-2.5">
                      <Link to={`/students/${s.id}`} className="font-medium hover:text-accent-ink hover:underline">
                        {s.name}
                      </Link>
                      {!s.active && <span className="ml-2 text-xs text-ink-3">(removed)</span>}
                    </td>
                    <td data-label="Roll no" className="tabular px-3 py-2.5 text-ink-2">{s.roll_no}</td>
                    <td data-label="College" className="px-3 py-2.5 text-ink-2">{s.college}</td>
                    <td data-label="LeetCode" className="px-3 py-2.5">
                      {s.leetcode_handle && s.handle_status !== "missing" ? (
                        <ExternalLink href={`https://leetcode.com/u/${encodeURIComponent(s.leetcode_handle)}/`}>{s.leetcode_handle}</ExternalLink>
                      ) : (
                        <span className="text-ink-3">{s.leetcode_handle || "—"}</span>
                      )}
                    </td>
                    <td data-label="Handle" className="px-3 py-2.5">
                      <HandleStatusBadge status={s.handle_status} />
                    </td>
                    <td data-label="Rating" className="px-3 py-2.5 text-right" title={s.rating_synced_at ? `From LeetCode, ${fmtIso(s.rating_synced_at)}` : "Not fetched yet"}>
                      {s.rating != null ? (
                        <>
                          <div className="tabular font-semibold text-ink">{s.rating.toLocaleString()}</div>
                          <div className="tabular text-[11px] text-ink-3">
                            {s.rating_top_pct != null ? `top ${s.rating_top_pct}%` : ""}
                            {s.rated_contests ? ` · ${s.rated_contests} ${s.rated_contests === 1 ? "contest" : "contests"}` : ""}
                          </div>
                        </>
                      ) : (
                        <span className="text-xs text-ink-3">{s.rating_synced_at ? "unrated" : "—"}</span>
                      )}
                    </td>
                    <td data-label="Attended" className="tabular px-5 py-2.5 text-right">
                      {s.contests_attended} <span className="text-ink-3">/ {s.contests_scanned}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-border px-5 py-3 text-[13px] text-ink-2">
          <span className="tabular">
            Showing {rows.length.toLocaleString()} of {total.toLocaleString()}
          </span>
          {total > limit && (
            <button className="font-medium text-accent-ink hover:underline" onClick={() => setLimit((l) => l + PAGE * 5)}>
              Show more
            </button>
          )}
        </div>
      </Card>
    </div>
  );
}

function sortDir(sort: Sort, key: "rating" | "attended"): "ascending" | "descending" | "none" {
  return sort === `${key}_desc` ? "descending" : sort === `${key}_asc` ? "ascending" : "none";
}

function SortArrow({ dir }: { dir: "ascending" | "descending" | "none" }) {
  return (
    <span aria-hidden className="w-2 text-[10px]">
      {dir === "descending" ? "▼" : dir === "ascending" ? "▲" : ""}
    </span>
  );
}
