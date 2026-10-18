# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Read stored contest results back in the shape the exporters (and later the API) use."""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Contest, Result, Student
from app.db.models import ProblemResult as ProblemRow
from app.leetcode.schemas import Contest as ContestSchema
from app.scan.matcher import Status, StudentResult
from app.scan.parser import Participant, ProblemResult
from app.services import roster

_STATUS_ORDER = {s.value: i for i, s in enumerate(Status)}


@dataclass
class ContestResults:
    contest: Contest
    labels: list[str]
    results: list[StudentResult]

    @property
    def contest_schema(self) -> ContestSchema:
        c = self.contest
        return ContestSchema(id=0, title=c.title, title_slug=c.slug,
                             start_time=c.start_time, duration=c.duration)


class ContestNotScannedError(Exception):
    pass


def load_contest_results(session: Session, slug: str) -> ContestResults:
    contest = session.get(Contest, slug)
    if contest is None:
        raise ContestNotScannedError(f"{slug} has not been scanned yet")
    rows = session.scalars(
        select(Result)
        .where(Result.contest_slug == slug)
        .options(joinedload(Result.student).joinedload(Student.college))
    ).all()
    # every solve in the contest in one query (the primary key starts with the contest);
    # selectinload would send the student keys back in batches of 500, ~75 ms each
    problems: dict[int, list[ProblemRow]] = defaultdict(list)
    for pr in session.scalars(select(ProblemRow).where(ProblemRow.contest_slug == slug).order_by(ProblemRow.q_label)):
        problems[pr.student_id].append(pr)

    results = []
    for r in rows:
        st = r.student
        student = roster.Student(
            row=st.sheet_row or 0, name=st.name, college=st.college.name if st.college else "",
            handle_raw=st.lc_handle_raw, lc_slug=st.lc_slug, extra=dict(st.extra or {}),
            roll_no=st.roll_no, handle_status=st.handle_status, db_id=st.id,
        )
        participant = None
        if r.global_rank is not None:
            participant = Participant(
                user_slug=st.lc_username or st.lc_slug or "",
                display_name=st.lc_username or st.lc_slug or "",
                global_rank=r.global_rank,
                leaderboard_rank=r.leaderboard_rank,
                rank_official=r.rank_source == "profile",
                score=r.score or 0,
                total_time_secs=r.total_time_secs,
                problems={
                    pr.q_label: ProblemResult(pr.q_label, pr.question_id, pr.solve_secs,
                                              pr.fail_count, pr.lang)
                    for pr in problems.get(r.student_id, ())
                },
                data_region="",
            )
        flag = ({"early_rank": r.early_rank, "early_score": r.early_score, "early_solved": r.early_solved}
                if r.flag else None)
        results.append(StudentResult(student, Status(r.status), participant, r.college_rank, flag))

    # the contest's own order: college rank (rank among the portal's students in this
    # contest), a tie going to less total time; then those who didn't take part
    results.sort(key=lambda x: (
        x.college_rank if x.college_rank is not None else float("inf"),
        (x.participant.total_time_secs if x.participant and x.participant.total_time_secs is not None else float("inf")),
        x.participant.global_rank if x.participant else float("inf"),
        _STATUS_ORDER[x.status.value],
        x.student.name.lower(),
    ))
    labels = [q["label"] for q in contest.questions]
    return ContestResults(contest, labels, results)
