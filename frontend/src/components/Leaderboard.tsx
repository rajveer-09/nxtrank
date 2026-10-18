/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { ContestResults, ResultRow, ResultStatus } from "../api";
import { fmtDuration, fmtInt } from "../format";
import { Badge, Button, Empty, Input, LeaderboardRank, Medal, ProfileRank, ResultStatusBadge, Select, cx, resultStatusLabel, scrollToTopOf } from "./ui";
import { Spacer, useReveal, useWindowRows } from "./virtual";

const STATUS_ORDER: ResultStatus[] = ["solved", "zero", "absent", "invalid_handle", "no_handle", "duplicate_handle"];
const MAX_FILTER_VALUES = 40;

/** Extra sheet columns (batch, section, ...) with few enough distinct values to filter on. */
const VIRTUAL_FROM = 100; // longer pages render only the rows near the screen
const ALL_ROWS = 100_000;

function filterableExtras(rows: ResultRow[]): [string, string[]][] {
  const values = new Map<string, Set<string>>();
  for (const r of rows)
    for (const [k, v] of Object.entries(r.extra)) {
      if (!v) continue;
      if (!values.has(k)) values.set(k, new Set());
      values.get(k)!.add(v);
    }
  return [...values.entries()]
    .filter(([, vs]) => vs.size >= 2 && vs.size <= MAX_FILTER_VALUES)
    .map(([k, vs]) => [k, [...vs].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))]);
}

/** `scoped`: the rows are one college or an instructor's students, so ranks (and medals)
 *  count within them; the portal-wide rank is shown underneath. */
export default function Leaderboard({ data, scoped = false }: { data: ContestResults; scoped?: boolean }) {
  const { labels, rows } = data;
  const rankInScope = useMemo(() => {
    const ranked = rows.filter((r) => r.college_rank != null).sort((a, b) => a.college_rank! - b.college_rank!);
    return new Map(ranked.map((r, i) => [r.student_id, i + 1]));
  }, [rows]);
  const [query, setQuery] = useState("");
  const [college, setCollege] = useState("");
  const [status, setStatus] = useState("");
  const [extraFilters, setExtraFilters] = useState<Record<string, string>>({});
  // the contest's order by default: best rank first, students who didn't take part last
  const [sorting, setSorting] = useState<SortingState>([{ id: "college_rank", desc: false }]);
  const root = useRef<HTMLDivElement>(null);

  const colleges = useMemo(() => [...new Set(rows.map((r) => r.college).filter(Boolean))].sort(), [rows]);
  const extras = useMemo(() => filterableExtras(rows), [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (!college || r.college === college) &&
        (!status ||
          (status === "participated" ? r.status === "solved" || r.status === "zero" : status === "flagged" ? !!r.flagged : r.status === status)) &&
        Object.entries(extraFilters).every(([k, v]) => !v || r.extra[k] === v) &&
        (!q ||
          r.name.toLowerCase().includes(q) ||
          (r.roll_no ?? "").toLowerCase().includes(q) ||
          r.leetcode_handle.toLowerCase().includes(q)),
    );
  }, [rows, query, college, status, extraFilters]);

  const columns = useMemo<ColumnDef<ResultRow>[]>(
    () => [
      {
        id: "college_rank",
        header: scoped ? "Rank" : "College rank",
        accessorFn: (r) => r.college_rank ?? undefined,
        sortUndefined: "last",
        // a tied rank goes to less total time (as on LeetCode), then the name
        sortingFn: (a, b) =>
          (a.original.college_rank ?? 0) - (b.original.college_rank ?? 0) ||
          (a.original.total_time_secs ?? Infinity) - (b.original.total_time_secs ?? Infinity) ||
          a.original.name.localeCompare(b.original.name),
        cell: ({ row }) => {
          const portal = row.original.college_rank;
          const rank = scoped ? rankInScope.get(row.original.student_id) : portal;
          if (rank == null) return <span className="text-ink-3">—</span>;
          return (
            <span className="inline-flex flex-col items-end">
              {rank <= 3 ? <Medal place={rank} /> : <span className="tabular font-semibold">{rank}</span>}
              {scoped && portal !== rank && <span className="tabular whitespace-nowrap text-[10px] text-ink-3" title="Rank among all students in the portal">#{portal} portal</span>}
            </span>
          );
        },
        meta: { align: "right" },
      },
      {
        id: "name",
        header: "Student",
        accessorFn: (r) => r.name.toLowerCase(),
        cell: ({ row }) => (
          <div className="min-w-40">
            <Link to={`/students/${row.original.student_id}`} className="font-medium text-ink hover:text-accent-ink hover:underline">
              {row.original.name}
            </Link>
            <div className="text-xs text-ink-3">
              {[row.original.roll_no, row.original.leetcode_handle].filter(Boolean).join(" · ")}
            </div>
          </div>
        ),
      },
      { id: "college", header: "College", accessorFn: (r) => r.college, cell: ({ getValue }) => <span className="text-ink-2">{getValue<string>()}</span> },
      {
        id: "global_rank",
        header: "Profile rank",
        accessorFn: (r) => r.global_rank ?? undefined,
        sortUndefined: "last",
        cell: ({ row }) => <ProfileRank rank={row.original.global_rank} official={row.original.rank_official} />,
        meta: { align: "right" },
      },
      {
        id: "leaderboard_rank",
        header: "Leaderboard rank",
        accessorFn: (r) => r.leaderboard_rank ?? undefined,
        sortUndefined: "last",
        cell: ({ row }) => <LeaderboardRank rank={row.original.leaderboard_rank} url={row.original.ranking_url} />,
        meta: { align: "right" },
      },
      {
        id: "solved",
        header: "Solved",
        accessorFn: (r) => r.solved ?? undefined,
        sortUndefined: "last",
        sortDescFirst: true,
        cell: ({ row }) =>
          row.original.solved == null ? (
            <span className="text-ink-3">—</span>
          ) : (
            <span className="tabular">
              {row.original.solved}
              <span className="text-ink-3">/{labels.length}</span>
            </span>
          ),
        meta: { align: "right" },
      },
      ...labels.map<ColumnDef<ResultRow>>((label) => ({
        id: label,
        header: label,
        accessorFn: (r) => r.problems[label]?.solve_secs,
        sortUndefined: "last",
        cell: ({ row }) => {
          const p = row.original.problems[label];
          if (!p)
            return (
              <span className="inline-grid grid-cols-[auto_1.5rem] gap-x-1 text-ink-3">
                <span className="text-right">—</span>
                <span />
              </span>
            );
          return (
            <span className="tabular whitespace-nowrap" title={`Accepted ${fmtDuration(p.solve_secs)} after the start${p.lang ? ` (${p.lang})` : ""}`}>
              <span className="inline-grid grid-cols-[auto_1.5rem] items-baseline gap-x-1">
                <span className="text-right">{fmtDuration(p.solve_secs)}</span>
                <span className="text-left text-xs text-ink-3" title={p.fail_count > 0 ? `${p.fail_count} wrong attempt(s), +5 min each` : undefined}>
                  {p.fail_count > 0 ? `+${p.fail_count}` : ""}
                </span>
              </span>
            </span>
          );
        },
        meta: { align: "right" },
      })),
      {
        id: "total_time",
        header: "Total time",
        accessorFn: (r) => r.total_time_secs ?? undefined,
        sortUndefined: "last",
        cell: ({ row }) =>
          row.original.total_time_secs == null ? (
            <span className="text-ink-3">—</span>
          ) : (
            <span className="tabular" title="LeetCode finish time, including 5 min per wrong attempt">
              {fmtDuration(row.original.total_time_secs)}
            </span>
          ),
        meta: { align: "right" },
      },
      {
        id: "status",
        header: "Status",
        accessorFn: (r) => STATUS_ORDER.indexOf(r.status),
        cell: ({ row }) => (
          <span className="inline-flex flex-col items-start gap-1">
            <ResultStatusBadge status={row.original.status} />
            {row.original.flagged && <FlaggedBadge row={row.original} />}
          </span>
        ),
      },
    ],
    [labels, scoped, rankInScope],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 50 } },
    autoResetPageIndex: true,
  });

  const { pageIndex, pageSize } = table.getState().pagination;
  const from = filtered.length === 0 ? 0 : pageIndex * pageSize + 1;
  const to = Math.min(filtered.length, (pageIndex + 1) * pageSize);
  const anyFilter = query || college || status || Object.values(extraFilters).some(Boolean);
  const pageRows = table.getRowModel().rows;
  const virtual = useWindowRows(pageRows.length, 49, pageRows.length > VIRTUAL_FROM);
  const virtualOn = pageRows.length > VIRTUAL_FROM;
  // (row, its position on this page): every row, or just those near the screen
  // short pages appear in steps of 12 rows, one frame each (no single long task)
  const revealed = useReveal(pageRows.length, 12, `${pageIndex}/${pageSize}/${JSON.stringify(sorting)}`);
  const shown = virtualOn
    ? virtual.items.map((v) => ({ row: pageRows[v.index], i: v.index }))
    : pageRows.slice(0, revealed).map((row, i) => ({ row, i }));
  const firstIndex = pageIndex * pageSize;

  return (
    <div ref={root} className="scroll-mt-20">
      {/* filters: one row above the table */}
      <div className="flex flex-wrap items-center gap-2 border-y border-fg/5 bg-fg/[0.015] px-5 py-2 [&_label>span:first-child]:sr-only">
        <label className="flex min-w-56 flex-1 flex-col gap-1 sm:max-w-xs">
          <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Search</span>
          <Input type="search" placeholder="Name, roll no or handle" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        {colleges.length > 1 && (
          <Select label="College" value={college} onChange={(e) => setCollege(e.target.value)}>
            <option value="">Any college</option>
            {colleges.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        )}
        {extras.map(([key, values]) => (
          <Select
            key={key}
            label={key}
            value={extraFilters[key] ?? ""}
            onChange={(e) => setExtraFilters((f) => ({ ...f, [key]: e.target.value }))}
          >
            <option value="">Any {key.toLowerCase()}</option>
            {values.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </Select>
        ))}
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          <option value="participated">Participated</option>
          {rows.some((r) => r.flagged) && <option value="flagged">Flagged by LeetCode</option>}
          {STATUS_ORDER.filter((s) => rows.some((r) => r.status === s)).map((s) => (
            <option key={s} value={s}>
              {resultStatusLabel(s)}
            </option>
          ))}
        </Select>
        {anyFilter && (
          <Button
            variant="ghost"
            onClick={() => {
              setQuery("");
              setCollege("");
              setStatus("");
              setExtraFilters({});
            }}
          >
            Clear filters
          </Button>
        )}
      </div>

      {filtered.length === 0 ? (
        <Empty>No students match these filters.</Empty>
      ) : (
        <div className="overflow-x-auto">
          {/* phones: the headers are hidden (rows become cards), so sorting is a menu */}
          <div className="flex items-center gap-2 border-b border-fg/5 px-4 py-2 sm:hidden">
            <Select
              label="Sort"
              value={sorting[0] ? `${sorting[0].id}:${sorting[0].desc ? "desc" : "asc"}` : "college_rank:asc"}
              onChange={(e) => {
                const [id, dir] = e.target.value.split(":");
                setSorting([{ id, desc: dir === "desc" }]);
              }}
            >
              {table.getAllLeafColumns().filter((c) => c.getCanSort() && typeof c.columnDef.header === "string").flatMap((c) => [
                <option key={`${c.id}:asc`} value={`${c.id}:asc`}>{`${c.columnDef.header as string} ↑`}</option>,
                <option key={`${c.id}:desc`} value={`${c.id}:desc`}>{`${c.columnDef.header as string} ↓`}</option>,
              ])}
            </Select>
          </div>
          <table className="stack-table w-full text-sm" aria-rowcount={filtered.length + 1}>
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-fg/5 text-xs text-ink-2">
                  {hg.headers.map((h) => {
                    const right = (h.column.columnDef.meta as { align?: string } | undefined)?.align === "right";
                    const sorted = h.column.getIsSorted();
                    return (
                      <th
                        key={h.id}
                        className={cx("whitespace-nowrap px-3 py-2.5 font-medium first:pl-5 last:pr-5", right ? "text-right" : "text-left")}
                        aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                      >
                        <button
                          type="button"
                          onClick={h.column.getToggleSortingHandler()}
                          className={cx("inline-flex items-center gap-1 hover:text-ink", sorted && "text-ink")}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          <span aria-hidden className="w-2 text-[10px]">
                            {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : ""}
                          </span>
                        </button>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody ref={virtual.anchor}>
              {virtualOn && <Spacer height={virtual.before} cols={columns.length} />}
              {shown.map(({ row, i }) => (
                <tr
                  key={row.id}
                  ref={virtualOn ? virtual.measure : undefined}
                  data-index={i}
                  aria-rowindex={firstIndex + i + 2}
                  className="border-b border-fg/5 last:border-0 hover:bg-surface-2/60"
                >
                  {row.getVisibleCells().map((cell) => {
                    const right = (cell.column.columnDef.meta as { align?: string } | undefined)?.align === "right";
                    return (
                      <td
                        key={cell.id}
                        data-label={cell.column.id === "name" || typeof cell.column.columnDef.header !== "string" ? undefined : cell.column.columnDef.header}
                        className={cx("px-3 py-2.5 first:pl-5 last:pr-5", right && "text-right", cell.column.id === "name" && "stack-full stack-first")}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {virtualOn && <Spacer height={virtual.after} cols={columns.length} />}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3 text-[13px] text-ink-2">
        <span className="tabular">
          {from}–{to} of {fmtInt(filtered.length)}
          {filtered.length !== rows.length && ` (filtered from ${fmtInt(rows.length)})`}
        </span>
        <div className="flex items-center gap-2">
          <Select label="Rows per page" hideLabel value={pageSize} onChange={(e) => table.setPageSize(Number(e.target.value))}>
            {[25, 50, 100, 500].map((n) => (
              <option key={n} value={n}>
                {n} / page
              </option>
            ))}
            <option value={ALL_ROWS}>All rows</option>
          </Select>
          <Button onClick={() => { table.previousPage(); scrollToTopOf(root.current); }} disabled={!table.getCanPreviousPage()}>
            Previous
          </Button>
          <Button onClick={() => { table.nextPage(); scrollToTopOf(root.current); }} disabled={!table.getCanNextPage()}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

/** What LeetCode did to an entry after the contest, in words. */
export function flaggedText(r: ResultRow): string {
  const f = r.flagged;
  if (!f) return "";
  const before = `${f.early_rank ? `rank ${f.early_rank.toLocaleString()} with ` : ""}${f.early_score ?? 0} pts on the early results`;
  const after =
    r.status !== "solved" && r.status !== "zero"
      ? "removed from the final leaderboard"
      : (r.score ?? 0) === 0
        ? "score set to 0 on the final leaderboard"
        : `moved to rank ${r.global_rank?.toLocaleString()} on the final leaderboard`;
  return `${before}; ${after}`;
}

function FlaggedBadge({ row }: { row: ResultRow }) {
  return (
    <span title={`${flaggedText(row)}. LeetCode does this to entries it finds breaking contest rules; it doesn't publish the reason.`}>
      <Badge tone="critical" icon="alert">Flagged by LeetCode</Badge>
    </span>
  );
}
