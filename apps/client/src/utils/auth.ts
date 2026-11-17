import { setAuthToken } from "@vibe-sorcery/api-client";
import Taro from "@tarojs/taro";
import { AUTH_EVENTS } from "../constants/events";
import { getToken, saveToken as saveStorageToken, clearTokenStorage } from "../platform/storage";
import { STACK_PAGE_ROUTES, stackPage } from "../constants/routes";
import { openStackPage } from "./navigation";
import { getLocaleCopy } from "./localeCopy";

export function bootstrapAuth() {
  const token = getToken();
  setAuthToken(token);
}

export function saveAuthToken(token: string) {
  saveStorageToken(token);
  setAuthToken(token);
  Taro.eventCenter.trigger(AUTH_EVENTS.login);
}

export function saveToken(token: string) {
  saveAuthToken(token);
}

export function clearToken() {
  clearTokenStorage();
  setAuthToken(null);
  Taro.eventCenter.trigger(AUTH_EVENTS.logout);
}

export function isLoggedIn(): boolean {
  bootstrapAuth();
  const token = getToken();
  return Boolean(token && token.trim());
}

function h5LocationPath(): string | undefined {
  if (process.env.TARO_ENV !== "h5" || typeof window === "undefined") return undefined;
  try {
    const hash = window.location.hash || "";
    if (hash.startsWith("#/")) {
      const inner = hash.slice(1);
      const path = inner.split("?")[0];
      if (!path || path.includes("/login/index")) return undefined;
      return inner.startsWith("/") ? inner : `/${inner}`;
    }
    const path = window.location.pathname || "";
    if (!path || path === "/" || path.includes("/login/index")) return undefined;
    return `${path}${window.location.search || ""}`;
  } catch {
    return undefined;
  }
}

export function loginReturnPath(): string | undefined {
  const fromH5 = h5LocationPath();
  if (fromH5) return fromH5;

  try {
    const pages = Taro.getCurrentPages();
    const top = pages[pages.length - 1];
    if (!top?.route) return undefined;
    const base = top.route.startsWith("/") ? top.route : `/${top.route}`;
    if (base.includes("/login/index")) return undefined;
    const opts = (top as { options?: Record<string, string> }).options;
    if (!opts || Object.keys(opts).length === 0) return base;
    const qs = Object.entries(opts)
      .filter(([, v]) => v != null && String(v) !== "")
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
      .join("&");
    return qs ? `${base}?${qs}` : base;
  } catch {
    return undefined;
  }
}

let lastLoginNavAt = 0;

export function requireAuth(next?: string): boolean {
  bootstrapAuth();
  if (getToken()) return true;
  const now = Date.now();
  if (now - lastLoginNavAt < 600) {
    Taro.showToast({ title: getLocaleCopy().loginUi.openingLogin, icon: "none" });
    return false;
  }
  lastLoginNavAt = now;
  const returnPath = next ?? loginReturnPath();
  const url = returnPath ? stackPage("login", { next: returnPath }) : STACK_PAGE_ROUTES.login;
  openStackPage(url);
  return false;
}
