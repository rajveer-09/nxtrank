# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Turn raw ranking rows into per-participant results."""

from dataclasses import dataclass

from app.leetcode.schemas import Question, RankRow, Submission

PENALTY_SECS = 300


@dataclass(frozen=True)
class ProblemResult:
    label: str  # "Q1".."Q4"
    question_id: int
    solve_secs: int  # accepted submission time - contest start (no penalty)
    fail_count: int  # wrong attempts before acceptance
    lang: str | None


@dataclass(frozen=True)
class Participant:
    user_slug: str
    display_name: str
    global_rank: int  # 1-based rank among leetcode.com users, as on the user's profile
    score: int
    total_time_secs: int | None  # finish time incl. penalties; None if nothing solved
    problems: dict[str, ProblemResult]  # keyed by label, in Q order
    data_region: str
    leaderboard_rank: int | None = None  # 1-based position on LeetCode's global leaderboard
    rank_official: bool = False  # global_rank comes from the student's LeetCode contest history

    @property
    def position(self) -> int:
        """Where this participant sits on the leaderboard pages."""
        return self.leaderboard_rank or self.global_rank

    @property
    def key(self) -> str:
        return self.user_slug.lower()

    @property
    def solved_count(self) -> int:
        return len(self.problems)


def question_labels(questions: list[Question]) -> dict[int, str]:
    """LeetCode lists contest questions in Q1..Qn order."""
    return {q.question_id: f"Q{i}" for i, q in enumerate(questions, start=1)}


def parse_participant(
    row: RankRow,
    subs: dict[str, Submission],
    start_time: int,
    labels: dict[int, str],
    *,
    rank_base: int = 0,
    global_rank: int | None = None,
) -> Participant:
    """`rank_base` is the rank LeetCode gives the winner (see rank_base()); `global_rank`
    is the leetcode.com-only rank when it differs from the leaderboard position."""
    found: dict[str, ProblemResult] = {}
    for sub in subs.values():
        label = labels.get(sub.question_id)
        if label is None:
            raise ValueError(f"{row.user_slug}: unknown question_id {sub.question_id}")
        found[label] = ProblemResult(
            label=label,
            question_id=sub.question_id,
            solve_secs=sub.date - start_time,
            fail_count=sub.fail_count,
            lang=sub.lang,
        )
    order = list(labels.values())
    problems = {label: found[label] for label in order if label in found}
    position = row.rank + 1 - rank_base
    return Participant(
        user_slug=row.user_slug,
        display_name=row.username,
        global_rank=global_rank or position,
        leaderboard_rank=position,
        score=row.score,
        total_time_secs=row.finish_time - start_time if problems else None,
        problems=problems,
        data_region=row.data_region,
    )


def parse_rows(
    rows: list[tuple[RankRow, dict[str, Submission]]],
    questions: list[Question],
    start_time: int,
) -> list[Participant]:
    labels = question_labels(questions)
    base = rank_base(row for row, _ in rows)
    com = leetcode_com_ranks((row for row, _ in rows), base)
    return [
        parse_participant(row, subs, start_time, labels, rank_base=base, global_rank=com.get(row.user_slug.lower()))
        for row, subs in rows
    ]


def rank_base(rows) -> int:
    """LeetCode numbers the leaderboard from 0 while a contest is fresh and from 1 once
    its ratings are published, so take the base from the winner's rank."""
    return 1 if min((r.rank for r in rows), default=0) == 1 else 0


def leetcode_com_ranks(rows, base: int) -> dict[str, int]:
    """1-based rank among leetcode.com users: the leaderboard position minus the
    leetcode.cn users ahead. Once ratings are published LeetCode merges leetcode.cn
    users into the global leaderboard, but profiles rank only .com users."""
    out: dict[str, int] = {}
    cn_ahead = 0
    cn_at_rank, last_rank = 0, None
    for r in sorted(rows, key=lambda r: r.rank):
        if r.rank != last_rank:  # CN users tied with this one are not ahead of it
            cn_ahead += cn_at_rank
            cn_at_rank, last_rank = 0, r.rank
        if r.data_region == "CN":
            cn_at_rank += 1
        else:
            out[r.user_slug.lower()] = r.rank + 1 - base - cn_ahead
    return out
