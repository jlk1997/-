import { nextCoreDoor, type CoreDoor } from "./nextCoreDoor";
import { isPostProcessDegraded } from "./postProcess";

export type WorkDoorInput = {
  id: string;
  release_status?: string | null;
  post_process_status?: Record<string, unknown> | null;
  parent_work_id?: string | null;
  from_workbench?: boolean;
  superseded_by_work_id?: string | null;
  degraded?: boolean;
};

export function resolveWorkCoreDoor<T extends WorkDoorInput>(work: T, works: T[] = []): {
  door: CoreDoor;
  workId: string;
  sourceId: string;
} {
  const targetId = releaseTargetId(work, works);
  const target = works.find((row) => row.id === targetId) || work;
  const hasResult =
    isWorkbenchMaster(target) ||
    Boolean(work.from_workbench) ||
    Boolean(work.superseded_by_work_id) ||
    targetId !== work.id;
  const degraded =
    work.degraded === true ||
    target.degraded === true ||
    isPostProcessDegraded(target.post_process_status) ||
    isPostProcessDegraded(work.post_process_status);
  return {
    door: nextCoreDoor({
      hasResult,
      releaseStatus: target.release_status ?? work.release_status,
      degraded,
    }),
    workId: hasResult ? targetId : work.id,
    sourceId: work.id,
  };
}

export function isWorkbenchMaster(work: {
  post_process_status?: Record<string, unknown> | null;
  from_workbench?: boolean;
}): boolean {
  if (work.from_workbench) return true;
  return Boolean(work.post_process_status && work.post_process_status.workbench);
}

/** Raw take with no beautified master yet. */
export function needsBeautifyMaster(work: {
  from_workbench?: boolean;
  superseded_by_work_id?: string | null;
  post_process_status?: Record<string, unknown> | null;
}): boolean {
  return !isWorkbenchMaster(work) && !work.superseded_by_work_id;
}

export function successorByParentId<
  T extends { id: string; parent_work_id?: string | null; post_process_status?: Record<string, unknown> | null; from_workbench?: boolean },
>(works: T[]): Map<string, T> {
  const map = new Map<string, T>();
  for (const work of works) {
    if (work.parent_work_id && isWorkbenchMaster(work)) {
      map.set(work.parent_work_id, work);
    }
  }
  return map;
}

export function preferWorkbenchMasters<
  T extends { id: string; parent_work_id?: string | null; post_process_status?: Record<string, unknown> | null; from_workbench?: boolean },
>(works: T[]): T[] {
  const hide = new Set(successorByParentId(works).keys());
  if (!hide.size) return works;
  return works.filter((work) => !hide.has(work.id));
}

export function releaseTargetId<
  T extends { id: string; parent_work_id?: string | null; post_process_status?: Record<string, unknown> | null; superseded_by_work_id?: string | null; from_workbench?: boolean },
>(work: T, works: T[] = []): string {
  if (work.superseded_by_work_id) return work.superseded_by_work_id;
  return successorByParentId(works).get(work.id)?.id || work.id;
}

export function radioFocusWorkId(
  trial: { work_id?: unknown; station?: unknown } | null | undefined,
  fallback: string,
): { workId: string; station?: string } {
  const workId = typeof trial?.work_id === "string" && trial.work_id ? trial.work_id : fallback;
  const station = typeof trial?.station === "string" && trial.station ? trial.station : undefined;
  return { workId, station };
}
