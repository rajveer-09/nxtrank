# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Time and EXPLAIN the analytics summary rebuild (read-only: everything is rolled back).

    python scripts/explain_rebuild.py [--plans] [--database-url URL]

In the plans, results and problem_results should each be read once, with no "Disk:" spills.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import make_engine, make_session_factory  # noqa: E402
from app.services import summaries  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--database-url", default=get_settings().database_url)
    ap.add_argument("--plans", action="store_true", help="print EXPLAIN (ANALYZE, BUFFERS) for the 'all' window")
    args = ap.parse_args()

    factory = make_session_factory(make_engine(args.database_url))
    with factory() as s:
        if not summaries.supported(s):
            sys.exit("the summaries only exist on PostgreSQL")
        count = lambda t: s.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # noqa: E731
        print(f"data: {count('students')} students, {count('contests')} contests, "
              f"{count('results')} results, {count('problem_results')} problem results\n")
        s.execute(text("SET LOCAL work_mem = '32MB'"))  # as the rebuild does
        total = 0.0
        for win in summaries.WINDOWS:
            for name, sql in (("students", summaries.student_select()), ("cohort", summaries.cohort_select())):
                t = time.perf_counter()
                s.execute(text(sql), {"n": win or None}).all()
                took = time.perf_counter() - t
                total += took
                print(f"  window {win or 'all':>3}  {name:8} {took * 1000:7.0f} ms")
        t = time.perf_counter()
        summaries.rebuild(s)
        print(f"\nqueries {total * 1000:.0f} ms; full rebuild (with writes) {(time.perf_counter() - t) * 1000:.0f} ms")
        if args.plans:
            for name, sql in (("students", summaries.student_select()), ("cohort", summaries.cohort_select())):
                plan = s.execute(text("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) " + sql), {"n": None}).scalars().all()
                print(f"\n---- {name}, window = all ----")
                print("\n".join(plan))
        s.rollback()


if __name__ == "__main__":
    main()
