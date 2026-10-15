# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Load the student roster from a Google Sheet or a CSV file.

The first row is the header. Headers are matched loosely (case, spaces and
punctuation ignored), so Google Form headers like "Full Name" or
"LeetCode Profile URL" work:

- name:    `name`, `full_name`, `student_name`
- handle:  `leetcode`, `leetcode_handle`, `leetcode_username`, `leetcode_url`, `handle`,
           `username`, or else the first header containing "leetcode".
           A handle or a profile URL both work.
- college: `college`, `college_name` (optional)
- roll no: `roll_no`, `roll_number`, `student_id`, ... (optional for one-off CSV scans,
           required to sync into the database -- it identifies the student)

Any other columns (batch, section, email...) are kept and copied to the output.
"""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services import gsheets

NAME_COLUMNS = ("name", "full_name", "student_name")
HANDLE_COLUMNS = (
    "leetcode", "leetcode_handle", "leetcode_username", "leetcode_url", "handle", "username",
)
COLLEGE_COLUMNS = ("college", "college_name")
ROLL_COLUMNS = (
    "roll_no", "roll_number", "rollno", "roll", "student_id", "studentid", "registration_no",
    "registration_number", "reg_no", "id",
)

_PROFILE_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?leetcode\.(?:com|cn)/(?:u/)?([^/?#\s]+)", re.IGNORECASE
)
_VALID_HANDLE = re.compile(r"[a-z0-9_.\-]+")


def normalize_handle(raw: str | None) -> str | None:
    """'https://leetcode.com/u/Rahul_V/' / '@Rahul_V' / ' rahul_v ' -> 'rahul_v'.

    Returns None if nothing handle-like remains.
    """
    s = (raw or "").strip()
    m = _PROFILE_URL.match(s)
    if m:
        s = m.group(1)
    s = s.strip().strip("/").lstrip("@").lower()
    return s if _VALID_HANDLE.fullmatch(s) else None


def _header_key(header: str) -> str:
    """'LeetCode Profile URL' -> 'leetcode_profile_url'"""
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


class RosterError(Exception):
    pass


@dataclass(frozen=True)
class Student:
    row: int  # row number in the sheet/file (header is row 1)
    name: str
    college: str
    handle_raw: str
    lc_slug: str | None  # normalized handle, None if missing/unparseable
    extra: dict[str, str] = field(default_factory=dict)
    roll_no: str = ""
    handle_status: str = "unchecked"  # valid | invalid | unchecked (set from the DB)
    db_id: int | None = None


def load_roster(
    source: str | Path, *, google_credentials: str | None = None
) -> tuple[list[Student], list[str]]:
    """Load from a Google Sheet URL or a CSV path. Returns (students, issues);
    issues are human-readable warnings about bad rows."""
    if gsheets.is_sheet_url(str(source)):
        try:
            rows = gsheets.fetch_rows(str(source), credentials_file=google_credentials)
        except gsheets.SheetError as e:
            raise RosterError(str(e)) from e
    else:
        with open(source, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    return parse_roster(rows, str(source))


def parse_roster(rows: list[list[str]], source: str = "roster") -> tuple[list[Student], list[str]]:
    if not rows or not any(h.strip() for h in rows[0]):
        raise RosterError(f"{source}: empty or missing header row")
    header = [h.strip() for h in rows[0]]
    keys = {}
    for idx, h in enumerate(header):
        if h:
            keys.setdefault(_header_key(h), idx)

    def find(aliases) -> int | None:
        return next((keys[a] for a in aliases if a in keys), None)

    name_idx = find(NAME_COLUMNS)
    if name_idx is None:
        raise RosterError(f"{source}: missing name column (one of: {', '.join(NAME_COLUMNS)})")
    handle_idx = find(HANDLE_COLUMNS)
    if handle_idx is None:
        handle_idx = next((i for k, i in keys.items() if "leetcode" in k), None)
    if handle_idx is None:
        raise RosterError(
            f"{source}: missing LeetCode handle column (one of: {', '.join(HANDLE_COLUMNS)}, "
            "or any header containing 'leetcode')"
        )
    college_idx = find(COLLEGE_COLUMNS)
    roll_idx = find(ROLL_COLUMNS)
    known = {name_idx, handle_idx, college_idx, roll_idx}
    extra_idx = [i for i, h in enumerate(header) if h and i not in known]

    students: list[Student] = []
    issues: list[str] = []
    first_row_for_slug: dict[str, int] = {}
    for row_no, raw_row in enumerate(rows[1:], start=2):
        # Sheets API drops trailing empty cells
        cells = [c.strip() for c in raw_row] + [""] * (len(header) - len(raw_row))
        name, raw = cells[name_idx], cells[handle_idx]
        if not name and not raw:
            continue
        slug = normalize_handle(raw)
        if not raw:
            issues.append(f"row {row_no} ({name}): no LeetCode handle")
        elif slug is None:
            issues.append(f"row {row_no} ({name}): can't parse LeetCode handle {raw!r}")
        elif slug in first_row_for_slug:
            issues.append(
                f"row {row_no} ({name}): handle {slug!r} already used by row {first_row_for_slug[slug]}"
            )
        else:
            first_row_for_slug[slug] = row_no
        students.append(
            Student(
                row=row_no,
                name=name,
                college=cells[college_idx] if college_idx is not None else "",
                handle_raw=raw,
                lc_slug=slug,
                extra={header[i]: cells[i] for i in extra_idx},
                roll_no=cells[roll_idx] if roll_idx is not None else "",
            )
        )
    return students, issues
