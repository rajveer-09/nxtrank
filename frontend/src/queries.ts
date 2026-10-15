/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
import { queryOptions, type QueryClient } from "@tanstack/react-query";
import {
  analyticsApi,
  api,
  rosterApi,
  type AnalyticsFilters,
  type ContestQuery,
  type ContestScope,
  type Role,
  type RosterShow,
  type StudentListQuery,
  type StudentsPageQuery,
} from "./api";
import { pages } from "./routes";

/** Every page's queries, shared by the page and the prefetcher (same keys).
 *  SETTLED (5 min): data that only changes with a scan or an admin edit; lists showing
 *  scan progress keep the 60 s default. */
export const SETTLED = 5 * 60_000;

export const DEFAULT_CONTESTS: ContestQuery = { show: "all", type: "", q: "", page: 1, per_page: 25 };
export const DEFAULT_ANALYTICS: AnalyticsFilters = { last: 10, extra: {} };
export const DEFAULT_STUDENTS_PAGE: StudentsPageQuery = { q: "", sort: "portal_rank", desc: false, offset: 0, limit: 50 };
export const DEFAULT_STUDENT_LIST: StudentListQuery = {
  q: "", college: "", handle: "", includeRemoved: false, sort: "name", limit: 100,
};
export const ROSTER_PAGE = 25;

export const contestsQuery = (q: ContestQuery) =>
  queryOptions({ queryKey: ["contests", q], queryFn: () => api.contests(q) });

export const contestQuery = (slug: string, scope: ContestScope) =>
  queryOptions({ queryKey: ["contest", slug, scope], queryFn: () => api.contest(slug, scope) });

/** Keyed by when the contest was last scanned: a new scan is a new key. */
export const resultsQuery = (slug: string, scannedAt: string | null | undefined, scope: ContestScope) =>
  queryOptions({ queryKey: ["results", slug, scannedAt, scope], queryFn: () => api.results(slug, scope), staleTime: SETTLED });

export const studentQuery = (id: number) =>
  queryOptions({ queryKey: ["student", id], queryFn: () => api.student(id), staleTime: SETTLED });

export const studentAnalyticsQuery = (id: number) =>
  queryOptions({ queryKey: ["student-analytics", id], queryFn: () => analyticsApi.student(id), staleTime: SETTLED });

export const studentListQuery = (f: StudentListQuery) =>
  queryOptions({
    queryKey: ["students", { search: f.q, college: f.college, handle: f.handle, showInactive: f.includeRemoved, sort: f.sort, limit: f.limit }],
    queryFn: () => api.students(f),
    staleTime: SETTLED,
  });

export const rosterQuery = (q: string, show: RosterShow, page: number) =>
  queryOptions({
    queryKey: ["roster", { search: q, show, page }],
    queryFn: () => rosterApi.list({ q, show, offset: page * ROSTER_PAGE, limit: ROSTER_PAGE }),
  });

/** The analytics pages: the portal's, or an instructor's own ("me"). */
export function analyticsQueries(kind: "portal" | "me") {
  const base = kind === "portal" ? ["analytics"] : ["instructor-analytics", "me"];
  return {
    base,
    overview: (f: AnalyticsFilters) =>
      queryOptions({
        queryKey: [...base, f],
        queryFn: () => (kind === "portal" ? analyticsApi.overview(f) : analyticsApi.instructor(f)),
        staleTime: SETTLED,
      }),
    students: (f: AnalyticsFilters, page: StudentsPageQuery) =>
      queryOptions({
        queryKey: [...base, "students", f, page],
        queryFn: () => (kind === "portal" ? analyticsApi.students(f, page) : analyticsApi.instructorStudents(f, page)),
        staleTime: SETTLED,
      }),
  };
}

/** Start loading a page's code and data, e.g. when the pointer heads for a link to it.
 *  Fresh data isn't fetched again; anything in flight is shared with the page. */
export function prefetchPath(qc: QueryClient, href: string, role: Role | undefined) {
  const url = new URL(href, window.location.origin);
  if (url.origin !== window.location.origin) return;
  const path = url.pathname;
  const get = (o: { queryKey: readonly unknown[]; queryFn?: unknown }) => void qc.prefetchQuery(o as never);
  let m: RegExpMatchArray | null;

  if (path === "/") {
    void pages.Contests.preload();
    get(contestsQuery(DEFAULT_CONTESTS));
  } else if ((m = path.match(/^\/contests\/([\w-]+)$/))) {
    const slug = m[1];
    const scope: ContestScope = role === "instructor" ? "mine" : "all";
    void pages.ContestPage.preload();
    void qc.prefetchQuery(contestQuery(slug, scope)).then(() => {
      const c = qc.getQueryData(contestQuery(slug, scope).queryKey);
      if (c?.status.has_data) get(resultsQuery(slug, c.status.scanned_at, scope));
    });
  } else if ((m = path.match(/^\/students\/(\d+)$/))) {
    const id = Number(m[1]);
    void pages.StudentPage.preload();
    get(studentQuery(id));
    get(studentAnalyticsQuery(id));
  } else if (path === "/students") {
    void pages.Students.preload();
    get(studentListQuery(DEFAULT_STUDENT_LIST));
  } else if (path === "/analytics") {
    void pages.Analytics.preload();
    const a = analyticsQueries("portal");
    get(a.overview(DEFAULT_ANALYTICS));
    get(a.students(DEFAULT_ANALYTICS, DEFAULT_STUDENTS_PAGE));
  } else if (path === "/my-students") {
    void pages.MyStudents.preload();
    if (role === "instructor" && !url.search) {
      const a = analyticsQueries("me");
      get(a.overview(DEFAULT_ANALYTICS));
      get(a.students(DEFAULT_ANALYTICS, DEFAULT_STUDENTS_PAGE));
    }
  } else if (path.startsWith("/admin") && role === "admin") {
    void pages.Admin.preload();
    if (path === "/admin" || path === "/admin/students") get(rosterQuery("", "active", 0));
  }
}
