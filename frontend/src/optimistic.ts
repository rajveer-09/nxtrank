/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
import type { QueryClient, QueryKey } from "@tanstack/react-query";

/** Optimistic updates: apply `update` to every cached query under `key` now and return an
 *  undo. Call in onMutate, undo in onError, refetch in onSettled. */
export async function patchCache<T>(qc: QueryClient, key: QueryKey, update: (old: T) => T): Promise<() => void> {
  await qc.cancelQueries({ queryKey: key }); // an older response mustn't overwrite the change
  const snapshot = qc.getQueriesData<T>({ queryKey: key });
  qc.setQueriesData<T>({ queryKey: key }, (old) => (old === undefined ? old : update(old)));
  return () => snapshot.forEach(([k, v]) => qc.setQueryData(k, v));
}

export type Undo = { undo: () => void };
