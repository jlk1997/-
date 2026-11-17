import Taro from "@tarojs/taro";
import { resolvePageUrl, socialPage } from "../constants/routes";
import { forceH5Hash, h5LocationMatches } from "./h5Path";
import { h5StackPageVisible, syncH5PageVisibility } from "./h5TabRouter";
import { setNavPending } from "./navPending";

function normalizeRoute(route: string) {
  return route.replace(/^\//, "").split("?")[0];
}

function healH5Route(resolved: string) {
  if (process.env.TARO_ENV !== "h5" || typeof window === "undefined") return;
  if (!h5LocationMatches(resolved)) forceH5Hash(resolved);
  syncH5PageVisibility();
}

function finishPending() {
  setNavPending(null);
}

/** Patch Taro navigation so legacy /pages/journey|provenance|feedback URLs resolve to packageStudio. */
export function installRouteAliases() {
  (["navigateTo", "redirectTo", "reLaunch"] as const).forEach((method) => {
    const original = Taro[method].bind(Taro) as (opts: { url: string }) => Promise<unknown>;
    (Taro as unknown as Record<string, typeof original>)[method] = (opts: { url: string }) =>
      original({ ...opts, url: resolvePageUrl(opts.url) });
  });
}

/** Open a non-tab page; handles stack duplicates and navigateTo failures on H5. */
export function openStackPage(url: string) {
  const resolved = resolvePageUrl(url);
  const target = normalizeRoute(resolved);
  const h5 = process.env.TARO_ENV === "h5" && typeof window !== "undefined";

  setNavPending(resolved);

  if (h5 && h5LocationMatches(resolved) && h5StackPageVisible(target)) {
    syncH5PageVisibility();
    finishPending();
    return;
  }

  const pages = Taro.getCurrentPages();
  const top = pages[pages.length - 1];
  if (top && normalizeRoute(top.route || "") === target) {
    if (h5 && !h5LocationMatches(resolved)) {
      void Taro.redirectTo({ url: resolved }).catch(() => {
        forceH5Hash(resolved);
        syncH5PageVisibility();
      }).finally(finishPending);
      return;
    }
    if (!h5 || h5StackPageVisible(target)) {
      healH5Route(resolved);
      finishPending();
      return;
    }
  }

  const existingIdx = pages.findIndex((p) => normalizeRoute(p.route || "") === target);
  if (existingIdx >= 0) {
    if (h5 && !h5LocationMatches(resolved)) {
      void Taro.redirectTo({ url: resolved }).catch(() => {
        forceH5Hash(resolved);
        syncH5PageVisibility();
      }).finally(finishPending);
      return;
    }
    const delta = pages.length - 1 - existingIdx;
    if (delta > 0) {
      void Taro.navigateBack({ delta })
        .then(() => {
          if (h5) healH5Route(resolved);
        })
        .catch(() => {
          if (h5) {
            forceH5Hash(resolved);
            syncH5PageVisibility();
          } else {
            void Taro.redirectTo({ url: resolved });
          }
        })
        .finally(finishPending);
      return;
    }
  }

  void Taro.navigateTo({ url: resolved })
    .then(() => {
      if (h5) healH5Route(resolved);
    })
    .catch(() => {
      if (h5) {
        forceH5Hash(resolved);
        syncH5PageVisibility();
        return;
      }
      void Taro.redirectTo({ url: resolved }).catch(() => {
        void Taro.reLaunch({ url: resolved });
      });
    })
    .finally(finishPending);
}

export function navigateToPage(url: string) {
  openStackPage(url);
}

/** Open radio without stacking the same page (WeChat navigateTo fails / duplicates). */
export function openRadioPage(query?: Record<string, string | undefined>) {
  openStackPage(socialPage("radio", query));
}
