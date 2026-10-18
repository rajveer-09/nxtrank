# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""Contest order (rank, then time) and students LeetCode penalised after a contest."""

from sqlalchemy import select

from app.db.models import Contest, Result, ScanRun
from app.scan.matcher import StudentResult, _assign_ranks
from app.scan.parser import Participant
from app.scan.matcher import Status
from app.services import flags
from app.services.roster import Student
from app.services.scans import write_rows
from tests.test_api import SLUG, client_for, env  # noqa: F401  (env is a fixture)


def _p(rank, time):
    return Participant(user_slug="u", display_name="u", global_rank=rank, leaderboard_rank=rank, rank_official=False,
                       score=10, total_time_secs=time, problems={}, data_region="")


def test_a_tied_rank_goes_to_less_time():
    people = [Student(row=i, name=n, college="", handle_raw=n, lc_slug=n, extra={}, roll_no=n, handle_status="valid", db_id=i)
              for i, n in enumerate(["slow", "fast", "first"])]
    results = [StudentResult(people[0], Status.SOLVED, _p(5, 900)), StudentResult(people[1], Status.SOLVED, _p(5, 600)),
               StudentResult(people[2], Status.SOLVED, _p(2, 1200))]
    _assign_ranks(results)
    assert {r.student.name: r.college_rank for r in results} == {"first": 1, "fast": 2, "slow": 3}


def test_judge():
    scored = flags.Before("solved", 40, 12, 3, None, None, None, None)
    row = {"status": "absent", "score": None, "global_rank": None}
    assert flags.judge(row, scored, 30000) == {"flag": "penalised", "early_rank": 40, "early_score": 12, "early_solved": 3}
    assert flags.judge({"status": "zero", "score": 0, "global_rank": 29000}, scored, 30000)["flag"] == "penalised"
    assert flags.judge({"status": "solved", "score": 12, "global_rank": 29800}, scored, 30000)["flag"] == "penalised"  # bottom 2%
    assert flags.judge({"status": "solved", "score": 12, "global_rank": 41}, scored, 30000) == {}  # just a normal shift
    assert flags.judge(row, flags.Before("zero", 900, 0, 0, None, None, None, None), 30000) == {}  # never scored
    assert flags.judge(row, None, 30000) == {}  # first scan: nothing to compare


def _rows(s):
    return [{"student_id": r.student_id, "status": r.status, "global_rank": r.global_rank,
             "leaderboard_rank": r.leaderboard_rank, "rank_source": r.rank_source, "college_rank": r.college_rank,
             "score": r.score, "solved_count": r.solved_count, "total_time_secs": r.total_time_secs, "problems": []}
            for r in s.scalars(select(Result).where(Result.contest_slug == SLUG))]


def _rescan(factory, change):
    with factory() as s:
        c = s.get(Contest, SLUG)
        meta = {k: getattr(c, k) for k in ("slug", "title", "contest_type", "start_time", "duration", "user_num", "questions")}
        rows = _rows(s)
        change(rows)
        run = ScanRun(contest_slug=SLUG, kind="final", status="complete")
        s.add(run)
        s.flush()
        write_rows(s, meta, rows, run)
        s.commit()


def test_a_scorer_removed_on_the_final_scan_is_flagged(env):
    _, factory = env
    with factory() as s:
        top = s.scalars(select(Result).where(Result.contest_slug == SLUG, Result.score > 0).order_by(Result.global_rank)).first()
        sid, rank, score = top.student_id, top.global_rank, top.score

    def remove(rows):
        for r in rows:
            if r["student_id"] == sid:
                r.update(status="absent", global_rank=None, leaderboard_rank=None, score=None, solved_count=None,
                         total_time_secs=None, college_rank=None)

    _rescan(factory, remove)
    with factory() as s:
        r = s.get(Result, (SLUG, sid))
        assert (r.flag, r.early_rank, r.early_score) == ("penalised", rank, score)
        assert s.scalars(select(Result).where(Result.flag.is_not(None))).all() == [r]  # nobody else

    _rescan(factory, remove)  # scanned again: still flagged, with the first numbers
    with factory() as s:
        assert s.get(Result, (SLUG, sid)).early_rank == rank

    c = client_for(env, "viewer")
    row = next(x for x in c.get(f"/api/contests/{SLUG}/results").json()["rows"] if x["student_id"] == sid)
    assert row["flagged"] == {"early_rank": rank, "early_score": score, "early_solved": row["flagged"]["early_solved"]}
    assert "flagged_by_leetcode" in c.get(f"/api/contests/{SLUG}/export.csv").text.splitlines()[0]


def test_saved_ranks_are_always_one_two_three_in_contest_order(env):
    _, factory = env

    def scramble(rows):  # e.g. stale or odd input: every participant claims rank 1
        for r in rows:
            if r["college_rank"] is not None:
                r["college_rank"] = 1

    _rescan(factory, scramble)
    with factory() as s:
        ranked = s.scalars(select(Result).where(Result.contest_slug == SLUG, Result.college_rank.is_not(None))
                           .order_by(Result.college_rank)).all()
    assert [r.college_rank for r in ranked] == list(range(1, len(ranked) + 1))
    keys = [(r.global_rank, r.total_time_secs if r.total_time_secs is not None else 10**9) for r in ranked]
    assert keys == sorted(keys)
