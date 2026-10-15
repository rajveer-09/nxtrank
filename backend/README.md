# NxtRank

LeetCode contest results, rankings and analytics for NxtWave students.

Scans finished LeetCode contests and stores every portal student's result in a database.
Students are added on the dashboard, one at a time or by Excel upload. Deployment: [../deploy/README.md](../deploy/README.md).

## Setup

```sh
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,sheets]"     # Windows (.venv/bin/python on Linux/macOS)
.venv/Scripts/python -m pip install -e ".[postgres]"       # only when using PostgreSQL
```

Configuration (environment variables):

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | SQLite file `backend/data/dashboard.db` | e.g. `postgresql+psycopg://user:pass@host/dbname` in production |
| `ROSTER_SHEET_URL` | — | Google Sheet with the students |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | service-account key for a private sheet |
| `PROXY_URL` | — | HTTP(S) proxy if the host IP gets Cloudflare challenges |
| `SLACK_WEBHOOK_URL` | — | alerts to a Slack channel ([incoming webhook](https://api.slack.com/messaging/webhooks)) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | — | alerts to a Telegram chat (bot from [@BotFather](https://t.me/BotFather)) |
| `DISPLAY_TZ` | `Asia/Kolkata` | timezone for times in alerts and `status` |
| `SCAN_DELAY_MINUTES` | `30` | first scan this long after a contest ends |
| `FINAL_SCAN_DAYS` | `4` | rescan this long after the end, once LeetCode has finalised ranks (`0` = off) |
| `SECRET_KEY` | random per start | signs dashboard login cookies; **set it**, or everyone is logged out on restart |
| `COOKIE_SECURE` | `false` | `true` when the dashboard is served over HTTPS |

See [.env.example](.env.example). Variables are read from the environment, and `backend/.env` is loaded
automatically if present (on the server, systemd's `EnvironmentFile` supplies them).

## Workflow

```sh
.venv/Scripts/python -m app.cli init-db                # create/upgrade tables (other commands also do this)
.venv/Scripts/python -m app.cli sync-roster            # Google Sheet -> students table
.venv/Scripts/python -m app.cli validate-handles       # check new/changed LeetCode handles exist
.venv/Scripts/python -m app.cli scan weekly-contest-520 biweekly-contest-150   # scan + store
.venv/Scripts/python -m app.cli export weekly-contest-520 --out results.csv --json results.json
.venv/Scripts/python -m app.cli status                 # students, last sync, recent scans, upcoming contests
.venv/Scripts/python -m app.cli sync-ratings           # LeetCode contest ratings (the worker does this after final scans)
.venv/Scripts/python -m app.cli worker                 # automation: runs forever (see below)
.venv/Scripts/python -m app.cli serve                  # dashboard (see below)
```

### `worker` (automation)

Checks the database every minute and does whatever is due:

| What | When |
|---|---|
| Discover upcoming contests (weekly + biweekly) and update the list of past contests | every 6 h; also fills in contests missed while the worker was down |
| Scans requested from the dashboard ("Get results", rescans) | next check, one at a time, oldest request first |
| Sync the roster from `ROSTER_SHEET_URL` | every 24 h, and right before each scan |
| Validate new/changed handles | before each scan |
| **Provisional scan** | contest end + 30 min (10:00 IST Sun / 22:00 IST Sat); retries at +45, +60, +90 min |
| **Final scan** | contest end + 4 days (plagiarism removals settled); retries 1 h and 3 h later; then refreshes LeetCode ratings |

Alerts go to Slack/Telegram: contest scheduled, results summary, scan failures (with the next retry time),
Cloudflare blocks, roster sync problems. `test-alert` sends a test message; `discover` runs discovery now.

All scheduling state is in the database, so the worker can be stopped and restarted any time: an interrupted scan is
retried, and contests that ended in the last 14 days without results are scanned on the next start. Run only
**one** worker per database. `worker --once` runs a single check (handy for testing or an external cron).

### `sync-roster`

Reads the sheet (`--source` or `$ROSTER_SHEET_URL`) and updates the `students` table, matching rows by
**roll number**:

- new roll numbers are added; changed name / college / handle / other columns are updated;
- a changed LeetCode handle is marked `unchecked` again for `validate-handles`;
- students no longer in the sheet are marked **inactive** (their past results stay); they're reactivated if they reappear;
- rows without a roll number, or with a duplicate one, are skipped and reported with their sheet row number;
- as a safety net, a sync that would deactivate more than half the active students is refused
  (usually the wrong tab or a renamed column). Use `--force` if it's intended.

### `validate-handles`

Asks LeetCode (GraphQL `matchedUser`) whether each handle exists. Only new/changed handles are checked
unless `--all` is given (~1,500 handles take ~8 min at 3 req/s). Students whose handle doesn't exist get status
`invalid_handle` in contest results instead of `absent`.

### `scan`

Scans the whole leaderboard of each finished contest and stores a result row for **every active student**
(including absent ones). Rescanning a contest replaces its results; `--kind final` marks the rescan done after
LeetCode finalises rankings. A failed scan is recorded and leaves earlier results untouched. `--sync` syncs the
roster first.

| Option | Default | |
|---|---|---|
| `--rps` | `3` | max requests/second to LeetCode |
| `--concurrency` | `4` | parallel page requests |
| `--proxy` | `$PROXY_URL` | |
| `--allow-unfinished` | off | scan a contest that hasn't ended (partial results) |

A ~40k-participant contest is ~1,660 pages, about 9–10 minutes at 3 req/s.

Exit codes: `0` success, `1` bad input / contest not finished, `2` scan incomplete or blocked.

### File-only mode (no database)

```sh
.venv/Scripts/python -m app.cli scan weekly-contest-520 --roster "<sheet URL or CSV>" --out results.csv --json results.json
```

## Dashboard

```sh
.venv/Scripts/python -m app.cli create-user alice --role admin   # prompts for a password (min 10 chars)
.venv/Scripts/python -m app.cli create-user bob                  # viewer (read-only)
cd ../frontend && npm install && npm run build && cd ../backend  # once, and after frontend changes
.venv/Scripts/python -m app.cli serve                            # http://127.0.0.1:8000
```

`serve` runs the API under `/api` (docs at `/api/docs`) and serves the built frontend from `../frontend/dist`.
Run the `worker` alongside it. Re-running `create-user` for an existing name resets its password/role and logs out
its sessions.

| Page | |
|---|---|
| Contests | **every** LeetCode weekly/biweekly contest (list kept in sync from LeetCode), filterable by with/without results, type and number. Contests with results show participation, solved ≥ 1, avg solved, best rank; others have a **Get results** button. A scan in progress shows a progress bar and "ready by" time; queued and automatically scheduled contests show their estimated ready time. Upcoming contests show when results will arrive |
| Contest | summary tiles, when students solved each question (10-minute histograms) with wrong-attempt counts, college breakdown, per-question solve rates, leaderboard of all students (college rank, global rank → LeetCode page, Q1–Q4 times + wrong attempts, total time, status); search + filters (college, sheet columns such as batch/section, status); Excel/CSV download |
| Students | everyone from the sheet, handle status (valid / invalid / missing), contests attended |
| Analytics | filter by period (last 5/10/20/all contests), college and sheet columns; attendance and average-solved trends; question by question (how often Q1–Q4 were solved, median time and middle-half range, wrong submissions) with per-question trend charts; college comparison; most consistent / top performers / most improved / needs attention; a sortable table of every student (consistency, Qn solved/attended, wrong submissions, average position, rating, trend) with CSV download |
| Student | attendance and streaks, consistency score, trend, LeetCode rating; question by question compared with all students (times solved out of contests attended, median/fastest time, wrong submissions); charts of problems solved, global position and rating; contest-by-contest history |
| Admin (admins only) | "Sync from Google Sheet" with the row-issue report; queue scans (rescans, backfill of past contests); scan history with errors |

Viewers can see everything except Admin, and can fetch results for contests that don't have any yet; rescanning a
contest that already has results is admin-only. "Ready by" times are estimates from the progress of the scan in
progress and the median length of recent scans; if the worker isn't running the page says so instead of giving a time. Excel downloads link each global rank to the LeetCode leaderboard page.

**Frontend development:** run `serve` (port 8000), then `cd ../frontend && npm run dev` and open
http://localhost:5173 (it proxies `/api` to port 8000 and hot-reloads).

### Analytics definitions

- **Attended**: on the LeetCode leaderboard (solved ≥ 1, or took part and solved 0).
- **Consistency** (0–100, needs ≥ 3 contests): 60 % attendance rate + 40 % stability, where stability =
  1 − min(1, std-dev of problems solved across attended contests ÷ 1.5). 80+ very consistent, 60+ consistent,
  40+ irregular, below that inconsistent.
- **Trend**: average problems solved in the latest attended contests (up to 4) minus the same number before them;
  ±0.5 counts as improving / declining.
- **Top %**: global rank ÷ participants worldwide.
- **Wrong submissions**: wrong attempts before the accepted submission. LeetCode doesn't publish attempts on problems
  that were never solved, so those can't be counted.
- **Needs attention**: missed the last 3+ contests, or declining.

## Database

Tables: `students`, `colleges`, `roster_syncs`, `contests`, `scan_runs`, `results`, `problem_results`
(see [app/db/models.py](app/db/models.py)). Schema changes go through Alembic:

```sh
.venv/Scripts/alembic revision --autogenerate -m "describe change"
.venv/Scripts/alembic upgrade head
```

## Roster (Google Sheet or CSV)

`sync-roster --source` / `$ROSTER_SHEET_URL` (and file-mode `--roster`) take a Google Sheet URL or a CSV
path. The first row is the header; headers are matched loosely, so Google Form headers work:

- **roll number** (required for `sync-roster`): `Roll No`, `Roll Number`, `Student ID`, `Registration No`, `ID`
- **name**: `Name`, `Full Name`, `Student Name`
- **LeetCode handle**: `LeetCode`, `LeetCode Username`, `LeetCode Profile URL`, `Handle`... (any header containing "leetcode")
- **college** (optional): `College`, `College Name`

Other columns (batch, section, email, timestamp) are copied to the output. Handles may be profile
URLs (`https://leetcode.com/u/Name/`), have `@`, or be in any case. Issues (missing/unparseable/duplicate
handles) are printed with the sheet row number. See [examples/students.sample.csv](examples/students.sample.csv).

The tab is picked from `#gid=` in the URL (copy the URL while the right tab is open), else the first tab.

### Private sheet via service account (recommended)

1. In [Google Cloud Console](https://console.cloud.google.com/): create a project, enable the **Google Sheets API**,
   create a **service account**, and download a JSON key for it.
2. Share the sheet with the service account's email (`...@....iam.gserviceaccount.com`) as **Viewer**.
3. Install the extra and pass the key:

```sh
.venv/Scripts/python -m pip install -e ".[sheets]"
.venv/Scripts/python -m app.cli scan weekly-contest-520 --roster "https://docs.google.com/spreadsheets/d/<id>/edit#gid=0" --google-credentials key.json
```

Keep the key file out of git.

### Link-shared sheet (no setup)

If the sheet is shared as "Anyone with the link can view", omit `--google-credentials`; it is downloaded as CSV.
Anyone with the link can then see student data.

## Output

One row per student:

| Column | Meaning |
|---|---|
| `roll_no` | the student's roll number (when the roster has one) |
| `status` | `solved` (≥1 solved), `zero` (on leaderboard, 0 solved), `absent` (not on leaderboard), `invalid_handle` (LeetCode user doesn't exist), `no_handle`, `duplicate_handle` |
| `global_rank` | LeetCode rank (1-based) |
| `college_rank` | rank among all participating students in the portal (the roster), across colleges |
| `total_time` | LeetCode finish time, including 5-minute penalties per wrong attempt |
| `Qn_time` | time from contest start to the accepted submission for question n (no penalty) |
| `Qn_wrong` | wrong attempts on question n before acceptance |
| `ranking_url` | link to the leetcode.com leaderboard page (25 per page) that shows this student |

## Guarantees

- The scan writes nothing unless **every** leaderboard page was fetched and validated, so a dropped page can never turn participants into "absent".
- If Cloudflare keeps challenging requests, the scan stops early (exit code 2) instead of retrying 1,600 pages.
- Unexpected API format changes fail validation loudly rather than producing wrong numbers.

## Tests

```sh
.venv/Scripts/python -m pytest
```

Tests run offline against real responses recorded from weekly-contest-520 in `tests/fixtures/`.
Database tests use a temporary SQLite file. Production runs PostgreSQL, and the analytics summary
tables, the parity test and the performance budgets (`tests/test_summaries.py`) only run there. To run
the suite on PostgreSQL, set `TEST_DATABASE_URL` to a local database. It is wiped before every test, so
anything other than localhost is refused. See `tests/dbutil.py` for a one-line Docker command.


## Credits

Built by **Rajveer Sharma** for **NxtWave**, 14–16 October 2026:

- **14 Oct 2026:** the dashboard (contest scanning, results, roster and Excel uploads, analytics, admin panel, roles, audit trail).
- **15 Oct 2026:** performance Phases 1–2: query budgets, orjson, caching and compression, the analytics summary tables, ETags, server-side paging and the deploy configs.
- **16 Oct 2026:** Phases 3–4: prefetching, skeletons, optimistic edits, virtualised tables, bundle and Lighthouse budgets, request timing and logs, load test, backups and CI.
