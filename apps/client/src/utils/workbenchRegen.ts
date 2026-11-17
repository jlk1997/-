import { vibeApi } from "../services/api";
import { persistActiveGeneration } from "./restoreGeneration";
import { openWorkbench, workbenchUrl } from "./workbenchNav";

export async function queueWorkbenchRegen(
  workId: string,
  kind: "extend" | "remelt" | "same_style",
  seconds = 15,
): Promise<{ job_id: string; session_id: string }> {
  const sess = await vibeApi.openWorkbenchSession(workId);
  const queued = await vibeApi.regenWorkbench(sess.id, kind, seconds);
  persistActiveGeneration({
    jobId: queued.job_id,
    returnUrl: workbenchUrl(workId),
    startedAt: new Date().toISOString(),
    jobType: "workbench",
    remixSource: { workId, title: sess.source_title || "", intent: "workbench" },
  });
  return queued;
}

export async function startWorkbenchRegen(
  workId: string,
  kind: "extend" | "remelt" | "same_style",
  seconds = 15,
): Promise<void> {
  await queueWorkbenchRegen(workId, kind, seconds);
  openWorkbench(workId);
}
