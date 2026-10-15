/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
export function fmtDuration(value: number | null | undefined): string {
  if (value == null) return "";
  const secs = Math.round(value);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

const dateTime = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const dateOnly = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });

export const fmtDateTime = (unixSecs: number) => dateTime.format(new Date(unixSecs * 1000));
export const fmtDate = (unixSecs: number) => dateOnly.format(new Date(unixSecs * 1000));
export const fmtIso = (iso: string | null) => (iso ? dateTime.format(new Date(iso)) : "");

export const fmtInt = (n: number | null | undefined) => (n == null ? "" : n.toLocaleString());

export const fmtPct = (x: number | null | undefined) => (x == null ? "" : `${Math.round(x * 100)}%`);

export const fmtDecimal = (x: number | null | undefined, digits = 1) => (x == null ? "" : x.toFixed(digits));

const whenFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
/** "Fri 16 Oct, 11:10 pm" -- short, for a time in the coming days. */
export const fmtWhen = (iso: string | null | undefined) => (iso ? whenFmt.format(new Date(iso)) : "");
