# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""Students LeetCode penalised after a contest.

LeetCode reviews contests after they end. Entries it finds breaking the rules (for
example plagiarism) are removed from the final leaderboard, have their score zeroed,
or are moved to the bottom. NxtRank sees this by comparing a rescan with the results
it replaces: a student who scored on the earlier scan and on the later one is gone, on
0 points, or in the bottom BOTTOM_SHARE of the leaderboard is flagged "penalised".

The flag records what LeetCode did, not why: LeetCode doesn't publish reasons, so the
dashboard says "flagged by LeetCode" and shows the early and final positions."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Result

PENALISED = "penalised"
BOTTOM_SHARE = 0.02  # the last 2% of the leaderboard counts as "moved to the bottom"
ATTENDED = ("solved", "zero")


@dataclass(frozen=True)
class Before:
    status: str
    rank: int | None
    score: int | None
    solved: int | None
    flag: str | None
    early_rank: int | None
    early_score: int | None
    early_solved: int | None


def snapshot(session: Session, slug: str) -> dict[int, Before]:
    """The contest's current results, before a rescan replaces them."""
    return {r.student_id: Before(r.status, r.global_rank, r.score, r.solved_count, r.flag,
                                 r.early_rank, r.early_score, r.early_solved)
            for r in session.scalars(select(Result).where(Result.contest_slug == slug))}


def judge(row: dict, before: Before | None, user_num: int | None) -> dict:
    """The flag fields for a new result row, given what the student had before."""
    if before is None:
        return {}
    # what they had first: an earlier flag keeps its original early numbers
    if before.flag == PENALISED:
        early = (before.early_rank, before.early_score, before.early_solved)
    elif before.status in ATTENDED and (before.score or 0) > 0:
        early = (before.rank, before.score, before.solved)
    else:
        return {}
    gone = row["status"] not in ATTENDED
    zeroed = not gone and (row["score"] or 0) == 0
    bottom = (not gone and row["global_rank"] is not None and user_num
              and row["global_rank"] >= (1 - BOTTOM_SHARE) * user_num
              and (early[0] is None or early[0] < (1 - BOTTOM_SHARE) * user_num))
    if not (gone or zeroed or bottom):
        return {}
    return {"flag": PENALISED, "early_rank": early[0], "early_score": early[1], "early_solved": early[2]}
