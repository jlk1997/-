/** Logic-style fader: 0 is silence, about 0.75 is unity, 1 is +6 dB. */

export function faderToDb(position: number): number {
  const t = Math.max(0, Math.min(1, position));
  if (t <= 0.001) return -80;
  if (t < 0.75) {
    const u = t / 0.75;
    return -60 * Math.pow(1 - u, 1.7);
  }
  return ((t - 0.75) / 0.25) * 6;
}

export function dbToFader(db: number): number {
  if (!Number.isFinite(db) || db <= -60) return 0;
  if (db < 0) {
    const u = 1 - Math.pow(-db / 60, 1 / 1.7);
    return Math.max(0, Math.min(0.75, u * 0.75));
  }
  return Math.max(0.75, Math.min(1, 0.75 + (Math.min(6, db) / 6) * 0.25));
}

export function dbToGain(db: number): number {
  if (!Number.isFinite(db) || db <= -80) return 0;
  return Math.pow(10, db / 20);
}

export function snapUnity(db: number): number {
  return Math.abs(db) < 0.35 ? 0 : db;
}

export function formatDb(db: number): string {
  if (!Number.isFinite(db) || db <= -80) return "-∞";
  const rounded = Math.round(db * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)}`;
}

export function barsBeats(seconds: number, bpm: number, beatsPerBar: number): string {
  const safeBpm = Math.max(1, bpm);
  const beats = Math.max(0, seconds) * (safeBpm / 60);
  const bar = Math.floor(beats / beatsPerBar) + 1;
  const beat = Math.floor(beats % beatsPerBar) + 1;
  const ticks = Math.floor((beats % 1) * 1000);
  return `${bar}.${beat}.${String(ticks).padStart(3, "0")}`;
}

export function formatTimecode(seconds: number): string {
  const whole = Math.max(0, seconds);
  const mins = Math.floor(whole / 60);
  const secs = Math.floor(whole % 60);
  const frames = Math.floor((whole % 1) * 1000);
  return `${mins}:${String(secs).padStart(2, "0")}.${String(frames).padStart(3, "0")}`;
}
