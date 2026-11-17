import Taro from "@tarojs/taro";
import { commercePage, creatorPage, openCreatorDesk, socialPage, stackPage } from "../constants/routes";
import { openWorkbench } from "../utils/workbenchNav";

type NavExtra = {
  workId?: string;
  stores?: string;
  station?: string;
  releaseId?: string;
};

export function focusShipCompleteBand() {
  if (typeof document === "undefined") return;
  const el = document.getElementById("ship-complete-band");
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("is-focus");
  window.setTimeout(() => el.classList.remove("is-focus"), 1600);
}

export function goShipBand(workId?: string) {
  openCreatorDesk("today", { workId });
  focusShipCompleteBand();
}

export function goSessionWaitCta(
  cta: { to: "remote" | "accounts" | "portal" },
  extra: { weapp?: boolean; seatId?: string | null } = {},
) {
  if (cta.to === "remote" || extra.weapp) {
    Taro.navigateTo({
      url: extra.seatId ? creatorPage("remoteLogin", { seatId: String(extra.seatId) }) : creatorPage("accounts"),
    });
    return;
  }
  if (cta.to === "portal") {
    Taro.navigateTo({ url: creatorPage("deliveries") });
    return;
  }
  Taro.navigateTo({
    url: extra.seatId ? creatorPage("remoteLogin", { seatId: String(extra.seatId) }) : creatorPage("accounts"),
  });
}

/** One map for desk / ledger / timeline / deliveries. Always keep workId when we have it. */
export function goCreatorAction(action: string, extra: NavExtra = {}) {
  const workId = extra.workId;
  if (action === "generate") {
    Taro.switchTab({ url: "/pages/create/index" });
    return;
  }
  if (action === "beautify") {
    if (workId) openWorkbench(workId);
    return;
  }
  if (action === "connector") {
    openCreatorDesk("today");
    return;
  }
  if (action === "import" || action === "claim") {
    Taro.navigateTo({ url: creatorPage("dataImport") });
    return;
  }
  if (action === "sync") {
    Taro.navigateTo({ url: commercePage("syncDesk", { workId }) });
    return;
  }
  if (action === "reprocess") {
    Taro.navigateTo({ url: workId ? `${stackPage("work")}?workId=${workId}` : stackPage("works", { filter: "needsFix" }) });
    return;
  }
  if (action === "qc" || action === "release") {
    goShipBand(workId);
    return;
  }
  if (action === "wait_review" || action === "wait" || action === "stores") {
    Taro.navigateTo({ url: creatorPage("deliveries", { workId, releaseId: extra.releaseId }) });
    return;
  }
  if (action === "watch_trial" || action === "radio_trial") {
    Taro.navigateTo({ url: socialPage("radio", { workId, station: extra.station }) });
    return;
  }
  if (action === "wallet") {
    Taro.navigateTo({ url: creatorPage("wallet") });
    return;
  }
  Taro.navigateTo({ url: creatorPage("settlements") });
}
