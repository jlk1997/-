import Taro from "@tarojs/taro";
import { getLocaleCopy } from "../utils/localeCopy";
import { stackPage } from "../constants/routes";
import { myReferralCode } from "./referral";

/** Canonical share payload (title + registered page path) for a work. */
export function workSharePayload(workId: string, title: string): { title: string; path: string } {
  const ref = myReferralCode() || undefined;
  return { title, path: stackPage("work", { workId, ref, play: "1" }) };
}

export function shareWork(workId: string, title: string) {
  const { title: t, path } = workSharePayload(workId, title);
  sharePage(t, path);
}

/** Absolute URL a browser can open. H5 is always hash-routed (WeChat-safe). */
export function absoluteShareUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (typeof window === "undefined") return normalized;
  return `${window.location.origin}/#${normalized}`;
}

async function copyShareUrl(url: string, copied: string, unavailable: string) {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
      Taro.showToast({ title: copied, icon: "success" });
      return;
    }
  } catch {
    /* fall through to Taro clipboard */
  }
  try {
    await Taro.setClipboardData({ data: url });
    Taro.showToast({ title: copied, icon: "success" });
  } catch {
    Taro.showToast({ title: unavailable, icon: "none" });
  }
}

export function copyEmbedLink(workId: string) {
  const path = `/packageOps/pages/embed/index?workId=${encodeURIComponent(workId)}`;
  const s = getLocaleCopy().shareUi;
  if (process.env.TARO_ENV === "h5" && typeof window !== "undefined") {
    void copyShareUrl(absoluteShareUrl(path), s.embedCopied, s.embedH5Only);
    return;
  }
  Taro.showToast({ title: s.embedH5Only, icon: "none" });
}

export function sharePage(title: string, path: string) {
  const s = getLocaleCopy().shareUi;
  if (process.env.TARO_ENV === "weapp") {
    return { title, path };
  }
  const url = absoluteShareUrl(path);
  if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
    void navigator.share({ title, url }).catch((err: unknown) => {
      if (err && typeof err === "object" && "name" in err && (err as { name: string }).name === "AbortError") return;
      void copyShareUrl(url, s.linkCopied, s.shareUnavailable);
    });
    return;
  }
  void copyShareUrl(url, s.linkCopied, s.shareUnavailable);
}
