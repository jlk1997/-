import Taro from "@tarojs/taro";
import { setItem, removeItem } from "../platform/storage";
import { showCoverUnavailable } from "./coverUnavailable";

export type SameStyleAction = "sameStyle" | "regenerate";

export function startSameStyle(workId: string, workTitle?: string, intent?: string) {
  seedCreate(workId, "sameStyle", workTitle, intent);
}

export function startRegenerate(workId: string, workTitle?: string, intent?: string) {
  seedCreate(workId, "regenerate", workTitle, intent);
}

export function startRemelt(workId: string, workTitle?: string, intent?: string) {
  seedCreate(workId, "regenerate", workTitle, intent);
  setItem("create:remelt", "1");
}

export function startCover(_workId?: string, _workTitle?: string, _intent?: string, _opts?: { lyricLock?: boolean }) {
  showCoverUnavailable();
}

function seedCreate(workId: string, mode: SameStyleAction, workTitle?: string, intent?: string) {
  setItem("create:seedWorkId", workId);
  setItem("create:mode", mode);
  if (workTitle) setItem("create:seedTitle", workTitle);
  else removeItem("create:seedTitle");
  if (intent?.trim()) setItem("create:seedIntent", intent.trim());
  else removeItem("create:seedIntent");
  Taro.switchTab({ url: "/pages/create/index" });
}
