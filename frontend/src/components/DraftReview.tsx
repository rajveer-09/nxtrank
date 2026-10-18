/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 18 October 2026
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { draftsApi, type DraftReview } from "../api";
import { fmtInt, fmtIso } from "../format";
import { RowsSkeleton } from "./skeletons";
import { Button, ConfirmDialog, Dialog, ErrorBox, ResultStatusBadge, cx } from "./ui";

const PAGE = 50;

/** Admins, on a contest page: a manual scan waiting for review. Nothing it found counts
 *  until "Add to dashboard"; "Discard" throws it away. */
export function DraftBanner({ review }: { review: DraftReview }) {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<"preview" | "publish" | "discard" | null>(null);
  const done = () => {
    setDialog(null);
    qc.invalidateQueries(); // results, stats, toppers and ratings may all have changed
  };
  const publish = useMutation({ mutationFn: () => draftsApi.publish(review.run_id), onSuccess: done });
  const discard = useMutation({ mutationFn: () => draftsApi.discard(review.run_id), onSuccess: done });
  const now = review.participated_before != null ? ` (now ${fmtInt(review.participated_before)})` : "";
  const changes = review.changed != null ? ` · ${fmtInt(review.changed)} ${review.changed === 1 ? "student changes" : "students change"} rank or status` : "";

  return (
    <div role="status" className="flex flex-col gap-3 rounded-xl bg-info/10 px-4 py-3 ring-1 ring-inset ring-info/25 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1 text-[13px]">
        <div className="font-semibold text-ink">
          {review.outdated ? "Outdated scan waiting for review" : "New scan ready for review"}
          <span className="ml-2 text-xs font-normal text-ink-3">{review.kind === "final" ? "final results" : "early results"} · scanned {fmtIso(review.finished_at)}</span>
        </div>
        <div className="mt-0.5 text-ink-2">
          {review.outdated
            ? "An automatic scan has updated this contest since, so this one can only be discarded."
            : `${fmtInt(review.participated)} of ${fmtInt(review.students)} took part${now}${changes}. Nothing changes on the dashboard until you add it.`}
          {review.expires_at && !review.outdated && <span className="text-ink-3"> Discarded automatically {fmtIso(review.expires_at)}.</span>}
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        <Button variant="ghost" size="sm" onClick={() => setDialog("preview")}>Preview</Button>
        {!review.outdated && (
          <Button variant="primary" size="sm" onClick={() => { publish.reset(); setDialog("publish"); }}>Add to dashboard</Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => { discard.reset(); setDialog("discard"); }} className="hover:bg-critical/10 hover:text-critical-ink">
          Discard
        </Button>
      </div>

      {dialog === "preview" && <DraftPreview review={review} onClose={() => setDialog(null)} />}
      <ConfirmDialog
        open={dialog === "publish"}
        title="Add this scan to the dashboard?"
        confirmLabel="Yes, add it"
        busy={publish.isPending}
        error={publish.error}
        onConfirm={() => publish.mutate()}
        onClose={() => setDialog(null)}
      >
        <p>
          It replaces this contest's results: {fmtInt(review.participated)} of {fmtInt(review.students)} took part{now}.
          Stats, toppers and analytics update straight away{review.kind === "final" ? ", and ratings refresh on the worker's next check" : ""}.
        </p>
      </ConfirmDialog>
      <ConfirmDialog
        open={dialog === "discard"}
        title="Discard this scan?"
        confirmLabel="Yes, discard"
        danger
        busy={discard.isPending}
        error={discard.error}
        onConfirm={() => discard.mutate()}
        onClose={() => setDialog(null)}
      >
        <p>The dashboard keeps showing what it shows now. You can scan the contest again later.</p>
      </ConfirmDialog>
    </div>
  );
}

/** The draft leaderboard, with what changed against the current results. */
function DraftPreview({ review, onClose }: { review: DraftReview; onClose: () => void }) {
  const [offset, setOffset] = useState(0);
  const rows = useQuery({
    queryKey: ["draft-rows", review.run_id, offset],
    queryFn: () => draftsApi.rows(review.run_id, offset, PAGE),
    placeholderData: keepPreviousData,
  });
  const total = rows.data?.total ?? 0;
  return (
    <Dialog
      open
      xl
      onClose={onClose}
      title={`Preview: ${review.title ?? review.contest_slug}`}
      footer={
        <div className="flex w-full items-center justify-between gap-2 text-xs text-ink-2">
          <span className="tabular">{total ? `${offset + 1}–${Math.min(total, offset + PAGE)} of ${fmtInt(total)}` : ""}</span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</Button>
            <Button variant="ghost" size="sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</Button>
            <Button size="sm" onClick={onClose}>Close</Button>
          </div>
        </div>
      }
    >
      {rows.isPending ? (
        <RowsSkeleton rows={8} cols={5} />
      ) : rows.isError ? (
        <ErrorBox error={rows.error} onRetry={() => rows.refetch()} />
      ) : (
        <table className={cx("w-full text-[13px]", rows.isPlaceholderData && "opacity-60")}>
          <thead className="sticky top-0 z-10 bg-surface text-left text-xs text-ink-2">
            <tr className="border-b border-fg/5">
              <th className="py-2 pr-3 font-medium">Rank</th>
              <th className="py-2 pr-3 font-medium">Student</th>
              <th className="py-2 pr-3 font-medium">Status</th>
              <th className="py-2 pr-3 text-right font-medium">Score</th>
              <th className="py-2 text-right font-medium">Solved</th>
            </tr>
          </thead>
          <tbody>
            {rows.data.rows.map((r) => {
              const b = r.before;
              const moved = b != null && (b.college_rank !== r.college_rank || b.status !== r.status);
              const fresh = b == null;
              return (
                <tr key={r.student_id} className={cx("border-b border-fg/5 last:border-0", (moved || fresh) && "bg-info/[0.06]")}>
                  <td className="tabular py-2 pr-3">
                    {r.college_rank ?? "—"}
                    {moved && b.college_rank !== r.college_rank && <span className="ml-1 text-xs text-ink-3">was {b.college_rank ?? "—"}</span>}
                  </td>
                  <td className="py-2 pr-3">
                    <div className="font-medium text-ink">{r.name}</div>
                    <div className="text-xs text-ink-3">{[r.roll_no, r.college].filter(Boolean).join(" · ")}</div>
                  </td>
                  <td className="py-2 pr-3">
                    <ResultStatusBadge status={r.status} />
                    {moved && b.status !== r.status && <div className="mt-0.5 text-xs text-ink-3">was {b.status.replace("_", " ")}</div>}
                    {fresh && <div className="mt-0.5 text-xs text-ink-3">new</div>}
                  </td>
                  <td className="tabular py-2 pr-3 text-right">{r.score ?? "—"}</td>
                  <td className="tabular py-2 text-right">{r.solved ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Dialog>
  );
}
