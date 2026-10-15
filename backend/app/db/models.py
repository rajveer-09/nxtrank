# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Database schema. Works on PostgreSQL (production) and SQLite (local dev/tests).

Changing a model? Create a migration:
    .venv/Scripts/alembic revision --autogenerate -m "describe change"
"""

from datetime import datetime, timezone

from sqlalchemy import (
    false,
    JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, MetaData,
    String, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class College(Base):
    """Managed by the super admin (Admin → Colleges)."""

    __tablename__ = "colleges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    # audit, as on Student
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_via: Mapped[str | None] = mapped_column(String(10))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_via: Mapped[str | None] = mapped_column(String(10))


class Student(Base):
    """One row per student, keyed by roll number. Added and edited by admins on the
    dashboard, one at a time or by Excel upload."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    roll_no: Mapped[str] = mapped_column(String(64), unique=True)  # stored upper-cased
    name: Mapped[str] = mapped_column(String(200))
    college_id: Mapped[int | None] = mapped_column(ForeignKey("colleges.id"))
    extra: Mapped[dict] = mapped_column(JSON, default=dict)  # other sheet columns
    lc_handle_raw: Mapped[str] = mapped_column(String(300), default="")
    lc_slug: Mapped[str | None] = mapped_column(String(100), index=True)  # normalized, lower
    lc_username: Mapped[str | None] = mapped_column(String(100))  # canonical case from LeetCode
    handle_status: Mapped[str] = mapped_column(String(16), default="unchecked")
    handle_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # False once removed (results kept)
    sheet_row: Mapped[int | None] = mapped_column(Integer)
    # audit: when, by whom (login) and how ("ui", "excel", "sheet" = old Google Sheet sync, "cli")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_via: Mapped[str | None] = mapped_column(String(10))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_via: Mapped[str | None] = mapped_column(String(10))
    # LeetCode contest rating (userContestRanking), refreshed by sync-ratings
    lc_rating: Mapped[float | None] = mapped_column(Float)
    lc_global_ranking: Mapped[int | None] = mapped_column(Integer)
    lc_top_percentage: Mapped[float | None] = mapped_column(Float)
    lc_contests_attended: Mapped[int | None] = mapped_column(Integer)
    ratings_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    college: Mapped[College | None] = relationship()


class RosterSync(Base):
    __tablename__ = "roster_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|complete|failed
    added: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    reactivated: Mapped[int] = mapped_column(Integer, default=0)
    deactivated: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class Contest(Base):
    __tablename__ = "contests"

    slug: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    contest_type: Mapped[str] = mapped_column(String(16))  # weekly | biweekly
    start_time: Mapped[int] = mapped_column(BigInteger)  # unix seconds
    duration: Mapped[int] = mapped_column(Integer)  # seconds
    user_num: Mapped[int | None] = mapped_column(Integer)  # participants on the leaderboard
    # [{"label": "Q1", "question_id": 4418, "credit": 3, "title": ..., "title_slug": ...}]
    questions: Mapped[list] = mapped_column(JSON, default=list)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_slug: Mapped[str] = mapped_column(String(100), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="provisional")  # provisional (early) | final
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|complete|failed|cancelled
    pages_total: Mapped[int | None] = mapped_column(Integer)
    pages_done: Mapped[int | None] = mapped_column(Integer)  # progress while running
    # set from the dashboard; the worker checks it while scanning and stops
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_num: Mapped[int | None] = mapped_column(Integer)
    students: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Result(Base):
    """A student's result in one contest. Every active student gets a row per scanned
    contest, including absent ones, so participation can be counted."""

    __tablename__ = "results"
    # the primary key serves "everyone in a contest"; this serves "everything about one student"
    __table_args__ = (Index("ix_results_student_contest", "student_id", "contest_slug"),)

    contest_slug: Mapped[str] = mapped_column(ForeignKey("contests.slug"), primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"))
    status: Mapped[str] = mapped_column(String(20))  # see app.scan.matcher.Status
    global_rank: Mapped[int | None] = mapped_column(Integer)  # as on the student's LeetCode profile
    leaderboard_rank: Mapped[int | None] = mapped_column(Integer)  # position on the global leaderboard (for links)
    # "scan": worked out from the leaderboard; "profile": LeetCode's official rank from the
    # student's contest history (published a few days after the contest)
    rank_source: Mapped[str | None] = mapped_column(String(10))
    college_rank: Mapped[int | None] = mapped_column(Integer)  # rank among portal students
    score: Mapped[int | None] = mapped_column(Integer)
    solved_count: Mapped[int | None] = mapped_column(Integer)
    total_time_secs: Mapped[int | None] = mapped_column(Integer)  # includes penalties

    student: Mapped[Student] = relationship()
    problems: Mapped[list["ProblemResult"]] = relationship(
        cascade="all, delete-orphan", order_by="ProblemResult.q_label"
    )


class ProblemResult(Base):
    __tablename__ = "problem_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["contest_slug", "student_id"],
            ["results.contest_slug", "results.student_id"],
            ondelete="CASCADE",
        ),
        Index("ix_problem_results_student_contest", "student_id", "contest_slug"),
    )

    contest_slug: Mapped[str] = mapped_column(String(100), primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    q_label: Mapped[str] = mapped_column(String(4), primary_key=True)  # Q1..Q4
    question_id: Mapped[int] = mapped_column(Integer)
    solve_secs: Mapped[int] = mapped_column(Integer)  # accepted time - start, no penalty
    fail_count: Mapped[int] = mapped_column(Integer)
    lang: Mapped[str | None] = mapped_column(String(32))


class User(Base):
    """Dashboard login. Roles: admin (sync roster, request scans, manage instructors),
    instructor (read only, plus a page for the students assigned to them) or viewer (read only)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)  # stored lower-case; an email for instructors
    display_name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # the super admin: an admin nobody can edit, deactivate or delete from the dashboard
    # (only `create-user` on the server changes it)
    is_super: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # audit, as on Student
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_via: Mapped[str | None] = mapped_column(String(10))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_via: Mapped[str | None] = mapped_column(String(10))


class InstructorCollege(Base):
    """An instructor follows every active student of this college."""

    __tablename__ = "instructor_colleges"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), primary_key=True)


class InstructorStudent(Base):
    """An instructor follows this student (in addition to whole colleges)."""

    __tablename__ = "instructor_students"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)


class Upload(Base):
    """One Excel upload (students or instructors): who, when, what it did, and whether it
    has been undone. Kept 90 days."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # students | instructors
    filename: Mapped[str] = mapped_column(String(255))
    uploaded_by: Mapped[str] = mapped_column(String(120))
    via: Mapped[str] = mapped_column(String(10), default="excel")  # excel | cli
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)  # added / updated / restored / unchanged / skipped
    issues: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(10), default="applied")  # applied | undone
    undone_by: Mapped[str | None] = mapped_column(String(120))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undo_result: Mapped[dict | None] = mapped_column(JSON)  # reverted / skipped (with reasons)


class UploadChange(Base):
    """What one upload did to one row: only the fields it changed, before and after."""

    __tablename__ = "upload_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    entity: Mapped[str] = mapped_column(String(16))  # student | instructor | college
    entity_id: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(300))  # "NW001 · Asha Rao"
    action: Mapped[str] = mapped_column(String(10))  # added | updated | restored
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)


class ScanRequest(Base):
    """A scan asked for from the dashboard; the worker picks it up on its next tick."""

    __tablename__ = "scan_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_slug: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16), default="provisional")
    requested_by: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    scan_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_runs.id"))
    error: Mapped[str | None] = mapped_column(Text)


class RatingHistory(Base):
    """A student's LeetCode rating after each contest they attended (from LeetCode's
    userContestRankingHistory; covers all their contests, not only scanned ones)."""

    __tablename__ = "rating_history"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    start_time: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # contest start, unix
    contest_title: Mapped[str] = mapped_column(String(200))
    contest_slug: Mapped[str] = mapped_column(String(100))
    rating: Mapped[float] = mapped_column(Float)
    ranking: Mapped[int | None] = mapped_column(Integer)
    problems_solved: Mapped[int | None] = mapped_column(Integer)
    total_problems: Mapped[int | None] = mapped_column(Integer)


class AppState(Base):
    """Small key/value store, e.g. the worker's heartbeat."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- read model: analytics summaries (PostgreSQL only; see app/services/summaries.py) ----
# Derived data. Rebuilt from results/problem_results/contests/students inside the same
# transaction as every change to them, so they never drift. Never edited directly.


class StudentStats(Base):
    """Raw per-student numbers over the last `win` scanned contests (0 = all contests).
    Labels and scores (consistency, trend, ...) are applied in Python when read."""

    __tablename__ = "student_stats"

    win: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)
    scanned: Mapped[int] = mapped_column(Integer)
    attended: Mapped[int] = mapped_column(Integer)
    sum_solved: Mapped[int] = mapped_column(Integer)
    sum_solved_sq: Mapped[int] = mapped_column(Integer)
    max_solved: Mapped[int | None] = mapped_column(Integer)
    avg_top_pct: Mapped[float | None] = mapped_column(Float)
    best_global_rank: Mapped[int | None] = mapped_column(Integer)
    best_college_rank: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    total_time: Mapped[int] = mapped_column(BigInteger)
    longest_streak: Mapped[int] = mapped_column(Integer)
    current_streak: Mapped[int] = mapped_column(Integer)
    absent_streak: Mapped[int] = mapped_column(Integer)
    trend_k: Mapped[int | None] = mapped_column(Integer)  # contests on each side of the trend
    trend_recent: Mapped[int | None] = mapped_column(Integer)  # problems solved in the last k
    trend_before: Mapped[int | None] = mapped_column(Integer)  # ... and in the k before them
    # {label: [attempted, solved, median_secs, sum_secs, best_secs, wrong]}
    questions: Mapped[dict | None] = mapped_column(JSON)


class CohortStats(Base):
    """Aggregates over all active students for the last `win` scanned contests: per
    question, per college and per contest (medians and quartiles need the raw rows)."""

    __tablename__ = "cohort_stats"

    win: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
