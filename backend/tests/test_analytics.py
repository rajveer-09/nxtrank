# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Analytics on a synthetic five-contest history:

  Steady  (College A, 2026): attends all 5, solves 3 every time (Q1-Q3), 1 wrong on Q2 each time
  Gone    (College A, 2027): solves Q1 in contests 1-2, then misses 3, 4, 5
  Climber (College B, 2026): solved 1, 1, 3, 4, 4 -> improving
"""

import asyncio

import pytest
from sqlalchemy import select

from app.db.migrate import upgrade
from app.db.models import College, Contest, ProblemResult, RatingHistory, Result, ScanRun, Student
from app.db.session import make_engine, make_session_factory
from app.services import analytics
from app.services.analytics import consistency_label, consistency_score, solved_trend
from app.services.ratings import sync_ratings, title_to_slug
from tests.dbutil import fresh_url

WEEK = 7 * 86400
T0 = 1_780_000_000
LABELS = ["Q1", "Q2", "Q3", "Q4"]


@pytest.fixture
def session(tmp_path):
    url = fresh_url(tmp_path)
    upgrade(url)
    with make_session_factory(make_engine(url))() as s:
        _seed(s)
        yield s


def _seed(s):
    a, b = College(name="College A"), College(name="College B")
    students = {
        "steady": Student(roll_no="R1", name="Steady", college=a, extra={"Batch": "2026"},
                          lc_slug="steady", handle_status="valid", lc_rating=1650.4),
        "gone": Student(roll_no="R2", name="Gone", college=a, extra={"Batch": "2027"},
                        lc_slug="gone", handle_status="valid"),
        "climber": Student(roll_no="R3", name="Climber", college=b, extra={"Batch": "2026"},
                           lc_slug="climber", handle_status="valid", lc_rating=1500.0),
    }
    s.add_all(students.values())
    s.flush()
    climber_solved = [1, 1, 3, 4, 4]
    for i in range(5):
        slug = f"weekly-contest-{500 + i}"
        s.add(Contest(slug=slug, title=f"Weekly Contest {500 + i}", contest_type="weekly",
                      start_time=T0 + i * WEEK, duration=5400, user_num=1000,
                      questions=[{"label": q, "question_id": 10 * i + n, "credit": 3,
                                  "title": q, "title_slug": q.lower()} for n, q in enumerate(LABELS)]))
        run = ScanRun(contest_slug=slug, status="complete")
        s.add(run)
        s.flush()

        def result(st, solved, rank, crank, problems):
            s.add(Result(contest_slug=slug, student_id=st.id, scan_run_id=run.id,
                         status=("solved" if solved else "zero") if rank else "absent",
                         global_rank=rank, college_rank=crank, score=solved * 4 if rank else None,
                         solved_count=solved if rank else None, total_time_secs=None))
            s.flush()
            for q, (secs, fails) in problems.items():
                s.add(ProblemResult(contest_slug=slug, student_id=st.id, q_label=q, question_id=0,
                                    solve_secs=secs, fail_count=fails, lang="python3"))

        result(students["steady"], 3, 200, 1, {"Q1": (300, 0), "Q2": (900, 1), "Q3": (2400, 0)})
        if i < 2:
            result(students["gone"], 1, 600, 3, {"Q1": (700, 2)})
        else:
            result(students["gone"], 0, None, None, {})
        n = climber_solved[i]
        result(students["climber"], n, 900 - 150 * i, 2,
               {q: (600 * (k + 1), 0) for k, q in enumerate(LABELS[:n])})
    s.commit()


def ids(s):
    return {st.name: st.id for st in s.scalars(select(Student))}


# ---- formulas ----------------------------------------------------------------------


def test_consistency_formula():
    assert consistency_score(2, 2, 0.0) is None  # too few contests
    assert consistency_score(5, 5, 0.0) == 100
    assert consistency_score(5, 2, 0.0) == round(100 * (0.6 * 0.4 + 0.4 * 1))
    assert consistency_score(5, 1, None) == 12  # one attendance: no stability credit
    assert consistency_score(4, 4, 3.0) == 60  # std >= 1.5 -> stability 0
    assert [consistency_label(x) for x in (85, 60, 45, 10, None)] == [
        "Very consistent", "Consistent", "Irregular", "Inconsistent", None]


def test_trend():
    assert solved_trend([1, 2, 3]) is None
    assert solved_trend([1, 1, 3, 4, 4]) == 2.0  # last 2 (4,4) vs previous 2 (1,3)
    assert solved_trend([4, 4, 4, 4, 1, 1, 1, 1]) == -3.0


# ---- per student -------------------------------------------------------------------


def test_student_metrics(session):
    w = analytics.load_window(session)
    sid = ids(session)
    steady = analytics.student_metrics(w, sid["Steady"])
    assert (steady["contests_scanned"], steady["contests_attended"]) == (5, 5)
    assert steady["consistency"] == 100 and steady["consistency_label"] == "Very consistent"
    assert (steady["current_streak"], steady["longest_streak"], steady["absent_streak"]) == (5, 5, 0)
    assert steady["avg_top_pct"] == 20.0
    q = steady["questions"]
    assert (q["Q1"]["solved"], q["Q1"]["attempted_contests"], q["Q1"]["solve_rate"]) == (5, 5, 1.0)
    assert (q["Q4"]["solved"], q["Q4"]["solve_rate"]) == (0, 0.0)
    assert q["Q2"]["wrong"] == 5 and q["Q2"]["wrong_per_solve"] == 1.0
    assert q["Q3"]["median_secs"] == 2400

    gone = analytics.student_metrics(w, sid["Gone"])
    assert (gone["contests_attended"], gone["absent_streak"], gone["current_streak"]) == (2, 3, 0)
    assert gone["attendance_rate"] == 0.4
    assert gone["questions"]["Q1"]["solved"] == 2 and gone["questions"]["Q1"]["attempted_contests"] == 2

    climber = analytics.student_metrics(w, sid["Climber"])
    assert climber["trend"] == 2.0 and climber["trend_label"] == "improving"
    assert climber["questions"]["Q4"]["solved"] == 2
    assert climber["best_global_rank"] == 300


def test_window_last_n(session):
    w = analytics.load_window(session, last=3)
    assert [c.slug for c in w.contests] == ["weekly-contest-502", "weekly-contest-503", "weekly-contest-504"]
    gone = analytics.student_metrics(w, ids(session)["Gone"])
    assert (gone["contests_scanned"], gone["contests_attended"]) == (3, 0)


# ---- cohort --------------------------------------------------------------------------


def test_overview(session):
    o = analytics.overview(session)
    assert o["window"]["contests"] == 5 and o["labels"] == LABELS
    assert o["summary"]["students"] == 3
    assert o["summary"]["participation_rate"] == round(12 / 15, 3)
    assert o["summary"]["avg_rating"] == 1575

    first, last = o["trend"][0], o["trend"][-1]
    assert first["participated"] == 3 and last["participated"] == 2
    assert last["questions"]["Q1"]["solve_rate"] == 1.0
    assert last["questions"]["Q4"]["solve_rate"] == 0.5

    q1 = next(q for q in o["questions"] if q["label"] == "Q1")
    assert (q1["attempts"], q1["solved"]) == (12, 12)
    assert q1["wrong"] == 4  # Gone: 2 wrong x 2 contests

    colleges = {c["college"]: c for c in o["colleges"]}
    assert colleges["College A"]["students"] == 2
    assert colleges["College A"]["participation_rate"] == 0.7

    leaders = o["leaders"]
    assert leaders["consistent"][0]["name"] == "Steady"
    assert leaders["top_performers"][0]["name"] == "Steady"
    assert [s["name"] for s in leaders["improved"]] == ["Climber"]
    (attention,) = leaders["attention"]
    assert attention["name"] == "Gone" and "missed the last 3 contests" in attention["reasons"]
    assert "questions" not in attention  # leader rows are trimmed

    assert o["filters"] == {"colleges": ["College A", "College B"], "extras": {"Batch": ["2026", "2027"]}}
    assert len(o["students"]) == 3 and "questions" in o["students"][0]


def test_overview_filters(session):
    o = analytics.overview(session, college="College A")
    assert o["summary"]["students"] == 2
    o = analytics.overview(session, extra={"Batch": "2026"})
    assert {s["name"] for s in o["students"]} == {"Steady", "Climber"}
    o = analytics.overview(session, college="Nowhere")
    assert o["summary"]["students"] == 0 and o["summary"]["participation_rate"] is None


def test_student_analytics_compares_with_cohort(session):
    sid = ids(session)["Steady"]
    session.add(RatingHistory(student_id=sid, start_time=T0, contest_title="Weekly Contest 500",
                              contest_slug="weekly-contest-500", rating=1600.2, ranking=200,
                              problems_solved=3, total_problems=4))
    session.commit()
    a = analytics.student_analytics(session, sid)
    assert a["questions"]["Q4"]["cohort_solve_rate"] == round(2 / 12, 3)
    assert len(a["series"]) == 5 and a["series"][0]["top_pct"] == 20.0
    assert a["rating"]["current"] == 1650 and a["rating"]["history"][0]["rating"] == 1600
    assert analytics.student_analytics(session, 999) is None


def test_contest_distributions(session):
    d = analytics.contest_distributions(session, "weekly-contest-504")
    assert d["bin_minutes"] == 10 and len(d["time_bins"]["Q1"]) == 9
    assert d["time_bins"]["Q1"][0] == 1  # Steady at 5 min
    assert d["time_bins"]["Q1"][1] == 1  # Climber at 10 min
    assert d["wrong_distribution"]["Q2"] == {"0": 1, "1": 1, "2": 0, "3+": 0}
    colleges = {c["college"]: c for c in d["colleges"]}
    assert colleges["College A"]["participated"] == 1 and colleges["College B"]["solved_all"] == 1


# ---- ratings -------------------------------------------------------------------------


class RatingClient:
    async def contest_ranking(self, handle):
        if handle == "gone":
            return None, []
        return ({"rating": 1712.6, "globalRanking": 5000, "topPercentage": 3.1, "attendedContestsCount": 2},
                [{"attended": True, "rating": 1600.0, "ranking": 300, "problemsSolved": 3, "totalProblems": 4,
                  "contest": {"title": "Weekly Contest 500", "startTime": T0}},
                 {"attended": True, "rating": 1712.6, "ranking": 150, "problemsSolved": 4, "totalProblems": 4,
                  "contest": {"title": "Biweekly Contest 150", "startTime": T0 + 3 * 86400}}])


def test_sync_ratings(session):
    summary = asyncio.run(sync_ratings(session, RatingClient()))
    assert (summary.checked, summary.rated, summary.errors) == (3, 2, 0)
    steady = session.get(Student, ids(session)["Steady"])
    assert round(steady.lc_rating) == 1713 and steady.lc_top_percentage == 3.1
    rows = session.scalars(select(RatingHistory).where(RatingHistory.student_id == steady.id)
                           .order_by(RatingHistory.start_time)).all()
    assert [r.contest_slug for r in rows] == ["weekly-contest-500", "biweekly-contest-150"]
    asyncio.run(sync_ratings(session, RatingClient()))  # re-sync replaces rows
    assert len(session.scalars(select(RatingHistory)).all()) == 4
    assert session.get(Student, ids(session)["Gone"]).lc_rating is None
    assert title_to_slug("Biweekly Contest 150") == "biweekly-contest-150"
