export type EqBandType = "highpass" | "lowshelf" | "bell" | "highshelf" | "lowpass";

export type EqBand = {
  type: EqBandType;
  freq: number;
  gain: number;
  q: number;
  enabled: boolean;
};

export type InsertType = "eq" | "compressor" | "gate" | "deesser" | "limiter" | "reverb" | "delay" | "widen";

export type MixInsert = {
  id: string;
  type: InsertType;
  bypass: boolean;
  params: Record<string, number | boolean | string | EqBand[]>;
};

export type MixSend = {
  id: string;
  bus: "aux-reverb" | "aux-delay";
  level: number;
  pre: boolean;
};

export type ChannelKind =
  | "vocal"
  | "drums"
  | "bass"
  | "guitar"
  | "piano"
  | "other"
  | "accompaniment"
  | "reference";

export type MixChannel = {
  id: string;
  name: string;
  kind: ChannelKind;
  color: string;
  inputGain: number;
  faderDb: number;
  pan: number;
  mute: boolean;
  solo: boolean;
  automationMode: "read" | "off";
  output: "master";
  inserts: MixInsert[];
  sends: MixSend[];
  automation: {
    volume: Array<{ t: number; db: number }>;
    pan: Array<{ t: number; pan: number }>;
  };
};

export type MixBus = {
  id: "aux-reverb" | "aux-delay" | "master";
  name: string;
  kind: "aux" | "master";
  faderDb: number;
  mute: boolean;
  inserts: MixInsert[];
};

export type MixRegion = {
  id: string;
  channel: string;
  start: number;
  end: number;
  offset: number;
  fadeIn: number;
  fadeOut: number;
  mute: boolean;
};

export type MixDocument = {
  version: 3;
  sourceWorkId?: string;
  tempo: { bpm: number; beatsPerBar: number; key: string };
  loop: { enabled: boolean; start: number; end: number };
  channels: MixChannel[];
  buses: MixBus[];
  regions: MixRegion[];
};
