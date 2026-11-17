import Taro from "@tarojs/taro";
import { getItem, setItem, removeItem } from "./storage";

export const PENDING_REFERRAL_KEY = "growth:pendingReferral";
export const MY_REFERRAL_KEY = "growth:myReferral";

const CODE_RE = /^[A-Z0-9]{4,24}$/i;

export function normalizeReferralCode(raw?: string | null): string {
  const code = String(raw || "").trim().toUpperCase();
  return CODE_RE.test(code) ? code : "";
}

export function captureReferralCode(raw?: string | null) {
  const code = normalizeReferralCode(raw);
  if (!code) return;
  setItem(PENDING_REFERRAL_KEY, code);
}

export function captureReferralFromQuery(query?: Record<string, unknown> | null) {
  if (!query) return;
  const ref = query.ref ?? query.referral ?? query.invite;
  if (typeof ref === "string") captureReferralCode(ref);
  const scene = query.scene;
  if (typeof scene === "string" && scene.trim()) {
    let decoded = scene;
    try {
      decoded = decodeURIComponent(scene);
    } catch {
      decoded = scene;
    }
    const fromQuery = decoded.match(/(?:^|&)ref=([A-Z0-9]+)/i);
    if (fromQuery?.[1]) {
      captureReferralCode(fromQuery[1]);
      return;
    }
    captureReferralCode(decoded);
  }
}

export function captureReferralFromLaunch() {
  try {
    const opts = Taro.getLaunchOptionsSync();
    captureReferralFromQuery((opts?.query || {}) as Record<string, unknown>);
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined") {
    try {
      captureReferralCode(new URLSearchParams(window.location.search).get("ref"));
      const hash = window.location.hash || "";
      const qs = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
      if (qs) captureReferralCode(new URLSearchParams(qs).get("ref"));
    } catch {
      /* ignore */
    }
  }
}

export function peekPendingReferral(): string {
  return normalizeReferralCode(getItem(PENDING_REFERRAL_KEY));
}

export function consumePendingReferral(): string {
  const code = peekPendingReferral();
  if (code) removeItem(PENDING_REFERRAL_KEY);
  return code;
}

export function rememberMyReferral(code?: string | null) {
  const normalized = normalizeReferralCode(code);
  if (normalized) setItem(MY_REFERRAL_KEY, normalized);
}

export function myReferralCode(): string {
  return normalizeReferralCode(getItem(MY_REFERRAL_KEY));
}

export function referralSharePath(code?: string | null): string {
  const ref = normalizeReferralCode(code) || myReferralCode();
  return ref ? `/pages/feed/index?ref=${encodeURIComponent(ref)}` : "/pages/feed/index";
}
