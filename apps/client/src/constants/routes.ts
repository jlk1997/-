import Taro from "@tarojs/taro";
import { removeItem, setItem } from "../platform/storage";

export const TAB_PAGE_ROUTES = [
  "/pages/create/index",
  "/pages/feed/index",
  "/pages/library/index",
  "/pages/creator/index",
  "/pages/profile/index",
] as const;

export const CREATOR_TAB_ROUTE = "/pages/creator/index";
export const LIBRARY_PAGE_ROUTE = "/pages/library/index";
export const CREATOR_PANE_KEY = "creator:pane";
export const CREATOR_SHIP_WORK_KEY = "creator:shipWork";

export type CreatorDeskPane = "today" | "release" | "money" | "tools";

export function rememberShipWork(workId?: string) {
  if (workId) setItem(CREATOR_SHIP_WORK_KEY, workId);
  else removeItem(CREATOR_SHIP_WORK_KEY);
}

export function clearShipFocus() {
  removeItem(CREATOR_SHIP_WORK_KEY);
}

export function openCreatorDesk(pane?: CreatorDeskPane, extra?: { workId?: string }) {
  if (pane) setItem(CREATOR_PANE_KEY, pane);
  if (extra?.workId) rememberShipWork(extra.workId);
  Taro.switchTab({ url: CREATOR_TAB_ROUTE }).catch(() => {
    void Taro.reLaunch({ url: CREATOR_TAB_ROUTE });
  });
}

export function openLibrary() {
  Taro.switchTab({ url: LIBRARY_PAGE_ROUTE }).catch(() => {
    void Taro.reLaunch({ url: LIBRARY_PAGE_ROUTE });
  });
}

export const TAB_PAGE_PATHS = TAB_PAGE_ROUTES.map((r) => r.replace(/^\//, ""));

/** Non-tab stack pages (packageStack + commerce routes for back-compat). */
export const COMMERCE_PAGE_ROUTES = {
  marketplace: "/packageCommerce/pages/marketplace/index",
  emotionCalendar: "/packageCommerce/pages/emotion-calendar/index",
  creatorEarnings: "/packageCommerce/pages/creator-earnings/index",
  syncDesk: "/packageCommerce/pages/sync-desk/index",
} as const;

export const STACK_PAGE_ROUTES = {
  login: "/packageStack/pages/login/index",
  pricing: "/packageStack/pages/pricing/index",
  settings: "/packageStack/pages/settings/index",
  notifications: "/packageStack/pages/notifications/index",
  search: "/packageStack/pages/search/index",
  playlists: "/packageStack/pages/playlists/index",
  playlist: "/packageStack/pages/playlist/index",
  challenges: "/packageStack/pages/challenges/index",
  challenge: "/packageStack/pages/challenge/index",
  works: "/packageStack/pages/works/index",
  work: "/packageStack/pages/work/index",
  collections: "/packageStack/pages/collections/index",
  user: "/packageStack/pages/user/index",
  nowPlaying: "/packageStack/pages/now-playing/index",
  marketplace: COMMERCE_PAGE_ROUTES.marketplace,
  emotionCalendar: COMMERCE_PAGE_ROUTES.emotionCalendar,
  creatorEarnings: COMMERCE_PAGE_ROUTES.creatorEarnings,
  syncDesk: COMMERCE_PAGE_ROUTES.syncDesk,
} as const;

export function commercePage(route: keyof typeof COMMERCE_PAGE_ROUTES, query?: Record<string, string | undefined>): string {
  return stackPage(route, query);
}

export function stackPage(route: keyof typeof STACK_PAGE_ROUTES, query?: Record<string, string | undefined>): string {
  const base = STACK_PAGE_ROUTES[route];
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v != null && v !== "") params.set(k, v);
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

/** Studio subpackage — must include package root in the path. */
export const STUDIO_PAGE_ROUTES = {
  journey: "/packageStudio/pages/journey/index",
  provenance: "/packageStudio/pages/provenance/index",
  feedback: "/packageStudio/pages/feedback/index",
  variationLab: "/packageStudio/pages/variation-lab/index",
  workbenchLite: "/packageStudio/pages/workbench-lite/index",
  workbenchPro: "/packageStudio/pages/workbench-lite/index",
} as const;

export const CREATOR_PAGE_ROUTES = {
  hub: "/packageCreator/pages/hub/index",
  help: "/packageCreator/pages/help/index",
  release: "/packageCreator/pages/release/index",
  deliveries: "/packageCreator/pages/deliveries/index",
  dataImport: "/packageCreator/pages/data-import/index",
  settlements: "/packageCreator/pages/settlements/index",
  wallet: "/packageCreator/pages/wallet/index",
  accounts: "/packageCreator/pages/accounts/index",
  work: "/packageCreator/pages/work/index",
  passport: "/packageCreator/pages/passport/index",
  commune: "/packageCreator/pages/commune/index",
  remoteLogin: "/packageCreator/pages/remote-login/index",
} as const;

export function creatorPage(route: keyof typeof CREATOR_PAGE_ROUTES, query?: Record<string, string | undefined>): string {
  const base = CREATOR_PAGE_ROUTES[route];
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v != null && v !== "") params.set(k, v);
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export const SOCIAL_PAGE_ROUTES = {
  charts: "/packageSocial/pages/charts/index",
  duels: "/packageSocial/pages/duels/index",
  duel: "/packageSocial/pages/duel/index",
  radio: "/packageSocial/pages/radio/index",
} as const;

export function socialPage(route: keyof typeof SOCIAL_PAGE_ROUTES, query?: Record<string, string | undefined>): string {
  const base = SOCIAL_PAGE_ROUTES[route];
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v != null && v !== "") params.set(k, v);
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

const LEGACY_STUDIO_PATHS: Record<string, string> = {
  "/pages/journey/index": STUDIO_PAGE_ROUTES.journey,
  "/pages/provenance/index": STUDIO_PAGE_ROUTES.provenance,
  "/pages/feedback/index": STUDIO_PAGE_ROUTES.feedback,
  "/pages/variation-lab/index": STUDIO_PAGE_ROUTES.variationLab,
};

const LEGACY_COMMERCE_PATHS: Record<string, string> = {
  "/pages/marketplace/index": COMMERCE_PAGE_ROUTES.marketplace,
  "/pages/emotion-calendar/index": COMMERCE_PAGE_ROUTES.emotionCalendar,
  "/pages/creator-earnings/index": COMMERCE_PAGE_ROUTES.creatorEarnings,
  ...Object.fromEntries(
    Object.values(COMMERCE_PAGE_ROUTES).map((p) => [p.replace("/packageCommerce", ""), p])
  ),
};

/** Map old /pages/{stack|commerce} bookmarks to subpackage routes. */
const LEGACY_STACK_PATHS: Record<string, string> = {
  ...Object.fromEntries(
    Object.values(STACK_PAGE_ROUTES)
      .filter((p) => p.startsWith("/packageStack"))
      .map((path) => [path.replace("/packageStack", ""), path])
  ),
  ...LEGACY_COMMERCE_PATHS,
};

/** Map old /pages/{journey,provenance,feedback} bookmarks to packageStudio routes. */
export function resolvePageUrl(url: string): string {
  const q = url.indexOf("?");
  const path = q >= 0 ? url.slice(0, q) : url;
  const search = q >= 0 ? url.slice(q) : "";
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const mapped = LEGACY_STUDIO_PATHS[normalized] ?? LEGACY_STACK_PATHS[normalized];
  return mapped ? `${mapped}${search}` : url;
}

export function studioPage(route: keyof typeof STUDIO_PAGE_ROUTES, query?: Record<string, string | undefined>): string {
  const base = STUDIO_PAGE_ROUTES[route];
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v != null && v !== "") params.set(k, v);
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export function isTabRoute(route: string): boolean {
  const n = route.replace(/^\//, "").split("?")[0];
  return TAB_PAGE_PATHS.some((p) => n === p || n.endsWith(`/${p}`));
}

export function isTabUrl(url: string): boolean {
  const path = url.split("?")[0];
  return TAB_PAGE_ROUTES.some((r) => path === r || path.startsWith(r));
}

/** 全屏沉浸页 — 不显示 AppShell 顶栏 */
export const IMMERSIVE_PAGE_PATHS = ["pages/now-playing/index", "packageStack/pages/now-playing/index"] as const;

export function isImmersiveRoute(route: string): boolean {
  return IMMERSIVE_PAGE_PATHS.some((p) => route.includes(p));
}

export function currentPageRoute(): string {
  try {
    return Taro.getCurrentPages().slice(-1)[0]?.route || "";
  } catch {
    return "";
  }
}

/** H5: prefer location hash for tab routes — stack can lag behind tab bar clicks. */
export function currentLayoutRoute(): string {
  const fromStack = currentPageRoute();
  if (process.env.TARO_ENV === "h5" && typeof window !== "undefined") {
    const hash = (window.location.hash || "").replace(/^#\/?/, "").split("?")[0]
      || (window.location.pathname || "").replace(/^\//, "").split("?")[0];
    if (hash && isTabRoute(hash)) {
      const hashPath = hash.replace(/^\//, "");
      if (!fromStack || fromStack !== hashPath) return hashPath;
      return fromStack;
    }
    if (hash && (isStudioTabBarRoute(hash))) {
      if (!fromStack || !isStudioTabBarRoute(fromStack)) return hash.replace(/^\//, "");
    }
    if (!fromStack && hash) return hash.replace(/^\//, "");
  }
  return fromStack;
}

/** Studio flows launched from 创作 — keep bottom tab bar visible on H5. */
export const STUDIO_TAB_BAR_ROUTES = [
  "packageStudio/pages/journey/index",
  "packageStudio/pages/feedback/index",
] as const;

export function isStudioTabBarRoute(route: string): boolean {
  return STUDIO_TAB_BAR_ROUTES.some((p) => route.includes(p));
}

export function shouldShowTabBarLayout(route?: string): boolean {
  const r = route ?? currentLayoutRoute();
  if (isTabRoute(r) || isStudioTabBarRoute(r)) return true;
  if (process.env.TARO_ENV === "h5" && typeof document !== "undefined") {
    if (document.documentElement.classList.contains("layout-tab-visible")) return true;
    const hash = window.location.hash.replace(/^#\/?/, "").split("?")[0];
    if (hash && (isTabRoute(hash) || isStudioTabBarRoute(hash))) return true;
  }
  return false;
}

/** @deprecated use shouldShowTabBarLayout */
export function isTabLayoutRoute(route: string): boolean {
  return shouldShowTabBarLayout(route);
}
