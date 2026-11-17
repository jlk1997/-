/** Current Taro H5 route without a leading slash (hash, or leftover browser path). */
export function h5ActiveRoute(): string {
  if (typeof window === "undefined") return "";
  const hash = window.location.hash || "";
  if (hash.startsWith("#/")) {
    return hash.slice(2).split("?")[0];
  }
  return (window.location.pathname || "").replace(/^\//, "").split("?")[0];
}

export function isTaroAppPathname(pathname: string): boolean {
  return /^\/(pages|package[A-Za-z]+)\//.test(pathname);
}

/**
 * Production used to ship Taro browser-mode URLs. WeChat treats those path
 * changes as a new document and remounts the first tab (创作). Fold them
 * back onto hash routes before the router boots.
 */
export function redirectLegacyBrowserPathToHash() {
  if (process.env.TARO_ENV !== "h5" || typeof window === "undefined") return;
  const path = window.location.pathname || "/";
  if (!isTaroAppPathname(path)) return;
  if ((window.location.hash || "").startsWith("#/")) return;
  const search = window.location.search || "";
  window.location.replace(`${window.location.origin}/#${path}${search}`);
}

export function h5LocationMatches(url: string): boolean {
  if (typeof window === "undefined") return false;
  const target = url.replace(/^\//, "");
  const hash = (window.location.hash || "").replace(/^#\/?/, "");
  if (hash && hash === target) return true;
  const path = `${(window.location.pathname || "").replace(/^\//, "")}${window.location.search || ""}`;
  return path === target;
}

export function forceH5Hash(url: string) {
  if (typeof window === "undefined") return;
  const resolved = url.startsWith("/") ? url : `/${url}`;
  const nextHash = `#${resolved}`;
  if (window.location.hash !== nextHash) {
    window.location.hash = resolved;
  }
}
