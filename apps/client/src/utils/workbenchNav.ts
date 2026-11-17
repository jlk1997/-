import Taro from "@tarojs/taro";
import { studioPage } from "../constants/routes";
import { isWorkbenchMaster } from "./workbenchWorks";
import { openStackPage } from "./navigation";

export function pickBeautifySourceId(
  works: Array<{
    id: string;
    from_workbench?: boolean;
    post_process_status?: Record<string, unknown> | null;
  }> = [],
): string | undefined {
  const raw = works.find((work) => !isWorkbenchMaster(work));
  return raw?.id || works[0]?.id;
}

/** Standing door for 美化台. Needs a song; empty library explains instead of opening a blank bench. */
export function openBeautifyDoor(opts: {
  workId?: string | null;
  works?: Array<{
    id: string;
    from_workbench?: boolean;
    post_process_status?: Record<string, unknown> | null;
  }>;
  needWorkTitle: string;
  prefer?: "lite" | "pro";
}): boolean {
  const workId = opts.workId || pickBeautifySourceId(opts.works);
  if (!workId) {
    Taro.showToast({ title: opts.needWorkTitle, icon: "none" });
    return false;
  }
  openWorkbench(workId, opts.prefer);
  return true;
}

/** The phone app never opens the desktop mixer. That lives at /studio. */
export function isDesktopWorkbench(): boolean {
  return false;
}

export function workbenchUrl(workId: string, _prefer?: "lite" | "pro", extra?: { packId?: string; need?: string }): string {
  return studioPage("workbenchLite", {
    workId,
    ...(extra?.packId ? { packId: extra.packId } : {}),
    ...(extra?.need ? { need: extra.need } : {}),
  });
}

export function openWorkbench(workId: string, prefer?: "lite" | "pro", extra?: { packId?: string; need?: string }): void {
  openStackPage(workbenchUrl(workId, prefer, extra));
}
