import type { EqBand, MixChannel, MixDocument, MixInsert, InsertType } from "@vibe-sorcery/types";
import { create } from "zustand";
import { emptyMix } from "@vibe-sorcery/mix-engine";

type MixState = {
  doc: MixDocument;
  saved: string;
  selectedId: string;
  mixerOpen: boolean;
  inspectorOpen: boolean;
  plugin: { channelId: string; insertId: string } | null;
  past: MixDocument[];
  future: MixDocument[];
  lcdMode: "bars" | "time";
  loadDoc: (doc: MixDocument) => void;
  select: (id: string) => void;
  toggleMixer: () => void;
  toggleInspector: () => void;
  toggleLoop: () => void;
  setLcd: (mode: "bars" | "time") => void;
  openPlugin: (channelId: string, insertId: string) => void;
  closePlugin: () => void;
  patchChannel: (id: string, patch: Partial<MixChannel>) => void;
  liveChannel: (id: string, patch: Partial<MixChannel>) => void;
  patchInsert: (channelId: string, insertId: string, params: MixInsert["params"]) => void;
  toggleBypass: (channelId: string, insertId: string) => void;
  moveInsert: (channelId: string, insertId: string, dir: -1 | 1) => void;
  splitAt: (channelId: string, time: number, duration: number) => void;
  addInsert: (channelId: string, type: InsertType) => void;
  setTempo: (bpm: number) => void;
  setLoop: (loop: Partial<MixDocument["loop"]>) => void;
  checkpoint: () => void;
  liveVolume: (id: string, points: Array<{ t: number; db: number }>) => void;
  livePan: (id: string, points: Array<{ t: number; pan: number }>) => void;
  setRegion: (id: string, patch: Partial<MixDocument["regions"][number]>) => void;
  undo: () => void;
  redo: () => void;
  markSaved: () => void;
};

function clone(doc: MixDocument): MixDocument {
  return JSON.parse(JSON.stringify(doc)) as MixDocument;
}

export const useMixStore = create<MixState>((set, get) => ({
  doc: emptyMix(),
  saved: "",
  selectedId: "vocal",
  mixerOpen: true,
  inspectorOpen: true,
  plugin: null,
  past: [],
  future: [],
  lcdMode: "bars",
  loadDoc: (doc) => set({ doc, past: [], future: [], saved: JSON.stringify(doc), selectedId: doc.channels[0]?.id || "vocal" }),
  select: (id) => set({ selectedId: id }),
  toggleMixer: () => set((state) => ({ mixerOpen: !state.mixerOpen })),
  toggleInspector: () => set((state) => ({ inspectorOpen: !state.inspectorOpen })),
  toggleLoop: () =>
    set((state) => ({ doc: { ...state.doc, loop: { ...state.doc.loop, enabled: !state.doc.loop.enabled } } })),
  setLcd: (mode) => set({ lcdMode: mode }),
  openPlugin: (channelId, insertId) => set({ plugin: { channelId, insertId } }),
  closePlugin: () => set({ plugin: null }),
  liveChannel: (id, patch) =>
    set((state) => ({
      doc: { ...state.doc, channels: state.doc.channels.map((channel) => (channel.id === id ? { ...channel, ...patch } : channel)) },
    })),
  patchChannel: (id, patch) => {
    const current = get().doc;
    set({
      past: [...get().past, clone(current)].slice(-50),
      future: [],
      doc: { ...current, channels: current.channels.map((channel) => (channel.id === id ? { ...channel, ...patch } : channel)) },
    });
  },
  patchInsert: (channelId, insertId, params) => {
    const current = get().doc;
    set({
      doc: {
        ...current,
        channels: current.channels.map((channel) =>
          channel.id !== channelId
            ? channel
            : {
                ...channel,
                inserts: channel.inserts.map((insert) => (insert.id === insertId ? { ...insert, params: { ...insert.params, ...params } } : insert)),
              },
        ),
        buses: current.buses.map((bus) =>
          bus.id !== channelId
            ? bus
            : { ...bus, inserts: bus.inserts.map((insert) => (insert.id === insertId ? { ...insert, params: { ...insert.params, ...params } } : insert)) },
        ),
      },
    });
  },
  toggleBypass: (channelId, insertId) => {
    const current = get().doc;
    const flip = (insert: MixInsert) => (insert.id === insertId ? { ...insert, bypass: !insert.bypass } : insert);
    set({
      past: [...get().past, clone(current)].slice(-50),
      future: [],
      doc: {
        ...current,
        channels: current.channels.map((channel) => (channel.id === channelId ? { ...channel, inserts: channel.inserts.map(flip) } : channel)),
        buses: current.buses.map((bus) => (bus.id === channelId ? { ...bus, inserts: bus.inserts.map(flip) } : bus)),
      },
    });
  },
  moveInsert: (channelId, insertId, dir) => {
    const current = get().doc;
    set({
      doc: {
        ...current,
        channels: current.channels.map((channel) => {
          if (channel.id !== channelId) return channel;
          const inserts = [...channel.inserts];
          const index = inserts.findIndex((insert) => insert.id === insertId);
          const next = index + dir;
          if (index < 0 || next < 0 || next >= inserts.length) return channel;
          const [row] = inserts.splice(index, 1);
          inserts.splice(next, 0, row);
          return { ...channel, inserts };
        }),
      },
    });
  },
  addInsert: (channelId, type) => {
    const current = get().doc;
    const host = current.channels.find((channel) => channel.id === channelId) || current.buses.find((bus) => bus.id === channelId);
    if (!host || host.inserts.length >= 8) return;
    const insert: MixInsert = {
      id: `${type}-${Math.random().toString(36).slice(2, 7)}`,
      type,
      bypass: false,
      params: defaultInsertParams(type),
    };
    const withInsert = (inserts: MixInsert[]) => (inserts.length >= 8 ? inserts : [...inserts, insert]);
    set({
      past: [...get().past, clone(current)].slice(-50),
      future: [],
      plugin: { channelId, insertId: insert.id },
      doc: {
        ...current,
        channels: current.channels.map((channel) => (channel.id === channelId ? { ...channel, inserts: withInsert(channel.inserts) } : channel)),
        buses: current.buses.map((bus) => (bus.id === channelId ? { ...bus, inserts: withInsert(bus.inserts) } : bus)),
      },
    });
  },
  setTempo: (bpm) =>
    set((state) => ({ doc: { ...state.doc, tempo: { ...state.doc.tempo, bpm: Math.max(40, Math.min(240, bpm || state.doc.tempo.bpm)) } } })),
  setLoop: (loop) => set((state) => ({ doc: { ...state.doc, loop: { ...state.doc.loop, ...loop } } })),
  checkpoint: () => set((state) => ({ past: [...state.past, clone(state.doc)].slice(-50), future: [] })),
  liveVolume: (id, points) =>
    set((state) => ({
      doc: {
        ...state.doc,
        channels: state.doc.channels.map((channel) =>
          channel.id === id
            ? { ...channel, automationMode: "read", automation: { ...channel.automation, volume: points } }
            : channel,
        ),
      },
    })),
  livePan: (id, points) =>
    set((state) => ({
      doc: {
        ...state.doc,
        channels: state.doc.channels.map((channel) =>
          channel.id === id
            ? { ...channel, automationMode: "read", automation: { ...channel.automation, pan: points } }
            : channel,
        ),
      },
    })),
  splitAt: (channelId, time, duration) => {
    const current = get().doc;
    const regions = current.regions.filter((region) => region.channel === channelId);
    const host = regions.find((region) => time > region.start && time < region.end);
    const nextRegions = host
      ? current.regions.flatMap((region) => {
          if (region.id !== host.id) return [region];
          return [
            { ...region, end: time },
            { ...region, id: `${region.id}-b`, start: time, offset: region.offset + (time - region.start) },
          ];
        })
      : [
          ...current.regions,
          { id: `${channelId}-${Math.round(time * 100)}`, channel: channelId, start: 0, end: time, offset: 0, fadeIn: 0, fadeOut: 0, mute: false },
          { id: `${channelId}-${Math.round(time * 100)}b`, channel: channelId, start: time, end: duration || time + 1, offset: time, fadeIn: 0, fadeOut: 0, mute: false },
        ];
    set({ past: [...get().past, clone(current)].slice(-50), future: [], doc: { ...current, regions: nextRegions } });
  },
  setRegion: (id, patch) => {
    const current = get().doc;
    set({ doc: { ...current, regions: current.regions.map((region) => (region.id === id ? { ...region, ...patch } : region)) } });
  },
  undo: () => {
    const past = get().past;
    const prev = past[past.length - 1];
    if (!prev) return;
    set({ past: past.slice(0, -1), future: [clone(get().doc), ...get().future], doc: prev });
  },
  redo: () => {
    const [next, ...future] = get().future;
    if (!next) return;
    set({ future, past: [...get().past, clone(get().doc)], doc: next });
  },
  markSaved: () => set({ saved: JSON.stringify(get().doc) }),
}));

export function selectedInsert(doc: MixDocument, plugin: { channelId: string; insertId: string } | null) {
  if (!plugin) return null;
  const channel = doc.channels.find((item) => item.id === plugin.channelId);
  const bus = doc.buses.find((item) => item.id === plugin.channelId);
  const insert = channel?.inserts.find((item) => item.id === plugin.insertId) || bus?.inserts.find((item) => item.id === plugin.insertId);
  return insert ? { insert, name: channel?.name || bus?.name || "" } : null;
}

function defaultInsertParams(type: InsertType): MixInsert["params"] {
  if (type === "compressor") return { threshold: -18, ratio: 3, attack: 0.01, release: 0.12, knee: 6, makeup: 0 };
  if (type === "gate") return { threshold: -42, ratio: 4 };
  if (type === "deesser") return { amount: 0.45, freq: 6500 };
  if (type === "limiter") return { ceiling: -1 };
  if (type === "reverb") return { preset: "hall", decay: 1.6, predelay: 0.02, mix: 0.25 };
  if (type === "delay") return { sync: 0.5, feedback: 0.35, cutoff: 6000, mix: 0.2 };
  if (type === "widen") return { amount: 1.2 };
  return { bands: [] };
}

export function bandsOf(insert: MixInsert | undefined): EqBand[] {
  const bands = insert?.params.bands;
  return Array.isArray(bands) ? (bands as EqBand[]) : [];
}
