/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { collegesApi, type CollegeRow, type CollegeList } from "../api";
import { fmtInt } from "../format";
import { AuditLine } from "./Roster";
import { Button, Card, CardHeader, ConfirmDialog, Consequences, Empty, ErrorBox, FieldLabel, Input, Textarea } from "./ui";
import { RowsSkeleton } from "./skeletons";
import { patchCache, type Undo } from "../optimistic";

/** The college list. Only the super admin adds, renames or deletes; everyone else picks from it. */
export default function CollegesCard() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["colleges"], queryFn: collegesApi.list });
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["colleges"] });
    qc.invalidateQueries({ queryKey: ["roster"] });
    qc.invalidateQueries({ queryKey: ["instructors"] });
  };
  const canEdit = list.data?.can_edit ?? false;
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (list.data?.colleges ?? []).filter((c) => !q || c.name.toLowerCase().includes(q));
  }, [list.data, query]);

  return (
    <Card>
      <CardHeader
        title="Colleges"
        subtitle={
          canEdit
            ? "The colleges students and instructors are assigned to. You're the super admin: add, rename or delete them here; other admins pick from this list."
            : "The colleges students and instructors are assigned to. Only the super admin can add, rename or delete colleges."
        }
        actions={
          canEdit && (
            <Button variant="primary" onClick={() => setAdding(true)} disabled={adding}>
              Add colleges
            </Button>
          )
        }
      />
      {adding && (
        <AddForm
          onDone={(msg) => {
            setAdding(false);
            setNote(msg);
            refresh();
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      {note && (
        <div className="flex items-center gap-2 border-y border-fg/5 bg-good/[0.06] px-5 py-2 text-[13px] text-ink-2">
          {note}
          <button className="ml-auto text-xs text-ink-3 hover:text-ink" onClick={() => setNote(null)}>
            Dismiss
          </button>
        </div>
      )}
      {list.isPending ? (
        <div className="px-5">
          <RowsSkeleton />
        </div>
      ) : list.isError ? (
        <div className="p-5">
          <ErrorBox error={list.error} onRetry={() => list.refetch()} />
        </div>
      ) : list.data.colleges.length === 0 ? (
        <Empty>No colleges yet.</Empty>
      ) : (
        <>
          <div className="flex items-center gap-3 border-y border-fg/5 bg-fg/[0.015] px-5 py-2">
            <Input type="search" placeholder="Find a college" value={query} onChange={(e) => setQuery(e.target.value)} className="w-full sm:w-72" />
            <span className="tabular ml-auto text-xs text-ink-3">{fmtInt(list.data.colleges.length)} colleges</span>
          </div>
          {rows.length === 0 ? (
            <Empty>No college matches.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-ink-2">
                  <tr className="border-b border-fg/5">
                    <th className="px-5 py-2 font-medium">College</th>
                    <th className="px-3 py-2 text-right font-medium">Students</th>
                    <th className="px-3 py-2 text-right font-medium">Instructors</th>
                    <th className="px-3 py-2 font-medium">Last change</th>
                    {canEdit && <th className="px-5 py-2"><span className="sr-only">Actions</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <CollegeLine key={c.id} c={c} canEdit={canEdit} onChanged={refresh} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function CollegeLine({ c, canEdit, onChanged }: { c: CollegeRow; canEdit: boolean; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(c.name);
  const [confirm, setConfirm] = useState(false);
  const qc = useQueryClient();
  // optimistic: the new name shows as soon as it's saved; if the server refuses, the old
  // name comes back and the editor reopens with the reason
  const rename = useMutation({
    mutationFn: (to: string) => collegesApi.rename(c.id, to),
    onMutate: async (to): Promise<Undo> => {
      setEditing(false);
      const undo = await patchCache<CollegeList>(qc, ["colleges"], (d) => ({
        ...d,
        colleges: d.colleges.map((x) => (x.id === c.id ? { ...x, name: to } : x)),
      }));
      return { undo };
    },
    onError: (_e, _v, ctx) => {
      ctx?.undo();
      setEditing(true);
    },
    onSettled: onChanged,
  });
  const remove = useMutation({
    mutationFn: () => collegesApi.remove(c.id),
    onSuccess: () => {
      setConfirm(false);
      onChanged();
    },
  });
  const used = c.students + c.removed_students;
  const err = rename.error ?? remove.error;

  function submit(e: FormEvent) {
    e.preventDefault();
    rename.mutate(name.trim());
  }

  return (
    <tr className="border-b border-fg/5 align-top last:border-0 hover:bg-fg/[0.02]">
      <td className="px-5 py-2.5">
        {editing ? (
          <form onSubmit={submit} className="flex items-center gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus required className="w-full max-w-sm" aria-label="College name" />
            <Button type="submit" variant="primary" size="sm" disabled={rename.isPending}>
              Save
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setEditing(false);
                setName(c.name);
              }}
            >
              Cancel
            </Button>
          </form>
        ) : (
          <span className="font-medium text-ink">{c.name}</span>
        )}
        {err && <div className="mt-1 text-xs text-critical">{(err as Error).message}</div>}
      </td>
      <td className="tabular px-3 py-2.5 text-right">
        {fmtInt(c.students)}
        {c.removed_students > 0 && <div className="text-[11px] text-ink-3">+{c.removed_students} removed</div>}
      </td>
      <td className="tabular px-3 py-2.5 text-right">{fmtInt(c.instructors)}</td>
      <td className="px-3 py-2.5">
        <AuditLine a={c} />
      </td>
      {canEdit && (
        <td className="whitespace-nowrap px-5 py-2.5 text-right">
          {!editing && (
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
              Rename
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              remove.reset();
              setConfirm(true);
            }}
            title={used > 0 ? "Only colleges with no students can be deleted" : "Delete this college"}
            className="hover:bg-critical/10 hover:text-critical-ink"
          >
            Delete
          </Button>
          <ConfirmDialog
            open={confirm}
            onClose={() => setConfirm(false)}
            onConfirm={() => remove.mutate()}
            busy={remove.isPending}
            error={remove.error}
            danger
            title={`Delete ${c.name}?`}
            confirmLabel="Yes, delete"
            blocked={
              used > 0
                ? `${used} ${used === 1 ? "student belongs" : "students belong"} to this college${c.removed_students ? ` (${c.removed_students} of them removed)` : ""}. Move them to another college, or rename this one, first.`
                : null
            }
          >
            <Consequences
              items={[
                "It disappears from the college list, filters and analytics.",
                c.instructors ? `${c.instructors} ${c.instructors === 1 ? "instructor loses" : "instructors lose"} it from their assigned colleges.` : "No instructor is assigned to it.",
                "This can't be undone, but you can add it again later.",
              ]}
            />
          </ConfirmDialog>
        </td>
      )}
    </tr>
  );
}

function AddForm({ onDone, onCancel }: { onDone: (msg: string) => void; onCancel: () => void }) {
  const [text, setText] = useState("");
  const names = text.split(/\n|,|;/).map((n) => n.trim()).filter(Boolean);
  // review first: which names are new, which are already on the list; nothing saved yet
  const check = useMutation({ mutationFn: () => collegesApi.add(names, true) });
  const add = useMutation({
    mutationFn: () => collegesApi.add(names),
    onSuccess: (r) =>
      onDone(
        [
          r.added.length ? `Added ${r.added.length} ${r.added.length === 1 ? "college" : "colleges"}.` : "",
          r.existing.length ? `Already on the list: ${r.existing.join(", ")}.` : "",
        ]
          .filter(Boolean)
          .join(" "),
      ),
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    add.reset();
    check.mutate();
  }
  const review = check.data;
  return (
    <form onSubmit={submit} className="flex flex-col gap-3 border-y border-fg/5 bg-fg/[0.015] px-5 py-4">
      <label className="flex flex-col gap-1">
        <FieldLabel>
          College names <span className="normal-case tracking-normal text-ink-3">· one per line (or separated by commas)</span>
        </FieldLabel>
        <Textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder={"Alpha Institute of Technology\nBeta College of Engineering"} autoFocus />
      </label>
      {check.isError && <ErrorBox error={check.error} />}
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" disabled={check.isPending || names.length === 0}>
          {check.isPending ? "Checking…" : "Review"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      {review && (
        <ConfirmDialog
          open
          onClose={() => check.reset()}
          onConfirm={() => add.mutate()}
          busy={add.isPending}
          error={add.error}
          title={review.added.length ? `Add ${review.added.length} ${review.added.length === 1 ? "college" : "colleges"}?` : "Nothing new to add"}
          confirmLabel={review.added.length ? `Save ${review.added.length} ${review.added.length === 1 ? "college" : "colleges"}` : "Nothing to save"}
          blocked={review.added.length ? null : "All of these are already on the list."}
        >
          {review.added.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-good-ink">Will be added</div>
              <div className="flex flex-wrap gap-1.5">
                {review.added.map((n) => (
                  <span key={n} className="rounded-full bg-good/10 px-2.5 py-1 text-xs text-ink ring-1 ring-inset ring-good/25">
                    {n}
                  </span>
                ))}
              </div>
            </div>
          )}
          {review.existing.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-ink-3">Already on the list (skipped)</div>
              <div className="flex flex-wrap gap-1.5">
                {review.existing.map((n) => (
                  <span key={n} className="rounded-full bg-fg/[0.05] px-2.5 py-1 text-xs text-ink-2 ring-1 ring-inset ring-fg/[0.08]">
                    {n}
                  </span>
                ))}
              </div>
            </div>
          )}
          <p className="text-xs text-ink-3">Nothing has been saved yet. Names are matched ignoring capital letters and extra spaces.</p>
        </ConfirmDialog>
      )}
    </form>
  );
}
