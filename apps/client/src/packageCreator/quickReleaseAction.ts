import Taro from "@tarojs/taro";
import { isNeedsAuth } from "@vibe-sorcery/api-client";
import { vibeApi } from "../services/api";
import { CREATOR_TAB_ROUTE, creatorPage, openCreatorDesk } from "../constants/routes";
import { goShipBand } from "./nextActionNav";
import { getItem, removeItem, setItem } from "../platform/storage";
import { getLocaleCopy } from "../utils/localeCopy";
import { openStackPage } from "../utils/navigation";
import { isPostProcessDegraded } from "../utils/postProcess";
import { confirmCreatorAction } from "./lib";
import { copyWeappCreatorLink } from "./WeappH5Bridge";
import { sendPollToExtension } from "./extensionPair";

const PENDING_RELEASE_KEY = "bittune.pendingQuickRelease";
const RESUME_COOLDOWN_MS = 15_000;
let resumeLock = false;
let lastResumeWork = "";
let lastResumeAt = 0;
const releaseInflight = new Set<string>();

export function rememberPendingRelease(workId: string) {
  if (!workId) return;
  if (workId !== lastResumeWork) {
    lastResumeWork = "";
    lastResumeAt = 0;
  }
  setItem(PENDING_RELEASE_KEY, workId);
}

export function peekPendingRelease() {
  return getItem(PENDING_RELEASE_KEY) || "";
}

export function clearPendingRelease() {
  removeItem(PENDING_RELEASE_KEY);
  lastResumeWork = "";
  lastResumeAt = 0;
}

type QuickReleaseCopy = {
  confirmOnce: string;
  confirmOnceHint?: string;
  confirmGo?: string;
  labelHint: string;
  back: string;
  oneTapOk: string;
};

function toastForNextAction(
  next: string,
  locale: ReturnType<typeof getLocaleCopy>,
  fallback: string,
) {
  const c = locale.creatorUi;
  if (next === "wait_connector") return c.oneTapWaitConnector || fallback;
  if (next === "assisting") return c.oneTapAssisting || fallback;
  if (next === "ops_handling") return c.oneTapOpsQueue || fallback;
  if (next === "partial_live") return c.oneTapPartialLive || fallback;
  if (next === "live") return c.oneTapLive || fallback;
  return fallback;
}

const IN_FLIGHT = new Set(["queued", "delivering", "live"]);

export function isReleaseInFlight(status?: string | null): boolean {
  return IN_FLIGHT.has(String(status || ""));
}

export function isQcReady(status?: string | null): boolean {
  const value = String(status || "");
  return value === "qc_ready" || isReleaseInFlight(value);
}

async function openDeliveries(workId: string, releaseId?: string) {
  const path = creatorPage("deliveries", { releaseId, workId });
  if (process.env.TARO_ENV === "weapp") await copyWeappCreatorLink(path);
  openStackPage(path);
}

function openAuthDesk() {
  goShipBand();
}

async function resolveReleaseState(opts: {
  workId: string;
  qcReady?: boolean;
  releaseStatus?: string | null;
}): Promise<{ status: string; ready: boolean }> {
  let status = opts.releaseStatus || "";
  let ready = opts.qcReady;
  if (ready == null || !status) {
    try {
      const work = (await vibeApi.getWork(opts.workId)) as { release_status?: string };
      status = work.release_status || status;
      if (ready == null) ready = isQcReady(status);
    } catch {
      if (ready == null) ready = false;
    }
  }
  return { status, ready: Boolean(ready) };
}

export async function confirmQuickRelease(opts: {
  workId: string;
  qcReady?: boolean;
  releaseStatus?: string | null;
  copy: QuickReleaseCopy;
  actionFail: string;
  skipConfirm?: boolean;
  stayOnCard?: boolean;
  selectedChannels?: string[];
  onBusy?: (workId: string) => void;
  onDone?: () => Promise<void> | void;
}): Promise<boolean> {
  const locale = getLocaleCopy();
  if (opts.workId && releaseInflight.has(opts.workId)) {
    Taro.showToast({ title: locale.creatorUi.alreadyPublishing || locale.creatorUi.oneTapQcWait, icon: "none" });
    return false;
  }
  if (opts.workId) releaseInflight.add(opts.workId);
  try {
  return await confirmQuickReleaseBody(opts, locale);
  } finally {
    if (opts.workId) releaseInflight.delete(opts.workId);
  }
}

async function confirmQuickReleaseBody(
  opts: Parameters<typeof confirmQuickRelease>[0],
  locale: ReturnType<typeof getLocaleCopy>,
): Promise<boolean> {
  if (process.env.TARO_ENV === "weapp") {
    if (opts.workId) openCreatorDesk("today", { workId: opts.workId });
    await copyWeappCreatorLink(CREATOR_TAB_ROUTE);
    Taro.showToast({ title: locale.creatorUi.weappDeskHint, icon: "none" });
    return false;
  }
  let workId = opts.workId;
  try {
    const work = (await vibeApi.getWork(opts.workId)) as {
      superseded_by_work_id?: string | null;
      post_process_status?: Record<string, unknown> | null;
    };
    if (work.superseded_by_work_id) workId = work.superseded_by_work_id;
    const target =
      work.superseded_by_work_id && work.superseded_by_work_id !== opts.workId
        ? ((await vibeApi.getWork(workId)) as { post_process_status?: Record<string, unknown> | null })
        : work;
    if (isPostProcessDegraded(target.post_process_status)) {
      Taro.showToast({ title: locale.worksUi.reprocessQueued, icon: "none" });
      try {
        await vibeApi.reprocessWork(workId).catch(() => vibeApi.triggerPostProcess(workId));
      } catch {
        /* user can retry from the work page */
      }
      return false;
    }
  } catch {
    /* keep the requested work if lookup fails */
  }
  const { status, ready } = await resolveReleaseState({ ...opts, workId });
  if (isReleaseInFlight(status)) {
    clearPendingRelease();
    if (!opts.stayOnCard) await openDeliveries(workId);
    return true;
  }
  if (!ready) {
    Taro.showToast({ title: locale.creatorUi.oneTapQcWait, icon: "none" });
    return false;
  }
  if (!opts.skipConfirm) {
    const confirmed = await confirmCreatorAction({
      title: opts.copy.confirmOnce,
      content: opts.copy.confirmOnceHint || locale.creatorUi.confirmOnceHint || opts.copy.labelHint,
      confirmText: opts.copy.confirmGo || locale.creatorUi.confirmGo,
      cancelText: opts.copy.back,
    });
    if (!confirmed) return false;
  }
  opts.onBusy?.(workId);
  try {
    const result = (await vibeApi.quickRelease({
      work_id: workId,
      consent: true,
      mode: "label",
      ...(opts.selectedChannels?.length ? { selected_channels: opts.selectedChannels } : {}),
    })) as {
      already_active?: boolean;
      id?: string;
      work_id?: string;
      needs_auth?: boolean;
      needs_handoff?: boolean;
      next_action?: string;
    };
    const shippedId = result.work_id || workId;
    const next = result.next_action || (result.needs_handoff || result.needs_auth ? "wait_connector" : "");
    const waitConnector = next === "wait_connector" || Boolean(result.needs_handoff || result.needs_auth);
    if (waitConnector) rememberPendingRelease(shippedId);
    else clearPendingRelease();
    if (result.already_active) {
      Taro.showToast({
        title: toastForNextAction(next, locale, opts.copy.oneTapOk),
        icon: waitConnector ? "none" : "success",
      });
      void sendPollToExtension();
      if (!opts.stayOnCard) await openDeliveries(shippedId, result.id);
      return true;
    }
    Taro.showToast({
      title: toastForNextAction(next, locale, opts.copy.oneTapOk),
      icon: waitConnector ? "none" : "success",
    });
    try {
      const trial = (await vibeApi.getRadioTrial(shippedId)) as { live?: boolean; status?: string };
      if (!trial?.live && trial?.status !== "ended") {
        await vibeApi.startRadioTrial(shippedId);
      }
    } catch {
      /* radio trial is the default next hop, not a release blocker */
    }
    await opts.onDone?.();
    void sendPollToExtension();
    if (!opts.stayOnCard) await openDeliveries(shippedId, result.id);
    return true;
  } catch (err) {
    if (isNeedsAuth(err)) {
      rememberPendingRelease(workId);
      Taro.showToast({ title: locale.creatorUi.oneTapNeedAuth, icon: "none" });
      openAuthDesk();
      return false;
    }
    Taro.showToast({ title: opts.actionFail, icon: "none" });
    return false;
  } finally {
    opts.onBusy?.("");
  }
}

export async function resumePendingQuickRelease(copy: QuickReleaseCopy, actionFail: string): Promise<boolean> {
  const workId = peekPendingRelease();
  if (!workId || resumeLock) return false;
  if (workId === lastResumeWork && Date.now() - lastResumeAt < RESUME_COOLDOWN_MS) return false;
  lastResumeWork = workId;
  lastResumeAt = Date.now();
  resumeLock = true;
  try {
    const locale = getLocaleCopy();
    const confirmed = await confirmCreatorAction({
      title: locale.creatorUi.resumePendingTitle || copy.confirmOnce,
      content: locale.creatorUi.resumePendingHint || copy.confirmOnceHint || locale.creatorUi.confirmOnceHint,
      confirmText: copy.confirmGo || locale.creatorUi.confirmGo,
      cancelText: copy.back,
    });
    if (!confirmed) {
      clearPendingRelease();
      return false;
    }
    return await confirmQuickRelease({
      workId,
      copy: { ...copy, oneTapOk: copy.oneTapOk },
      actionFail,
      skipConfirm: Boolean(workId),
      stayOnCard: true,
    });
  } finally {
    resumeLock = false;
  }
}
