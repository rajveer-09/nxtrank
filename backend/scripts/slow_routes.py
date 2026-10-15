# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Slowest API routes from the request log (p50 / p95 / max, database time, queries), plus
pg_stat_statements' most expensive statements with --database-url.

    journalctl -u dashboard-api --since yesterday -o cat | python scripts/slow_routes.py
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict


def parse(lines) -> dict[tuple[str, str], list[dict]]:
    by_route: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in lines:
        start = line.find('{"route"')
        if start < 0:
            continue
        try:
            rec = json.loads(line[start:])
        except ValueError:
            continue
        by_route[(rec.get("method", "?"), rec["route"])].append(rec)
    return by_route


def pct(values: list[float], p: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1]


def report(by_route, top: int) -> None:
    rows = []
    for (method, route), recs in by_route.items():
        ms = [r["ms"] for r in recs]
        errors = sum(1 for r in recs if r.get("status", 200) >= 500)
        rows.append((pct(ms, 95), method, route, len(recs), pct(ms, 50), max(ms),
                     statistics.fmean(r.get("db_ms", 0) for r in recs),
                     statistics.fmean(r.get("queries", 0) for r in recs), errors))
    rows.sort(reverse=True)
    print(f"{'route':52} {'calls':>6} {'p50':>7} {'p95':>7} {'max':>7} {'db avg':>7} {'queries':>7} {'5xx':>4}")
    for p95, method, route, n, p50, mx, db, q, errors in rows[:top]:
        print(f"{method + ' ' + route:52} {n:6d} {p50:7.1f} {p95:7.1f} {mx:7.1f} {db:7.1f} {q:7.1f} {errors:4d}")
    print("(milliseconds)")


def pg_top(url: str, top: int) -> None:
    sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
    from sqlalchemy import create_engine, text

    from app.db.session import normalize_url

    with create_engine(normalize_url(url)).connect() as conn:
        rows = conn.execute(text(
            "SELECT calls, round(total_exec_time) AS total_ms, round(mean_exec_time::numeric, 1) AS mean_ms, "
            "left(regexp_replace(query, '\\s+', ' ', 'g'), 90) AS query "
            "FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT :n"), {"n": top}).all()
    print(f"\n{'calls':>8} {'total ms':>10} {'mean ms':>8}  statement")
    for calls, total, mean, query in rows:
        print(f"{calls:8d} {total:10.0f} {mean:8.1f}  {query}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log", nargs="?", help="log file (default: standard input)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--database-url", help="also show pg_stat_statements' most expensive statements")
    args = ap.parse_args()
    with (open(args.log, encoding="utf-8") if args.log else sys.stdin) as f:
        by_route = parse(f)
    if not by_route:
        sys.exit("no request log lines found")
    report(by_route, args.top)
    if args.database_url:
        pg_top(args.database_url, args.top)


if __name__ == "__main__":
    main()
