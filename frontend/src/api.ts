/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
// Typed client for the backend API (same origin; session cookie auth).

export class ApiError extends Error {
  constructor(
    /** HTTP status; 0 when the request never reached the server */
    public status: number,
    message: string,
    /** the server's stable error name ("not_found", "leetcode_blocked", "network", …) */
    public code: string = "error",
    /** quote this to find the server's log line for the request */
    public requestId: string | null = null,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      credentials: "same-origin",
      ...init,
      headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Couldn't reach the server. Check your connection and try again.", "network");
  }
  if (!res.ok) {
    let message = res.statusText;
    let code = "error";
    let requestId = res.headers.get("X-Request-ID");
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
      if (typeof body.code === "string") code = body.code;
      if (typeof body.request_id === "string") requestId = body.request_id;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message, code, requestId);
  }
  return res.json() as Promise<T>;
}

/** Starts waking the database (it sleeps when idle) without waiting for an answer. */
export function warmDatabase() {
  fetch("/api/warm", { credentials: "omit", cache: "no-store" }).catch(() => {
    /* best effort: the real request will wait for it anyway */
  });
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

/** Which students a contest page shows: everyone, an instructor's own, or one college. */
export type ContestScope = "all" | "mine" | `college:${string}` | `instructor:${number}`;

function scopeQuery(scope: ContestScope) {
  if (scope === "mine") return "?mine=true";
  if (scope.startsWith("instructor:")) return `?instructor_id=${Number(scope.slice("instructor:".length))}`;
  if (scope.startsWith("college:")) return `?${new URLSearchParams({ college: scope.slice("college:".length) })}`;
  return "";
}

// ---- types -------------------------------------------------------------------

export type Role = "admin" | "instructor" | "viewer";
export interface Me {
  username: string;
  role: Role;
  name: string | null;
  is_super: boolean; // the super admin: nobody can change this login from the dashboard
  scans_enabled: boolean; // false on staging: its data is a copy of production's
  /** set while an admin views the dashboard as this instructor */
  viewing_as: { admin: string; admin_username: string; until: string } | null;
}

export type ResultStatus = "solved" | "zero" | "absent" | "invalid_handle" | "no_handle" | "duplicate_handle";
export type ContestState =
  | "upcoming"
  | "live"
  | "scheduled"
  | "scanning"
  | "queued"
  | "provisional"
  | "final"
  | "failed"
  | "not_scanned";

export interface Summary {
  students: number;
  participated: number;
  solved_any: number;
  zero: number;
  absent: number;
  invalid_handle: number;
  no_handle: number;
  participation_rate: number | null;
  avg_solved: number | null;
  best_global_rank: number | null;
}

export interface ContestStatus {
  state: ContestState;
  has_data: boolean;
  in_review?: boolean; // a manual scan is waiting for an admin's review
  scanned_at?: string | null;
  ready_at?: string | null; // estimated time the results will be ready
  progress?: number; // 0..1 while scanning
  position?: number; // place in the queue
  rescan?: boolean;
  error?: string | null;
  requested_by?: string | null; // queued / scanning: who asked for it (null = automatic)
  cancel_requested?: boolean; // scanning: a stop was requested
  final_at?: string | null; // early results: when final results should be ready
}

export interface ContestListItem extends ContestStatus {
  slug: string;
  title: string;
  contest_type: string;
  start_time: number;
  duration: number;
  participants_worldwide: number | null;
  summary: Summary | null;
}

export interface WorkerStatus {
  alive: boolean;
  last_seen: string | null;
}

export interface ScanStatus {
  worker: WorkerStatus;
  running: {
    slug: string;
    kind: string;
    pages_done: number;
    pages_total: number | null;
    progress: number;
    started_at: string | null;
    ready_at: string | null;
    cancel_requested: boolean;
    requested_by: string | null;
  } | null;
  queue: { slug: string; kind: string; position: number; requested_by: string | null; requested_at: string | null; ready_at: string | null }[];
  typical_scan_secs: number;
}

export interface ContestPage extends ScanStatus {
  upcoming: ContestListItem[];
  items: ContestListItem[];
  total: number;
  page: number;
  per_page: number;
  with_data: number;
  latest_slugs: string[]; // most recent finished contest, plus the other kind if held the same weekend
}

export interface ContestQuery {
  show?: "all" | "with_data" | "without_data";
  type?: "weekly" | "biweekly" | "";
  q?: string;
  page?: number;
  per_page?: number;
}

// ---- topics -------------------------------------------------------------------------

export type TagState = "official" | "provisional" | "insufficient" | "pending";
export interface QuestionTopics {
  state: TagState;
  tags: { slug: string; name: string; source: "official" | "community" }[];
  mentions: number | null; // community topic mentions (provisional)
  fetched_at: string | null;
}
export interface TopicMetrics {
  appeared: number;
  solved: number;
  solve_rate: number | null;
  accuracy: number | null;
  median_secs: number | null;
}
export interface TopicRow extends TopicMetrics {
  slug: string;
  name: string;
  official: TopicMetrics; // the same, counting official tags only
  provisional_appeared: number;
  provisional_questions: number;
}
export interface TopicsData {
  topics: TopicRow[];
  weakest?: string[]; // groups: lowest solve rate among topics seen 10+ times
  coverage: {
    contests: number;
    contests_provisional: number;
    questions: number;
    official: number;
    provisional: number;
    insufficient: number;
    pending: number;
    last_refresh: string | null;
  };
}
export interface TagsStatus {
  last_run: { at: string; line: string; checked: number; failed: number; changed: number } | null;
  counts: Record<TagState, number>;
  refresh_requested: boolean;
  questions: { contest: string; contest_title: string; label: string; slug: string; title: string | null; state: TagState; tags: QuestionTopics["tags"]; mentions: number | null; fetched_at: string | null }[];
}

function topicParams(f: AnalyticsFilters) {
  const p = new URLSearchParams();
  if (f.last) p.set("last", String(f.last));
  if (f.college) p.set("college", f.college);
  return p;
}

export interface Rules {
  analytics: {
    trend_threshold: number;
    trend_k: number;
    absent_streak_alert: number;
    top_n: number;
    medals: number;
    consistency_min_contests: number;
    attendance_weight: number;
    stability_weight: number;
    std_cap: number;
    consistency_labels: { from: number; label: string }[];
    windows: number[];
  };
  schedule: {
    timezone: string;
    scan_delay_minutes: number;
    provisional_retries_minutes: number[];
    final_working_days: number | null;
    final_time: string | null;
    final_retries_hours: number[];
    auto_lookback_days: number;
    ratings_every_hours: number;
    worker_awake_window: string;
    worker_max_sleep_minutes: number;
  };
  tags: { min_mentions: number; top_share: number; max_tags: number; min_top: number; min_total: number; recent_days: number; nightly_time: string; monthly: string; weak_min_appeared: number; weakest_shown: number };
  review: { enabled: boolean; draft_days: number; view_as_minutes: number };
}

export const topicsApi = {
  cohort: (f: AnalyticsFilters) => request<TopicsData>(`/api/analytics/topics?${topicParams(f)}`),
  instructor: (f: AnalyticsFilters, instructorId?: number) => {
    const p = topicParams(f);
    if (instructorId) p.set("instructor_id", String(instructorId));
    return request<TopicsData>(`/api/instructor/analytics/topics?${p}`);
  },
  student: (id: number, last?: number) => request<TopicsData>(`/api/students/${id}/topics${last ? `?last=${last}` : ""}`),
  status: () => request<TagsStatus>("/api/tags/status"),
  refresh: () => post<{ requested: boolean }>("/api/admin/tags/refresh", {}),
};

export interface QuestionStat {
  label: string;
  question_id: number;
  credit: number;
  title: string;
  title_slug: string;
  url: string | null;
  solved: number;
  solve_rate: number | null;
  median_solve_secs: number | null;
  avg_wrong: number | null;
  topics?: QuestionTopics; // contest page: the question's topic tags
}

/** A manual scan waiting for an admin: what adding it would change. */
export interface DraftReview {
  run_id: number;
  contest_slug: string;
  title: string | null;
  kind: string;
  finished_at: string | null;
  expires_at: string | null;
  outdated: boolean; // an automatic scan came after it: it can only be discarded
  students: number;
  solved_any: number;
  participated: number;
  participated_before: number | null; // null: the contest had no results yet
  joined: number | null;
  left: number | null;
  changed: number | null;
}

export interface DraftRow {
  student_id: number;
  name: string;
  roll_no: string | null;
  college: string | null;
  status: ResultStatus;
  college_rank: number | null;
  global_rank: number | null;
  score: number | null;
  solved: number | null;
  before: { status: ResultStatus; college_rank: number | null; score: number | null } | null;
}

export const draftsApi = {
  rows: (runId: number, offset = 0, limit = 50) =>
    request<{ total: number; offset: number; rows: DraftRow[] }>(`/api/admin/scans/${runId}/draft/rows?offset=${offset}&limit=${limit}`),
  publish: (runId: number) => post<{ published: number; contest_slug: string }>(`/api/admin/scans/${runId}/publish`, {}),
  discard: (runId: number) => post<{ discarded: number }>(`/api/admin/scans/${runId}/discard`, {}),
};

export interface ContestDetail {
  review?: DraftReview | null; // admins: a manual scan waiting for review
  slug: string;
  title: string;
  contest_type: string;
  start_time: number;
  duration: number;
  participants_worldwide: number | null;
  leetcode_url: string;
  scan: { kind: "provisional" | "final"; finished_at: string | null } | null;
  status: ContestStatus;
  summary: Summary;
  questions: QuestionStat[];
  distributions: ContestDistributions;
  final_scan_at: string | null; // when the final scan runs (11 pm on the 5th working day after the contest)
  colleges: string[]; // colleges with students in this contest (for the scope filter)
}

export interface ProblemResult {
  solve_secs: number;
  fail_count: number;
  lang: string | null;
}

export interface ResultRow {
  student_id: number;
  roll_no: string | null;
  name: string;
  college: string;
  extra: Record<string, string>;
  leetcode_handle: string;
  status: ResultStatus;
  global_rank: number | null;
  ranking_url: string | null;
  rank_official?: boolean; // from the student's LeetCode profile (else estimated from the leaderboard)
  leaderboard_rank?: number | null; // position on leetcode.com's Global leaderboard (incl. leetcode.cn)
  college_rank: number | null;
  score: number | null;
  solved: number | null;
  total_time_secs: number | null;
  /** LeetCode removed this entry, zeroed it or moved it to the bottom after the contest;
   *  what the earlier scan showed */
  flagged?: { early_rank: number | null; early_score: number | null; early_solved: number | null } | null;
  problems: Record<string, ProblemResult>;
}

export interface ContestResults {
  labels: string[];
  rows: ResultRow[];
}

export type HandleStatus = "valid" | "invalid" | "unchecked" | "missing";

export interface StudentListItem {
  id: number;
  roll_no: string;
  name: string;
  college: string;
  extra: Record<string, string>;
  leetcode_handle: string;
  handle_status: HandleStatus;
  active: boolean;
  contests_attended: number;
  contests_scanned: number;
  rating: number | null; // LeetCode contest rating
  rating_top_pct: number | null;
  rated_contests: number | null;
  rating_synced_at: string | null;
}

export type StudentSort = "name" | "rating_desc" | "rating_asc" | "attended_desc" | "attended_asc";

export interface StudentListQuery {
  q: string;
  college: string;
  handle: string;
  includeRemoved: boolean;
  sort: StudentSort;
  limit: number;
}

/** The Students page: filtered, sorted and cut to `limit` rows by the server. */
export interface StudentList {
  rows: StudentListItem[];
  total: number; // matching the filters
  active: number;
  handle_problems: number;
  colleges: string[];
}

export interface HistoryItem {
  contest_slug: string;
  contest_title: string;
  start_time: number;
  questions: string[];
  status: ResultStatus;
  global_rank: number | null;
  ranking_url: string | null;
  rank_official?: boolean;
  leaderboard_rank?: number | null;
  college_rank: number | null;
  solved: number | null;
  total_time_secs: number | null;
  problems: Record<string, ProblemResult>;
}

export interface StudentDetail {
  id: number;
  roll_no: string;
  name: string;
  college: string;
  extra: Record<string, string>;
  leetcode_handle: string;
  leetcode_url: string | null;
  handle_status: HandleStatus;
  active: boolean;
  history: HistoryItem[];
}


export interface ScanRun {
  id: number;
  contest_slug: string;
  kind: string;
  status: "running" | "complete" | "failed" | "cancelled" | "review" | "discarded";
  review_decision: string | null; // published | discarded | replaced | outdated | expired
  reviewed_by: string | null;
  started_at: string | null;
  finished_at: string | null;
  participants: number | null;
  students: number | null;
  error: string | null;
}

export interface ScanRequest {
  id: number;
  contest_slug: string;
  kind: string;
  requested_by: string | null;
  requested_at: string | null;
  handled_at: string | null;
  scan_run_id: number | null;
  error: string | null;
}

// ---- endpoints -------------------------------------------------------------------

export const api = {
  me: () => request<Me>("/api/auth/me"),
  login: (username: string, password: string) => post<Me>("/api/auth/login", { username, password }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout", {}),
  /** the numbers behind every rule, for the Guide */
  rules: () => request<Rules>("/api/rules"),

  contests: (q: ContestQuery = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== "") p.set(k, String(v));
    return request<ContestPage>(`/api/contests?${p}`);
  },
  scanStatus: () => request<ScanStatus>("/api/scan-status"),
  cancelScan: (slug: string) =>
    request<{ cancelled: "queued" | "running" }>(`/api/contests/${encodeURIComponent(slug)}/scan/cancel`, { method: "POST" }),
  scanPreview: (slug: string) => request<ScanPreview>(`/api/contests/${encodeURIComponent(slug)}/scan/preview`),
  getResults: (slug: string) =>
    request<{ request: { position: number; ready_at: string | null } | null; worker: WorkerStatus }>(
      `/api/contests/${encodeURIComponent(slug)}/scan`,
      { method: "POST" },
    ),
  contest: (slug: string, scope: ContestScope = "all") =>
    request<ContestDetail>(`/api/contests/${encodeURIComponent(slug)}${scopeQuery(scope)}`),
  results: (slug: string, scope: ContestScope = "all") =>
    request<ContestResults>(`/api/contests/${encodeURIComponent(slug)}/results${scopeQuery(scope)}`),
  exportUrl: (slug: string, format: "csv" | "xlsx") => `/api/contests/${encodeURIComponent(slug)}/export.${format}`,

  students: (f: StudentListQuery) => {
    const p = new URLSearchParams({ sort: f.sort, limit: String(f.limit) });
    if (f.q) p.set("q", f.q);
    if (f.college) p.set("college", f.college);
    if (f.handle) p.set("handle", f.handle);
    if (f.includeRemoved) p.set("include_removed", "true");
    return request<StudentList>(`/api/students?${p}`);
  },
  student: (id: number) => request<StudentDetail>(`/api/students/${id}`),

  scanRuns: () => request<ScanRun[]>("/api/admin/scan-runs"),
  scanRequests: () => request<ScanRequest[]>("/api/admin/scan-requests"),
  /** kind "auto": final results once the contest's final-scan time (5th working day) has passed, else early. */
  requestScan: (slug: string, kind: "auto" | "provisional" | "final" = "auto") =>
    post<ScanRequest>("/api/admin/scans", { slug, kind }),
};

// ---- analytics -------------------------------------------------------------------

export interface QuestionPerf {
  attempted_contests: number;
  solved: number;
  solve_rate: number | null;
  median_secs: number | null;
  avg_secs: number | null;
  best_secs: number | null;
  wrong: number;
  wrong_per_solve: number | null;
  cohort_solve_rate?: number | null;
  cohort_median_secs?: number | null;
  cohort_wrong_per_solve?: number | null;
}

export type TrendLabel = "improving" | "steady" | "declining";

export interface StudentMetrics {
  contests_scanned: number;
  contests_attended: number;
  attendance_rate: number | null;
  current_streak: number;
  longest_streak: number;
  absent_streak: number;
  avg_solved: number | null;
  solved_std: number | null;
  avg_top_pct: number | null;
  best_global_rank: number | null;
  best_college_rank: number | null;
  consistency: number | null;
  consistency_label: string | null;
  trend: number | null;
  trend_label: TrendLabel | null;
  questions: Record<string, QuestionPerf>;
}

export interface StudentRef {
  id: number;
  name: string;
  roll_no: string;
  college: string;
  extra: Record<string, string>;
  rating: number | null;
}

export type StudentAnalyticsRow = StudentRef &
  StudentMetrics & {
    points: number; // LeetCode contest points over the selected contests
    portal_rank: number | null; // position in the portal by points (null: no points yet)
  };

export interface Topper {
  id: number;
  name: string;
  roll_no: string;
  college: string;
  points: number;
  portal_rank: number;
  contests_attended: number;
  avg_solved: number | null;
  best_global_rank: number | null;
}

export interface CollegeRankingRow {
  college: string;
  students: number;
  ranked: number;
  in_top: number;
  in_top_10: number;
  best_portal_rank: number | null;
  rank: number | null;
}
export type LeaderRow = Omit<StudentAnalyticsRow, "questions" | "extra"> & { reasons?: string[] };

export interface TrendPoint {
  slug: string;
  title: string;
  start_time: number;
  students: number;
  participated: number;
  participation_rate: number | null;
  avg_solved: number | null;
  median_top_pct: number | null;
  best_global_rank: number | null;
  questions: Record<string, { solve_rate: number | null; solved: number; median_secs: number | null; wrong_per_solver: number | null }>;
}

export interface QuestionSummary {
  label: string;
  attempts: number;
  solved: number;
  solve_rate: number | null;
  median_secs: number | null;
  p25_secs: number | null;
  p75_secs: number | null;
  wrong: number;
  wrong_per_solve: number | null;
}

export interface CollegeStats {
  college: string;
  students: number;
  participation_rate: number | null;
  avg_solved: number | null;
  median_top_pct: number | null;
  best_global_rank: number | null;
  avg_consistency: number | null;
  avg_rating: number | null;
  solved_any_share: number | null;
}

export interface AnalyticsOverview {
  window: { contests: number; first: string | null; last: string | null };
  labels: string[];
  summary: {
    students: number;
    participation_rate: number | null;
    avg_solved: number | null;
    active_participants: number;
    avg_rating: number | null;
    rated_students: number;
    needs_attention: number;
  };
  trend: TrendPoint[];
  questions: QuestionSummary[];
  colleges: CollegeStats[];
  leaders: { consistent: LeaderRow[]; top_performers: LeaderRow[]; improved: LeaderRow[]; attention: LeaderRow[] };
  toppers: { overall: Topper[]; colleges: { college: string; students: number; toppers: Topper[] }[] };
  college_ranking: CollegeRankingRow[];
  top_n: number;
  instructor?: { id: number; name: string; email: string };
  filters: { colleges: string[]; extras: Record<string, string[]> };
}

export interface StudentAnalytics extends StudentMetrics {
  labels: string[];
  series: {
    slug: string;
    title: string;
    start_time: number;
    status: ResultStatus;
    solved: number | null;
    questions: number;
    global_rank: number | null;
    top_pct: number | null;
    college_rank: number | null;
    total_time_secs: number | null;
  }[];
  rating: {
    current: number | null;
    global_ranking: number | null;
    top_percentage: number | null;
    contests_attended: number | null;
    synced_at: string | null;
    history: { title: string; slug: string; start_time: number; rating: number; ranking: number | null; solved: number | null; total: number | null }[];
  };
}

export interface ContestDistributions {
  bin_minutes: number;
  time_bins: Record<string, number[]>;
  wrong_distribution: Record<string, Record<"0" | "1" | "2" | "3+", number>>;
  colleges: {
    college: string;
    students: number;
    participated: number;
    participation_rate: number | null;
    avg_solved: number | null;
    solved_all: number;
    best_global_rank: number | null;
    best_college_rank: number | null;
  }[];
}

export interface AnalyticsFilters {
  last?: number;
  college?: string;
  extra?: Record<string, string>;
}

/** One page of the "All students" table: searched, sorted and sliced by the server. */
export interface StudentsPageQuery {
  q: string;
  sort: string;
  desc: boolean;
  offset: number;
  limit: number;
}

export interface StudentsPage {
  labels: string[];
  total: number;
  offset: number;
  rows: StudentAnalyticsRow[];
}

function pageParams(f: AnalyticsFilters, page: StudentsPageQuery) {
  const p = analyticsParams(f);
  if (page.q) p.set("q", page.q);
  p.set("sort", page.sort);
  if (page.desc) p.set("desc", "true");
  if (page.offset) p.set("offset", String(page.offset));
  p.set("limit", String(page.limit));
  return p;
}

function analyticsParams(f: AnalyticsFilters) {
  const p = new URLSearchParams();
  if (f.last) p.set("last", String(f.last));
  if (f.college) p.set("college", f.college);
  for (const [k, v] of Object.entries(f.extra ?? {})) if (v) p.set(`extra.${k}`, v);
  return p;
}

export const analyticsApi = {
  overview: (f: AnalyticsFilters) => request<AnalyticsOverview>(`/api/analytics?${analyticsParams(f)}`),
  /** An instructor's students: their own, or (admins) the instructor given. */
  instructor: (f: AnalyticsFilters, instructorId?: number) => {
    const p = analyticsParams(f);
    if (instructorId) p.set("instructor_id", String(instructorId));
    return request<AnalyticsOverview>(`/api/instructor/analytics?${p}`);
  },
  students: (f: AnalyticsFilters, page: StudentsPageQuery) =>
    request<StudentsPage>(`/api/analytics/students?${pageParams(f, page)}`),
  instructorStudents: (f: AnalyticsFilters, page: StudentsPageQuery, instructorId?: number) => {
    const p = pageParams(f, page);
    if (instructorId) p.set("instructor_id", String(instructorId));
    return request<StudentsPage>(`/api/instructor/analytics/students?${p}`);
  },
  student: (id: number) => request<StudentAnalytics>(`/api/students/${id}/analytics`),
  /** Ask LeetCode for the student's rating now (kept if fetched in the last 10 minutes). */
  refreshRating: (id: number) =>
    post<{ rating: number | null; top_percentage: number | null; contests_attended: number | null; synced_at: string | null; fetched_now: boolean }>(
      `/api/students/${id}/rating/refresh`,
      {},
    ),
};

// ---- instructors (admin) -------------------------------------------------------------

export interface Instructor extends Audit {
  id: number;
  email: string;
  name: string;
  active: boolean;
  colleges: string[];
  roll_nos: string[];
  students: number; // active students they follow
}

export interface InstructorInput {
  email: string;
  name: string;
  password?: string; // required when adding; blank keeps the current one
  colleges: string[];
  roll_nos: string[];
  active: boolean;
}

export const instructorsApi = {
  list: () => request<InstructorList>("/api/admin/instructors"),
  upload: (file: File) => uploadFile<ImportSummary>("/api/admin/instructors/import", file),
  preview: (file: File) => uploadFile<UploadPreview>("/api/admin/instructors/import", file, true),
  templateUrl: "/api/admin/instructors/template.xlsx",
  create: (body: InstructorInput) => post<Instructor>("/api/admin/instructors", body),
  update: (id: number, body: InstructorInput) =>
    request<Instructor>(`/api/admin/instructors/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  remove: (id: number) => request<{ deleted: number }>(`/api/admin/instructors/${id}`, { method: "DELETE" }),
  /** see the dashboard as this instructor (read-only, up to an hour) */
  viewAs: (id: number) => post<Me>(`/api/admin/instructors/${id}/view-as`, {}),
  returnToAdmin: () => post<Me>("/api/auth/return", {}),
};

// ---- student roster (admin) ---------------------------------------------------------

/** Who changed a row last, when, and how. */
export type Via = "ui" | "excel" | "cli" | "sheet" | "undo";
export interface Audit {
  created_at: string | null;
  created_by: string | null;
  created_via: Via | null;
  updated_at: string | null;
  updated_by: string | null;
  updated_via: Via | null;
}

export interface RosterStudent extends Audit {
  id: number;
  roll_no: string;
  name: string;
  college: string;
  leetcode: string; // as entered: handle or profile URL
  handle: string | null; // normalized
  handle_status: HandleStatus;
  extra: Record<string, string>;
  active: boolean;
}

export interface StudentInput {
  roll_no: string;
  name: string;
  college: string;
  leetcode: string;
  extra: Record<string, string>;
}

export interface ImportSummary {
  added: number;
  updated: number;
  restored?: number;
  unchanged?: number;
  skipped: number;
  issues: string[];
  upload_id?: number; // its entry in the upload history
}

/** Send a file as the raw request body; the server reads .xlsx or .csv by its name. */
function uploadFile<T>(path: string, file: File, preview = false) {
  return request<T>(`${path}?${new URLSearchParams({ filename: file.name, preview: String(preview) })}`, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/octet-stream" },
  });
}

export type RosterShow = "active" | "removed" | "all";

export interface InstructorList {
  instructors: Instructor[];
  colleges: string[];
  max_upload_rows: number;
}

export interface CollegeList {
  colleges: CollegeRow[];
  can_edit: boolean;
}

/** One page of the admin roster (searched and paged by the server). */
export interface RosterList {
  students: RosterStudent[];
  total: number; // matching the search
  active: number;
  removed: number;
  colleges: string[];
  extra_columns: string[];
  max_upload_rows: number;
}

export const rosterApi = {
  list: (f: { q: string; show: RosterShow; offset: number; limit: number }) => {
    const p = new URLSearchParams({ show: f.show, offset: String(f.offset), limit: String(f.limit) });
    if (f.q) p.set("q", f.q);
    return request<RosterList>(`/api/admin/students?${p}`);
  },
  create: (body: StudentInput) => post<RosterStudent>("/api/admin/students", body),
  update: (id: number, body: StudentInput) =>
    request<RosterStudent>(`/api/admin/students/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  setActive: (id: number, active: boolean) => post<RosterStudent>(`/api/admin/students/${id}/active`, { active }),
  upload: (file: File) => uploadFile<ImportSummary>("/api/admin/students/import", file),
  /** Check a file and list what would happen to every row; nothing is saved. */
  preview: (file: File) => uploadFile<UploadPreview>("/api/admin/students/import", file, true),
  templateUrl: "/api/admin/students/template.xlsx",
};

// ---- admins (admin) -------------------------------------------------------------------

export interface AdminUser extends Audit {
  id: number;
  email: string;
  name: string;
  active: boolean;
  is_super: boolean;
  is_you: boolean;
  editable: boolean; // false for the super admin
}

export interface AdminInput {
  email: string;
  name: string;
  password?: string; // required when adding; blank keeps the current one
  active: boolean;
}

export const adminsApi = {
  list: () => request<AdminUser[]>("/api/admin/admins"),
  create: (body: AdminInput) => post<AdminUser>("/api/admin/admins", body),
  update: (id: number, body: AdminInput) =>
    request<AdminUser>(`/api/admin/admins/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  remove: (id: number) => request<{ deleted: number }>(`/api/admin/admins/${id}`, { method: "DELETE" }),
};

// ---- colleges (admin; changes: super admin only) -----------------------------------------

export interface CollegeRow extends Audit {
  id: number;
  name: string;
  students: number; // active
  removed_students: number;
  instructors: number;
}

export const collegesApi = {
  list: () => request<CollegeList>("/api/admin/colleges"),
  /** preview: report which names are new / already listed, without saving */
  add: (names: string[], preview = false) =>
    post<{ added: string[]; existing: string[] }>(`/api/admin/colleges${preview ? "?preview=true" : ""}`, { names }),
  rename: (id: number, name: string) =>
    request<CollegeRow>(`/api/admin/colleges/${id}`, { method: "PUT", body: JSON.stringify({ name }) }),
  remove: (id: number) => request<{ deleted: number }>(`/api/admin/colleges/${id}`, { method: "DELETE" }),
};

/** What queuing a scan would do, for the confirmation pop-up. */
export interface ScanPreview {
  slug: string;
  title: string | null;
  has_data: boolean;
  kind: "provisional" | "final" | null; // null: decided once LeetCode reports the contest's date
  final_scan_at: string | null;
  final_ready_at: string | null; // the final scan's start plus a typical scan
  students: number;
  ahead: number; // scans before this one
  ready_at: string;
  typical_scan_secs: number;
  already: "queued" | "scanning" | null;
  worker: WorkerStatus;
  can_request: boolean;
}

// ---- upload history (admin) -----------------------------------------------------------

export interface UploadItem {
  id: number;
  kind: "students" | "instructors";
  filename: string;
  uploaded_by: string;
  via: string;
  uploaded_at: string;
  rows: number;
  counts: Record<string, number>; // added / updated / restored / unchanged / skipped
  issues: string[];
  status: "applied" | "undone";
  undone_by: string | null;
  undone_at: string | null;
  undo_result: { reverted: number; skipped: string[] } | null;
  changes: number;
}

export interface UploadChange {
  entity: "student" | "instructor" | "college";
  entity_id: number;
  label: string;
  action: "added" | "updated" | "restored";
  before: Record<string, unknown> | null; // only the fields the upload changed
  after: Record<string, unknown>;
}

export const uploadsApi = {
  list: (kind: "students" | "instructors") => request<UploadItem[]>(`/api/admin/uploads?kind=${kind}`),
  get: (id: number) => request<Omit<UploadItem, "changes"> & { changes: UploadChange[] }>(`/api/admin/uploads/${id}`),
  undo: (id: number) => post<{ reverted: number; skipped: string[] }>(`/api/admin/uploads/${id}/undo`, {}),
};

/** One row of an upload under review, and what saving would do to it. */
export interface PreviewRecord {
  row: number; // row in the file (the header is row 1)
  key: string; // roll no (students) or email (instructors)
  name: string;
  action: "added" | "updated" | "restored" | "unchanged" | "skipped";
  reason?: string; // skipped
  before?: Record<string, unknown> | null; // only the fields that would change
  after?: Record<string, unknown>;
}

export interface UploadPreview extends ImportSummary {
  rows: number; // records in the file
  records: PreviewRecord[];
  new_colleges?: string[];
}
