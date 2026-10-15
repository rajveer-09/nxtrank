# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Command line entry point.

Database workflow (DATABASE_URL, default: SQLite in backend/data/):
    python -m app.cli init-db
    python -m app.cli import-students students.xlsx   # or add them on the dashboard (Admin page)
    python -m app.cli validate-handles
    python -m app.cli scan weekly-contest-520 [biweekly-contest-150 ...]
    python -m app.cli export weekly-contest-520 --out results.csv
    python -m app.cli status
    python -m app.cli worker          # runs forever: discovers contests, scans 30 min after they end
    python -m app.cli create-user alice --role admin
    python -m app.cli serve           # dashboard API (+ built frontend) on http://127.0.0.1:8000

One-off scan straight from a sheet/CSV to a CSV file, without the database:
    python -m app.cli scan weekly-contest-520 --roster students.csv --out results.csv
"""

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.migrate import upgrade
from app.db.models import Contest, ScanRun, Student
from app.db.session import make_engine, make_session_factory
from app.leetcode.client import LeetCodeClient, LeetCodeError
from app.scan.matcher import match_students
from app.scan.parser import parse_rows, question_labels
from app.scan.scanner import ContestNotFinishedError, ScanIncompleteError, scan_contest
from app.services.export import summarize, write_csv, write_json
from app.services.discovery import discover_contests, sync_past_contests
from app.services.handles import validate_handles
from app.services.ratings import sync_ratings
from app.services.notify import Notifier
from app.services.results import ContestNotScannedError, load_contest_results
from app.services.roster import RosterError, load_roster
from app.services.roster_admin import VIA_CLI, RosterEditError, import_students
from app.services.tabular import TableError, read_table
from app.services.scans import scan_and_store
from app.services.users import UserError, set_user
from app.worker import Worker

log = logging.getLogger("app.cli")

_SLUG = re.compile(r"(weekly|biweekly)-contest-\d+")

EXIT_OK, EXIT_ERROR, EXIT_INCOMPLETE = 0, 1, 2


def _safe_url(database_url: str) -> str:
    """The database URL without its password, for printing."""
    return make_url(database_url).render_as_string(hide_password=True)


def _session(args):
    upgrade(args.database_url)  # no-op when already at the latest schema
    return make_session_factory(make_engine(args.database_url))()


def _client(args) -> LeetCodeClient:
    return LeetCodeClient(proxy=args.proxy, rps=args.rps)


# ---- commands ---------------------------------------------------------------


def cmd_init_db(args) -> int:
    upgrade(args.database_url)
    print(f"database ready: {_safe_url(args.database_url)}")
    return EXIT_OK


def cmd_import_students(args) -> int:
    """Add / update students from an .xlsx or .csv (same as the dashboard's Excel upload)."""
    path = Path(args.file)
    try:
        rows = read_table(path.read_bytes(), path.name)
    except (OSError, TableError) as e:
        log.error("%s", e)
        return EXIT_ERROR
    with _session(args) as session:
        try:
            summary = import_students(session, rows, actor=args.by, via=VIA_CLI, source=path.name)
        except RosterEditError as e:
            log.error("%s", e)
            return EXIT_ERROR
    for issue in summary["issues"]:
        log.warning("%s", issue)
    print(f"students: {summary['added']} added, {summary['updated']} updated, {summary['restored']} restored, "
          f"{summary['unchanged']} unchanged, {summary['skipped']} skipped")
    return EXIT_OK


async def cmd_validate_handles(args) -> int:
    with _session(args) as session:
        async with _client(args) as client:
            summary = await validate_handles(session, client, recheck_all=args.all,
                                             concurrency=args.concurrency)
        invalid = session.scalars(
            select(Student).where(Student.active.is_(True), Student.handle_status == "invalid")
            .order_by(Student.roll_no)
        ).all()
    for st in invalid:
        log.warning("invalid handle: %s (%s) -> %r", st.roll_no, st.name, st.lc_handle_raw)
    print(f"handles: {summary.checked} checked ({summary.valid} valid, {summary.invalid} invalid), "
          f"{summary.errors} errors; {len(invalid)} active students have invalid handles")
    return EXIT_INCOMPLETE if summary.errors else EXIT_OK


async def cmd_scan(args) -> int:
    if args.roster:
        if len(args.slugs) != 1:
            log.error("--roster mode scans one contest at a time")
            return EXIT_ERROR
        return await _scan_to_file(args, args.slugs[0])

    exit_code = EXIT_OK
    with _session(args) as session:
        active = session.scalar(select(func.count()).where(Student.active.is_(True)))
        if not active:
            log.error("no active students in the database; add them on the Admin page or with import-students")
            return EXIT_ERROR
        async with _client(args) as client:
            for slug in args.slugs:
                try:
                    run = await scan_and_store(
                        session, client, slug, kind=args.kind, concurrency=args.concurrency,
                        allow_unfinished=args.allow_unfinished,
                    )
                except ContestNotFinishedError as e:
                    log.error("%s: contest not finished yet: %s", slug, e)
                    exit_code = max(exit_code, EXIT_ERROR)
                    continue
                except (ScanIncompleteError, LeetCodeError) as e:
                    log.error("%s: %s -- previous results (if any) kept", slug, e)
                    exit_code = EXIT_INCOMPLETE
                    continue
                stored = load_contest_results(session, slug)
                summary = summarize(stored.results)
                print(f"{stored.contest.title}: {run.user_num} participants, "
                      f"{run.pages_total} pages; " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return exit_code


async def _scan_to_file(args, slug: str) -> int:
    try:
        students, issues = load_roster(args.roster, google_credentials=args.google_credentials)
    except (OSError, RosterError) as e:
        log.error("%s", e)
        return EXIT_ERROR
    for issue in issues:
        log.warning("roster: %s", issue)
    log.info("roster: %d students loaded (%d issues)", len(students), len(issues))

    try:
        async with _client(args) as client:
            scan = await scan_contest(
                client, slug, concurrency=args.concurrency, allow_unfinished=args.allow_unfinished,
            )
    except ContestNotFinishedError as e:
        log.error("contest not finished yet: %s", e)
        return EXIT_ERROR
    except (ScanIncompleteError, LeetCodeError) as e:
        log.error("%s", e)
        log.error("nothing was written; re-run the scan")
        return EXIT_INCOMPLETE

    participants = parse_rows(scan.rows, scan.questions, scan.info.contest.start_time)
    results = match_students(students, participants)
    labels = list(question_labels(scan.questions).values())

    out_csv = Path(args.out or f"results/{slug}.csv")
    write_csv(out_csv, slug, results, labels)
    log.info("wrote %s", out_csv)
    if args.json:
        write_json(args.json, scan.info.contest, labels, scan.user_num, results)
        log.info("wrote %s", args.json)

    summary = summarize(results)
    print(f"{scan.info.contest.title}: {scan.user_num} participants, {scan.pages} pages scanned")
    print("  " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return EXIT_OK


def cmd_export(args) -> int:
    with _session(args) as session:
        try:
            stored = load_contest_results(session, args.slug)
        except ContestNotScannedError as e:
            log.error("%s", e)
            return EXIT_ERROR
    out_csv = Path(args.out or f"results/{args.slug}.csv")
    write_csv(out_csv, args.slug, stored.results, stored.labels)
    print(f"wrote {out_csv}")
    if args.json:
        write_json(args.json, stored.contest_schema, stored.labels, stored.contest.user_num or 0,
                   stored.results)
        print(f"wrote {args.json}")
    return EXIT_OK


async def cmd_sync_ratings(args) -> int:
    with _session(args) as session:
        async with _client(args) as client:
            summary = await sync_ratings(session, client, concurrency=args.concurrency)
    print(f"ratings: {summary.checked} students checked, {summary.rated} have a contest rating, "
          f"{summary.errors} errors")
    return EXIT_INCOMPLETE if summary.errors else EXIT_OK


async def cmd_discover(args) -> int:
    with _session(args) as session:
        async with _client(args) as client:
            new = await discover_contests(session, client)
            past = await sync_past_contests(session, client, full=args.full)
    print(f"new contests: {', '.join(new) or 'none'}; {len(past)} past contests added to the list")
    return _print_schedule(args)


def cmd_test_alert(args) -> int:
    notifier = Notifier.from_settings(args.settings)
    if not notifier.enabled:
        log.error("no alert channel configured: set SLACK_WEBHOOK_URL and/or "
                  "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")
        return EXIT_ERROR
    notifier.send("Test alert from the worker.")
    print("sent (check the channel; delivery errors are logged above)")
    return EXIT_OK


async def cmd_worker(args) -> int:
    session_factory = make_session_factory(make_engine(args.database_url))
    upgrade(args.database_url)
    notifier = Notifier.from_settings(args.settings)
    if not notifier.enabled:
        log.warning("no alert channel configured; alerts are only logged")
    worker = Worker(session_factory, lambda: _client(args), settings=args.settings,
                    notifier=notifier)
    if args.once:
        await worker.tick()
        return EXIT_OK
    await worker.run_forever(args.interval)
    return EXIT_OK


def cmd_create_user(args) -> int:
    import getpass

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass(f"password for {args.username}: ")
        if getpass.getpass("repeat password: ") != password:
            log.error("passwords don't match")
            return EXIT_ERROR
    with _session(args) as session:
        try:
            user, created = set_user(session, args.username, password, "admin" if args.super else args.role,
                                     is_super=True if args.super else None)
        except UserError as e:
            log.error("%s", e)
            return EXIT_ERROR
    print(f"{'created' if created else 'updated'} {'super admin' if user.is_super else user.role} user {user.username!r}")
    return EXIT_OK


def cmd_serve(args) -> int:
    import uvicorn

    from app.api.app import create_app

    if not args.settings.secret_key:
        log.warning("SECRET_KEY not set: logins reset whenever the server restarts")
    upgrade(args.database_url)
    settings = args.settings
    if args.database_url != settings.database_url:
        from dataclasses import replace

        settings = replace(settings, database_url=args.database_url)
    # app.requests logs every API call (with timings); uvicorn's own access log would repeat it
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info", access_log=False)
    return EXIT_OK


def _print_schedule(args) -> int:
    from datetime import datetime, timedelta, timezone

    from app.worker import Policy, format_time

    policy = Policy.from_settings(args.settings)
    now = datetime.now(timezone.utc)
    with _session(args) as session:
        contests = session.scalars(
            select(Contest).where(
                Contest.start_time + Contest.duration
                >= int((now - policy.lookback).timestamp())
            ).order_by(Contest.start_time)
        ).all()
        done = {slug for slug, in session.execute(
            select(ScanRun.contest_slug).where(ScanRun.status == "complete"))}
    tz = args.settings.display_tz
    print("contests (last 14 days and upcoming):" if contests else "no recent or upcoming contests known")
    for c in contests:
        end = datetime.fromtimestamp(c.start_time + c.duration, timezone.utc)
        state = "scanned" if c.slug in done else f"scan due {format_time(end + policy.scan_delay, tz)}"
        print(f"  {c.slug:24} starts {format_time(end - timedelta(seconds=c.duration), tz)}  {state}")
    return EXIT_OK


def cmd_status(args) -> int:
    with _session(args) as session:
        counts = dict(session.execute(
            select(Student.handle_status, func.count())
            .where(Student.active.is_(True)).group_by(Student.handle_status)
        ).all())
        inactive = session.scalar(select(func.count()).where(Student.active.is_(False)))
        runs = session.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(10)).all()

    print(f"database: {_safe_url(args.database_url)}")
    print(f"students: {sum(counts.values())} active ({', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'none'}), "
          f"{inactive} inactive")
    print("recent scans:" if runs else "no scans yet")
    for run in runs:
        line = f"  #{run.id} {run.contest_slug} {run.kind} {run.status} {run.started_at:%Y-%m-%d %H:%M}"
        if run.status == "complete":
            line += f" ({run.user_num} participants, {run.students} students)"
        elif run.error:
            line += f" -- {run.error[:120]}"
        print(line)
    return _print_schedule(args)


# ---- argument parsing ---------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true")
    common.add_argument("--database-url", default=settings.database_url,
                        help="default: $DATABASE_URL or SQLite in backend/data/")

    net = argparse.ArgumentParser(add_help=False)
    net.add_argument("--concurrency", type=int, default=4)
    net.add_argument("--rps", type=float, default=3.0, help="max requests per second")
    net.add_argument("--proxy", default=settings.proxy_url, help="proxy URL (default: $PROXY_URL)")

    sheet = argparse.ArgumentParser(add_help=False)
    sheet.add_argument("--google-credentials", default=settings.google_credentials,
                       help="service-account JSON key for private sheets "
                            "(default: $GOOGLE_APPLICATION_CREDENTIALS)")

    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", parents=[common], help="create/upgrade the database schema")

    p = sub.add_parser("import-students", parents=[common],
                       help="add / update students from an Excel (.xlsx) or CSV file")
    p.add_argument("file", help="file with Roll No, Name, College, LeetCode (+ any other) columns")
    p.add_argument("--by", default="cli", help="recorded as who made the change (default: cli)")

    p = sub.add_parser("validate-handles", parents=[common, net],
                       help="check that students' LeetCode handles exist")
    p.add_argument("--all", action="store_true", help="re-check all handles, not just new/changed")

    p = sub.add_parser("scan", parents=[common, net, sheet],
                       help="scan finished contest(s) and store results")
    p.add_argument("slugs", nargs="+", metavar="slug", help="e.g. weekly-contest-520")
    p.add_argument("--kind", choices=["provisional", "final"], default="provisional")
    p.add_argument("--allow-unfinished", action="store_true",
                   help="scan even if the contest hasn't ended (results are partial)")
    p.add_argument("--roster", help="file mode: Google Sheet URL or CSV; skip the database")
    p.add_argument("--out", help="file mode: output CSV (default: results/<slug>.csv)")
    p.add_argument("--json", help="file mode: also write JSON")

    p = sub.add_parser("export", parents=[common], help="export stored results to CSV/JSON")
    p.add_argument("slug")
    p.add_argument("--out", help="output CSV (default: results/<slug>.csv)")
    p.add_argument("--json", help="also write JSON")

    sub.add_parser("status", parents=[common], help="show roster, scans and upcoming contests")

    p = sub.add_parser("discover", parents=[common, net],
                       help="find upcoming contests and update the list of past contests")
    p.add_argument("--full", action="store_true", help="re-read the whole past-contest list")

    sub.add_parser("sync-ratings", parents=[common, net],
                   help="refresh students' LeetCode contest ratings (the worker does this after final scans)")

    sub.add_parser("test-alert", parents=[common], help="send a test Slack/Telegram alert")

    p = sub.add_parser("create-user", parents=[common],
                       help="create a dashboard login, or reset its password/role")
    p.add_argument("username")
    p.add_argument("--role", choices=["admin", "viewer"], default="viewer")
    p.add_argument("--super", action="store_true",
                   help="make this admin the super admin (can't be changed from the dashboard)")
    p.add_argument("--password-stdin", action="store_true", help="read the password from stdin")

    p = sub.add_parser("serve", parents=[common], help="run the dashboard API (+ built frontend)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)

    p = sub.add_parser("worker", parents=[common, net],
                       help="run the scheduler: discover contests, scan them after they end")
    p.add_argument("--once", action="store_true", help="run a single check and exit")
    p.add_argument("--interval", type=float, default=60, help="seconds between checks")

    args = parser.parse_args(argv)
    args.settings = settings
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    for slug in getattr(args, "slugs", None) or [getattr(args, "slug", None)]:
        if slug is not None and not _SLUG.fullmatch(slug):
            parser.error(f"invalid contest slug {slug!r}")

    commands = {
        "init-db": cmd_init_db,
        "import-students": cmd_import_students,
        "validate-handles": cmd_validate_handles,
        "scan": cmd_scan,
        "export": cmd_export,
        "status": cmd_status,
        "discover": cmd_discover,
        "sync-ratings": cmd_sync_ratings,
        "test-alert": cmd_test_alert,
        "worker": cmd_worker,
        "create-user": cmd_create_user,
        "serve": cmd_serve,
    }
    result = commands[args.command](args)
    return asyncio.run(result) if asyncio.iscoroutine(result) else result


if __name__ == "__main__":
    sys.exit(main())
