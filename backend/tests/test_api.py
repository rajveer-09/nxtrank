# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import asyncio
import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from app.api import routes_auth
from app.api.app import create_app
from app.db.migrate import upgrade
from app.db.models import Student
from app.db.session import make_engine, make_session_factory
from app.services.roster import parse_roster
from app.services.roster_sync import sync_roster
from app.services.scans import scan_and_store
from app.services.users import set_user
from tests.conftest import FakeClient
from tests.test_worker import settings as make_settings
from tests.dbutil import fresh_url

SLUG = "weekly-contest-520"
ROSTER = [
    ["Roll No", "Name", "College", "Batch", "LeetCode"],
    ["R1", "Top Ranker", "College A", "2026", "karanVk"],
    ["R2", "Penalty Case", "College A", "2026", "kunaallll"],
    ["R3", "=HYPERLINK(\"evil\")", "College B", "2027", "SaranyaMohanasundharam"],
    ["R4", "Ghost", "College B", "2027", "ghost_handle_xyz"],
]


@pytest.fixture
def env(tmp_path):
    url = fresh_url(tmp_path)
    upgrade(url)
    factory = make_session_factory(make_engine(url))
    with factory() as s:
        students, issues = parse_roster(ROSTER, "sheet")
        sync_roster(s, students, issues, "sheet")
        asyncio.run(scan_and_store(s, FakeClient(), SLUG))
        set_user(s, "admin", "admin-password-1", "admin")
        set_user(s, "viewer", "viewer-password-1", "viewer")
    settings = replace(make_settings(), database_url=url,
                       frontend_dist=tmp_path / "dist")
    return settings, factory


def client_for(env, login: str | None = None) -> TestClient:
    settings, factory = env
    client = TestClient(create_app(settings, factory))
    if login:
        r = client.post("/api/auth/login", json={"username": login, "password": f"{login}-password-1"})
        assert r.status_code == 200, r.text
    return client


def test_requires_login(env):
    c = client_for(env)
    for path in ["/api/contests", f"/api/contests/{SLUG}/results", "/api/students",
                 "/api/admin/scan-runs", "/api/auth/me"]:
        assert c.get(path).status_code == 401, path
    assert c.get("/api/health").json() == {"ok": True}


def test_login_logout_and_throttle(env):
    c = client_for(env)
    assert c.post("/api/auth/login", json={"username": "viewer", "password": "nope"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "nobody", "password": "nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"username": " Viewer ", "password": "viewer-password-1"})
    assert r.json() == {"username": "viewer", "role": "viewer", "name": None, "is_super": False, "scans_enabled": True, "viewing_as": None}
    assert c.get("/api/auth/me").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401

    for _ in range(5):
        c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin-password-1"})
    assert r.status_code == 429


def test_password_reset_ends_sessions(env):
    c = client_for(env, "viewer")
    with env[1]() as s:
        set_user(s, "viewer", "a-new-password-2", "viewer")
    assert c.get("/api/auth/me").status_code == 401


def test_contest_list_and_detail(env):
    c = client_for(env, "viewer")
    data = c.get("/api/contests").json()
    assert [x["slug"] for x in data["items"]] == [SLUG] and data["total"] == 1
    item = data["items"][0]
    assert item["state"] == "provisional" and item["has_data"] is True
    assert item["summary"]["students"] == 4
    assert item["summary"]["participated"] == 3
    assert item["summary"]["best_global_rank"] == 1

    detail = c.get(f"/api/contests/{SLUG}").json()
    q = {x["label"]: x for x in detail["questions"]}
    assert q["Q1"]["solved"] == 3 and q["Q3"]["solved"] == 1
    assert q["Q4"]["url"] == "https://leetcode.com/problems/lexicographically-largest-power-array/"
    assert c.get("/api/contests/weekly-contest-1").status_code == 404


def test_results_rows(env):
    c = client_for(env, "viewer")
    data = c.get(f"/api/contests/{SLUG}/results").json()
    assert data["labels"] == ["Q1", "Q2", "Q3", "Q4"]
    rows = {r["roll_no"]: r for r in data["rows"]}
    assert rows["R2"]["global_rank"] == 976
    assert rows["R2"]["ranking_url"].endswith("/ranking/40/?region=global_v2")
    assert rows["R2"]["problems"]["Q4"]["fail_count"] == 2
    assert rows["R1"]["extra"] == {"Batch": "2026"}
    assert rows["R4"]["status"] == "absent" and rows["R4"]["ranking_url"] is None


def test_exports(env):
    c = client_for(env, "viewer")
    r = c.get(f"/api/contests/{SLUG}/export.csv")
    assert r.headers["content-disposition"] == f'attachment; filename="{SLUG}.csv"'
    text = r.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text  # formula injection neutralised

    r = c.get(f"/api/contests/{SLUG}/export.xlsx")
    ws = load_workbook(io.BytesIO(r.content)).active
    header = [cell.value for cell in ws[1]]
    rank = ws.cell(row=2, column=header.index("global_rank") + 1)
    assert rank.value == 1
    assert rank.hyperlink.target.endswith("/ranking/1/?region=global_v2")
    names = [ws.cell(row=i, column=header.index("name") + 1).value for i in range(2, 6)]
    assert "'=HYPERLINK(\"evil\")" in names


def _sheet(content: bytes) -> tuple[list[str], list[dict]]:
    ws = load_workbook(io.BytesIO(content)).active
    header = [cell.value for cell in ws[1]]
    return header, [dict(zip(header, (c.value for c in row))) for row in ws.iter_rows(min_row=2)]


def test_filtered_exports(env):
    c = client_for(env, "viewer")
    # no filter: everyone, no selection rank
    header, rows = _sheet(c.get(f"/api/contests/{SLUG}/export.xlsx").content)
    assert len(rows) == 4 and "rank_in_selection" not in header

    r = c.get(f"/api/contests/{SLUG}/export.xlsx", params={"college": "College B"})
    assert r.headers["content-disposition"] == f'attachment; filename="{SLUG}-college-b.xlsx"'
    header, rows = _sheet(r.content)
    assert {row["roll_no"] for row in rows} == {"R3", "R4"}
    assert header.index("rank_in_selection") == header.index("global_rank") + 1
    ranked = [row for row in rows if row["college_rank"]]
    assert [row["rank_in_selection"] for row in ranked] == list(range(1, len(ranked) + 1))

    # sheet columns, status and search combine; the leaderboard's rules
    header, rows = _sheet(c.get(f"/api/contests/{SLUG}/export.xlsx",
                                params={"extra.Batch": "2026", "status": "participated"}).content)
    assert [row["roll_no"] for row in rows] == ["R1", "R2"]
    assert [row["rank_in_selection"] for row in rows] == [1, 2]
    header, rows = _sheet(c.get(f"/api/contests/{SLUG}/export.xlsx", params={"q": "ghost"}).content)
    assert [row["roll_no"] for row in rows] == ["R4"] and rows[0]["rank_in_selection"] is None

    r = c.get(f"/api/contests/{SLUG}/export.csv", params={"extra.Batch": "2027"})
    assert r.headers["content-disposition"] == f'attachment; filename="{SLUG}-2027.csv"'
    lines = r.content.decode("utf-8-sig").strip().splitlines()
    assert len(lines) == 3 and "rank_in_selection" in lines[0]
    assert c.get(f"/api/contests/{SLUG}/export.xlsx", params={"mine": "true"}).status_code == 400


def test_group_report(env):
    assert client_for(env, "viewer").get("/api/admin/groups/report").status_code == 403
    c = client_for(env, "admin")
    data = c.get("/api/admin/groups/report", params={"key": "Batch", "value": "2026"}).json()
    assert data["key"] == "Batch" and data["value"] == "2026"
    assert {"key": "Batch", "values": ["2026", "2027"]} in data["options"]
    assert [ct["slug"] for ct in data["contests"]] == [SLUG]
    contest = data["contests"][0]
    assert contest["students"] == 2 and contest["participated"] == 2
    assert [t["name"] for t in contest["top"]] == ["Top Ranker", "Penalty Case"]
    students = data["students"]
    assert [s["roll_no"] for s in students] == ["R1", "R2"]
    assert [s["rank"] for s in students] == [1, 2]
    assert [s["results"][SLUG]["rank"] for s in students] == [1, 2]
    assert students[1]["results"][SLUG]["global_rank"] == 976
    # nobody in the group: an empty report, not an error
    empty = c.get("/api/admin/groups/report").json()
    assert empty["value"] == "Top K" and empty["students"] == [] and empty["contests"][0]["students"] == 0


def test_students(env):
    c = client_for(env, "viewer")
    students = c.get("/api/students").json()["rows"]
    by_roll = {s["roll_no"]: s for s in students}
    assert by_roll["R1"]["contests_attended"] == 1
    assert by_roll["R4"]["contests_attended"] == 0 and by_roll["R4"]["contests_scanned"] == 1

    # filtered, sorted and paged on the server
    page = c.get("/api/students", params={"sort": "attended_desc", "limit": 2}).json()
    assert page["total"] == 4 and page["active"] == 4 and len(page["rows"]) == 2
    assert page["colleges"] == ["College A", "College B"]
    attended = [s["contests_attended"] for s in c.get("/api/students", params={"sort": "attended_desc"}).json()["rows"]]
    assert attended == sorted(attended, reverse=True)
    assert [s["roll_no"] for s in c.get("/api/students", params={"college": "College B"}).json()["rows"]] == ["R3", "R4"] \
        or {s["roll_no"] for s in c.get("/api/students", params={"college": "College B"}).json()["rows"]} == {"R3", "R4"}
    assert c.get("/api/students", params={"q": "kunaal"}).json()["total"] == 1  # by handle
    assert c.get("/api/students", params={"sort": "secret"}).status_code == 422

    detail = c.get(f"/api/students/{by_roll['R2']['id']}").json()
    assert detail["leetcode_url"] == "https://leetcode.com/u/kunaallll/"
    (h,) = detail["history"]
    assert h["contest_slug"] == SLUG and h["global_rank"] == 976 and h["college_rank"] == 2
    assert h["problems"]["Q4"]["fail_count"] == 2
    assert c.get("/api/students/9999").status_code == 404


def test_admin_endpoints_need_admin(env):
    c = client_for(env, "viewer")
    assert c.get("/api/admin/scan-runs").status_code == 403
    assert c.post("/api/admin/scans", json={"slug": SLUG}).status_code == 403
    assert c.get("/api/admin/students").status_code == 403
    assert c.post("/api/admin/students", json={"roll_no": "X", "name": "Y"}).status_code == 403
    assert c.post("/api/admin/students/import?filename=a.csv", content=b"x").status_code == 403


def test_admin_scan_requests_and_runs(env):
    c = client_for(env, "admin")
    r = c.post("/api/admin/scans", json={"slug": " Weekly-Contest-521 ", "kind": "provisional"})
    assert r.status_code == 202 and r.json()["contest_slug"] == "weekly-contest-521"
    again = c.post("/api/admin/scans", json={"slug": "weekly-contest-521"}).json()
    assert again["id"] == r.json()["id"]
    assert c.post("/api/admin/scans", json={"slug": "contest-1"}).status_code == 422
    assert [x["contest_slug"] for x in c.get("/api/admin/scan-requests").json()] == ["weekly-contest-521"]

    runs = c.get("/api/admin/scan-runs").json()
    assert runs[0]["contest_slug"] == SLUG and runs[0]["status"] == "complete"
    assert c.get("/api/contests").json()["items"][0]["state"] == "provisional"


def test_serves_built_frontend(env, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    c = client_for(env)
    assert c.get("/").text == "<html>app</html>"
    assert c.get(f"/contests/{SLUG}").text == "<html>app</html>"
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/favicon.svg").text == "<svg/>"
    assert c.get("/api/nope").status_code == 404
    assert c.get("/../pyproject.toml").text == "<html>app</html>"


def test_caching_and_precompressed_assets(env, tmp_path):
    import gzip

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)")
    (dist / "assets" / "app-abc123.js.gz").write_bytes(gzip.compress(b"console.log(1)"))
    c = client_for(env, "viewer")

    plain = c.get("/assets/app-abc123.js", headers={"Accept-Encoding": "identity"})
    assert plain.text == "console.log(1)" and "immutable" in plain.headers["cache-control"]
    packed = c.get("/assets/app-abc123.js", headers={"Accept-Encoding": "gzip"})
    assert packed.headers["content-encoding"] == "gzip" and packed.text == "console.log(1)"  # client decodes
    assert "javascript" in packed.headers["content-type"] and packed.headers["vary"] == "Accept-Encoding"
    assert c.get("/contests/x").headers["cache-control"] == "no-cache"  # index.html: always revalidate
    assert c.get("/api/contests").headers["cache-control"] == "private, no-store"  # time-dependent

    # data-only responses: kept by the browser and revalidated with their ETag
    first = c.get("/api/students")
    tag = first.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache" and tag.startswith('W/"')
    again = c.get("/api/students", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == tag
    assert c.get("/api/students?x=1", headers={"If-None-Match": tag}).status_code == 200  # another URL
    assert client_for(env, "admin").get("/api/students", headers={"If-None-Match": tag}).status_code == 200
    with env[1]() as s:  # any data change: a new version, so a new ETag
        s.scalars(select(Student).limit(1)).one().name = "Renamed"
        s.commit()
    changed = c.get("/api/students", headers={"If-None-Match": tag})
    assert changed.status_code == 200 and changed.headers["etag"] != tag


def test_analytics_endpoints(env):
    c = client_for(env, "viewer")
    o = c.get("/api/analytics").json()
    assert o["summary"]["students"] == 4 and o["window"]["contests"] == 1
    assert c.get("/api/analytics", params={"college": "College B"}).json()["summary"]["students"] == 2
    assert c.get("/api/analytics", params={"extra.Batch": "2027"}).json()["summary"]["students"] == 2
    assert c.get("/api/analytics", params={"last": 0}).status_code == 422

    assert "students" not in o  # served a page at a time:
    page = c.get("/api/analytics/students", params={"sort": "name", "limit": 2}).json()
    assert page["total"] == 4 and [s["name"] for s in page["rows"]] == ["=HYPERLINK(\"evil\")", "Ghost"]
    assert "Q4" in page["rows"][0]["questions"]
    assert c.get("/api/analytics/students", params={"q": "r2"}).json()["total"] == 1
    assert c.get("/api/analytics/students", params={"sort": "secret"}).status_code == 422
    sid = c.get("/api/analytics/students", params={"q": "R2"}).json()["rows"][0]["id"]
    a = c.get(f"/api/students/{sid}/analytics").json()
    assert a["questions"]["Q4"]["wrong"] == 2 and a["series"][0]["global_rank"] == 976
    assert c.get("/api/students/999/analytics").status_code == 404

    d = c.get(f"/api/contests/{SLUG}").json()["distributions"]
    assert sum(d["time_bins"]["Q1"]) == 3 and len(d["colleges"]) == 2
    assert client_for(env).get("/api/analytics").status_code == 401


def test_server_timing_and_request_log(env, caplog):
    import json
    import logging
    import re

    c = client_for(env, "viewer")
    with caplog.at_level(logging.INFO, logger="app.requests"):
        r = c.get("/api/students", params={"limit": 2})
    timing = r.headers["server-timing"]
    m = re.fullmatch(r'db;dur=([\d.]+);desc="(\d+) queries", app;dur=([\d.]+), total;dur=([\d.]+)', timing)
    assert m, timing
    db, queries, app_ms, total = float(m[1]), int(m[2]), float(m[3]), float(m[4])
    assert queries >= 2 and total >= db and abs(db + app_ms - total) < 0.2

    (line,) = [json.loads(rec.getMessage()) for rec in caplog.records if rec.name == "app.requests"]
    assert line["route"] == "/api/students" and line["method"] == "GET" and line["status"] == 200
    assert line["queries"] == queries and line["ms"] >= line["db_ms"]

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.requests"):
        c.get("/api/health")
        c.get(f"/api/contests/{SLUG}/nope")
    lines = [json.loads(rec.getMessage()) for rec in caplog.records if rec.name == "app.requests"]
    assert [x["status"] for x in lines] == [404]  # health checks aren't logged; misses are


def test_sign_ins_are_logged_without_passwords(env, caplog):
    import logging

    c = client_for(env)
    with caplog.at_level(logging.INFO, logger="app.api.routes_auth"):
        c.post("/api/auth/login", json={"username": "viewer", "password": "wrong-guess-123"})
        c.post("/api/auth/login", json={"username": "viewer", "password": "viewer-password-1"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "failed login for 'viewer'" in text and "login viewer (viewer)" in text
    assert "wrong-guess-123" not in text and "viewer-password-1" not in text
