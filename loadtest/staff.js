/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
// Load test: 50 staff browsing at once; run before launch and during
// a scan. Read-only, but real load: use staging or quiet hours.
//   k6 run -e BASE_URL=https://... -e EMAIL=... -e PASSWORD=... loadtest/staff.js

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE = __ENV.BASE_URL || "http://127.0.0.1:8010";
const USERS = Number(__ENV.USERS || 50);

// server time, from each response's Server-Timing header (excludes the network)
const serverMs = new Trend("server_ms", true);
const analyticsServerMs = new Trend("analytics_server_ms", true);

export const options = {
  noCookiesReset: true, // stay signed in across iterations, like a real person
  scenarios: {
    staff: {
      executor: "ramping-vus",
      stages: [
        { duration: "30s", target: USERS }, // people arriving
        { duration: "2m", target: USERS }, // everyone browsing
        { duration: "15s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    server_ms: ["p(95)<100"],
    analytics_server_ms: ["p(95)<200"],
    http_req_duration: ["p(95)<800"], // what users wait for, network included
  },
};

function get(path, tag) {
  const r = http.get(`${BASE}${path}`, { tags: { name: tag || path } });
  check(r, { [`${tag || path} ok`]: (res) => res.status === 200 || res.status === 304 });
  const m = /total;dur=([\d.]+)/.exec(r.headers["Server-Timing"] || "");
  if (m) (path.includes("analytics") ? analyticsServerMs : serverMs).add(Number(m[1]));
  return r;
}

const pause = (min, max) => sleep(min + Math.random() * (max - min));

export default function () {
  // each virtual user signs in once and keeps its cookie
  if (__ITER === 0) {
    const r = http.post(`${BASE}/api/auth/login`, JSON.stringify({ username: __ENV.EMAIL, password: __ENV.PASSWORD }),
      { headers: { "Content-Type": "application/json" }, tags: { name: "login" } });
    if (!check(r, { "signed in": (res) => res.status === 200 })) return;
  }

  group("contests", () => {
    const list = get("/api/contests?show=all&page=1&per_page=25", "/api/contests").json();
    get("/api/scan-status");
    const withData = (list.items || []).filter((c) => c.has_data);
    if (withData.length) {
      const c = withData[Math.floor(Math.random() * Math.min(5, withData.length))];
      pause(1, 3);
      get(`/api/contests/${c.slug}`, "/api/contests/{slug}");
      get(`/api/contests/${c.slug}/results?college=&mine=false`, "/api/contests/{slug}/results");
    }
  });
  pause(2, 5);

  group("analytics", () => {
    const last = [5, 10, 20, 0][Math.floor(Math.random() * 4)];
    const q = last ? `last=${last}` : "";
    get(`/api/analytics?${q}`, "/api/analytics");
    get(`/api/analytics/students?${q}&sort=portal_rank&limit=50`, "/api/analytics/students");
  });
  pause(2, 5);

  group("students", () => {
    const list = get("/api/students?sort=name&limit=100", "/api/students").json();
    const rows = list.rows || [];
    if (rows.length) {
      const s = rows[Math.floor(Math.random() * rows.length)];
      pause(1, 3);
      get(`/api/students/${s.id}`, "/api/students/{id}");
      get(`/api/students/${s.id}/analytics`, "/api/students/{id}/analytics");
    }
  });
  pause(3, 8);
}
