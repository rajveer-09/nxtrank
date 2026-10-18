from sqlalchemy import func, select

from app.cli import CLEAR_DATA_CONFIRMATION, EXIT_ERROR, EXIT_OK, main
from app.db.migrate import upgrade
from app.db.models import (
    CohortStats,
    College,
    Contest,
    InstructorStudent,
    ProblemResult,
    RatingHistory,
    Result,
    ScanRequest,
    ScanRun,
    Student,
    StudentStats,
    User,
)
from app.db.session import make_engine, make_session_factory
from tests.dbutil import fresh_url


def test_clear_data_previews_then_clears_and_preserves_setup(tmp_path, capsys):
    url = fresh_url(tmp_path)
    upgrade(url)
    factory = make_session_factory(make_engine(url))
    with factory() as session:
        college = College(name="Keep College")
        student = Student(roll_no="DUMMY1", name="Dummy Student", college=college)
        admin = User(username="admin@example.com", password_hash="not-a-real-hash", role="admin")
        instructor = User(username="instructor@example.com", password_hash="not-a-real-hash", role="instructor")
        session.add_all([student, admin, instructor])
        session.flush()
        session.add(InstructorStudent(user_id=instructor.id, student_id=student.id))
        contest = Contest(
            slug="weekly-contest-999", title="Dummy contest", contest_type="weekly", start_time=1, duration=1
        )
        run = ScanRun(contest_slug=contest.slug, status="complete")
        session.add_all([contest, run])
        session.flush()
        session.add(Result(contest_slug=contest.slug, student_id=student.id, scan_run_id=run.id, status="absent"))
        session.add(ScanRequest(contest_slug=contest.slug, scan_run_id=run.id))
        session.add(
            RatingHistory(
                student_id=student.id,
                start_time=1,
                contest_title="Dummy contest",
                contest_slug=contest.slug,
                rating=1,
                ranking=1,
                problems_solved=0,
                total_problems=4,
            )
        )
        session.flush()
        session.add(
            ProblemResult(
                contest_slug=contest.slug,
                student_id=student.id,
                q_label="Q1",
                question_id=1,
                solve_secs=1,
                fail_count=0,
            )
        )
        session.add(
            StudentStats(
                win=0,
                student_id=student.id,
                scanned=1,
                attended=0,
                sum_solved=0,
                sum_solved_sq=0,
                max_solved=0,
                avg_top_pct=None,
                best_global_rank=None,
                best_college_rank=None,
                points=0,
                total_time=0,
                longest_streak=0,
                current_streak=0,
                absent_streak=1,
                trend_k=None,
                trend_recent=None,
                trend_before=None,
                questions={},
            )
        )
        session.add(CohortStats(win=0, payload={}))
        session.commit()
        instructor_id, admin_id, college_id = instructor.id, admin.id, college.id
    capsys.readouterr()

    assert main(["clear-data", "--database-url", url]) == EXIT_OK
    preview = capsys.readouterr().out
    assert "mode: PREVIEW (no rows deleted)" in preview
    assert "contest definitions preserved (will show as not scanned): 1" in preview
    assert "students: 1" in preview
    assert "contest results: 1" in preview

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Student)) == 1
        assert session.scalar(select(func.count()).select_from(Contest)) == 1

    assert main(["clear-data", "--database-url", url, "--execute", "--confirm", "wrong"]) == EXIT_ERROR
    capsys.readouterr()

    assert main(["clear-data", "--database-url", url, "--execute", "--confirm", CLEAR_DATA_CONFIRMATION]) == EXIT_OK
    assert "student and scan data cleared; contest definitions preserved" in capsys.readouterr().out

    with factory() as session:
        for model in (
            Student,
            ScanRun,
            ScanRequest,
            Result,
            ProblemResult,
            RatingHistory,
            InstructorStudent,
            StudentStats,
            CohortStats,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.scalar(select(func.count()).select_from(Contest)) == 1
        assert session.get(User, admin_id) is not None
        assert session.get(User, instructor_id) is not None
        assert session.get(College, college_id) is not None
