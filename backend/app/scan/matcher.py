# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Match roster students to leaderboard participants and compute ranks."""

from dataclasses import dataclass
from enum import StrEnum

from app.scan.parser import Participant
from app.services.roster import Student


class Status(StrEnum):
    SOLVED = "solved"  # on leaderboard, solved >= 1
    ZERO = "zero"  # on leaderboard, solved 0
    ABSENT = "absent"  # valid-looking handle, not on leaderboard
    INVALID_HANDLE = "invalid_handle"  # not on leaderboard, and LeetCode says the user doesn't exist
    NO_HANDLE = "no_handle"  # roster handle missing or unparseable
    DUPLICATE_HANDLE = "duplicate_handle"  # handle already used by an earlier roster row


@dataclass
class StudentResult:
    student: Student
    status: Status
    participant: Participant | None = None
    college_rank: int | None = None  # rank among portal students, see _assign_ranks


_STATUS_ORDER = {s: i for i, s in enumerate(Status)}


def match_students(students: list[Student], participants: list[Participant]) -> list[StudentResult]:
    # Students are leetcode.com users; a leetcode.cn user with the same handle is someone else.
    by_key = {p.key: p for p in participants if p.data_region != "CN"}
    claimed: set[str] = set()
    results: list[StudentResult] = []

    for student in students:
        slug = student.lc_slug
        if not slug:
            results.append(StudentResult(student, Status.NO_HANDLE))
            continue
        if slug in claimed:
            results.append(StudentResult(student, Status.DUPLICATE_HANDLE))
            continue
        claimed.add(slug)
        p = by_key.get(slug)
        if p is None:
            invalid = student.handle_status == "invalid"
            results.append(StudentResult(student, Status.INVALID_HANDLE if invalid else Status.ABSENT))
        else:
            status = Status.SOLVED if p.solved_count else Status.ZERO
            results.append(StudentResult(student, status, p))

    _assign_ranks(results)
    results.sort(
        key=lambda r: (
            r.participant.global_rank if r.participant else float("inf"),
            _STATUS_ORDER[r.status],
            r.student.name.lower(),
        )
    )
    return results


def _assign_ranks(results: list[StudentResult]) -> None:
    """College rank = position among all participating students in the portal
    (the whole roster, across colleges). Global ranks are unique, so ordering by
    them is a strict order."""
    ranked = sorted(
        (r for r in results if r.participant), key=lambda r: r.participant.global_rank
    )
    for i, r in enumerate(ranked, start=1):
        r.college_rank = i
