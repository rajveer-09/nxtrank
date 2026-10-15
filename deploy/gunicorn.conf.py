# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""Gunicorn settings for the dashboard API.

Gunicorn manages the processes (restarts a crashed worker, graceful reloads), and each
worker runs Uvicorn's event loop. Run from backend/:

    gunicorn -c ../deploy/gunicorn.conf.py "app.api.app:create_app()"
"""

import multiprocessing
import os

# Caddy is the only thing that talks to us, over loopback.
bind = os.environ.get("BIND", "127.0.0.1:8000")

# One worker per core (capped): requests are mostly short DB round trips.
workers = int(os.environ.get("WEB_CONCURRENCY", min(multiprocessing.cpu_count(), 4)))
worker_class = "uvicorn_worker.UvicornWorker"  # uses uvloop + httptools when installed

# Each worker opens its own connection pool after forking; never share one across forks.
preload_app = False

timeout = 60            # a worker stuck this long is killed and replaced
graceful_timeout = 20   # finish in-flight requests on reload/stop
keepalive = 5           # Caddy reuses upstream connections

# Restart workers now and then to cap slow memory growth; jitter avoids restarting all at once.
max_requests = 5000
max_requests_jitter = 500

# Trust X-Forwarded-* only from Caddy on this machine.
forwarded_allow_ips = "127.0.0.1"

# The app logs one JSON line per API request itself (app.requests: route, status,
# duration, database time, query count), so no separate access log.
accesslog = None
errorlog = "-"   # journald collects stdout/stderr
loglevel = "info"
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"stdout": {"class": "logging.StreamHandler", "formatter": "plain", "stream": "ext://sys.stdout"}},
    "root": {"level": "INFO", "handlers": ["stdout"]},
}
