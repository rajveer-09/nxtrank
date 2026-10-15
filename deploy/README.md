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
