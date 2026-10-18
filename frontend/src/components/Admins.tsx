/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { adminsApi, type AdminUser } from "../api";
import { AuditLine } from "./Roster";
import { Badge, Button, Card, CardHeader, ConfirmDialog, Consequences, Empty, ErrorBox, FieldLabel, Modal, useFlash, Input, cx } from "./ui";
import { RowsSkeleton } from "./skeletons";
import { patchCache, type Undo } from "../optimistic";

/** Admin logins. Admins edit each other; the super admin can't be changed here. */
export default function AdminsCard() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["admins"], queryFn: adminsApi.list });
  const [editing, setEditing] = useState<AdminUser | "new" | null>(null);
  const [flashed, flash] = useFlash();
  const refresh = () => qc.invalidateQueries({ queryKey: ["admins"] });

  return (
    <Card>
      <CardHeader
        title="Admins"
        subtitle="Admins manage students, instructors, scans and each other. The super admin can't be edited, deactivated or deleted by anyone here."
        actions={
          <Button variant="primary" onClick={() => setEditing("new")} disabled={editing === "new"}>
            Add admin
          </Button>
        }
      />
      {/* add / edit over the page where you clicked, not at the top of the list */}
      <Modal open={editing !== null} onClose={() => setEditing(null)} label={editing === "new" ? "New admin" : "Edit admin"}>
        {editing !== null && (
          <AdminForm
            key={editing === "new" ? "new" : editing.id}
            admin={editing === "new" ? null : editing}
            onDone={() => {
              if (editing !== "new" && editing) flash(editing.id); // show which row changed
              setEditing(null);
              refresh();
            }}
            onCancel={() => setEditing(null)}
          />
        )}
      </Modal>
      {list.isPending ? (
        <div className="px-5">
          <RowsSkeleton />
        </div>
      ) : list.isError ? (
        <div className="p-5">
          <ErrorBox error={list.error} onRetry={() => list.refetch()} />
        </div>
      ) : list.data.length === 0 ? (
        <Empty>No admins.</Empty>
      ) : (
        <ul className="divide-y divide-fg/5 border-t border-fg/5">
          {list.data.map((a) => (
            <AdminRow key={a.id} a={a} onEdit={() => setEditing(a)} onChanged={refresh} editing={editing !== null && editing !== "new" && editing.id === a.id} flashed={flashed === a.id} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function LockIcon() {
  return (
    <svg aria-hidden viewBox="0 0 12 12" className="h-3 w-3">
      <path d="M3.5 5.5V4a2.5 2.5 0 0 1 5 0v1.5M2.75 5.5h6.5v5h-6.5z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

function AdminRow({ a, onEdit, onChanged, editing, flashed }: { a: AdminUser; onEdit: () => void; onChanged: () => void; editing: boolean; flashed?: boolean }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<"toggle" | "delete" | null>(null);
  const done = () => {
    setConfirm(null);
    onChanged();
  };
  // optimistic: the row shows the new state as soon as it's confirmed
  const toggle = useMutation({
    mutationFn: (active: boolean) => adminsApi.update(a.id, { email: a.email, name: a.name, password: "", active }),
    onMutate: async (active): Promise<Undo> => {
      setConfirm(null);
      const undo = await patchCache<AdminUser[]>(qc, ["admins"], (d) => d.map((x) => (x.id === a.id ? { ...x, active } : x)));
      return { undo };
    },
    onError: (_e, _v, ctx) => ctx?.undo(),
    onSettled: onChanged,
  });
  const remove = useMutation({ mutationFn: () => adminsApi.remove(a.id), onSuccess: done });
  const err = toggle.error ?? remove.error;

  return (
    <li className={cx("flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:gap-4", editing && "bg-accent-soft/30", flashed && "row-flash", !a.active && "opacity-70")}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold text-ink">{a.name}</span>
          {a.is_super && (
            <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-ink ring-1 ring-inset ring-accent/25">
              <LockIcon />
              Super admin
            </span>
          )}
          {a.is_you && <span className="rounded-full bg-fg/[0.06] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-2">You</span>}
          {!a.active && (
            <Badge tone="neutral" icon="dash">
              Deactivated
            </Badge>
          )}
        </div>
        <div className="truncate text-xs text-ink-3">{a.email}</div>
        {err && <div className="mt-1.5 text-xs text-critical">{(err as Error).message}</div>}
      </div>
      <AuditLine a={a} className="shrink-0 sm:w-56" />
      <div className="flex shrink-0 items-center gap-1 sm:w-64 sm:justify-end">
        {a.editable ? (
          <>
            <Button variant="ghost" size="sm" onClick={onEdit}>
              Edit
            </Button>
            {!a.is_you && (
              <>
                <Button variant="ghost" size="sm" onClick={() => { toggle.reset(); setConfirm("toggle"); }}>
                  {a.active ? "Deactivate" : "Activate"}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => { remove.reset(); setConfirm("delete"); }} className="hover:bg-critical/10 hover:text-critical-ink">
                  Delete
                </Button>
                <ConfirmDialog
                  open={confirm === "toggle"}
                  onClose={() => setConfirm(null)}
                  onConfirm={() => toggle.mutate(!a.active)}
                  danger={a.active}
                  title={a.active ? `Deactivate ${a.name}?` : `Activate ${a.name}?`}
                  confirmLabel={a.active ? "Yes, deactivate" : "Yes, activate"}
                >
                  <p>{a.email}</p>
                  <Consequences
                    items={
                      a.active
                        ? ["They're signed out now and can't log in or change anything.", "Activate them again any time; nothing else is lost."]
                        : ["They can log in again with their current password, with full admin access."]
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
                  title={`Delete ${a.name} for good?`}
                  confirmLabel="Yes, delete"
                >
                  <p>{a.email}</p>
                  <Consequences
                    items={[
                      "Their admin login is removed. This can't be undone.",
                      "What they changed stays, still recorded under their name.",
                      "To only block access for now, deactivate them instead.",
                    ]}
                  />
                </ConfirmDialog>
              </>
            )}
          </>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-xs text-ink-3" title="Only changeable from the server's command line (create-user)">
            <LockIcon />
            Protected
          </span>
        )}
      </div>
    </li>
  );
}

function AdminForm({ admin, onDone, onCancel }: { admin: AdminUser | null; onDone: () => void; onCancel: () => void }) {
  const [form, setForm] = useState({ email: admin?.email ?? "", name: admin?.name ?? "", password: "" });
  const save = useMutation({
    mutationFn: () =>
      admin
        ? adminsApi.update(admin.id, { ...form, active: admin.active })
        : adminsApi.create({ ...form, active: true }),
    onSuccess: onDone,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4 px-5 py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-semibold text-ink">{admin ? `Edit ${admin.name}` : "New admin"}</h3>
        {admin && <AuditLine a={admin} className="text-right" />}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <FieldLabel>Name</FieldLabel>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required placeholder="Priya Nair" />
        </label>
        <label className="flex flex-col gap-1">
          <FieldLabel>Email (login)</FieldLabel>
          <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required placeholder="priya@nxtwave.co.in" />
        </label>
        <label className="flex flex-col gap-1">
          <FieldLabel>{admin ? "New password" : "Password"}</FieldLabel>
          <Input
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required={!admin}
            minLength={10}
            placeholder={admin ? "Leave blank to keep" : "At least 10 characters"}
          />
        </label>
      </div>
      {save.isError && <ErrorBox error={save.error} />}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : admin ? "Save changes" : "Add admin"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
