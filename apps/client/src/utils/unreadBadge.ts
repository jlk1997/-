import { vibeApi } from "../services/api";

const TTL_MS = 45_000;
let cached = 0;
let at = 0;
let inflight: Promise<number> | null = null;

export function primeUnread(count: number) {
  cached = count;
  at = Date.now();
}

export function peekUnread() {
  return cached;
}

export async function fetchUnreadCount(force = false): Promise<number> {
  if (!force && at && Date.now() - at < TTL_MS) return cached;
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await vibeApi.getNotificationUnread();
      primeUnread(res.unread_count);
      return cached;
    } catch {
      return cached;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}
