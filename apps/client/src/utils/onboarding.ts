import Taro from "@tarojs/taro";
import { getItem, removeItem, setItem } from "../platform/storage";
import { hasLocalPrivacyConsent } from "../components/legal/PrivacyConsentGate";
import { isLoggedIn } from "./auth";

/** Bump when coach copy/steps change materially — clears per-page done flags only. */
export const ONBOARDING_VERSION = "5";
export const ONBOARDING_RESET_EVENT = "vs:onboarding:reset";

const GLOBAL_DISABLED_KEY = `onboarding:v${ONBOARDING_VERSION}:all`;
const pageKey = (page: string) => `onboarding:v${ONBOARDING_VERSION}:page:${page}`;
const LEGACY_PAGE_KEY = (page: string) => `onboarding_done_${page}`;
const JOURNEY_GUIDE_KEY = `onboarding:v${ONBOARDING_VERSION}:journey_guide_collapsed`;
const CONSENT_BANNER_KEY = "consent_banner_dismissed";

export type CoachPage = "create" | "journey" | "feed" | "library" | "profile" | "creator";

export const COACH_PAGE_ROUTES: Record<CoachPage, string> = {
  create: "pages/create/index",
  feed: "pages/feed/index",
  library: "pages/library/index",
  profile: "pages/profile/index",
  creator: "pages/creator/index",
  journey: "packageStudio/pages/journey/index",
};

/** True when `route` is the host page for this coach (hash / stack path). */
export function isCoachPageActive(page: CoachPage, route: string): boolean {
  const target = COACH_PAGE_ROUTES[page];
  const n = route.replace(/^\//, "").split("?")[0];
  return n === target || n.endsWith(target);
}

/** Pages that auto-show multi-step coach on first visit (others: settings only). */
export const AUTO_COACH_PAGES: CoachPage[] = ["create", "creator"];

export function isOnboardingGloballyDisabled(): boolean {
  return getItem(GLOBAL_DISABLED_KEY) === "1";
}

export function disableAllOnboarding(): void {
  setItem(GLOBAL_DISABLED_KEY, "1");
}

export function enableAllOnboarding(): void {
  removeItem(GLOBAL_DISABLED_KEY);
  AUTO_COACH_PAGES.forEach((p) => {
    removeItem(pageKey(p));
    removeItem(LEGACY_PAGE_KEY(p));
  });
  removeItem(JOURNEY_GUIDE_KEY);
  removeItem(CONSENT_BANNER_KEY);
  Taro.eventCenter.trigger(ONBOARDING_RESET_EVENT);
}

export function isPageOnboardingDone(page: CoachPage): boolean {
  if (isOnboardingGloballyDisabled()) return true;
  return getItem(pageKey(page)) === "1";
}

export function markPageOnboardingDone(page: CoachPage): void {
  setItem(pageKey(page), "1");
}

export function shouldShowPageCoach(page: CoachPage): boolean {
  if (process.env.TARO_ENV === "h5" && !hasLocalPrivacyConsent()) return false;
  if (isOnboardingGloballyDisabled()) return false;
  if (!AUTO_COACH_PAGES.includes(page)) return false;
  if (AUTO_COACH_PAGES.includes(page) && !isLoggedIn()) return false;
  return !isPageOnboardingDone(page);
}

export function isJourneyGuideCollapsed(): boolean {
  return getItem(JOURNEY_GUIDE_KEY) === "1";
}

export function setJourneyGuideCollapsed(collapsed: boolean): void {
  setItem(JOURNEY_GUIDE_KEY, collapsed ? "1" : "0");
}

export function getConsentBannerDismissed(): Record<string, string> {
  try {
    const raw = getItem(CONSENT_BANNER_KEY);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function setConsentBannerDismissed(versions: Record<string, string>): void {
  setItem(CONSENT_BANNER_KEY, JSON.stringify(versions));
}
