/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { rosterApi, type Audit, type ImportSummary, type RosterList, type RosterShow, type RosterStudent, type StudentInput, type UploadPreview, type Via } from "../api";
import { ROSTER_PAGE, rosterQuery } from "../queries";
import { useDebounced } from "../useDebounced";
import UploadReview from "./UploadReview";
import { fmtInt, fmtIso } from "../format";
import UploadHistory, { ChangesDialog } from "./UploadHistory";
import { Badge, Button, Card, CardHeader, ConfirmDialog, Consequences, Empty, ErrorBox, FieldLabel, HandleStatusBadge, Input, LinkButton, Select, cx } from "./ui";
import { RowsSkeleton } from "./skeletons";
import { patchCache, type Undo } from "../optimistic";

// ---- shared bits (also used by the instructors section) -------------------------------

const VIA_LABEL: Record<Via, string> = { ui: "Dashboard", excel: "Excel upload", cli: "Command line", sheet: "Google Sheet (old sync)", undo: "Undo of an upload" };

/** "Changed 14 Oct, 9:41 pm by asha@… · Excel upload" — who touched the row last, and how. */
export function AuditLine({ a, className }: { a: Audit; className?: string }) {
  const at = a.updated_at ?? a.created_at;
  const via = a.updated_via ?? a.created_via;
  const by = a.updated_by ?? a.created_by;
  if (!at && !by && !via) return <span className={cx("text-xs text-ink-3", className)}>—</span>;
  const created = !a.updated_at || a.updated_at === a.created_at;
  const full = [
    a.created_at && `Added ${fmtIso(a.created_at)}${a.created_by ? ` by ${a.created_by}` : ""}${a.created_via ? ` (${VIA_LABEL[a.created_via]})` : ""}`,
    !created && at && `Last changed ${fmtIso(at)}${by ? ` by ${by}` : ""}${via ? ` (${VIA_LABEL[via]})` : ""}`,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <div className={cx("text-xs leading-snug", className)} title={full}>
      <div className="text-ink-2">
        {created ? "Added" : "Changed"} {at ? fmtIso(at) : via === "sheet" ? "from the Google Sheet" : ""}
      </div>
      <div className="flex min-w-0 items-center gap-1.5 text-ink-3">
        {by && <span className="max-w-44 truncate">{by}</span>}
        {via && (
          <span
            className={cx(
              "shrink-0 rounded-full px-1.5 py-px text-[10px] font-semibold ring-1 ring-inset",
              via === "excel" ? "bg-good/10 text-good-ink ring-good/25" : via === "ui" ? "bg-accent-soft text-accent-ink ring-accent/25" : "bg-fg/[0.05] text-ink-2 ring-fg/10",
            )}
          >
            {via === "ui" ? "UI" : via === "excel" ? "Excel" : via === "cli" ? "CLI" : via === "undo" ? "Undo" : "Sheet"}
          </span>
        )}
      </div>
    </div>
  );
}

/** A button that opens a file picker for .xlsx / .csv. */
export function UploadButton({ onFile, busy, label = "Upload Excel" }: { onFile: (f: File) => void; busy: boolean; label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = ""; // allow the same file again
        }}
      />
      <Button onClick={() => input.current?.click()} disabled={busy}>
        <svg aria-hidden viewBox="0 0 16 16" className="h-3.5 w-3.5">
          <path d="M8 10.5V2.5M5 5.5l3-3 3 3M2.5 10v2.5a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {busy ? "Uploading…" : label}
      </Button>
    </>
  );
}

/** What an upload did: counts, then each skipped row and why. */
export function ImportResult({ file, s, onClose }: { file: string; s: ImportSummary; onClose: () => void }) {
  const [viewing, setViewing] = useState(false);
  const counts: [string, number | undefined, "good" | "accent" | "neutral" | "warning"][] = [
    ["added", s.added, "good"],
    ["updated", s.updated, "accent"],
    ["restored", s.restored, "accent"],
    ["unchanged", s.unchanged, "neutral"],
    ["skipped", s.skipped, "warning"],
  ];
  return (
    <div className="flex flex-col gap-2 border-y border-fg/5 bg-fg/[0.015] px-5 py-3">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <span className="font-medium text-ink">Uploaded {file}:</span>
        {counts
          .filter(([, n]) => !!n)
          .map(([label, n, tone]) => (
            <Badge key={label} tone={tone}>
              {fmtInt(n)} {label}
            </Badge>
          ))}
        {counts.every(([, n]) => !n) && <span className="text-ink-3">no rows found</span>}
        <span className="ml-auto flex items-center gap-3">
          {s.upload_id != null && (s.added || s.updated || s.restored) ? (
            <button className="text-xs font-medium text-accent-ink hover:underline" onClick={() => setViewing(true)}>
              View changes
            </button>
          ) : null}
          <button className="text-xs text-ink-3 hover:text-ink" onClick={onClose}>
            Dismiss
          </button>
        </span>
        {viewing && s.upload_id != null && <ChangesDialog uploadId={s.upload_id} onClose={() => setViewing(false)} />}
      </div>
      {s.issues.length > 0 && (
        <details open={s.issues.length <= 5}>
          <summary className="cursor-pointer text-xs text-warning-ink">
            {s.issues.length} {s.issues.length === 1 ? "row was" : "rows were"} skipped — fix them in the file and upload it again
          </summary>
          <ul className="mt-1.5 max-h-48 list-disc overflow-y-auto pl-5 text-xs text-ink-2">
            {s.issues.map((i, n) => (
              <li key={n}>{i}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ---- the student roster ------------------------------------------------------------------

const PAGE = ROSTER_PAGE;
const BLANK: StudentInput = { roll_no: "", name: "", college: "", leetcode: "", extra: {} };

export default function RosterCard() {
  const qc = useQueryClient();
  // searched and paged on the server: 25 rows come down, not the whole roster
  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim());
  const [show, setShow] = useState<RosterShow>("active");
  const [page, setPage] = useState(0);
  const list = useQuery({
    ...rosterQuery(search, show, page),
    placeholderData: keepPreviousData,
  });
  const [editing, setEditing] = useState<RosterStudent | "new" | null>(null);
  const [result, setResult] = useState<{ file: string; s: ImportSummary } | null>(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["roster"] });
    qc.invalidateQueries({ queryKey: ["students"] });
    qc.invalidateQueries({ queryKey: ["analytics"] });
  };
  // upload = check first (nothing saved), review, then save
  const [review, setReview] = useState<{ file: File; data: UploadPreview } | null>(null);
  const check = useMutation({
    mutationFn: (f: File) => rosterApi.preview(f),
    onSuccess: (data, file) => setReview({ file, data }),
  });
  const upload = useMutation({
    mutationFn: (f: File) => rosterApi.upload(f),
    onSuccess: (s, f) => {
      setReview(null);
      setResult({ file: f.name, s });
      refresh();
      qc.invalidateQueries({ queryKey: ["uploads", "students"] });
    },
  });
  const max = list.data?.max_upload_rows ?? 5000;

  return (
    <Card>
      <CardHeader
        title="Students"
        subtitle={`Add students one at a time, or upload an Excel file (up to ${fmtInt(max)} students per file). Every change records when, by whom and how.`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <LinkButton href={rosterApi.templateUrl} download>
              Download template
            </LinkButton>
            <UploadButton
              onFile={(f) => {
                setResult(null);
                upload.reset();
                check.mutate(f);
              }}
              busy={check.isPending}
              label={check.isPending ? "Checking…" : "Upload Excel"}
            />
            <Button variant="primary" onClick={() => setEditing("new")} disabled={editing === "new"}>
              Add student
            </Button>
          </div>
        }
      />
      {check.isError && (
        <div className="px-5 pb-3">
          <ErrorBox error={check.error} />
        </div>
      )}
      {review && (
        <UploadReview
          file={review.file}
          data={review.data}
          noun="student"
          keyLabel="Roll no"
          saving={upload.isPending}
          error={upload.error}
          onSave={() => upload.mutate(review.file)}
          onCancel={() => setReview(null)}
        />
      )}
      {result && <ImportResult file={result.file} s={result.s} onClose={() => setResult(null)} />}
      <UploadHistory kind="students" noun="student" />
      {editing !== null && list.data && (
        <StudentForm
          key={editing === "new" ? "new" : editing.id}
          student={editing === "new" ? null : editing}
          colleges={list.data.colleges}
          extraColumns={list.data.extra_columns}
          onDone={() => {
            setEditing(null);
            refresh();
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {list.isPending ? (
        <div className="px-5">
          <RowsSkeleton />
        </div>
      ) : list.isError ? (
        <div className="p-5">
          <ErrorBox error={list.error} />
        </div>
      ) : (
        <StudentTable
          data={list.data}
          fetching={list.isPlaceholderData}
          query={query}
          onQuery={(q) => {
            setQuery(q);
            setPage(0);
          }}
          show={show}
          onShow={(v) => {
            setShow(v);
            setPage(0);
          }}
          page={page}
          onPage={setPage}
          onEdit={(s) => setEditing(s)}
          onChanged={refresh}
          editingId={editing !== null && editing !== "new" ? editing.id : null}
        />
      )}
    </Card>
  );
}

function StudentTable({
  data,
  fetching,
  query,
  onQuery,
  show,
  onShow,
  page,
  onPage,
  onEdit,
  onChanged,
  editingId,
}: {
  data: RosterList;
  fetching: boolean;
  query: string;
  onQuery: (q: string) => void;
  show: RosterShow;
  onShow: (show: RosterShow) => void;
  page: number;
  onPage: (page: number) => void;
  onEdit: (s: RosterStudent) => void;
  onChanged: () => void;
  editingId: number | null;
}) {
  const { students: shown, total, removed, extra_columns: extraColumns } = data;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  if (data.active + data.removed === 0) return <Empty>No students yet. Add one, or upload the Excel template filled in.</Empty>;
  return (
    <>
      <div className="flex flex-wrap items-center gap-3 border-y border-fg/5 bg-fg/[0.015] px-5 py-2">
        <Input
          type="search"
          placeholder="Search name, roll no, handle, college"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          className="w-full sm:w-80"
        />
        <Select
          label="Show"
          hideLabel
          value={show}
          onChange={(e) => onShow(e.target.value as RosterShow)}
        >
          <option value="active">Active students</option>
          <option value="removed">Removed ({removed})</option>
          <option value="all">Everyone</option>
        </Select>
        <span className="tabular ml-auto text-xs text-ink-3">{fmtInt(total)} students</span>
      </div>
      {total === 0 ? (
        <Empty>No students match.</Empty>
      ) : (
        <div className={cx("overflow-x-auto transition-opacity", fetching && "opacity-60")}>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-2">
              <tr className="border-b border-fg/5">
                <th className="px-5 py-2 font-medium">Student</th>
                <th className="px-3 py-2 font-medium">College</th>
                <th className="px-3 py-2 font-medium">LeetCode</th>
                {extraColumns.length > 0 && <th className="px-3 py-2 font-medium">{extraColumns.join(" · ")}</th>}
                <th className="px-3 py-2 font-medium">Last change</th>
                <th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody>
              {shown.map((s) => (
                <StudentRow key={s.id} s={s} extraColumns={extraColumns} onEdit={() => onEdit(s)} onChanged={onChanged} editing={editingId === s.id} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-border px-5 py-3 text-[13px] text-ink-2">
          <span className="tabular">
            {page * PAGE + 1}–{Math.min(total, (page + 1) * PAGE)} of {fmtInt(total)}
          </span>
          <div className="flex gap-2">
            <Button onClick={() => onPage(page - 1)} disabled={page === 0}>
              Previous
            </Button>
            <Button onClick={() => onPage(page + 1)} disabled={page >= pages - 1}>
              Next
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

function StudentRow({ s, extraColumns, onEdit, onChanged, editing }: { s: RosterStudent; extraColumns: string[]; onEdit: () => void; onChanged: () => void; editing: boolean }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  // optimistic: the row (and the counts) change as soon as it's confirmed
  const toggle = useMutation({
    mutationFn: (active: boolean) => rosterApi.setActive(s.id, active),
    onMutate: async (active): Promise<Undo> => {
      setConfirm(false);
      const delta = active ? 1 : -1;
      const undo = await patchCache<RosterList>(qc, ["roster"], (d) => ({
        ...d,
        students: d.students.map((x) => (x.id === s.id ? { ...x, active } : x)),
        active: d.active + delta,
        removed: d.removed - delta,
      }));
      return { undo };
    },
    onError: (_e, _v, ctx) => ctx?.undo(),
    onSettled: onChanged,
  });
  return (
    <tr className={cx("border-b border-fg/5 align-top last:border-0 hover:bg-fg/[0.02]", editing && "bg-accent-soft/30", !s.active && "opacity-60")}>
      <td className="px-5 py-2.5">
        <Link to={`/students/${s.id}`} className="font-medium text-ink hover:text-accent-ink hover:underline">
          {s.name}
        </Link>
        <div className="flex items-center gap-1.5 text-xs text-ink-3">
          {s.roll_no}
          {!s.active && <Badge tone="neutral" icon="dash">Removed</Badge>}
        </div>
      </td>
      <td className="px-3 py-2.5 text-ink-2">{s.college || <span className="text-ink-3">—</span>}</td>
      <td className="px-3 py-2.5">
        {s.handle ? (
          <div className="flex flex-col items-start gap-1">
            <span className="text-[13px]">{s.handle}</span>
            <HandleStatusBadge status={s.handle_status} />
          </div>
        ) : (
          <span className="text-xs text-ink-3">no handle</span>
        )}
      </td>
      {extraColumns.length > 0 && (
        <td className="whitespace-nowrap px-3 py-2.5 text-xs text-ink-2">{extraColumns.map((k) => s.extra[k] || "—").join(" · ")}</td>
      )}
      <td className="px-3 py-2.5">
        {toggle.isPending ? <span className="text-xs text-ink-3">Saving…</span> : <AuditLine a={s} />}
        {toggle.isError && <div className="mt-1 text-xs text-critical">{(toggle.error as Error).message}</div>}
      </td>
      <td className="whitespace-nowrap px-5 py-2.5 text-right">
        <Button variant="ghost" size="sm" onClick={onEdit}>
          Edit
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            toggle.reset();
            setConfirm(true);
          }}
          className={s.active ? "hover:bg-critical/10 hover:text-critical-ink" : ""}
          title={s.active ? "Remove from the roster; past results are kept" : "Put back on the roster"}
        >
          {s.active ? "Remove" : "Restore"}
        </Button>
        <ConfirmDialog
          open={confirm}
          onClose={() => setConfirm(false)}
          onConfirm={() => toggle.mutate(!s.active)}
          danger={s.active}
          title={s.active ? `Remove ${s.name}?` : `Restore ${s.name}?`}
          confirmLabel={s.active ? "Yes, remove" : "Yes, restore"}
        >
          <p>
            {s.roll_no}
            {s.college ? ` · ${s.college}` : ""}
            {s.handle ? ` · ${s.handle}` : ""}
          </p>
          <Consequences
            items={
              s.active
                ? [
                    "They leave future scans, analytics, toppers and instructors' pages.",
                    "Their past contest results stay, and they can be restored any time.",
                    s.handle ? `Their LeetCode handle (${s.handle}) becomes free for another student.` : null,
                  ]
                : [
                    "They're back in scans, analytics and instructors' pages, with their full history.",
                    s.handle ? `Not possible if another active student now uses ${s.handle}.` : null,
                  ]
            }
          />
        </ConfirmDialog>
      </td>
    </tr>
  );
}

function StudentForm({ student, colleges, extraColumns, onDone, onCancel }: { student: RosterStudent | null; colleges: string[]; extraColumns: string[]; onDone: () => void; onCancel: () => void }) {
  const [form, setForm] = useState<StudentInput>(
    student ? { roll_no: student.roll_no, name: student.name, college: student.college, leetcode: student.leetcode, extra: { ...student.extra } } : BLANK,
  );
  const keys = [...new Set([...extraColumns, ...Object.keys(form.extra)])];
  const save = useMutation({
    mutationFn: (body: StudentInput) => (student ? rosterApi.update(student.id, body) : rosterApi.create(body)),
    onSuccess: onDone,
  });
  const set = <K extends keyof StudentInput>(k: K, v: StudentInput[K]) => setForm((f) => ({ ...f, [k]: v }));

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(form);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 border-y border-fg/5 bg-fg/[0.015] px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-semibold text-ink">{student ? `Edit ${student.name}` : "New student"}</h3>
        {student && <AuditLine a={student} className="text-right" />}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1">
          <FieldLabel>Roll no</FieldLabel>
          <Input value={form.roll_no} onChange={(e) => set("roll_no", e.target.value)} required placeholder="NW2026001" />
        </label>
        <label className="flex flex-col gap-1">
          <FieldLabel>Name</FieldLabel>
          <Input value={form.name} onChange={(e) => set("name", e.target.value)} required placeholder="Asha Rao" />
        </label>
        <div className="flex flex-col gap-1">
          <Select label="College" value={form.college} onChange={(e) => set("college", e.target.value)} className="w-full">
            <option value="">No college</option>
            {colleges.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
          <span className="text-[11px] text-ink-3">
            Missing one? <Link to="/admin/colleges" className="text-accent-ink hover:underline">Colleges</Link> (super admin)
          </span>
        </div>
        <label className="flex flex-col gap-1">
          <FieldLabel>LeetCode</FieldLabel>
          <Input value={form.leetcode} onChange={(e) => set("leetcode", e.target.value)} placeholder="username or profile URL" />
        </label>
        {keys.map((k) => (
          <label key={k} className="flex flex-col gap-1">
            <FieldLabel>{k}</FieldLabel>
            <Input value={form.extra[k] ?? ""} onChange={(e) => set("extra", { ...form.extra, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      {save.isError && <ErrorBox error={save.error} />}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : student ? "Save changes" : "Add student"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
