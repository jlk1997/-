import { getItem, setItem } from "./storage";

const FRONTEND_KEY = "platform:frontendBaseUrl";
const MOCK_AI_KEY = "platform:mockAi";
const MOCK_PAY_KEY = "platform:mockPayment";

const DEBUG_KEY = "platform:debug";
const FARM_NAV_KEY = "platform:farmNavigate";
const PARTNERS_KEY = "platform:partners";

export type PlatformHonesty = {
  mock_ai?: boolean;
  mock_payment?: boolean;
  frontend_base_url?: string;
  debug?: boolean;
  farm_navigate?: boolean;
  partners_configured?: boolean;
  essentia_ready?: boolean;
  payout_mode?: string;
  kyc_provider_configured?: boolean;
};

export function cachePlatformHonesty(cfg: PlatformHonesty) {
  if (cfg.frontend_base_url) {
    const cleaned = cfg.frontend_base_url.replace(/\/$/, "");
    if (isPublicFrontendOrigin(cleaned)) setItem(FRONTEND_KEY, cleaned);
  }
  if (typeof cfg.mock_ai === "boolean") setItem(MOCK_AI_KEY, cfg.mock_ai ? "1" : "0");
  if (typeof cfg.mock_payment === "boolean") setItem(MOCK_PAY_KEY, cfg.mock_payment ? "1" : "0");
  if (typeof cfg.debug === "boolean") setItem(DEBUG_KEY, cfg.debug ? "1" : "0");
  if (typeof cfg.farm_navigate === "boolean") setItem(FARM_NAV_KEY, cfg.farm_navigate ? "1" : "0");
  if (typeof cfg.partners_configured === "boolean") setItem(PARTNERS_KEY, cfg.partners_configured ? "1" : "0");
}

export function cachedFrontendBaseUrl(): string {
  const stored = (getItem(FRONTEND_KEY) || "").replace(/\/$/, "");
  if (stored && isPublicFrontendOrigin(stored)) return stored;
  if (typeof window !== "undefined" && window.location?.origin && isPublicFrontendOrigin(window.location.origin)) {
    return window.location.origin;
  }
  return "";
}

export function creatorOsH5Url(path: string): string {
  const base = cachedFrontendBaseUrl();
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${normalized}` : normalized;
}

export function isAbsoluteHttpUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

export function isPublicFrontendOrigin(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (!host || host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host === "[::1]") return false;
    if (host.endsWith(".local") || host.endsWith(".localhost")) return false;
    if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return false;
    return true;
  } catch {
    return false;
  }
}

export function creatorOsH5Ready(path: string): boolean {
  const url = creatorOsH5Url(path);
  return isAbsoluteHttpUrl(url) && isPublicFrontendOrigin(url);
}

export async function refreshPlatformHonesty() {
  try {
    const { vibeApi } = await import("../services/api");
    cachePlatformHonesty(await vibeApi.getPlatformConfig());
  } catch {
    /* keep cache */
  }
}

export function cachedMockAi(): boolean {
  return getItem(MOCK_AI_KEY) === "1";
}

export function cachedMockPayment(): boolean {
  return getItem(MOCK_PAY_KEY) === "1";
}

export function cachedDebug(): boolean {
  return getItem(DEBUG_KEY) === "1";
}

export function cachedFarmNavigate(): boolean {
  return getItem(FARM_NAV_KEY) === "1";
}

export function cachedPartnersConfigured(): boolean {
  return getItem(PARTNERS_KEY) === "1";
}
