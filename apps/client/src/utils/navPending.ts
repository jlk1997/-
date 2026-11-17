type Listener = (url: string | null) => void;

const listeners = new Set<Listener>();
let pending: string | null = null;
let pendingTimer: ReturnType<typeof setTimeout> | null = null;

export function setNavPending(url: string | null) {
  pending = url;
  if (pendingTimer) {
    clearTimeout(pendingTimer);
    pendingTimer = null;
  }
  if (url) {
    pendingTimer = setTimeout(() => setNavPending(null), 8000);
  }
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("h5-nav-pending", Boolean(url));
  }
  listeners.forEach((fn) => fn(pending));
}

export function getNavPending() {
  return pending;
}

export function subscribeNavPending(fn: Listener) {
  listeners.add(fn);
  fn(pending);
  return () => listeners.delete(fn);
}
