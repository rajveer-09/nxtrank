# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Export results: CSV / Excel (for spreadsheets), JSON / dicts (for files and the API)."""

import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import IO

from app.leetcode.links import contest_ranking_url
from app.leetcode.schemas import Contest
from app.scan.matcher import StudentResult

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def fmt_secs(secs: int | None) -> str:
    if secs is None:
        return ""
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _safe(value):
    """Stop spreadsheet apps from treating sheet-supplied text as a formula."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


PARTICIPATED = ("solved", "zero")


def select_results(
    results: list[StudentResult], *, student_ids: set[int] | None = None, college: str | None = None,
    q: str = "", status: str | None = None, extra: dict[str, str] | None = None,
) -> list[StudentResult]:
    """The rows the contest page's leaderboard shows for these filters (same rules as its
    filter bar): students in `student_ids`, one college, a status ("participated",
    "flagged" or a result status), sheet-column values, and a search of name, roll
    number and handle. The contest's order is kept."""
    needle = q.strip().lower()

    def keep(r: StudentResult) -> bool:
        st = r.student
        if student_ids is not None and st.db_id not in student_ids:
            return False
        if college and st.college != college:
            return False
        if status:
            if status == "participated":
                if r.status.value not in PARTICIPATED:
                    return False
            elif status == "flagged":
                if not r.flag:
                    return False
            elif r.status.value != status:
                return False
        if extra and any(st.extra.get(k) != v for k, v in extra.items()):
            return False
        handle = st.lc_slug or st.handle_raw or ""
        return not needle or any(needle in v.lower() for v in (st.name, st.roll_no or "", handle))

    return [r for r in results if keep(r)]


def table(slug: str, results: list[StudentResult], labels: list[str],
          selection: bool = False) -> tuple[list[str], list[list]]:
    """Header and rows shared by the CSV and Excel exports. The last column is ranking_url.
    `selection`: the rows are a filtered part of the contest, so a rank_in_selection
    column (1 = best of these rows) comes before the portal-wide college_rank."""
    extra_cols = list(results[0].student.extra) if results else []
    with_roll = any(r.student.roll_no for r in results)
    header = [
        *(["roll_no"] if with_roll else []), "name", "college", *extra_cols,
        "leetcode_handle", "status", "global_rank", *(["rank_in_selection"] if selection else []),
        "college_rank", "score", "solved", "total_time",
    ]
    for label in labels:
        header += [f"{label}_time", f"{label}_wrong"]
    with_flags = any(r.flag for r in results)  # only contests where LeetCode penalised someone
    if with_flags:
        header.append("flagged_by_leetcode")
    header.append("ranking_url")

    # results come in the contest's order, so the n-th ranked row is n-th of the selection
    in_selection = {id(r): i for i, r in enumerate((r for r in results if r.college_rank is not None), start=1)}
    rows = []
    for r in results:
        p = r.participant
        row = [
            *([r.student.roll_no] if with_roll else []),
            r.student.name,
            r.student.college,
            *(r.student.extra.get(c, "") for c in extra_cols),
            r.student.lc_slug or r.student.handle_raw,
            r.status.value,
            p.global_rank if p else "",
            *([in_selection.get(id(r), "")] if selection else []),
            r.college_rank or "",
            p.score if p else "",
            p.solved_count if p else "",
            fmt_secs(p.total_time_secs) if p else "",
        ]
        for label in labels:
            prob = p.problems.get(label) if p else None
            row += [fmt_secs(prob.solve_secs), prob.fail_count] if prob else ["", ""]
        if with_flags:
            row.append(f"early rank {r.flag['early_rank']}, {r.flag['early_score']} pts" if r.flag else "")
        row.append(contest_ranking_url(slug, p.position) if p else "")
        rows.append([_safe(v) for v in row])
    return header, rows


def write_csv_to(f: IO[str], slug: str, results: list[StudentResult], labels: list[str],
                 selection: bool = False) -> None:
    header, rows = table(slug, results, labels, selection)
    w = csv.writer(f)
    w.writerow(header)
    w.writerows(rows)


def write_csv(path: str | Path, slug: str, results: list[StudentResult], labels: list[str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel shows non-ASCII names correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        write_csv_to(f, slug, results, labels)


def xlsx_bytes(title: str, slug: str, results: list[StudentResult], labels: list[str],
               selection: bool = False) -> bytes:
    """Excel workbook; the global rank cell links to the LeetCode leaderboard page."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    header, rows = table(slug, results, labels, selection)
    rank_col = header.index("global_rank") + 1
    wb = Workbook()
    ws = wb.active
    ws.title = (title or slug)[:31]
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    link_font = Font(color="1C5CAB", underline="single")
    for i, row in enumerate(rows, start=2):
        ws.append(row)
        url = row[-1]
        if url:
            cell = ws.cell(row=i, column=rank_col)
            cell.hyperlink = url
            cell.font = link_font
    ws.freeze_panes = "A2"
    for idx, name in enumerate(header, start=1):
        width = max(len(str(name)), *(len(str(r[idx - 1])) for r in rows[:200])) if rows else len(name)
        ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 8), 40)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def result_dict(slug: str, r: StudentResult) -> dict:
    p = r.participant
    return {
        "student_id": r.student.db_id,
        "roll_no": r.student.roll_no or None,
        "name": r.student.name,
        "college": r.student.college,
        "extra": r.student.extra,
        "leetcode_handle": r.student.lc_slug or r.student.handle_raw,
        "status": r.status.value,
        "global_rank": p.global_rank if p else None,
        "ranking_url": contest_ranking_url(slug, p.position) if p else None,
        "rank_official": bool(p and p.rank_official),
        "leaderboard_rank": p.position if p else None,
        "college_rank": r.college_rank,
        "score": p.score if p else None,
        "solved": p.solved_count if p else None,
        "total_time_secs": p.total_time_secs if p else None,
        # LeetCode removed this entry, zeroed it or moved it to the bottom after the contest
        "flagged": r.flag,
        "problems": {
            label: {"solve_secs": prob.solve_secs, "fail_count": prob.fail_count, "lang": prob.lang}
            for label, prob in (p.problems.items() if p else ())
        },
    }


def write_json(
    path: str | Path, contest: Contest, labels: list[str], user_num: int,
    results: list[StudentResult],
) -> None:
    doc = {
        "contest": {
            "slug": contest.title_slug,
            "title": contest.title,
            "start_time": contest.start_time,
            "duration": contest.duration,
            "participants": user_num,
            "questions": labels,
        },
        "summary": summarize(results),
        "results": [result_dict(contest.title_slug, r) for r in results],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")


def summarize(results: list[StudentResult]) -> dict[str, int]:
    counts = Counter(r.status.value for r in results)
    return {"students": len(results), **counts}
