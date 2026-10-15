# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import csv

import pytest

from app.scan.matcher import match_students
from app.scan.parser import parse_rows
from app.services.export import fmt_secs, write_csv
from app.services import gsheets
from app.services.roster import RosterError, load_roster, parse_roster
from tests.conftest import ranking


def write(tmp_path, text):
    path = tmp_path / "students.csv"
    path.write_text(text, encoding="utf-8-sig")  # Excel-style BOM
    return path


def test_load_roster_with_aliases_extras_and_issues(tmp_path):
    path = write(tmp_path, (
        "Name,College,Batch,LeetCode_URL\n"
        "Asha,A,2026,https://leetcode.com/u/Asha_1/\n"
        "Bala,B,2026,\n"
        "Chen,A,2027,not a handle!\n"
        "Dev,A,2027,asha_1\n"
        ",,,\n"
    ))
    students, issues = load_roster(path)
    assert [s.name for s in students] == ["Asha", "Bala", "Chen", "Dev"]
    assert students[0].lc_slug == "asha_1"
    assert students[0].extra == {"Batch": "2026"}
    assert len(issues) == 3
    assert "already used by row 2" in issues[2]  # sheet row numbers, header = row 1


def test_load_roster_requires_handle_column(tmp_path):
    with pytest.raises(RosterError, match="handle column"):
        load_roster(write(tmp_path, "name,college\nAsha,A\n"))


def test_google_form_style_headers_and_short_rows():
    rows = [
        ["Timestamp", "Email Address", "Full Name", "College Name", "LeetCode Profile URL"],
        ["1/1/2026", "a@x.com", "Asha", "A", "https://leetcode.com/u/Asha_1/"],
        ["1/1/2026", "b@x.com", "Bala", "B"],  # Sheets API drops trailing empty cells
    ]
    students, issues = parse_roster(rows, "sheet")
    assert [(s.name, s.college, s.lc_slug, s.row) for s in students] == [
        ("Asha", "A", "asha_1", 2), ("Bala", "B", None, 3),
    ]
    assert students[0].extra == {"Timestamp": "1/1/2026", "Email Address": "a@x.com"}
    assert issues == ["row 3 (Bala): no LeetCode handle"]


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://docs.google.com/spreadsheets/d/1AbC-d_9/edit#gid=123", ("1AbC-d_9", 123)),
        ("https://docs.google.com/spreadsheets/d/1AbC-d_9/edit?usp=sharing", ("1AbC-d_9", None)),
    ],
)
def test_parse_sheet_url(url, expected):
    assert gsheets.is_sheet_url(url)
    assert gsheets.parse_sheet_url(url) == expected


def test_load_roster_from_sheet_url(monkeypatch):
    calls = {}

    def fake_fetch(url, credentials_file=None):
        calls["args"] = (url, credentials_file)
        return [["name", "leetcode"], ["Asha", "asha_1"]]

    monkeypatch.setattr(gsheets, "fetch_rows", fake_fetch)
    url = "https://docs.google.com/spreadsheets/d/abc/edit#gid=0"
    students, _ = load_roster(url, google_credentials="key.json")
    assert calls["args"] == (url, "key.json")
    assert students[0].lc_slug == "asha_1"


def test_sheet_errors_become_roster_errors(monkeypatch):
    def boom(url, credentials_file=None):
        raise gsheets.SheetError("not shared")

    monkeypatch.setattr(gsheets, "fetch_rows", boom)
    with pytest.raises(RosterError, match="not shared"):
        load_roster("https://docs.google.com/spreadsheets/d/abc/edit")


def test_fmt_secs():
    assert fmt_secs(None) == ""
    assert fmt_secs(59) == "0:00:59"
    assert fmt_secs(5400) == "1:30:00"


def test_csv_end_to_end(tmp_path, info):
    p1 = ranking(1)
    participants = parse_rows(list(zip(p1.total_rank, p1.submissions)), p1.questions,
                              info.contest.start_time)
    roster, _ = load_roster(write(tmp_path, "name,college,leetcode\nKaran,X,KARANVK\nNobody,X,ghost\n"))
    out = tmp_path / "out.csv"
    write_csv(out, "weekly-contest-520", match_students(roster, participants), ["Q1", "Q2", "Q3", "Q4"])

    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["name"] == "Karan"
    assert "roll_no" not in rows[0]  # roster without roll numbers
    assert rows[0]["global_rank"] == "1"
    assert rows[0]["college_rank"] == "1"
    assert rows[0]["solved"] == "4"
    assert rows[0]["Q1_time"] == "0:02:18"
    assert rows[0]["Q1_wrong"] == "0"
    assert rows[0]["ranking_url"] == (
        "https://leetcode.com/contest/weekly-contest-520/ranking/1/?region=global_v2"
    )
    assert rows[1]["status"] == "absent"
    assert rows[1]["ranking_url"] == ""
    assert rows[1]["Q1_time"] == ""
