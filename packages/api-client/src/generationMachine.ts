import type { JobPayload } from "./jobTracker";

/** Shared generation states for the phone app and the desktop studio. */
export type GenerationView =
  | "idle"
  | "submitting"
  | "queued"
  | "running"
  | "takes_ready"
  | "finalizing"
  | "done"
  | "failed"
  | "stalled";

function hasListenAudio(result: Record<string, unknown> | undefined): boolean {
  if (!result) return false;
  if (result.audio_url || result.work_id) return true;
  const ids = result.work_ids;
  if (Array.isArray(ids) && ids.length > 0) return true;
  const steps = result.completed_steps;
  return Array.isArray(steps) && steps.length > 0;
}

/** Map a job payload to the one state the UI is allowed to show. */
export function generationStateFromJob(job: Partial<JobPayload> | null | undefined, opts?: { submitting?: boolean }): GenerationView {
  if (opts?.submitting) return "submitting";
  if (!job) return "idle";
  if (job.stalled && job.status !== "completed" && job.status !== "failed" && job.status !== "cancelled") {
    return "stalled";
  }
  if (job.status === "failed" || job.status === "cancelled") return "failed";
  if (job.status === "completed") return "done";
  const ready = hasListenAudio(job.result);
  if (ready && (job.status === "audio_ready" || job.status === "post_processing" || job.status === "running")) {
    return "takes_ready";
  }
  if (job.status === "post_processing" || job.phase === "post_processing") return "finalizing";
  if (job.status === "pending" || job.phase === "queued") return "queued";
  if (job.status === "audio_ready") return "takes_ready";
  if (job.status === "running" || job.status === "submitting") return "running";
  return "idle";
}
