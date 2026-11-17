import type { ChannelKind, EqBand, MixBus, MixChannel, MixDocument, MixInsert, MixRegion } from "@vibe-sorcery/types";

const STEM_ROWS: Array<[ChannelKind, string, string]> = [
  ["vocal", "人声", "#ff5d5d"],
  ["drums", "鼓", "#f5c451"],
  ["bass", "贝斯", "#f08a24"],
  ["guitar", "吉他", "#3dd68c"],
  ["piano", "钢琴", "#7aa2ff"],
  ["other", "其他", "#c07bff"],
  ["reference", "原曲", "#8e8e93"],
];

export function defaultEqBands(): EqBand[] {
  return [
    { type: "highpass", freq: 30, gain: 0, q: 0.7, enabled: false },
    { type: "lowshelf", freq: 90, gain: 0, q: 0.7, enabled: true },
    { type: "bell", freq: 240, gain: 0, q: 1.2, enabled: true },
    { type: "bell", freq: 900, gain: 0, q: 1.2, enabled: true },
    { type: "bell", freq: 2500, gain: 0, q: 1.4, enabled: true },
    { type: "bell", freq: 6500, gain: 0, q: 1.2, enabled: true },
    { type: "highshelf", freq: 11000, gain: 0, q: 0.7, enabled: true },
    { type: "lowpass", freq: 18000, gain: 0, q: 0.7, enabled: false },
  ];
}

export function eqInsert(id: string): MixInsert {
  return { id, type: "eq", bypass: false, params: { bands: defaultEqBands() } };
}

function sends(id: string): MixChannel["sends"] {
  return [
    { id: `${id}-rv`, bus: "aux-reverb", level: 0, pre: false },
    { id: `${id}-dl`, bus: "aux-delay", level: 0, pre: false },
  ];
}

export function makeChannel(kind: ChannelKind, name: string, color: string, mute = false): MixChannel {
  return {
    id: kind,
    name,
    kind,
    color,
    inputGain: 0,
    faderDb: 0,
    pan: 0,
    mute,
    solo: false,
    automationMode: "off",
    output: "master",
    inserts: [eqInsert(`${kind}-eq`)],
    sends: sends(kind),
    automation: { volume: [], pan: [] },
  };
}

function masterBus(): MixBus {
  return {
    id: "master",
    name: "Stereo Out",
    kind: "master",
    faderDb: 0,
    mute: false,
    inserts: [
      eqInsert("master-eq"),
      { id: "master-comp", type: "compressor", bypass: false, params: { threshold: -12, ratio: 2, attack: 0.02, release: 0.18, knee: 6, makeup: 0 } },
      { id: "master-lim", type: "limiter", bypass: false, params: { ceiling: -1 } },
    ],
  };
}

export function emptyMix(workId?: string, bpm = 120, key = ""): MixDocument {
  return {
    version: 3,
    sourceWorkId: workId,
    tempo: { bpm, beatsPerBar: 4, key },
    loop: { enabled: false, start: 0, end: 8 },
    channels: STEM_ROWS.map(([kind, name, color]) => makeChannel(kind, name, color, kind === "reference")),
    buses: [
      {
        id: "aux-reverb",
        name: "Aux 1 混响",
        kind: "aux",
        faderDb: 0,
        mute: false,
        inserts: [{ id: "aux-rv", type: "reverb", bypass: false, params: { decay: 1.6, mix: 1, predelay: 0.02, preset: "hall" } }],
      },
      {
        id: "aux-delay",
        name: "Aux 2 延迟",
        kind: "aux",
        faderDb: 0,
        mute: false,
        inserts: [{ id: "aux-dl", type: "delay", bypass: false, params: { mix: 1, feedback: 0.35, sync: 0.5, cutoff: 6000 } }],
      },
      masterBus(),
    ],
    regions: [],
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function documentFromServer(raw: unknown, workId?: string): MixDocument {
  const blob = asRecord(raw);
  if (Number(blob.version) >= 3 && Array.isArray(blob.channels)) {
    const base = emptyMix(workId);
    const channels = (blob.channels as unknown[]).map((item, index) => channelFromServer(item, base.channels[index]));
    return {
      ...base,
      sourceWorkId: String(asRecord(blob.source).work_id || workId || ""),
      tempo: {
        bpm: numberOf(asRecord(blob.tempo).bpm, base.tempo.bpm),
        beatsPerBar: numberOf(asRecord(blob.tempo).beats_per_bar, 4),
        key: String(asRecord(blob.tempo).key || ""),
      },
      loop: {
        enabled: Boolean(asRecord(blob.loop).enabled),
        start: numberOf(asRecord(blob.loop).start, 0),
        end: numberOf(asRecord(blob.loop).end, 0),
      },
      channels: channels.length ? channels : base.channels,
      buses: Array.isArray(blob.buses) ? (blob.buses as unknown[]).map((item) => busFromServer(item, base)) : base.buses,
      regions: Array.isArray(blob.regions) ? (blob.regions as unknown[]).map(regionFromServer).filter((row): row is MixRegion => Boolean(row)) : [],
    };
  }
  return emptyMix(workId);
}

function numberOf(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function channelFromServer(raw: unknown, fallback?: MixChannel): MixChannel {
  const row = asRecord(raw);
  const kind = String(row.kind || fallback?.kind || "other") as ChannelKind;
  const id = String(row.id || kind);
  const base = fallback || makeChannel(kind, String(row.name || kind), "#8e8e93");
  return {
    ...base,
    id,
    name: String(row.name || base.name),
    kind,
    color: String(row.color || base.color),
    inputGain: numberOf(row.input_gain, 0),
    faderDb: numberOf(row.fader_db, 0),
    pan: numberOf(row.pan, 0),
    mute: Boolean(row.mute),
    solo: Boolean(row.solo),
    automationMode: row.automation_mode === "read" ? "read" : "off",
    inserts: Array.isArray(row.inserts) ? (row.inserts as unknown[]).map(insertFromServer) : base.inserts,
    sends: Array.isArray(row.sends) && (row.sends as unknown[]).length ? (row.sends as unknown[]).map(sendFromServer) : sends(id),
    automation: {
      volume: volumePoints(asRecord(row.automation).volume),
      pan: panPoints(asRecord(row.automation).pan),
    },
  };
}

function insertFromServer(raw: unknown): MixInsert {
  const row = asRecord(raw);
  const params = asRecord(row.params);
  const bands = Array.isArray(params.bands) ? (params.bands as EqBand[]) : undefined;
  return {
    id: String(row.id || "insert"),
    type: String(row.type || "eq") as MixInsert["type"],
    bypass: Boolean(row.bypass),
    params: bands ? { ...params, bands } : (params as MixInsert["params"]),
  };
}

function sendFromServer(raw: unknown): MixChannel["sends"][number] {
  const row = asRecord(raw);
  const bus = row.bus === "aux-delay" ? "aux-delay" : "aux-reverb";
  return { id: String(row.id || bus), bus, level: numberOf(row.level, 0), pre: Boolean(row.pre) };
}

function busFromServer(raw: unknown, base: MixDocument): MixBus {
  const row = asRecord(raw);
  const id = (row.id === "aux-delay" || row.id === "master" ? row.id : "aux-reverb") as MixBus["id"];
  const fallback = base.buses.find((bus) => bus.id === id) || base.buses[2];
  return {
    ...fallback,
    id,
    name: String(row.name || fallback.name),
    faderDb: numberOf(row.fader_db, 0),
    mute: Boolean(row.mute),
    inserts: Array.isArray(row.inserts) ? (row.inserts as unknown[]).map(insertFromServer) : fallback.inserts,
  };
}

function regionFromServer(raw: unknown): MixRegion | null {
  const row = asRecord(raw);
  if (!row.channel) return null;
  return {
    id: String(row.id || "region"),
    channel: String(row.channel),
    start: numberOf(row.start, 0),
    end: numberOf(row.end, 0),
    offset: numberOf(row.offset, 0),
    fadeIn: numberOf(row.fade_in, 0),
    fadeOut: numberOf(row.fade_out, 0),
    mute: Boolean(row.mute),
  };
}

function volumePoints(raw: unknown): Array<{ t: number; db: number }> {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const row = asRecord(item);
    return { t: numberOf(row.t, 0), db: numberOf(row.db ?? row.v, 0) };
  });
}

function panPoints(raw: unknown): Array<{ t: number; pan: number }> {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const row = asRecord(item);
    return { t: numberOf(row.t, 0), pan: numberOf(row.pan ?? row.v, 0) };
  });
}

export function documentToServer(doc: MixDocument): Record<string, unknown> {
  return {
    version: 3,
    source: doc.sourceWorkId ? { work_id: doc.sourceWorkId } : {},
    tempo: { bpm: doc.tempo.bpm, beats_per_bar: doc.tempo.beatsPerBar, key: doc.tempo.key },
    loop: { enabled: doc.loop.enabled, start: doc.loop.start, end: doc.loop.end },
    channels: doc.channels.map((channel) => ({
      id: channel.id,
      name: channel.name,
      kind: channel.kind,
      color: channel.color,
      input_gain: channel.inputGain,
      fader_db: channel.faderDb,
      pan: channel.pan,
      mute: channel.mute,
      solo: channel.solo,
      automation_mode: channel.automationMode,
      output: "master",
      inserts: channel.inserts,
      sends: channel.sends,
      automation: channel.automation,
    })),
    buses: doc.buses.map((bus) => ({
      id: bus.id,
      name: bus.name,
      kind: bus.kind,
      fader_db: bus.faderDb,
      mute: bus.mute,
      inserts: bus.inserts,
    })),
    regions: doc.regions.map((region) => ({
      id: region.id,
      channel: region.channel,
      start: region.start,
      end: region.end,
      offset: region.offset,
      fade_in: region.fadeIn,
      fade_out: region.fadeOut,
      mute: region.mute,
    })),
  };
}
