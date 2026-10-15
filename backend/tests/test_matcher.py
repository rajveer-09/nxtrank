# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import pytest

from app.scan.matcher import Status, match_students
from app.scan.parser import Participant, ProblemResult
from app.services.roster import Student, normalize_handle


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Rahul_Verma", "rahul_verma"),
        ("  rahul_verma  ", "rahul_verma"),
        ("@Rahul_Verma", "rahul_verma"),
        ("https://leetcode.com/u/Rahul_Verma/", "rahul_verma"),
        ("leetcode.com/u/Rahul_Verma", "rahul_verma"),
        ("https://www.leetcode.com/Rahul_Verma/", "rahul_verma"),
        ("https://leetcode.com/u/karanVk/?tab=contest", "karanvk"),
        ("rahul-v.01", "rahul-v.01"),
        ("", None),
        ("Rahul Verma", None),
        ("https://leetcode.com/", None),
    ],
)
def test_normalize_handle(raw, expected):
    assert normalize_handle(raw) == expected


def student(name, handle, college="A"):
    return Student(row=0, name=name, college=college, handle_raw=handle,
                   lc_slug=normalize_handle(handle))


def participant(slug, rank, solved):
    problems = {
        f"Q{i}": ProblemResult(f"Q{i}", i, 600 * i, 0, "python3")
        for i in range(1, solved + 1)
    }
    return Participant(user_slug=slug, display_name=slug, global_rank=rank,
                       score=solved * 4, total_time_secs=600 * solved if solved else None,
                       problems=problems, data_region="US")


def test_statuses_and_ranks():
    students = [
        student("Asha", "asha_1", "A"),
        student("Bala", "https://leetcode.com/u/Bala_X/", "B"),
        student("Chen", "chen", "A"),
        student("Dev", "dev", "A"),
        student("Esha", ""),
        student("Faiz", "ASHA_1", "B"),
    ]
    participants = [
        participant("Bala_X", 120, 3),
        participant("asha_1", 900, 2),
        participant("chen", 30000, 0),
        participant("someone_else", 1, 4),
    ]
    results = match_students(students, participants)
    by_name = {r.student.name: r for r in results}

    assert by_name["Bala"].status == Status.SOLVED
    assert by_name["Bala"].college_rank == 1
    assert by_name["Asha"].college_rank == 2  # ranked across colleges, not within "A"
    assert by_name["Chen"].status == Status.ZERO
    assert by_name["Chen"].college_rank == 3
    assert by_name["Dev"].status == Status.ABSENT and by_name["Dev"].college_rank is None
    assert by_name["Esha"].status == Status.NO_HANDLE
    assert by_name["Faiz"].status == Status.DUPLICATE_HANDLE

    # participants first in global-rank order, then the rest
    assert [r.student.name for r in results][:3] == ["Bala", "Asha", "Chen"]
