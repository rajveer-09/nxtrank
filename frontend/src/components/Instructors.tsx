/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { instructorsApi, type ImportSummary, type Instructor, type InstructorInput, type UploadPreview, type InstructorList } from "../api";
import UploadReview from "./UploadReview";
import { fmtInt } from "../format";
import { AuditLine, ImportResult, UploadButton } from "./Roster";
import UploadHistory from "./UploadHistory";
import { Badge, Button, Card, CardHeader, ConfirmDialog, Consequences, Empty, ErrorBox, FieldLabel, Input, LinkButton, Textarea, cx } from "./ui";
import { RowsSkeleton } from "./skeletons";
import { patchCache, type Undo } from "../optimistic";

const BLANK: InstructorInput = { email: "", name: "", password: "", colleges: [], roll_nos: [], active: true };

/** Admin: add, edit, deactivate and delete instructors, and choose whose students they follow. */
export default function InstructorsCard() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["instructors"], queryFn: instructorsApi.list });
  const [editing, setEditing] = useState<Instructor | "new" | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["instructors"] });
  const [result, setResult] = useState<{ file: string; s: ImportSummary } | null>(null);
  const [review, setReview] = useState<{ file: File; data: UploadPreview } | null>(null);
  const check = useMutation({
    mutationFn: (f: File) => instructorsApi.preview(f),
    onSuccess: (data, file) => setReview({ file, data }),
  });
  const upload = useMutation({
    mutationFn: (f: File) => instructorsApi.upload(f),
    onSuccess: (s, f) => {
      setReview(null);
      setResult({ file: f.name, s });
      refresh();
      qc.invalidateQueries({ queryKey: ["uploads", "instructors"] });
    },
  });

  return (
    <Card>
      <CardHeader
        title="Instructors"
        subtitle={`Instructors log in with their email and see a “My students” page for the colleges and students you assign them. Add them here or upload an Excel file (up to ${list.data?.max_upload_rows ?? 300} per file).`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <LinkButton href={instructorsApi.templateUrl} download>
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
              Add instructor
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
          noun="instructor"
          keyLabel="Email"
          saving={upload.isPending}
          error={upload.error}
          onSave={() => upload.mutate(review.file)}
          onCancel={() => setReview(null)}
        />
      )}
      {result && <ImportResult file={result.file} s={result.s} onClose={() => setResult(null)} />}
      <UploadHistory kind="instructors" noun="instructor" />
      {editing !== null && list.data && (
        <InstructorForm
          key={editing === "new" ? "new" : editing.id}
          instructor={editing === "new" ? null : editing}
          colleges={list.data.colleges}
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
      ) : list.data.instructors.length === 0 ? (
        <Empty>No instructors yet.</Empty>
      ) : (
        <ul className="divide-y divide-fg/5 border-t border-fg/5">
          {list.data.instructors.map((i) => (
            <InstructorRow key={i.id} i={i} onEdit={() => setEditing(i)} onChanged={refresh} editing={editing !== null && editing !== "new" && editing.id === i.id} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function InstructorRow({ i, onEdit, onChanged, editing }: { i: Instructor; onEdit: () => void; onChanged: () => void; editing: boolean }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<"toggle" | "delete" | null>(null);
  const done = () => {
    setConfirm(null);
    onChanged();
  };
  // optimistic: the row shows the new state as soon as it's confirmed
  const toggle = useMutation({
    mutationFn: (active: boolean) => instructorsApi.update(i.id, { ...i, password: "", active }),
    onMutate: async (active): Promise<Undo> => {
      setConfirm(null);
      const undo = await patchCache<InstructorList>(qc, ["instructors"], (d) => ({
        ...d,
        instructors: d.instructors.map((x) => (x.id === i.id ? { ...x, active } : x)),
      }));
      return { undo };
    },
    onError: (_e, _v, ctx) => ctx?.undo(),
    onSettled: onChanged,
  });
  const remove = useMutation({ mutationFn: () => instructorsApi.remove(i.id), onSuccess: done });
  const assigned = [i.colleges.join(", "), i.roll_nos.length ? `${i.roll_nos.length} individual ${i.roll_nos.length === 1 ? "student" : "students"}` : ""].filter(Boolean).join(" and ");
  const err = toggle.error ?? remove.error;

  return (
    <li className={cx("flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:gap-4", editing && "bg-accent-soft/30", !i.active && "opacity-70")}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold text-ink">{i.name}</span>
          {i.active ? (
            <Badge tone="good" icon="check">Active</Badge>
          ) : (
            <Badge tone="neutral" icon="dash">Deactivated</Badge>
          )}
        </div>
        <div className="truncate text-xs text-ink-3">{i.email}</div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
          {i.colleges.map((c) => (
            <span key={c} className="rounded-full bg-fg/[0.05] px-2 py-0.5 ring-1 ring-inset ring-fg/[0.06]">
              {c}
            </span>
          ))}
          {i.roll_nos.length > 0 && (
            <span className="rounded-full bg-fg/[0.05] px-2 py-0.5 ring-1 ring-inset ring-fg/[0.06]" title={i.roll_nos.join(", ")}>
              +{i.roll_nos.length} {i.roll_nos.length === 1 ? "student" : "students"} by roll no
            </span>
          )}
          {i.colleges.length === 0 && i.roll_nos.length === 0 && <span className="text-ink-3">No students assigned</span>}
        </div>
        {err && <div className="mt-1.5 text-xs text-critical">{(err as Error).message}</div>}
      </div>
      <div className="tabular shrink-0 text-xs text-ink-2 sm:w-24 sm:text-right">{fmtInt(i.students)} students</div>
      <AuditLine a={i} className="shrink-0 sm:w-48" />
      <div className="flex shrink-0 flex-wrap items-center gap-1">
        <Link to={`/my-students?instructor=${i.id}`} className="rounded-md px-2.5 py-1 text-xs font-medium text-accent-ink hover:bg-accent-soft">
          View
        </Link>
        <Button variant="ghost" size="sm" onClick={onEdit}>
          Edit
        </Button>
        <Button variant="ghost" size="sm" onClick={() => { toggle.reset(); setConfirm("toggle"); }}>
          {i.active ? "Deactivate" : "Activate"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => { remove.reset(); setConfirm("delete"); }}
          className="hover:bg-critical/10 hover:text-critical-ink"
          title="Delete this login for good"
        >
          Delete
        </Button>
        <ConfirmDialog
          open={confirm === "toggle"}
          onClose={() => setConfirm(null)}
          onConfirm={() => toggle.mutate(!i.active)}
          danger={i.active}
          title={i.active ? `Deactivate ${i.name}?` : `Activate ${i.name}?`}
          confirmLabel={i.active ? "Yes, deactivate" : "Yes, activate"}
        >
          <p>{i.email}</p>
          <Consequences
            items={
              i.active
                ? ["They're signed out now and can't log in.", `Their setup is kept${assigned ? ` (${assigned})` : ""}; activate them again any time.`]
                : ["They can log in again with their current password.", `They see their ${i.students} students again.`]
            }
          />
        </ConfirmDialog>
        <ConfirmDialog
          open={confirm === "delete"}
          onClose={() => setConfirm(null)}
          onConfirm={() => remove.mutate()}
          busy={remove.isPending}
          error={remove.error}
          danger
          title={`Delete ${i.name} for good?`}
          confirmLabel="Yes, delete"
        >
          <p>{i.email}</p>
          <Consequences
            items={[
              `Their login is removed${assigned ? `, and with it their assignments (${assigned})` : ""}.`,
              "This can't be undone. To keep their setup, deactivate them instead.",
              "Students and their results aren't affected.",
            ]}
          />
        </ConfirmDialog>
      </div>
    </li>
  );
}

function InstructorForm({ instructor, colleges, onDone, onCancel }: { instructor: Instructor | null; colleges: string[]; onDone: () => void; onCancel: () => void }) {
  const [form, setForm] = useState<InstructorInput>(instructor ? { ...instructor, password: "" } : BLANK);
  const [rolls, setRolls] = useState((instructor?.roll_nos ?? []).join(", "));
  const [filter, setFilter] = useState("");
  const save = useMutation({
    mutationFn: (body: InstructorInput) => (instructor ? instructorsApi.update(instructor.id, body) : instructorsApi.create(body)),
    onSuccess: onDone,
  });
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? colleges.filter((c) => c.toLowerCase().includes(q)) : colleges;
  }, [colleges, filter]);
  const set = <K extends keyof InstructorInput>(k: K, v: InstructorInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const toggleCollege = (c: string) => set("colleges", form.colleges.includes(c) ? form.colleges.filter((x) => x !== c) : [...form.colleges, c]);

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate({ ...form, roll_nos: rolls.split(/[\s,;]+/).filter(Boolean) });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 border-y border-fg/5 bg-fg/[0.015] px-5 py-4">
      <h3 className="text-[13px] font-semibold text-ink">{instructor ? `Edit ${instructor.name}` : "New instructor"}</h3>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <FieldLabel>Name</FieldLabel>
          <Input value={form.name} onChange={(e) => set("name", e.target.value)} required placeholder="Asha Rao" />
        </label>
        <label className="flex flex-col gap-1">
          <FieldLabel>Email (login)</FieldLabel>
          <Input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} required placeholder="asha@nxtwave.co.in" />
        </label>
        <label className="flex flex-col gap-1">
          <FieldLabel>{instructor ? "New password" : "Password"}</FieldLabel>
          <Input
            type="password"
            autoComplete="new-password"
            value={form.password ?? ""}
            onChange={(e) => set("password", e.target.value)}
            required={!instructor}
            minLength={10}
            placeholder={instructor ? "Leave blank to keep" : "At least 10 characters"}
          />
        </label>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <FieldLabel>
            Colleges <span className="normal-case tracking-normal text-ink-3">· all their students ({form.colleges.length} selected)</span>
          </FieldLabel>
          {colleges.length > 8 && <Input type="search" placeholder="Find a college" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-full sm:w-56" />}
        </div>
        {colleges.length === 0 ? (
          <p className="text-xs text-ink-3">No colleges yet. They come from the roster sheet.</p>
        ) : (
          <div className="flex max-h-44 flex-wrap gap-1.5 overflow-y-auto">
            {shown.map((c) => {
              const on = form.colleges.includes(c);
              return (
                <button
                  key={c}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggleCollege(c)}
                  className={cx(
                    "ripple inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ring-1 ring-inset transition-colors",
                    on ? "bg-accent-soft font-medium text-accent-ink ring-accent/40" : "bg-surface text-ink-2 ring-fg/[0.08] hover:text-ink",
                  )}
                >
                  {on && (
                    <svg aria-hidden viewBox="0 0 12 12" className="h-3 w-3">
                      <path d="m2.5 6.5 2.2 2.2 4.8-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                  {c}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <label className="flex flex-col gap-1">
        <FieldLabel>
          Individual students <span className="normal-case tracking-normal text-ink-3">· roll numbers, separated by commas or new lines (optional)</span>
        </FieldLabel>
        <Textarea rows={2} value={rolls} onChange={(e) => setRolls(e.target.value)} placeholder="NW2026001, NW2026002" />
      </label>

      {save.isError && <ErrorBox error={save.error} />}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : instructor ? "Save changes" : "Add instructor"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
