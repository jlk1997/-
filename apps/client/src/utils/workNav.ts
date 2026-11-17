import { creatorPage, stackPage } from "../constants/routes";
import { isPostProcessDegraded } from "./postProcess";
import { openStackPage } from "./navigation";

export type WorkFilter = "all" | "draft" | "published" | "derivative" | "needsFix";

export function openWorkDetail(workId: string) {
  openStackPage(stackPage("work", { workId }));
}

/** Owner social wins go to the label ledger, not the public stack page. */
export function openWorkForOwner(workId: string, mine: boolean) {
  openStackPage(mine ? creatorPage("work", { workId }) : stackPage("work", { workId }));
}

function hasCommunityPost(
  postByWork: Record<string, string | { postId?: string } | undefined>,
  workId: string,
): boolean {
  const entry = postByWork[workId];
  if (!entry) return false;
  if (typeof entry === "string") return !!entry;
  return !!entry.postId;
}

export function isWorkPublished(
  work: { id: string; visibility?: string },
  postByWork: Record<string, string | { postId?: string } | undefined>,
): boolean {
  return work.visibility === "public" || hasCommunityPost(postByWork, work.id);
}

export function filterWorks<
  T extends { id: string; visibility?: string; parent_work_id?: string; post_process_status?: Record<string, unknown> },
>(
  works: T[],
  filter: WorkFilter,
  postByWork: Record<string, string | { postId?: string } | undefined>,
): T[] {
  if (filter === "all") return works;
  if (filter === "published") {
    return works.filter((w) => isWorkPublished(w, postByWork));
  }
  if (filter === "draft") {
    return works.filter((w) => !isWorkPublished(w, postByWork));
  }
  if (filter === "derivative") {
    return works.filter((w) => !!w.parent_work_id);
  }
  if (filter === "needsFix") {
    return works.filter((w) => isPostProcessDegraded(w.post_process_status));
  }
  return works;
}

export function parseWorkFilter(raw?: string): WorkFilter {
  if (raw === "published" || raw === "draft" || raw === "derivative" || raw === "needsFix") return raw;
  return "all";
}
