# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Fill an empty local database with synthetic data (load tests, Lighthouse, trying the
dashboard at full size). Refuses non-local databases and databases that have students.

    python scripts/seed_demo.py --database-url URL --students 1500 --contests 52 \\
        --admin demo@example.com --password-stdin < password.txt
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.db.migrate import upgrade  # noqa: E402
from app.db.models import Student  # noqa: E402
from app.db.session import make_engine, make_session_factory, normalize_url  # noqa: E402
from app.services.users import set_user  # noqa: E402
from tests.test_summaries import seed  # noqa: E402  (the same generator the tests use)

LOCAL = {"localhost", "127.0.0.1", "::1"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--students", type=int, default=1500)
    ap.add_argument("--contests", type=int, default=52)
    ap.add_argument("--admin", help="also create this admin login")
    ap.add_argument("--password-stdin", action="store_true", help="the admin's password, from standard input")
    args = ap.parse_args()

    url = normalize_url(args.database_url)
    if url.get_backend_name() != "sqlite" and url.host not in LOCAL:
        sys.exit(f"refusing to seed demo data into {url.host}: local databases only")
    upgrade(args.database_url)
    factory = make_session_factory(make_engine(args.database_url))
    with factory() as s:
        if s.scalar(select(func.count()).select_from(Student)):
            sys.exit("this database already has students; seed an empty one")
    seed(factory, args.students, args.contests, seed=11)
    if args.admin:
        password = sys.stdin.readline().strip() if args.password_stdin else None
        if not password:
            sys.exit("--admin needs --password-stdin")
        with factory() as s:
            set_user(s, args.admin, password, "admin")
    print(f"seeded {args.students} students x {args.contests} contests")


if __name__ == "__main__":
    main()
