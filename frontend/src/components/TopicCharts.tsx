/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 18 October 2026
 */
import { useId, useRef, useState } from "react";
import type { TopicMetrics, TopicRow } from "../api";
import { fmtInt, fmtPct } from "../format";
import { cx } from "./ui";

const metricsOf = (r: TopicRow, officialOnly: boolean): TopicMetrics => (officialOnly ? r.official : r);

/** Solve rate per topic: one bar each, best first. With `compare`, a tick marks the
 *  group's rate on the same topic (e.g. this student vs everyone). */
export function TopicBars({
  rows,
  officialOnly,
  compare,
  compareLabel,
  limit = 10,
}: {
  rows: TopicRow[];
  officialOnly: boolean;
  compare?: Map<string, number | null>;
  compareLabel?: string;
  limit?: number;
}) {
  const [active, setActive] = useState<string | null>(null);
  const data = rows
    .map((r) => ({ r, m: metricsOf(r, officialOnly) }))
    .filter(({ m }) => m.appeared > 0 && m.solve_rate != null)
    .sort((a, b) => b.m.appeared - a.m.appeared)
    .slice(0, limit)
    .sort((a, b) => (b.m.solve_rate ?? 0) - (a.m.solve_rate ?? 0) || a.r.name.localeCompare(b.r.name));
  if (!data.length) return null;
  const label = `Solve rate by topic${compare ? `, with ${compareLabel ?? "the group"} for comparison` : ""}`;
  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-2">
        <span className="font-medium text-ink">Solve rate by topic</span>
        {compare && (
          <span className="flex items-center gap-3" aria-hidden>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-3 rounded-sm bg-[var(--series-1)]" />
              This student
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-3 w-0.5 rounded-full bg-ink" />
              {compareLabel ?? "Group"}
            </span>
          </span>
        )}
      </figcaption>
      {/* one text alternative for the whole chart (the table below has every number) */}
      <div role="img" aria-label={`${label}: ${data.map(({ r, m }) => `${r.name} ${fmtPct(m.solve_rate)}`).join(", ")}`}>
        <ul aria-hidden className="flex flex-col">
          {data.map(({ r, m }) => {
            const rate = m.solve_rate ?? 0;
            const other = compare?.get(r.slug) ?? null;
            const on = active === r.slug;
            return (
              <li
                key={r.slug}
                className={cx(
                  "relative grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)_3rem] items-center gap-3 rounded-md px-1 py-1.5",
                  on && "bg-fg/[0.04]",
                )}
                onPointerEnter={() => setActive(r.slug)}
                onPointerLeave={() => setActive(null)}
                onClick={() => setActive(on ? null : r.slug)} // touch: tap to read
              >
                <span className="truncate text-xs text-ink-2" title={r.name}>
                  {r.name}
                </span>
                <span className="relative h-2.5 rounded-full bg-bar-track">
                  <span
                    className="absolute inset-y-0 left-0 rounded-full bg-[var(--series-1)]"
                    style={{ width: `${Math.max(rate * 100, rate > 0 ? 1.5 : 0)}%` }}
                  />
                  {other != null && (
                    <span
                      className="absolute -inset-y-1 w-0.5 -translate-x-1/2 rounded-full bg-ink ring-2 ring-[var(--surface)]"
                      style={{ left: `${other * 100}%` }}
                    />
                  )}
                </span>
                <span className="tabular text-right text-xs font-medium text-ink">{fmtPct(rate)}</span>
                {on && (
                  <span
                    role="tooltip"
                    className="pointer-events-none absolute -top-1 left-[7.5rem] z-10 -translate-y-full rounded-md bg-surface-2 px-2.5 py-1.5 text-[11px] leading-snug text-ink shadow-(--shadow-pop) ring-1 ring-inset ring-fg/10"
                  >
                    <b>{r.name}</b>: solved {fmtInt(m.solved)} of {fmtInt(m.appeared)} ({fmtPct(rate)}) · accuracy{" "}
                    {fmtPct(m.accuracy) || "—"}
                    {other != null && (
                      <>
                        {" "}
                        · {compareLabel ?? "group"} {fmtPct(other)}
                      </>
                    )}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </figure>
  );
}

const SLOTS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
const TOP = SLOTS.length; // the rest folds into "Other"

/** Topics keep their colour while filters change (colour follows the topic, not its
 *  rank): slots are handed out once per chart and reused. */
function useStableSlots(slugs: string[]): (slug: string) => string {
  const assigned = useRef(new Map<string, number>());
  const used = new Set<number>();
  for (const s of slugs) {
    const slot = assigned.current.get(s);
    if (slot != null) used.add(slot);
  }
  for (const s of slugs) {
    if (assigned.current.has(s) && used.has(assigned.current.get(s)!)) continue;
    const free = SLOTS.findIndex((_, i) => !used.has(i));
    if (free === -1) break;
    assigned.current.set(s, free);
    used.add(free);
  }
  return (slug) => SLOTS[assigned.current.get(slug) ?? 0];
}

function arc(cx0: number, cy0: number, r: number, a0: number, a1: number) {
  const p = (a: number) => [cx0 + r * Math.sin(a), cy0 - r * Math.cos(a)];
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  return `M ${x0} ${y0} A ${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1} ${y1}`;
}

/** Topic mix: each topic's share of question appearances, the top four plus "Other". */
export function TopicDonut({ rows, officialOnly }: { rows: TopicRow[]; officialOnly: boolean }) {
  const [active, setActive] = useState<string | null>(null);
  const uid = useId().replace(/:/g, "");
  const all = rows
    .map((r) => ({ slug: r.slug, name: r.name, n: metricsOf(r, officialOnly).appeared }))
    .filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
  const top = all.slice(0, TOP);
  const colorOf = useStableSlots(top.map((t) => t.slug));
  const rest = all.slice(TOP).reduce((sum, x) => sum + x.n, 0);
  const parts = [
    ...top.map((t) => ({ ...t, color: colorOf(t.slug) })),
    ...(rest ? [{ slug: "other", name: `Other (${all.length - TOP})`, n: rest, color: "var(--series-other)" }] : []),
  ];
  const total = parts.reduce((s, p) => s + p.n, 0);
  if (parts.length < 2 || !total) return null; // one slice isn't a chart

  // a thin flat ring of glass: square ends, 2px gaps, lit edges, a faint glow
  const size = 148,
    c = size / 2,
    r = 60,
    width = 11,
    gap = parts.length > 1 ? 2 / r : 0; // a 2px cut between segments
  let start = 0;
  const shown = parts.find((p) => p.slug === active);
  return (
    <figure className="flex min-w-0 flex-col gap-3">
      <figcaption className="text-xs font-medium text-ink">Topic mix</figcaption>
      <div className="flex flex-wrap items-center gap-6">
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          role="img"
          aria-label={`Topic mix of question appearances: ${parts.map((p) => `${p.name} ${fmtPct(p.n / total)}`).join(", ")}`}
          className="shrink-0 overflow-visible"
        >
          <defs>
            {/* glass: each segment lit from the top left, slightly translucent */}
            {parts.map((p) => (
              <linearGradient key={p.slug} id={`${uid}-${p.slug}`} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" style={{ stopColor: `color-mix(in srgb, ${p.color} 72%, white)` }} stopOpacity="0.95" />
                <stop offset="100%" style={{ stopColor: p.color }} stopOpacity="0.82" />
              </linearGradient>
            ))}
            <radialGradient id={`${uid}-core`} cx="40%" cy="30%" r="75%">
              <stop offset="0%" stopColor="white" stopOpacity="0.07" />
              <stop offset="100%" stopColor="white" stopOpacity="0" />
            </radialGradient>
          </defs>
          {/* frosted centre: barely there */}
          <circle
            cx={c}
            cy={c}
            r={r - width / 2 - 5}
            fill={`url(#${uid}-core)`}
            stroke="color-mix(in srgb, var(--fg) 8%, transparent)"
            strokeWidth="0.75"
          />
          {parts.map((p) => {
            const a0 = start,
              a1 = start + (p.n / total) * Math.PI * 2;
            start = a1;
            const on = active === p.slug;
            const w = on ? width + 3 : width;
            const s0 = a0 + gap / 2,
              s1 = Math.max(s0 + 0.002, a1 - gap / 2);
            return (
              <g
                key={p.slug}
                opacity={active && !on ? 0.35 : 1}
                style={{ filter: `drop-shadow(0 0 ${on ? 6 : 3.5}px color-mix(in srgb, ${p.color} ${on ? 40 : 24}%, transparent))` }}
                onPointerEnter={() => setActive(p.slug)}
                onPointerLeave={() => setActive(null)}
                onClick={() => setActive(on ? null : p.slug)}
                className="cursor-pointer transition-opacity duration-200 ease-out"
              >
                <path d={arc(c, c, r, s0, s1)} fill="none" stroke={`url(#${uid}-${p.slug})`} strokeWidth={w} strokeLinecap="butt" />
                {/* light catching the two edges of the glass */}
                <path
                  d={arc(c, c, r - w / 2 + 0.6, s0, s1)}
                  fill="none"
                  stroke="white"
                  strokeOpacity="0.38"
                  strokeWidth="0.9"
                  pointerEvents="none"
                />
                <path
                  d={arc(c, c, r + w / 2 - 0.6, s0, s1)}
                  fill="none"
                  stroke="white"
                  strokeOpacity="0.16"
                  strokeWidth="0.9"
                  pointerEvents="none"
                />
              </g>
            );
          })}
          <text x={c} y={c + 2} textAnchor="middle" className="fill-ink text-[22px] font-semibold tracking-tight tabular-nums">
            {shown ? fmtPct(shown.n / total) : fmtInt(total)}
          </text>
          <text x={c} y={c + 19} textAnchor="middle" className="fill-ink-3 text-[10.5px] uppercase tracking-[0.08em]">
            {shown ? (shown.name.length > 18 ? `${shown.name.slice(0, 17)}…` : shown.name) : "appearances"}
          </text>
        </svg>
        <ul className="flex min-w-48 flex-1 flex-col text-[12.5px]">
          {parts.map((p) => (
            <li
              key={p.slug}
              className={cx(
                "grid grid-cols-[auto_minmax(0,1fr)_auto_3.5rem] items-center gap-2.5 border-b border-fg/[0.06] py-1.5 transition-opacity last:border-0",
                active && active !== p.slug && "opacity-45",
              )}
              onPointerEnter={() => setActive(p.slug)}
              onPointerLeave={() => setActive(null)}
            >
              <span
                aria-hidden
                className="h-2 w-2 rounded-[2px]"
                style={{ background: `linear-gradient(135deg, color-mix(in srgb, ${p.color} 72%, white), ${p.color})` }}
              />
              <span className="truncate text-ink-2">{p.name}</span>
              <span className="tabular font-semibold text-ink">{fmtPct(p.n / total)}</span>
              <span className="tabular text-right text-ink-3">{fmtInt(p.n)}</span>
            </li>
          ))}
        </ul>
      </div>
    </figure>
  );
}
