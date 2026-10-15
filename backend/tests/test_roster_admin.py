# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Managing students and instructors on the dashboard: one at a time, by Excel upload,
and the audit trail (when, who, how) on every row."""

import io
import time

from openpyxl import Workbook, load_workbook
from sqlalchemy import event, select

from app.db.models import Student
from app.services.roster_admin import MAX_STUDENT_ROWS, import_students
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)
from tests.test_worker import factory  # noqa: F401  (fixture)


def xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(c, what: str, data: bytes, name: str = "list.xlsx"):
    return c.post(f"/api/admin/{what}/import", params={"filename": name}, content=data,
                  headers={"Content-Type": "application/octet-stream"})


def test_add_edit_remove_restore_a_student(env):
    admin = client_for(env, "admin")
    r = admin.post("/api/admin/students", json={"roll_no": " nw1 ", "name": "Asha  Rao", "college": "college a",
                                                "leetcode": "https://leetcode.com/u/Asha_R/", "extra": {"Batch": "2026"}})
    assert r.status_code == 201, r.text
    st = r.json()
    assert (st["roll_no"], st["name"], st["college"], st["handle"]) == ("NW1", "Asha Rao", "College A", "asha_r")
    assert (st["created_by"], st["created_via"], st["updated_via"]) == ("admin", "ui", "ui")

    assert "already belongs" in admin.post("/api/admin/students", json={"roll_no": "NW1", "name": "X"}).json()["detail"]
    assert "already used by Asha Rao" in admin.post(
        "/api/admin/students", json={"roll_no": "NW2", "name": "B", "leetcode": "asha_r"}).json()["detail"]
    assert "can't read" in admin.post("/api/admin/students", json={"roll_no": "NW3", "name": "C", "leetcode": "a b"}).json()["detail"]

    r = admin.put(f"/api/admin/students/{st['id']}", json={**st, "leetcode": "asha_new"})
    assert r.json()["handle"] == "asha_new" and r.json()["handle_status"] == "unchecked"

    assert admin.post(f"/api/admin/students/{st['id']}/active", json={"active": False}).json()["active"] is False
    listing = admin.get("/api/admin/students", params={"show": "removed"}).json()
    removed = next(s for s in listing["students"] if s["roll_no"] == "NW1")
    assert removed["active"] is False and removed["updated_by"] == "admin"
    assert "Batch" in listing["extra_columns"] and listing["max_upload_rows"] == MAX_STUDENT_ROWS
    assert listing["total"] == listing["removed"] == 1
    active = admin.get("/api/admin/students", params={"limit": 2}).json()  # active ones, a page at a time
    assert len(active["students"]) == 2 and active["total"] == active["active"] and all(s["active"] for s in active["students"])
    assert admin.get("/api/admin/students", params={"q": "nw1", "show": "all"}).json()["total"] == 1
    assert admin.post(f"/api/admin/students/{st['id']}/active", json={"active": True}).json()["active"] is True


def test_excel_upload_adds_updates_and_reports_bad_rows(env):
    from tests.test_admins import _with_super

    _with_super(env).post("/api/admin/colleges", json={"names": ["College C"]})  # only the super admin adds colleges
    admin = client_for(env, "admin")
    data = xlsx([
        ["Roll No", "Name", "College", "LeetCode", "Batch"],
        ["R1", "Top Ranker", "College A", "karanVk", 2025],  # existing: batch changed
        ["NW10", "New One", "College C", "new_one", 2027],  # added (and a new college)
        ["NW11", "", "College C", "x_y", 2027],  # no name
        ["NW10", "Dup Roll", "College C", "dup", 2027],  # roll twice
        ["NW12", "Dup Handle", "College C", "kunaallll", 2027],  # R2's handle
        [None, None, None, None, None],  # blank row, ignored
    ])
    r = upload(admin, "students", data)
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["added"], s["updated"], s["skipped"]) == (1, 1, 3)
    assert any("row 4" in i and "name is required" in i for i in s["issues"])
    assert any("row 5" in i and "also on row 3" in i for i in s["issues"])
    assert any("row 6" in i and "already used by" in i for i in s["issues"])

    students = {x["roll_no"]: x for x in admin.get("/api/admin/students", params={"show": "all", "limit": 5000}).json()["students"]}
    assert students["NW10"]["created_via"] == "excel" and students["NW10"]["created_by"] == "admin"
    assert students["NW10"]["extra"] == {"Batch": "2027"}  # 2027.0 in Excel -> "2027"
    assert students["R1"]["updated_via"] == "excel" and students["R1"]["created_via"] != "excel"
    assert "NW11" not in students

    # uploading again changes nothing
    again = upload(admin, "students", data).json()
    assert (again["added"], again["updated"], again["unchanged"]) == (0, 0, 2)


def test_upload_errors(env):
    admin = client_for(env, "admin")
    assert "Excel" in upload(admin, "students", b"hello", "list.txt").json()["detail"]
    assert "couldn't read" in upload(admin, "students", b"not a zip", "list.xlsx").json()["detail"]
    assert "Roll No" in upload(admin, "students", xlsx([["Name", "LeetCode"], ["A", "a"]])).json()["detail"]
    too_many = [["Roll No", "Name", "LeetCode"]] + [[f"X{i}", "N", ""] for i in range(MAX_STUDENT_ROWS + 1)]
    assert "per upload" in upload(admin, "students", xlsx(too_many)).json()["detail"]
    # CSV works too
    ok = upload(admin, "students", "Roll No,Name,LeetCode\nC1,From Csv,from_csv\n".encode(), "list.csv").json()
    assert ok["added"] == 1


def test_templates_download(env):
    admin = client_for(env, "admin")
    for what, first in (("students", "Roll No"), ("instructors", "Name")):
        r = admin.get(f"/api/admin/{what}/template.xlsx")
        assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
        ws = load_workbook(io.BytesIO(r.content)).worksheets[0]
        assert ws.cell(1, 1).value == first
    # the students template uploads cleanly as is -- its example colleges are new, so for a
    # regular admin the rows are skipped until the super admin adds those colleges
    template = admin.get("/api/admin/students/template.xlsx").content
    skipped = upload(admin, "students", template).json()
    assert skipped["skipped"] == 2 and all("Admin → Colleges" in i for i in skipped["issues"])
    from tests.test_admins import _with_super
    assert upload(_with_super(env), "students", template).json()["added"] == 2


def test_instructor_excel_upload_and_audit(env):
    admin = client_for(env, "admin")
    data = xlsx([
        ["Name", "Email", "Password", "Colleges", "Roll Nos", "Active"],
        ["Asha Rao", "Asha@x.in", "teach-password-1", "College A", "", "Yes"],
        ["Ravi", "ravi@x.in", "teach-password-2", "College A, College B", "R3; R4", ""],
        ["No Pass", "np@x.in", "", "College A", "", ""],  # new needs a password
        ["Bad College", "bc@x.in", "teach-password-3", "Nowhere", "", ""],
        ["Admin", "admin", "", "", "", ""],  # an admin login
        ["Weird", "w@x.in", "teach-password-4", "", "", "maybe"],
    ])
    s = upload(admin, "instructors", data).json()
    assert (s["added"], s["updated"], s["skipped"]) == (2, 0, 4), s
    assert len(s["issues"]) == 4
    rows = {i["email"]: i for i in admin.get("/api/admin/instructors").json()["instructors"]}
    assert rows["ravi@x.in"]["colleges"] == ["College A", "College B"] and rows["ravi@x.in"]["roll_nos"] == ["R3", "R4"]
    assert (rows["asha@x.in"]["created_via"], rows["asha@x.in"]["created_by"]) == ("excel", "admin")

    # update: deactivate Asha, keep her password
    s = upload(admin, "instructors", xlsx([["Name", "Email", "Active"], ["Asha R", "asha@x.in", "No"]])).json()
    assert s["updated"] == 1
    asha = next(i for i in admin.get("/api/admin/instructors").json()["instructors"] if i["email"] == "asha@x.in")
    assert asha["active"] is False and asha["name"] == "Asha R" and asha["updated_via"] == "excel"

    # editing on the dashboard is recorded as ui
    r = admin.put(f"/api/admin/instructors/{asha['id']}", json={**asha, "password": "", "active": True})
    assert r.json()["updated_via"] == "ui"


def test_big_upload_is_fast_and_uses_a_fixed_number_of_queries(factory):
    """5,000 rows: every row is checked in memory, then saved in one go."""
    rows = [["Roll No", "Name", "College", "LeetCode"]] + [
        [f"S{i:05d}", f"Student {i}", f"College {i % 50}", f"handle_{i}"] for i in range(MAX_STUDENT_ROWS)]
    with factory() as s:
        selects = []
        event.listen(s.get_bind(), "before_cursor_execute",
                     lambda conn, cur, stmt, *a: selects.append(stmt) if stmt.lstrip().upper().startswith("SELECT") else None)
        started = time.perf_counter()
        summary = import_students(s, rows, actor="admin")
        took = time.perf_counter() - started
        assert summary["added"] == MAX_STUDENT_ROWS and summary["skipped"] == 0
        assert len(selects) <= 5, len(selects)  # not one per row
        assert took < 30, took
        assert s.scalar(select(Student).where(Student.roll_no == "S04999")).college.name == "College 49"
