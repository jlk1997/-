export function postProcessState(status?: Record<string, unknown> | null): string {
  return String(status?.state || "").toLowerCase();
}

export function isPostProcessDegraded(status?: Record<string, unknown> | null): boolean {
  if (!status) return false;
  const state = postProcessState(status);
  if (
    state === "ready" ||
    state === "ok" ||
    state === "passed" ||
    state === "complete" ||
    state === "completed" ||
    state === "pending" ||
    state === "running"
  ) {
    return false;
  }
  return state === "degraded" || Boolean(status.failed || status.last_error);
}

export function isPostProcessPending(status?: Record<string, unknown> | null): boolean {
  const state = postProcessState(status);
  return state === "pending" || state === "running";
}
