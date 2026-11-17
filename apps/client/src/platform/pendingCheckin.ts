import { getItem, removeItem, setItem } from "./storage";

export const PENDING_CHECKIN_KEY = "engagement:pendingCheckin";
const MAX_AGE_MS = 2 * 60 * 60 * 1000;

export type PendingCheckin = {
  work_id: string;
  workTitle?: string;
  listen_ratio: number;
  arousal: number;
  valence: number;
  mood_tags: string[];
  station?: string;
  saved_at?: number;
};

export function savePendingCheckin(payload: PendingCheckin) {
  setItem(PENDING_CHECKIN_KEY, JSON.stringify({ ...payload, saved_at: Date.now() }));
}

export function peekPendingCheckin(): PendingCheckin | null {
  const raw = getItem(PENDING_CHECKIN_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PendingCheckin;
    if (!parsed?.work_id) {
      removeItem(PENDING_CHECKIN_KEY);
      return null;
    }
    if (typeof parsed.listen_ratio !== "number" || parsed.listen_ratio < 0.8) {
      removeItem(PENDING_CHECKIN_KEY);
      return null;
    }
    const savedAt = Number(parsed.saved_at || 0);
    if (!savedAt || Date.now() - savedAt > MAX_AGE_MS) {
      removeItem(PENDING_CHECKIN_KEY);
      return null;
    }
    return parsed;
  } catch {
    removeItem(PENDING_CHECKIN_KEY);
    return null;
  }
}

export function consumePendingCheckin(): PendingCheckin | null {
  const pending = peekPendingCheckin();
  if (pending) removeItem(PENDING_CHECKIN_KEY);
  return pending;
}
