/** Mirrors backend `next_core_door`. One stereo master; never DistroKid tracks>1.
 *  Order is asserted in `backend/tests/test_next_core_door_mirror.py`.
 */

export type CoreDoor = "beautify" | "fix" | "radio" | "release" | "deliveries";

const SHIPPING = new Set(["queued", "delivering", "live"]);

export function nextCoreDoor(opts: {
  hasResult?: boolean;
  releaseStatus?: string | null;
  degraded?: boolean;
}): CoreDoor {
  const status = String(opts.releaseStatus || "");
  if (!opts.hasResult) return "beautify";
  if (SHIPPING.has(status)) return "deliveries";
  if (opts.degraded) return "fix";
  if (status === "qc_ready") return "release";
  return "radio";
}

export function isShippingStatus(status?: string | null): boolean {
  return SHIPPING.has(String(status || ""));
}
