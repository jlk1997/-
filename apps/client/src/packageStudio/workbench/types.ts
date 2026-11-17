import type { vibeApi } from "../../services/api";
import type { Copy } from "@vibe-sorcery/i18n";

export type Variant = "lite" | "pro";
export type Session = Awaited<ReturnType<typeof vibeApi.openWorkbenchSession>>;
export type Pack = Awaited<ReturnType<typeof vibeApi.listEffectPacks>>[number];
export type PackScope = "official" | "community" | "mine";
export type Lane = Session["mix_graph"]["lanes"][number];
export type Node = Session["mix_graph"]["nodes"][number];
export type Clip = NonNullable<Session["mix_graph"]["clips"]>[number];
export type BenchCopy = Copy["workbenchUi"];

export const NODE_LABEL: Record<string, keyof BenchCopy> = {
  eq: "eq",
  compress: "compress",
  reverb: "reverb",
  delay: "delay",
  loudness: "loudness",
  highpass: "highpass",
  lowpass: "lowpass",
  widen: "widen",
  pitch: "pitch",
  tempo: "tempo",
  limiter: "limiter",
  ai_denoise: "aiDenoise",
  ai_vocal: "aiVocal",
  ai_remaster: "aiRemaster",
  regen_extend: "regenExtend15",
  regen_remelt: "regenRemelt",
  regen_same_style: "regenSame",
};

export const LANE_LABEL: Record<string, "laneMaster" | "laneVocal" | "laneDrums" | "laneBass" | "laneOther" | "laneAccompaniment"> = {
  master: "laneMaster",
  vocal: "laneVocal",
  drums: "laneDrums",
  bass: "laneBass",
  other: "laneOther",
  accompaniment: "laneAccompaniment",
};

export const NEED_OPTIONS = [
  { id: "vocal", label: "needVocal" },
  { id: "club", label: "needClub" },
  { id: "radio", label: "needRadio" },
  { id: "lofi", label: "needLofi" },
  { id: "warm", label: "needWarm" },
  { id: "space", label: "needSpace" },
  { id: "voice", label: "needVoice" },
  { id: "width", label: "needWidth" },
  { id: "close", label: "needClose" },
  { id: "bright", label: "needBright" },
  { id: "denoise", label: "needDenoise" },
  { id: "master", label: "needMaster" },
] as const;

export function needLabel(need: string, w: BenchCopy): string {
  const hit = NEED_OPTIONS.find((row) => row.id === need);
  return hit ? String(w[hit.label]) : need;
}

export const isWeapp = process.env.TARO_ENV === "weapp";
