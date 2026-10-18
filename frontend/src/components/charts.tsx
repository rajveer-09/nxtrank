/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
// Small SVG charts. Single series in the accent hue; hairline grid; crosshair (line)
// or per-bar (column) tooltips, also reachable with the keyboard; every chart has a table view.
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) max = min + 1;
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
  if (ticks[ticks.length - 1] < max) ticks.push(Number((ticks[ticks.length - 1] + step).toPrecision(12)));
  return ticks;
}

/** Every `every`-th tick plus the last one, skipping regular ticks that would crowd the last. */
function showTick(i: number, n: number, every: number) {
  if (i === n - 1) return true;
  return i % every === 0 && n - 1 - i >= Math.max(1, every * 0.75);
}

export function shortContest(title: string) {
  const m = title.match(/^(Weekly|Biweekly) Contest (\d+)$/);
  return m ? `${m[1][0]}${m[2]}` : title;
}

const TIP_W = 176;

/** Sits beside the hovered x (right of it, or left near the edge) so it never covers the point. */
function Tooltip({ x, y, width, children }: { x: number; y: number; width: number; children: ReactNode }) {
  const right = x + 14;
  const left = right + TIP_W <= width ? right : Math.max(0, x - 14 - TIP_W);
  return (
    <div
      role="status"
      className="chart-tip pointer-events-none absolute z-10 rounded-md border border-border-strong bg-popover px-2.5 py-2 text-xs shadow-lg shadow-black/40"
      style={{ left, top: Math.max(y - 30, 0), width: TIP_W }}
    >
      {children}
    </div>
  );
}

export interface LinePoint {
  label: string; // tooltip title, e.g. contest name
  tick: string; // short x-axis label
  y: number | null;
  note?: string; // extra tooltip line
}

export function LineChart({
  points,
  format,
  domain,
  invert = false,
  height = 200,
  area = true, // a wash under the line; skipped when inverted (its baseline would be the top)
  ariaLabel,
}: {
  points: LinePoint[];
  format: (v: number) => string;
  domain?: [number, number];
  invert?: boolean; // smaller is better (e.g. rank): best at the top
  height?: number;
  area?: boolean;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const gradientId = `area-${useId().replace(/:/g, "")}`;
  const values = points.map((p) => p.y).filter((v): v is number => v != null);
  if (values.length === 0) return <p className="grid min-h-36 place-items-center rounded-md border border-dashed border-fg/10 px-4 text-center text-xs text-ink-3">No data for this period yet.</p>;

  const lo = domain ? domain[0] : Math.min(...values);
  const hi = domain ? domain[1] : Math.max(...values);
  const ticks = niceTicks(domain ? lo : Math.max(0, lo - (hi - lo) * 0.1), hi);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const m = { l: 48, r: 56, t: 10, b: 26 };
  const iw = Math.max(width - m.l - m.r, 10);
  const ih = height - m.t - m.b;
  const xAt = (i: number) => m.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);
  const yAt = (v: number) => {
    const t = (v - yMin) / (yMax - yMin || 1);
    return m.t + (invert ? t : 1 - t) * ih;
  };

  const segments: string[] = [];
  let cur = "";
  points.forEach((p, i) => {
    if (p.y == null) {
      if (cur) segments.push(cur);
      cur = "";
    } else cur += `${cur ? "L" : "M"}${xAt(i)},${yAt(p.y)}`;
  });
  if (cur) segments.push(cur);
  const base = invert ? m.t : m.t + ih;
  const areaPath = segments
    .map((d) => {
      const xs = [...d.matchAll(/[ML]([\d.]+),/g)].map((x) => x[1]);
      return `${d}L${xs[xs.length - 1]},${base}L${xs[0]},${base}Z`;
    })
    .join("");
  const lastIdx = points.map((p) => p.y).findLastIndex((v) => v != null);
  const every = Math.max(1, Math.ceil(points.length / Math.max(1, Math.floor(iw / 56))));

  function nearest(clientX: number, rect: DOMRect) {
    const x = clientX - rect.left;
    let best = 0;
    points.forEach((_, i) => {
      if (Math.abs(xAt(i) - x) < Math.abs(xAt(best) - x)) best = i;
    });
    setActive(best);
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "ArrowRight") setActive((a) => Math.min(points.length - 1, (a ?? -1) + 1));
    else if (e.key === "ArrowLeft") setActive((a) => Math.max(0, (a ?? points.length) - 1));
    else return;
    e.preventDefault();
  }
  const a = active != null ? points[active] : null;

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} className="block overflow-visible">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={m.l + iw} y1={yAt(t)} y2={yAt(t)} stroke="var(--border)" strokeWidth={1} />
              <text x={m.l - 8} y={yAt(t)} dy="0.32em" textAnchor="end" className="tabular fill-ink-3 text-[11px]">
                {format(t)}
              </text>
            </g>
          ))}
          {points.map((p, i) =>
            showTick(i, points.length, every) ? (
              <text key={i} x={xAt(i)} y={height - 6} textAnchor="middle" className="fill-ink-3 text-[11px]">
                {p.tick}
              </text>
            ) : null,
          )}
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.24} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          {area && !invert && <path d={areaPath} fill={`url(#${gradientId})`} className="chart-area" />}
          {segments.map((d, i) => (
            <path key={i} d={d} pathLength={1} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className="chart-line" />
          ))}
          {active != null && points[active].y != null && (
            <circle cx={xAt(active)} cy={yAt(points[active].y!)} r={10} fill="var(--accent)" opacity={0.18} />
          )}
          {points.map((p, i) =>
            p.y != null && (points.length <= 24 || i === active || i === lastIdx) ? (
              <circle key={i} cx={xAt(i)} cy={yAt(p.y)} r={i === active ? 5 : 4} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
            ) : null,
          )}
          {lastIdx >= 0 && (
            <text x={xAt(lastIdx) + 9} y={yAt(points[lastIdx].y!)} dy="0.32em" className="tabular fill-ink text-[12px] font-semibold">
              {format(points[lastIdx].y!)}
            </text>
          )}
          {active != null && <line x1={xAt(active)} x2={xAt(active)} y1={m.t} y2={m.t + ih} stroke="color-mix(in srgb, var(--fg) 18%, transparent)" strokeWidth={1} />}
          <rect
            x={m.l - 12}
            y={0}
            width={iw + 24}
            height={height}
            fill="transparent"
            role="img"
            tabIndex={0}
            aria-label={`${ariaLabel}: use left and right arrow keys to read values`}
            className="cursor-crosshair outline-none focus-visible:stroke-accent"
            onPointerMove={(e) => nearest(e.clientX, (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect())}
            onPointerLeave={() => setActive(null)}
            onFocus={() => setActive((x) => x ?? lastIdx)}
            onBlur={() => setActive(null)}
            onKeyDown={onKey}
          />
        </svg>
      )}
      {a && (
        <Tooltip x={xAt(active!)} y={a.y != null ? yAt(a.y) : m.t} width={width}>
          <div className="tabular text-sm font-semibold text-ink">{a.y != null ? format(a.y) : "—"}</div>
          <div className="text-ink-2">{a.label}</div>
          {a.note && <div className="text-ink-3">{a.note}</div>}
        </Tooltip>
      )}
    </div>
  );
}

export interface Column {
  label: string; // tooltip title
  tick: string;
  value: number | null;
  note?: string;
}

export function ColumnChart({
  columns,
  format,
  max,
  height = 160,
  ariaLabel,
}: {
  columns: Column[];
  format: (v: number) => string;
  max?: number;
  height?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const top = max ?? Math.max(1, ...columns.map((c) => c.value ?? 0));
  const ticks = niceTicks(0, top, 3);
  const yMax = ticks[ticks.length - 1];
  const m = { l: 36, r: 8, t: 8, b: 22 };
  const iw = Math.max(width - m.l - m.r, 10);
  const ih = height - m.t - m.b;
  const band = iw / Math.max(columns.length, 1);
  const bw = Math.min(24, Math.max(band - 2, 2));
  const yAt = (v: number) => m.t + ih - (v / yMax) * ih;
  const every = Math.max(1, Math.ceil(columns.length / Math.max(1, Math.floor(iw / 40))));
  const a = active != null ? columns[active] : null;

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} className="block">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={m.l + iw} y1={yAt(t)} y2={yAt(t)} stroke="var(--border)" strokeWidth={1} />
              <text x={m.l - 6} y={yAt(t)} dy="0.32em" textAnchor="end" className="tabular fill-ink-3 text-[11px]">
                {format(t)}
              </text>
            </g>
          ))}
          {columns.map((c, i) => {
            const cx = m.l + band * i + band / 2;
            const v = c.value ?? 0;
            const h = (v / yMax) * ih;
            const r = Math.min(4, h, bw / 2);
            const x0 = cx - bw / 2;
            const y0 = m.t + ih - h;
            const d =
              h > 0
                ? `M${x0},${m.t + ih}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + bw - r}Q${x0 + bw},${y0} ${x0 + bw},${y0 + r}V${m.t + ih}Z`
                : "";
            return (
              <g key={i}>
                {d && (
                  <path
                    d={d}
                    fill={active === i ? "var(--accent-ink)" : "var(--accent)"}
                    opacity={active == null || active === i ? 1 : 0.55}
                    className="chart-bar"
                    style={{ animationDelay: `${Math.min(i * 25, 300)}ms` }}
                  />
                )}
                {c.value == null && (
                  <text x={cx} y={m.t + ih - 4} textAnchor="middle" className="fill-ink-3 text-[10px]">
                    –
                  </text>
                )}
                {c.tick && showTick(i, columns.length, every) && (
                  <text x={cx} y={height - 5} textAnchor="middle" className="fill-ink-3 text-[11px]">
                    {c.tick}
                  </text>
                )}
                <rect
                  x={m.l + band * i}
                  y={0}
                  width={band}
                  height={height - m.b}
                  fill="transparent"
                  role="img"
                  tabIndex={0}
                  aria-label={`${c.label}: ${c.value != null ? format(c.value) : "no value"}${c.note ? `, ${c.note}` : ""}`}
                  className="outline-none"
                  onPointerEnter={() => setActive(i)}
                  onPointerLeave={() => setActive(null)}
                  onFocus={() => setActive(i)}
                  onBlur={() => setActive(null)}
                />
              </g>
            );
          })}
          <line x1={m.l} x2={m.l + iw} y1={m.t + ih} y2={m.t + ih} stroke="var(--border-strong)" strokeWidth={1} />
        </svg>
      )}
      {a && (
        <Tooltip x={m.l + band * active! + band / 2} y={yAt(a.value ?? 0)} width={width}>
          <div className="tabular text-sm font-semibold text-ink">{a.value != null ? format(a.value) : "—"}</div>
          <div className="text-ink-2">{a.label}</div>
          {a.note && <div className="text-ink-3">{a.note}</div>}
        </Tooltip>
      )}
    </div>
  );
}

/** Horizontal share bar with an optional comparison tick (e.g. cohort average). */
export function Meter({ value, compare, label }: { value: number | null; compare?: number | null; label: string }) {
  const pct = Math.max(0, Math.min(1, value ?? 0)) * 100;
  return (
    <div className="relative h-2.5 w-full rounded-full bg-bar-track" role="img" aria-label={label} title={label}>
      <div className="meter-fill h-full rounded-full bg-accent" style={{ width: `${pct > 0 ? Math.max(pct, 1.5) : 0}%` }} />
      {compare != null && (
        <div
          aria-hidden
          className="absolute -top-1 h-4.5 w-0.5 rounded-full bg-ink"
          style={{ left: `calc(${Math.max(0, Math.min(1, compare)) * 100}% - 1px)` }}
        />
      )}
    </div>
  );
}

/** Collapsible table view of a chart's data. */
export function ChartTable({ columns, rows }: { columns: string[]; rows: (string | number)[][] }) {
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-ink-2 hover:text-ink">Show as table</summary>
      <div className="mt-2 max-h-64 overflow-auto rounded-lg border border-border">
        <table className="w-full">
          <thead className="sticky top-0 bg-surface-2 text-ink-2">
            <tr>
              {columns.map((c) => (
                <th key={c} className="px-3 py-1.5 text-left font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-border">
                {r.map((v, j) => (
                  <td key={j} className="tabular px-3 py-1.5">
                    {v}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
