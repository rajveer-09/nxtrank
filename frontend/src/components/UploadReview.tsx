/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useMemo, useState } from "react";
import type { PreviewRecord, UploadPreview } from "../api";
import { fmtInt } from "../format";
import { Badge, Button, Dialog, ErrorBox, cx } from "./ui";
import { Spacer, useBoxRows } from "./virtual";

type Filter = "all" | "added" | "updated" | "unchanged" | "skipped";

const ACTION: Record<string, [string, "good" | "accent" | "neutral" | "warning"]> = {
  added: ["New", "good"],
  updated: ["Update", "accent"],
  restored: ["Restore", "accent"],
  unchanged: ["No change", "neutral"],
  skipped: ["Skipped", "warning"],
};

const FIELD: Record<string, string> = {
  name: "Name", email: "Email", college: "College", colleges: "Colleges", leetcode: "LeetCode",
  roll_nos: "Roll nos", active: "Status",
};

function val(key: string, v: unknown): string {
  if (v == null || v === "") return "—";
  if (key === "active") return v ? "active" : "removed";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  return String(v);
}

/** What an added row will contain, or an updated row's changes (old → new). */
function Details({ r }: { r: PreviewRecord }) {
  if (r.action === "skipped") return <span className="text-warning-ink">{r.reason}</span>;
  if (r.action === "unchanged") return <span className="text-ink-3">Already up to date</span>;
  const after = r.after ?? {};
  if (r.action === "added") {
    const bits = Object.entries(after)
      .filter(([k, v]) => k !== "name" && k !== "email" && k !== "active" && v != null && v !== "" && !(Array.isArray(v) && !v.length))
      .flatMap(([k, v]) =>
        k === "extra" ? Object.entries(v as Record<string, string>).filter(([, x]) => x).map(([c, x]) => `${c} ${x}`) : [`${FIELD[k] ?? k}: ${val(k, v)}`],
      );
    return <span className="text-ink-2">{bits.join(" · ") || "—"}</span>;
  }
  const lines: { f: string; from: string; to: string }[] = [];
  for (const [k, to] of Object.entries(after)) {
    const from = r.before?.[k];
    if (k === "extra") {
      const a = (from ?? {}) as Record<string, string>;
      const b = (to ?? {}) as Record<string, string>;
      for (const c of new Set([...Object.keys(a), ...Object.keys(b)])) if (a[c] !== b[c]) lines.push({ f: c, from: a[c] || "—", to: b[c] || "—" });
    } else lines.push({ f: FIELD[k] ?? k, from: val(k, from), to: val(k, to) });
  }
  return (
    <span className="flex flex-col gap-0.5">
      {lines.map((l, i) => (
        <span key={i}>
          <span className="text-ink-3">{l.f}: </span>
          <span className="text-ink-3 line-through decoration-ink-3/50">{l.from}</span>
          <span className="mx-1 text-ink-3">→</span>
          <span className="text-ink">{l.to}</span>
        </span>
      ))}
    </span>
  );
}

/** Review an Excel upload before anything is saved: the record count, every record and
 *  what will happen to it; Save writes it, Cancel discards it. */
export default function UploadReview({
  file,
  data,
  noun,
  keyLabel,
  saving,
  error,
  onSave,
  onCancel,
}: {
  file: File;
  data: UploadPreview;
  noun: string; // "student"
  keyLabel: string; // "Roll no" / "Email"
  saving: boolean;
  error: unknown;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const counts: Record<Filter, number> = {
    all: data.records.length,
    added: data.added,
    updated: data.updated + (data.restored ?? 0),
    unchanged: data.unchanged ?? 0,
    skipped: data.skipped,
  };
  const toSave = data.added + data.updated + (data.restored ?? 0);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return data.records.filter(
      (r) =>
        (filter === "all" || r.action === filter || (filter === "updated" && r.action === "restored")) &&
        (!q || r.key.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)),
    );
  }, [data.records, filter, query]);
  const plural = (n: number) => `${fmtInt(n)} ${n === 1 ? noun : noun + "s"}`;
  const virtual = useBoxRows(rows.length, 41);

  const tabs: [Filter, string][] = [
    ["all", "All"],
    ["added", "New"],
    ["updated", "Updates"],
    ["unchanged", "No change"],
    ["skipped", "Skipped"],
  ];

  return (
    <Dialog
      open
      xl
      busy={saving}
      onClose={onCancel}
      title={`Review ${file.name}`}
      footer={
        <div className="flex w-full flex-wrap items-center gap-3">
          <span className="mr-auto text-xs text-ink-3">Nothing has been saved yet.</span>
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onSave} disabled={saving || toSave === 0} autoFocus>
            {saving ? "Saving…" : toSave === 0 ? "Nothing to save" : `Save ${plural(toSave)}`}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {/* the record count and what will happen */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Tile label="Records in file" value={fmtInt(data.rows)} />
          <Tile label="New" value={fmtInt(data.added)} tone="good" />
          <Tile label="Updates" value={fmtInt(data.updated + (data.restored ?? 0))} tone="accent" />
          <Tile label="No change" value={fmtInt(data.unchanged ?? 0)} />
          <Tile label="Skipped" value={fmtInt(data.skipped)} tone={data.skipped ? "warning" : undefined} />
        </div>
        {!!data.restored && <p className="text-xs text-ink-2">Updates include {plural(data.restored)} who had been removed and will be restored.</p>}
        {!!data.new_colleges?.length && (
          <p className="text-xs text-ink-2">
            New {data.new_colleges.length === 1 ? "college" : "colleges"} will be added: <span className="text-ink">{data.new_colleges.join(", ")}</span>
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1 rounded-lg bg-fg/[0.04] p-1 ring-1 ring-inset ring-fg/[0.06]">
            {tabs.map(([f, label]) => (
              <button
                key={f}
                type="button"
                onClick={() => {
                  setFilter(f);
                  virtual.toTop();
                }}
                aria-pressed={filter === f}
                className={cx(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  filter === f ? "bg-surface text-ink shadow-sm ring-1 ring-inset ring-fg/[0.08]" : "text-ink-2 hover:text-ink",
                )}
              >
                {label} <span className="tabular text-ink-3">{fmtInt(counts[f])}</span>
              </button>
            ))}
          </div>
          <input
            type="search"
            placeholder={`Find a name or ${keyLabel.toLowerCase()}`}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              virtual.toTop();
            }}
            className="ml-auto h-8 w-full rounded-md border border-border bg-field px-2.5 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none sm:w-60"
          />
        </div>

        <div ref={virtual.box} className="max-h-[46vh] overflow-auto rounded-lg ring-1 ring-inset ring-fg/[0.08]">
          {rows.length === 0 ? (
            <p className="px-4 py-8 text-center text-[13px] text-ink-3">No records here.</p>
          ) : (
            <table className="w-full text-[13px]" aria-rowcount={rows.length + 1}>
              <thead className="sticky top-0 z-10 bg-surface text-left text-[11px] uppercase tracking-wide text-ink-3 shadow-[0_1px_0_var(--border)]">
                <tr>
                  <th className="w-14 px-3 py-2 font-medium">Row</th>
                  <th className="px-3 py-2 font-medium">{keyLabel}</th>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Details</th>
                </tr>
              </thead>
              <tbody>
                <Spacer height={virtual.before} cols={5} />
                {virtual.items.map(({ index }) => {
                  const r = rows[index];
                  return (
                  <tr
                    key={`${r.row}-${r.key}`}
                    ref={virtual.measure}
                    data-index={index}
                    aria-rowindex={index + 2}
                    className={cx("border-t border-fg/[0.05] align-top", r.action === "skipped" && "bg-warning/[0.04]")}
                  >
                    <td className="tabular px-3 py-2 text-ink-3">{r.row}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-ink">{r.key || "—"}</td>
                    <td className="px-3 py-2 text-ink">{r.name || "—"}</td>
                    <td className="px-3 py-2">
                      <Badge tone={ACTION[r.action][1]}>{ACTION[r.action][0]}</Badge>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <Details r={r} />
                    </td>
                  </tr>
                  );
                })}
                <Spacer height={virtual.after} cols={5} />
              </tbody>
            </table>
          )}
        </div>
        {rows.length > 0 && <span className="tabular text-xs text-ink-3">{plural(rows.length)} · scroll to see them all</span>}
        {error != null && <ErrorBox error={error} />}
      </div>
    </Dialog>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: "good" | "accent" | "warning" }) {
  return (
    <div className="rounded-lg bg-fg/[0.03] px-3 py-2 ring-1 ring-inset ring-fg/[0.06]">
      <div className="text-[10px] font-medium uppercase tracking-wide text-ink-3">{label}</div>
      <div
        className={cx(
          "tabular mt-0.5 text-lg font-semibold",
          tone === "good" ? "text-good-ink" : tone === "accent" ? "text-accent-ink" : tone === "warning" ? "text-warning-ink" : "text-ink",
        )}
      >
        {value}
      </div>
    </div>
  );
}
