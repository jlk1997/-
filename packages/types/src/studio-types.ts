import type { MusicCreativeSpec, SoundRecipeOptions } from "./music-creative-spec";

export type Waypoint = {
  step: number;
  arousal: number;
  valence: number;
  description?: string;
};

export type MusicParams = {
  bpm_range: [number, number];
  key: string;
  duration_preference: "short" | "medium" | "long";
};

export type JourneyPayload = {
  steps: number;
  target_curve: string;
  instrumental: boolean;
  title?: string;
  waypoints: Waypoint[];
};

export type PlatformStudioConfig = {
  curves: string[];
  keys: string[];
  bpm_presets: Array<{ label: string; range: [number, number] }>;
  duration_options: Array<{ value: string; label: string }>;
  sound_recipe?: SoundRecipeOptions;
  max_lyrics_length: number;
  default_bpm_range: [number, number];
  default_key: string;
  default_duration: string;
  lyrics_optimizer_default: boolean;
  cover_mode_default: string;
  max_prompt_length?: number;
  song_modes?: string[];
  default_song_mode?: string;
  freedom_levels?: string[];
  default_freedom?: string;
  structure_tags?: string[];
  structure_templates?: Array<{ id: string; minutes: number }>;
  compose_eta_p50_seconds?: number;
  qualities?: string[];
  wav_master_available?: boolean;
  vocal_is_guidance?: boolean;
};

export type { MusicCreativeSpec, SoundRecipeOptions };

export const DEFAULT_MUSIC_PARAMS: MusicParams = {
  bpm_range: [80, 120],
  key: "auto",
  duration_preference: "medium",
};

export const CURVE_LABELS: Record<string, string> = {
  calm_to_energy: "平静 → 能量",
  sad_to_hope: "低落 → 希望",
  chaos_to_order: "纷乱 → 安定",
  neutral: "保持平稳",
};
