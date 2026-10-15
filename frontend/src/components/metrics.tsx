/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
// Shared bits for analytics views.
import type { TrendLabel } from "../api";
import { Badge } from "./ui";

const ringTone = (score: number) =>
  score >= 80 ? "var(--good)" : score >= 60 ? "var(--accent)" : score >= 40 ? "var(--warning)" : "var(--critical)";

/** Consistency score as a small progress ring with the number inside, and its label. */
export function ConsistencyBadge({ score, label }: { score: number | null; label: string | null }) {
  if (score == null) return <span className="text-xs text-ink-3">needs 3+ contests</span>;
  const r = 10.5;
  const c = 2 * Math.PI * r;
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap" title={`Consistency ${score}/100 · ${label}`}>
      <span className="relative grid h-7 w-7 shrink-0 place-items-center">
        <svg viewBox="0 0 28 28" className="absolute inset-0 -rotate-90" aria-hidden>
          <circle cx="14" cy="14" r={r} fill="none" stroke="var(--bar-track)" strokeWidth="3" />
          <circle
            cx="14"
            cy="14"
            r={r}
            fill="none"
            stroke={ringTone(score)}
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray={`${(score / 100) * c} ${c}`}
            className="ring-arc"
          />
        </svg>
        <span className="tabular relative text-[10px] font-bold text-ink">{score}</span>
      </span>
      <span className="text-xs font-medium text-ink-2">{label}</span>
    </span>
  );
}


export function TrendBadge({ label, delta }: { label: TrendLabel | null; delta: number | null }) {
  if (label == null) return <span className="text-xs text-ink-3">—</span>;
  const sign = delta != null && delta > 0 ? "+" : "";
  if (label === "improving")
    return (
      <Badge tone="good" icon={null}>
        ▲ Improving <span className="tabular">{sign}{delta?.toFixed(1)}</span>
      </Badge>
    );
  if (label === "declining")
    return (
      <Badge tone="critical" icon={null}>
        ▼ Declining <span className="tabular">{delta?.toFixed(1)}</span>
      </Badge>
    );
  return <Badge tone="neutral">Steady</Badge>;
}

export const fmtTopPct = (x: number | null | undefined) =>
  x == null ? "" : x < 1 ? `top ${x.toFixed(2)}%` : `top ${x < 10 ? x.toFixed(1) : Math.round(x)}%`;

/** Download rows as a CSV file (text that looks like a formula is neutralised). */
export function downloadCsv(filename: string, header: string[], rows: (string | number | null | undefined)[][]) {
  const cell = (v: string | number | null | undefined) => {
    let s = v == null ? "" : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const text = "﻿" + [header, ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export const DEFINITIONS = [
  ["Attended", "On the LeetCode leaderboard for that contest (solved at least one problem, or took part and solved none)."],
  ["Consistency", "0–100, needs 3+ contests: 60% attendance rate + 40% stability (how little the number of problems solved varies between attended contests)."],
  ["Trend", "Average problems solved in the latest attended contests (up to 4) minus the same number of contests before them. ±0.5 or more counts as improving / declining."],
  ["Top %", "Global rank ÷ participants worldwide. Top 5% means better than 95% of everyone who took part."],
  ["Wrong submissions", "Wrong attempts before the accepted submission (each adds 5 min of penalty). LeetCode doesn't publish attempts on problems that were never solved."],
  ["Time taken", "Time from the contest start to the accepted submission, without penalties."],
];

export function Definitions() {
  return (
    <details className="text-[13px] text-ink-2">
      <summary className="cursor-pointer hover:text-ink">How are these calculated?</summary>
      <dl className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {DEFINITIONS.map(([term, def]) => (
          <div key={term}>
            <dt className="font-medium text-ink">{term}</dt>
            <dd>{def}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
