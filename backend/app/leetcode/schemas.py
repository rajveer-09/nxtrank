# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Typed models for LeetCode's (unofficial) contest JSON endpoints.

Unknown fields are ignored; missing or mistyped fields raise ValidationError so a
format change on LeetCode's side fails loudly instead of producing wrong results.
"""

from pydantic import BaseModel, ConfigDict, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Contest(_Model):
    id: int
    title: str
    title_slug: str
    start_time: int  # unix seconds
    duration: int  # seconds

    @property
    def end_time(self) -> int:
        return self.start_time + self.duration


class Question(_Model):
    question_id: int  # internal id, used as the key in submissions
    credit: int
    title: str = ""
    title_slug: str = ""


class ContestInfo(_Model):
    """GET /contest/api/info/{slug}/"""

    contest: Contest
    questions: list[Question] = []  # may be empty before the contest starts


class RankRow(_Model):
    user_slug: str  # the real handle (mixed case)
    username: str  # display name, may contain spaces -- never match on it
    rank: int  # 0-based
    score: int
    finish_time: int  # unix seconds, includes 300s penalty per wrong attempt
    data_region: str = "US"
    country_name: str | None = None


class Submission(_Model):
    question_id: int
    date: int  # unix seconds of the accepted submission
    fail_count: int
    lang: str | None = None


class RankingPage(_Model):
    """GET /contest/api/ranking/{slug}/?pagination={page}&region=global"""

    is_past: bool = True
    user_num: int
    questions: list[Question]
    total_rank: list[RankRow]
    # Parallel to total_rank; keys are str(question_id).
    submissions: list[dict[str, Submission]]

    @model_validator(mode="after")
    def _arrays_are_parallel(self) -> "RankingPage":
        if len(self.total_rank) != len(self.submissions):
            raise ValueError(
                f"total_rank ({len(self.total_rank)}) and submissions "
                f"({len(self.submissions)}) have different lengths"
            )
        return self
