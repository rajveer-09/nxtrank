# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""Analytics read model (precomputed summaries), PostgreSQL only.

`student_stats` and `cohort_stats` hold raw numbers for the last 5 / 10 / 20 / all scanned
contests. They are recomputed from source by set-based SQL in the same transaction as any
change to results or the roster (see `track`), so they can't drift. The rules (scores,
labels, ranks) are applied in app.services.analytics.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

WINDOWS = (5, 10, 20, 0)  # last N scanned contests; 0 = all
LOCK_ID = 730_101  # pg_advisory_xact_lock key: one rebuild at a time
DATA_VERSION = "data_version"

RESULT_TABLES = {"results", "problem_results", "contests"}
# changes here don't alter any numbers, but they change what some pages show
VERSION_TABLES = {"students", "colleges", "rating_history", "instructor_colleges", "instructor_students", "users",
                  "question_tags"}  # effective topic tags: topic stats change
COHORT_COLUMNS = {"active", "college_id"}  # student columns that move them between cohorts

# ---- SQL ---------------------------------------------------------------------------

# The window: the latest :n scanned contests (LIMIT NULL = all), numbered oldest first,
# and the question labels each one had.
_WINDOW = """
latest AS (
    SELECT c.slug, c.user_num, c.start_time, c.questions
    FROM contests c
    WHERE EXISTS (SELECT 1 FROM results r WHERE r.contest_slug = c.slug)
    ORDER BY c.start_time DESC, c.slug DESC
    LIMIT CAST(:n AS integer)
),
w AS (
    SELECT slug, user_num, row_number() OVER (ORDER BY start_time, slug) AS pos
    FROM latest
),
wq AS (
    SELECT l.slug, q ->> 'label' AS label
    FROM latest l CROSS JOIN LATERAL json_array_elements(CAST(l.questions AS json)) AS q
)"""

# "attended" = on the leaderboard; top % = global rank / participants x 100
_ROW_COLUMNS = """
           r.status IN ('solved', 'zero')                                  AS att,
           coalesce(r.solved_count, 0)                                     AS solved,
           r.global_rank,
           CASE WHEN r.global_rank <> 0 AND w.user_num <> 0
                THEN CAST(r.global_rank AS float8) / w.user_num * 100 END  AS pct"""

STUDENT_COLUMNS = (
    "student_id", "scanned", "attended", "sum_solved", "sum_solved_sq", "max_solved", "avg_top_pct",
    "best_global_rank", "best_college_rank", "points", "total_time", "longest_streak", "current_streak",
    "absent_streak", "trend_k", "trend_recent", "trend_before", "questions",
)


def student_select(subset: bool = False) -> str:
    """One row per student with results in the window: STUDENT_COLUMNS.
    subset: only students in :ids (an integer array)."""
    only = "WHERE r.student_id = ANY(CAST(:ids AS integer[]))" if subset else ""
    return f"""
WITH {_WINDOW},
rows AS (
    SELECT r.student_id, r.contest_slug, w.pos, {_ROW_COLUMNS},
           r.solved_count, r.score, r.total_time_secs, r.college_rank
    FROM results r JOIN w ON w.slug = r.contest_slug
    {only}
),
base AS (
    SELECT student_id,
           count(*)                                                        AS scanned,
           count(*) FILTER (WHERE att)                                     AS attended,
           coalesce(sum(solved) FILTER (WHERE att), 0)                     AS sum_solved,
           coalesce(sum(solved * solved) FILTER (WHERE att), 0)            AS sum_solved_sq,
           max(solved_count)                                               AS max_solved,
           avg(pct) FILTER (WHERE att)                                     AS avg_top_pct,
           min(global_rank) FILTER (WHERE att AND global_rank <> 0)        AS best_global_rank,
           min(college_rank) FILTER (WHERE att AND college_rank <> 0)      AS best_college_rank,
           coalesce(sum(score) FILTER (WHERE att), 0)                      AS points,
           coalesce(sum(total_time_secs) FILTER (WHERE att AND solved_count <> 0), 0) AS total_time
    FROM rows GROUP BY student_id
),
seq AS (            -- gaps and islands over each student's scanned contests
    SELECT student_id, att,
           row_number() OVER (PARTITION BY student_id ORDER BY pos DESC)   AS from_end,
           row_number() OVER (PARTITION BY student_id ORDER BY pos)
         - row_number() OVER (PARTITION BY student_id, att ORDER BY pos)   AS island
    FROM rows
),
islands AS (
    SELECT student_id, att, count(*) AS len, min(from_end) AS from_end
    FROM seq GROUP BY student_id, att, island
),
streaks AS (
    SELECT student_id,
           coalesce(max(len) FILTER (WHERE att), 0)                        AS longest_streak,
           coalesce(max(len) FILTER (WHERE att AND from_end = 1), 0)       AS current_streak,
           coalesce(max(len) FILTER (WHERE NOT att AND from_end = 1), 0)   AS absent_streak
    FROM islands GROUP BY student_id
),
att_desc AS (       -- attended contests, newest first
    SELECT student_id, solved,
           row_number() OVER (PARTITION BY student_id ORDER BY pos DESC)   AS k,
           count(*) OVER (PARTITION BY student_id)                         AS n
    FROM rows WHERE att
),
trend AS (          -- the last k attended vs the k before them, k = min(4, n / 2), n >= 4
    SELECT student_id,
           least(4, max(n) / 2)                                            AS trend_k,
           sum(solved) FILTER (WHERE k <= least(4, n / 2))                 AS trend_recent,
           sum(solved) FILTER (WHERE k > least(4, n / 2) AND k <= 2 * least(4, n / 2)) AS trend_before
    FROM att_desc GROUP BY student_id HAVING max(n) >= 4
),
q_att AS (          -- attended contests that had the question
    SELECT r.student_id, wq.label, count(*) AS attempted
    FROM rows r JOIN wq ON wq.slug = r.contest_slug
    WHERE r.att GROUP BY r.student_id, wq.label
),
q_sol AS (
    SELECT p.student_id, p.q_label AS label, count(*) AS solved,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY p.solve_secs)       AS median_secs,
           sum(p.solve_secs) AS sum_secs, min(p.solve_secs) AS best_secs, sum(p.fail_count) AS wrong
    FROM problem_results p
    JOIN rows r ON r.student_id = p.student_id AND r.contest_slug = p.contest_slug AND r.att
    JOIN wq ON wq.slug = p.contest_slug AND wq.label = p.q_label
    GROUP BY p.student_id, p.q_label
),
questions AS (
    SELECT a.student_id,
           json_object_agg(a.label, json_build_array(a.attempted, coalesce(s.solved, 0), s.median_secs,
                                                     s.sum_secs, s.best_secs, coalesce(s.wrong, 0))) AS questions
    FROM q_att a LEFT JOIN q_sol s ON s.student_id = a.student_id AND s.label = a.label
    GROUP BY a.student_id
)
SELECT b.student_id, b.scanned, b.attended, b.sum_solved, b.sum_solved_sq, b.max_solved, b.avg_top_pct,
       b.best_global_rank, b.best_college_rank, b.points, b.total_time,
       coalesce(s.longest_streak, 0), coalesce(s.current_streak, 0), coalesce(s.absent_streak, 0),
       t.trend_k, t.trend_recent, t.trend_before, q.questions
FROM base b
LEFT JOIN streaks s USING (student_id)
LEFT JOIN trend t USING (student_id)
LEFT JOIN questions q USING (student_id)"""


def cohort_select(subset: bool = False) -> str:
    """One JSON document of the cohort's aggregates: the active students, or (subset)
    the students in :ids. Shapes (read by analytics.CohortRaw.from_payload):
      q_att      {label: attempts}
      q_sol      {label: [solved, median, p25, p75, wrong]}
      colleges   {college_id or 0: median top %}
      contests   {slug: [students, participated, sum_solved, median top %, best global rank]}
      contest_q  {"slug/label": [solved, median, wrong]}"""
    who = "s.id = ANY(CAST(:ids AS integer[]))" if subset else "s.active"
    return f"""
WITH {_WINDOW},
cohort AS (
    SELECT s.id AS student_id, coalesce(s.college_id, 0) AS college_key FROM students s WHERE {who}
),
crow AS (
    SELECT r.student_id, r.contest_slug, co.college_key, {_ROW_COLUMNS}
    FROM results r JOIN w ON w.slug = r.contest_slug JOIN cohort co ON co.student_id = r.student_id
),
cprob AS (          -- solves in attended contests, for questions the contest had
    SELECT p.contest_slug, p.q_label AS label, p.solve_secs, p.fail_count
    FROM problem_results p
    JOIN crow r ON r.student_id = p.student_id AND r.contest_slug = p.contest_slug AND r.att
    JOIN wq ON wq.slug = p.contest_slug AND wq.label = p.q_label
),
q_sol AS (
    SELECT label, count(*) AS solved,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY solve_secs)  AS median,
           percentile_cont(0.25) WITHIN GROUP (ORDER BY solve_secs) AS p25,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY solve_secs) AS p75,
           sum(fail_count) AS wrong
    FROM cprob GROUP BY label
),
colleges AS (
    SELECT college_key, percentile_cont(0.5) WITHIN GROUP (ORDER BY pct) AS median_pct
    FROM crow WHERE att AND pct IS NOT NULL GROUP BY college_key
),
contests AS (
    SELECT contest_slug, count(*) AS students, count(*) FILTER (WHERE att) AS participated,
           coalesce(sum(solved) FILTER (WHERE att), 0) AS sum_solved,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY pct) FILTER (WHERE att AND pct IS NOT NULL) AS median_pct,
           min(global_rank) FILTER (WHERE att AND global_rank <> 0) AS best_global_rank
    FROM crow GROUP BY contest_slug
),
contest_q AS (
    SELECT contest_slug, label, count(*) AS solved,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY solve_secs) AS median, sum(fail_count) AS wrong
    FROM cprob GROUP BY contest_slug, label
),
q_att AS (          -- attempts at a question: everyone who took part in a contest that had it
    SELECT wq.label, sum(c.participated) AS attempts
    FROM contests c JOIN wq ON wq.slug = c.contest_slug WHERE c.participated > 0 GROUP BY wq.label
)
SELECT json_build_object(
    'q_att',     (SELECT coalesce(json_object_agg(label, attempts), '{{}}') FROM q_att),
    'q_sol',     (SELECT coalesce(json_object_agg(label, json_build_array(solved, median, p25, p75, wrong)), '{{}}')
                  FROM q_sol),
    'colleges',  (SELECT coalesce(json_object_agg(college_key, median_pct), '{{}}') FROM colleges),
    'contests',  (SELECT coalesce(json_object_agg(contest_slug, json_build_array(students, participated, sum_solved,
                                                                              median_pct, best_global_rank)), '{{}}')
                  FROM contests),
    'contest_q', (SELECT coalesce(json_object_agg(contest_slug || '/' || label, json_build_array(solved, median, wrong)),
                                  '{{}}') FROM contest_q)
) AS payload"""


# ---- rebuild -------------------------------------------------------------------------


def supported(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def rebuild(session: Session, *, students: bool = True, cohort: bool = True) -> None:
    """Recompute the summaries from source in the current transaction (no commit)."""
    if not supported(session) or not (students or cohort):
        return
    started = time.perf_counter()
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_ID})
    session.execute(text("SET LOCAL work_mem = '32MB'"))  # this transaction only: sorts stay in memory
    cols = ", ".join(STUDENT_COLUMNS)
    for win in WINDOWS:
        params = {"win": win, "n": win or None}
        if students:
            session.execute(text("DELETE FROM student_stats WHERE win = :win"), params)
            session.execute(text(f"INSERT INTO student_stats (win, {cols}) SELECT :win, x.* FROM ({student_select()}) x"),
                            params)
        if cohort:
            session.execute(text("DELETE FROM cohort_stats WHERE win = :win"), params)
            session.execute(text(f"INSERT INTO cohort_stats (win, payload) SELECT :win, x.payload FROM ({cohort_select()}) x"),
                            params)
    log.info("analytics summaries rebuilt (%s) in %.0f ms",
             "students + cohort" if students else "cohort", (time.perf_counter() - started) * 1000)


def bump_version(session: Session) -> None:
    session.execute(text(
        "UPDATE app_state SET value = CAST(CAST(value AS bigint) + 1 AS varchar(20)), updated_at = CURRENT_TIMESTAMP "
        "WHERE key = :k"), {"k": DATA_VERSION})


def data_version(session: Session) -> str:
    return session.execute(text("SELECT value FROM app_state WHERE key = :k"), {"k": DATA_VERSION}).scalar() or "0"


def ensure_built(session: Session) -> bool:
    """Build the summaries if they've never been built (new database, or just migrated).
    Returns whether it did. Commits."""
    if not supported(session):
        return False
    have = session.execute(text("SELECT count(*) FROM cohort_stats")).scalar()
    if have == len(WINDOWS):
        return False
    rebuild(session)
    bump_version(session)
    session.commit()
    return True


# ---- noticing changes ------------------------------------------------------------------


def _pending(session: Session) -> dict:
    return session.info.setdefault("summaries", {"students": False, "cohort": False, "version": False})


def _note_object(p: dict, obj, new: bool, deleted: bool) -> None:
    table = getattr(type(obj), "__tablename__", None)
    if table in RESULT_TABLES:
        p["students"] = p["version"] = True
    elif table == "students":
        p["version"] = True
        if deleted or (not new and any(inspect(obj).attrs[c].history.has_changes() for c in COHORT_COLUMNS)):
            p["cohort"] = True
    elif table in VERSION_TABLES:
        p["version"] = True


def _after_flush(session: Session, _ctx) -> None:
    p = _pending(session)
    for obj in session.new:
        _note_object(p, obj, new=True, deleted=False)
    for obj in session.dirty:
        if session.is_modified(obj, include_collections=False):
            _note_object(p, obj, new=False, deleted=False)
    for obj in session.deleted:
        _note_object(p, obj, new=False, deleted=True)


def _on_execute(state) -> None:
    """Bulk UPDATE / DELETE / INSERT statements bypass the unit of work."""
    if not (state.is_update or state.is_delete or state.is_insert):
        return
    table = getattr(getattr(state.statement, "table", None), "name", None)
    p = _pending(state.session)
    if table in RESULT_TABLES:
        p["students"] = p["version"] = True
    elif table == "students":
        p["cohort"] = p["version"] = True
    elif table in VERSION_TABLES:
        p["version"] = True


def _before_commit(session: Session) -> None:
    session.flush()  # so the last changes are noted too
    p = session.info.pop("summaries", None)
    if not p or not any(p.values()):
        return
    students, cohort = p["students"], p["students"] or p["cohort"]
    rebuild(session, students=students, cohort=cohort)
    bump_version(session)


def _clear(session: Session, *_args) -> None:
    session.info.pop("summaries", None)


def track(factory: sessionmaker) -> None:
    """Keep the summaries and data_version current for sessions from this factory."""
    event.listen(factory, "after_flush", _after_flush)
    event.listen(factory, "do_orm_execute", _on_execute)
    event.listen(factory, "before_commit", _before_commit)
    event.listen(factory, "after_commit", _clear)
    event.listen(factory, "after_rollback", _clear)


# ---- reading ---------------------------------------------------------------------------


def window_key(last: int | None, scanned: int) -> int | None:
    """The stored window answering `last`, or None if it isn't stored (compute live)."""
    if not last or last >= scanned:
        return 0
    return last if last in WINDOWS else None


def student_rows(session: Session, last: int | None, ids: list[int] | None = None) -> list:
    """STUDENT_COLUMNS rows computed live (a window that isn't stored)."""
    sql = student_select(subset=ids is not None)
    return list(session.execute(text(sql), {"n": last, "ids": ids}))


def cohort_payload(session: Session, win: int | None, last: int | None, ids: list[int] | None = None) -> dict:
    """Cohort aggregates: stored (win given, whole active cohort) or computed live."""
    if win is not None and ids is None:
        stored = session.execute(text("SELECT payload FROM cohort_stats WHERE win = :win"), {"win": win}).scalar()
        if stored is not None:
            return stored
    sql = cohort_select(subset=ids is not None)
    return session.execute(text(sql), {"n": last, "ids": ids}).scalar()
