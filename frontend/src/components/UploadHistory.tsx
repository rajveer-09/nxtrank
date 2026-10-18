/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { uploadsApi, type UploadChange, type UploadItem } from "../api";
import { fmtInt, fmtIso } from "../format";
import { Badge, Button, Dialog, ErrorBox, cx } from "./ui";
import { RowsSkeleton } from "./skeletons";

const FIELD: Record<string, string> = {
  name: "Name",
  email: "Email",
  college: "College",
  colleges: "Colleges",
  leetcode: "LeetCode",
  roll_nos: "Roll nos",
  active: "Status",
  password: "Password",
};

function show(key: string, v: unknown): string {
  if (v == null || v === "") return "—";
  if (key === "active") return v ? "active" : "removed";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  return String(v);
}

/** "College: Alpha → Beta" lines for one change; extra columns (Batch, …) one by one. */
function changeLines(c: UploadChange): { field: string; from: string; to: string }[] {
  if (c.action === "added") return [];
  const out: { field: string; from: string; to: string }[] = [];
  for (const [k, to] of Object.entries(c.after)) {
    const from = c.before?.[k];
    if (k === "extra") {
      const a = (from ?? {}) as Record<string, string>;
      const b = (to ?? {}) as Record<string, string>;
      for (const col of new Set([...Object.keys(a), ...Object.keys(b)]))
        if (a[col] !== b[col]) out.push({ field: col, from: a[col] || "—", to: b[col] || "—" });
    } else if (k === "password") {
      out.push({ field: "Password", from: "", to: "changed (not shown, not undone)" });
    } else {
      out.push({ field: FIELD[k] ?? k, from: show(k, from), to: show(k, to) });
    }
  }
  return out;
}

/** "1 student", "3 students" */
const count = (n: number, noun: string) => `${fmtInt(n)} ${n === 1 ? noun : noun + "s"}`;

const COUNT_TONE: Record<string, "good" | "accent" | "neutral" | "warning"> = {
  added: "good",
  updated: "accent",
  restored: "accent",
  unchanged: "neutral",
  skipped: "warning",
};

/** Past Excel uploads for students or instructors: what each changed, and undo. */
export default function UploadHistory({ kind, noun }: { kind: "students" | "instructors"; noun: string }) {
  const list = useQuery({ queryKey: ["uploads", kind], queryFn: () => uploadsApi.list(kind) });
  const [open, setOpen] = useState(false);
  const [viewing, setViewing] = useState<UploadItem | null>(null);
  const [undoing, setUndoing] = useState<UploadItem | null>(null);
  const items = list.data ?? [];
  if (list.isPending || items.length === 0) return null;
  const latest = items[0];

  return (
    <div className="border-y border-fg/5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-5 py-2.5 text-left text-[13px] text-ink-2 hover:bg-fg/[0.02]"
      >
        <svg aria-hidden viewBox="0 0 16 16" className={cx("h-3.5 w-3.5 transition-transform", open && "rotate-90")}>
          <path d="m6 4 4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="font-medium text-ink">Upload history</span>
        <span className="text-ink-3">
          · {items.length} {items.length === 1 ? "upload" : "uploads"} · last {fmtIso(latest.uploaded_at)} by {latest.uploaded_by}
        </span>
      </button>
      {open && (
        <ul className="divide-y divide-fg/5 border-t border-fg/5">
          {items.map((u) => (
            <li key={u.id} className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-[13px] font-medium text-ink" title={u.filename}>
                    {u.filename}
                  </span>
                  {u.status === "undone" ? (
                    <Badge tone="neutral" icon="dash">
                      Undone
                    </Badge>
                  ) : null}
                </div>
                <div className="text-xs text-ink-3">
                  {fmtIso(u.uploaded_at)} · by {u.uploaded_by}
                  {u.via === "cli" ? " (command line)" : ""}
                  {u.status === "undone" && u.undone_at ? ` · undone ${fmtIso(u.undone_at)} by ${u.undone_by}` : ""}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {Object.entries(u.counts)
                    .filter(([, n]) => n > 0)
                    .map(([k, n]) => (
                      <Badge key={k} tone={COUNT_TONE[k] ?? "neutral"}>
                        {fmtInt(n)} {k}
                      </Badge>
                    ))}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button variant="ghost" size="sm" onClick={() => setViewing(u)} disabled={u.changes === 0}>
                  View changes
                </Button>
                {u.status === "applied" && u.changes > 0 && (
                  <Button variant="ghost" size="sm" onClick={() => setUndoing(u)} className="hover:bg-critical/10 hover:text-critical-ink">
                    Undo
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {viewing && <ChangesDialog uploadId={viewing.id} onClose={() => setViewing(null)} />}
      {undoing && <UndoDialog upload={undoing} noun={noun} onClose={() => setUndoing(null)} />}
    </div>
  );
}

export function ChangesDialog({ uploadId, onClose }: { uploadId: number; onClose: () => void }) {
  const detail = useQuery({ queryKey: ["upload", uploadId], queryFn: () => uploadsApi.get(uploadId) });
  const upload = detail.data;
  const [query, setQuery] = useState("");
  const changes = (detail.data?.changes ?? []).filter((c) => !query || c.label.toLowerCase().includes(query.toLowerCase()));
  return (
    <Dialog
      open
      wide
      onClose={onClose}
      title={upload ? `Changes from ${upload.filename}` : "Changes"}
      footer={
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      }
    >
      {detail.isPending ? (
        <RowsSkeleton />
      ) : detail.isError ? (
        <ErrorBox error={detail.error} onRetry={() => detail.refetch()} />
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-ink-3">
            {fmtIso(detail.data.uploaded_at)} by {detail.data.uploaded_by}. Only the fields this upload changed are shown.
          </p>
          {detail.data.changes.length > 8 && (
            <input
              type="search"
              placeholder="Find a name or roll no"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-8 rounded-md border border-border bg-field px-2.5 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
            />
          )}
          <ul className="max-h-[50vh] divide-y divide-fg/5 overflow-y-auto rounded-lg ring-1 ring-inset ring-fg/[0.06]">
            {changes.map((c, i) => (
              <ChangeRow key={i} c={c} />
            ))}
          </ul>
          {detail.data.status === "undone" && detail.data.undo_result && <UndoResult r={detail.data.undo_result} />}
        </div>
      )}
    </Dialog>
  );
}

function ChangeRow({ c }: { c: UploadChange }) {
  const lines = changeLines(c);
  const tag: Record<string, ReactNode> = {
    added: <Badge tone="good">added</Badge>,
    updated: <Badge tone="accent">updated</Badge>,
    restored: <Badge tone="accent">restored</Badge>,
  };
  return (
    <li className="px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-ink">{c.entity === "college" ? `College: ${c.label}` : c.label}</span>
        {tag[c.action]}
      </div>
      {lines.length > 0 && (
        <dl className="mt-1 grid grid-cols-[minmax(5rem,auto)_1fr] gap-x-3 gap-y-0.5 text-xs">
          {lines.map((l, i) => (
            <div key={i} className="contents">
              <dt className="text-ink-3">{l.field}</dt>
              <dd className="text-ink-2">
                {l.from && (
                  <>
                    <span className="line-through decoration-ink-3/60">{l.from}</span>
                    <span className="mx-1.5 text-ink-3">→</span>
                  </>
                )}
                <span className="text-ink">{l.to}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}

function UndoResult({ r }: { r: { reverted: number; skipped: string[] } }) {
  return (
    <div className="rounded-lg bg-fg/[0.03] px-3 py-2.5 text-xs ring-1 ring-inset ring-fg/[0.06]">
      <div className="text-ink">
        {fmtInt(r.reverted)} {r.reverted === 1 ? "change" : "changes"} undone
        {r.skipped.length > 0 && `, ${r.skipped.length} left as they are`}
      </div>
      {r.skipped.length > 0 && (
        <ul className="mt-1.5 max-h-40 list-disc overflow-y-auto pl-4 text-ink-2">
          {r.skipped.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UndoDialog({ upload, noun, onClose }: { upload: UploadItem; noun: string; onClose: () => void }) {
  const qc = useQueryClient();
  const undo = useMutation({
    mutationFn: () => uploadsApi.undo(upload.id),
    onSuccess: () => {
      for (const key of ["uploads", "roster", "students", "instructors", "colleges", "analytics", "upload"]) qc.invalidateQueries({ queryKey: [key] });
    },
  });
  const c = upload.counts;
  const done = undo.data;
  return (
    <Dialog
      open
      onClose={onClose}
      busy={undo.isPending}
      title={done ? "Upload undone" : `Undo ${upload.filename}?`}
      footer={
        done ? (
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose} disabled={undo.isPending}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => undo.mutate()} disabled={undo.isPending} autoFocus className="bg-critical hover:bg-critical/90">
              {undo.isPending ? "Undoing…" : "Yes, undo"}
            </Button>
          </>
        )
      }
    >
      {done ? (
        <UndoResult r={done} />
      ) : (
        <div className="flex flex-col gap-3">
          <p>Everything this upload changed is put back the way it was before it:</p>
          <ul className="flex flex-col gap-1.5 rounded-lg bg-fg/[0.03] px-4 py-3 ring-1 ring-inset ring-fg/[0.06]">
            {!!c.updated && <li>{count(c.updated, noun)} put back to {c.updated === 1 ? "its" : "their"} earlier details</li>}
            {!!c.added && <li>{count(c.added, noun)} it added {c.added === 1 ? "is" : "are"} removed</li>}
            {!!c.restored && <li>{count(c.restored, noun)} it brought back {c.restored === 1 ? "is" : "are"} removed again</li>}
          </ul>
          <p className="text-xs text-ink-3">
            Anything changed since this upload (on the dashboard or by a later upload) is left as it is and listed afterwards. The undo is recorded against your name.
            {upload.kind === "instructors" ? " Passwords are never undone." : ""}
          </p>
          {undo.isError && <ErrorBox error={undo.error} />}
        </div>
      )}
    </Dialog>
  );
}
