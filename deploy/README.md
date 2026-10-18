# Deploying NxtRank

The production setup: one free Oracle Cloud VM (Mumbai or Hyderabad) running Caddy, the
API, the worker and Postgres.

```
Browser ──HTTPS──▶ Caddy ──┬── /assets, index.html  (frontend/dist, pre-compressed)
                           └── /api/* ──▶ Gunicorn (Uvicorn workers) ──▶ Postgres (localhost)
                                         dashboard-worker (scans) ──────┘
```

| File | Goes to | What it does |
|---|---|---|
| `Caddyfile` | `/etc/caddy/Caddyfile` | HTTPS, HTTP/2/3, static files with cache headers, `/api` proxy |
| `gunicorn.conf.py` | stays here | API processes: one per core, restarts crashed workers |
| `dashboard-api.service` | `/etc/systemd/system/` | Runs migrations, then the API; restarts on failure |
| `dashboard-worker.service` | `/etc/systemd/system/` | The single scan worker |
| `postgresql.conf.snippet` | `/etc/postgresql/<v>/main/conf.d/dashboard.conf` | Memory settings, localhost only, slow-query logging |
| `backup.sh`, `restore-drill.sh`, `copy-to-neon.sh` | stay here | Nightly dump, monthly restore drill, weekly off-site copy |
| `dashboard-{backup,restore-drill,neon-copy}.{service,timer}` | `/etc/systemd/system/` | Schedule those three |

The VM setup is further down. The dashboard currently runs on free hosted services
instead, and the runbook below is for that setup.

## Runbook: Render + Neon (current setup)

| Part | Where |
|---|---|
| Website and API | Render web service `nxtrank-nxtwave` (branch `master`); staging service on branch `staging` |
| Database | Neon project "NxtRank Production": branch `production`, plus a staging branch |
| Worker (scans) | A laptop on a home connection (`python -m app.cli worker`), because LeetCode's Cloudflare blocks cloud servers |
| Uptime | UptimeRobot checks `/api/health` every 5 minutes |
| Backups | GitHub Actions workflow **Backup**, nightly at 02:00 IST |

**Render environment variables (production):**
- `DATABASE_URL`, `SECRET_KEY`;
- `COOKIE_SECURE=true`;
- `APP_ENV=production` (hides `/api/docs`);
- optionally `SLACK_WEBHOOK_URL` or `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, so API crashes and worker problems are sent as alerts.

Staging uses `APP_ENV=staging`.

### Backups
- **Setting up (once):** add two repository secrets under GitHub → Settings → Secrets and variables → Actions:
  - `BACKUP_DATABASE_URL`: production's connection string;
  - `BACKUP_PASSPHRASE`: at least 20 random characters. **Store this passphrase in a password manager as well. Without it, a backup can't be opened.**
  - Then run the workflow once by hand: Actions → Backup → Run workflow, with "restore check" ticked.
- **What it does:**
  - each night it takes a `pg_dump`, checks that the dump can be read, encrypts it (GPG, AES-256) and keeps it as a run artifact for 7 days;
  - on the 1st of each month it also restores the dump into a scratch Postgres and compares every table's row count with production;
  - a failed run sends GitHub's usual failure email.
- **Restoring:**
  1. Download the artifact from the run you want, then decrypt it: `gpg --decrypt nxtrank-<stamp>.dump.gpg > nxtrank.dump`.
  2. Safest: in Neon, create a new branch and restore into it first, check it, and only then point Render at it (or restore into `production`).
  3. Stop the worker on the laptop.
  4. Restore: `pg_restore --clean --if-exists --no-owner --no-privileges -d "<direct connection string>" nxtrank.dump`.
  5. Start the worker again.
  6. Neon also keeps its own history, which can restore the branch to any moment in its restore window.

### When something goes wrong
| Symptom | What to do |
|---|---|
| A user reports an error with a "Reference: abc123…" | Search Render's logs for that ID. The crash's full traceback, and the request's JSON line (`"rid"`), carry it. |
| The site doesn't open | Render free services sleep after 15 minutes idle, and the first visit takes about 30 to 60 seconds. If it stays down, check Render → Events and Logs, and UptimeRobot. |
| "Worker isn't running" banner | Start it on the laptop: `cd backend && .venv\Scripts\python -m app.cli worker`. A second copy started by mistake waits rather than scanning twice ("another worker … is running"). |
| Scans fail with "blocked" | Cloudflare is blocking the network the worker is on. Run it from a home connection, or set `PROXY_URL` to a residential proxy. |
| Neon says compute hours are used up | The database is paused until the month resets. Lower the awake window (cron-job.org) or upgrade Neon; data is not lost. |
| "too many failed logins" | Shared across processes, and clears 15 minutes after the last failed try. |
| A password or the database URL leaked | Rotate it in Neon or the dashboard; update Render, `backend/.env` on the laptop and the `BACKUP_DATABASE_URL` secret. Changing `SECRET_KEY` signs everyone out. |

## First install (Ubuntu 24.04)

```bash
sudo apt install -y python3.12-venv postgresql caddy git nodejs npm
sudo useradd --system --create-home --home-dir /srv/dashboard dashboard
sudo -u dashboard git clone <repo> /srv/dashboard
cd /srv/dashboard

# Database (local, not exposed)
sudo -u postgres createuser dashboard
sudo -u postgres createdb -O dashboard dashboard
sudo cp deploy/postgresql.conf.snippet /etc/postgresql/16/main/conf.d/dashboard.conf
sudo systemctl restart postgresql
sudo -u postgres psql dashboard -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"

# Backend
cd backend
sudo -u dashboard python3 -m venv .venv
sudo -u dashboard .venv/bin/pip install -e ".[prod]"
sudo -u dashboard cp .env.example .env   # set DATABASE_URL, SECRET_KEY
#   DATABASE_URL=postgresql+psycopg://dashboard@/dashboard   (Unix socket, no password needed)
sudo chmod 600 .env

# Frontend
cd ../frontend && sudo -u dashboard npm ci && sudo -u dashboard npm run build

# Services
sudo cp ../deploy/dashboard-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard-api dashboard-worker
sudo cp ../deploy/Caddyfile /etc/caddy/Caddyfile   # edit the hostname first
sudo systemctl reload caddy
```

Open only ports 80 and 443 in the VM's security list (and 22 for SSH, ideally limited to
your IP). Postgres and Gunicorn listen on localhost only.

## Server hygiene (once)

```bash
sudo apt install -y unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades  # security fixes, automatically
sudo ufw default deny incoming && sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
# SSH keys only: in /etc/ssh/sshd_config set PasswordAuthentication no and PermitRootLogin no
sudo systemctl reload ssh
```

The Oracle security list should also open only 22, 80 and 443. Postgres and Gunicorn
listen on localhost and are never reachable from outside.

## Backups

```bash
sudo -u postgres psql -c "ALTER ROLE dashboard CREATEDB"     # the restore drill uses a scratch database
sudo -u dashboard cp deploy/backup.env.example deploy/backup.env && sudo chmod 600 deploy/backup.env
sudo cp deploy/dashboard-{backup,restore-drill,neon-copy}.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard-backup.timer dashboard-restore-drill.timer
sudo systemctl start dashboard-backup && sudo systemctl start dashboard-restore-drill   # try both now
```

| What | When | |
|---|---|---|
| `backup.sh` | nightly | Compressed `pg_dump`, checked readable, kept 14 days. With `OCI_BUCKET` set, it is also copied to Object Storage; give the bucket a 14-day lifecycle rule. |
| `restore-drill.sh` | monthly | Restores the newest dump into a scratch database and compares row counts with live. A failure shows in `systemctl --failed`. |
| `copy-to-neon.sh` | weekly | Restores the newest dump into Neon as an off-site copy. **It replaces that database**, so enable `dashboard-neon-copy.timer` only once the VM is live and Neon is just the copy. |

To restore for real: `systemctl stop dashboard-api dashboard-worker`, then
`pg_restore --clean --if-exists --no-owner -d dashboard <dump>`, then start both again.

## Checking on it (performance)

```bash
cd /srv/dashboard/backend
journalctl -u dashboard-api --since yesterday -o cat | .venv/bin/python scripts/slow_routes.py --database-url "$DATABASE_URL"
.venv/bin/python scripts/explain_rebuild.py --plans        # the analytics rebuild at today's data size
```

Every API response also carries a `Server-Timing` header (DevTools -> Network -> Timing).
Before launch, and once while a scan is running, run the load test in `loadtest/staff.js`.

## Deploying an update

```bash
cd /srv/dashboard && sudo -u dashboard git pull
(cd frontend && sudo -u dashboard npm ci && sudo -u dashboard npm run build)
(cd backend && sudo -u dashboard .venv/bin/pip install -e ".[prod]")
sudo systemctl restart dashboard-api dashboard-worker
```

The new frontend goes live as soon as the build finishes. `index.html` is never cached,
and the old hashed files stay until the next build, so open tabs keep working.
Restarting the API runs any new migrations first.

## Checking on it

```bash
systemctl status dashboard-api dashboard-worker
journalctl -u dashboard-api -f
sudo -u dashboard psql -c "SELECT calls, round(mean_exec_time) ms, left(query, 80)
                           FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10"
```

---

Author: Rajveer Sharma · © NxtWave · 15–16 October 2026
