/** Keep in sync with backend/app/core/preview_contract.py */

export const EQ_HZ = { low: 120, mid: 1000, high: 8000 } as const;
export const EQ_Q = { low: 1.5, mid: 2.5, high: 4 } as const;
export const LIVE_LU_TOLERANCE = 0.5;
export const APPROX_LU_TOLERANCE = 1.5;

export type Fidelity = "live" | "approx" | "render";

export const FIDELITY: Record<string, Fidelity> = {
  eq: "live",
  highpass: "live",
  lowpass: "live",
  widen: "live",
  pan: "live",
  delay: "live",
  reverb: "live",
  compress: "approx",
  limiter: "approx",
  loudness: "approx",
  pitch: "render",
  tempo: "render",
  ai_denoise: "render",
  ai_vocal: "render",
  ai_remaster: "render",
  regen_extend: "render",
  regen_remelt: "render",
  regen_same_style: "render",
};

export function fidelityOf(type: string): Fidelity {
  return FIDELITY[type] || "render";
}

export function fidelityLabel(type: string): string {
  const kind = fidelityOf(type);
  if (kind === "live") return "实时";
  if (kind === "approx") return "近似";
  return "需渲染";
}
