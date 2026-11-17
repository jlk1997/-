import { API_BASE } from "@vibe-sorcery/api-client";
import { EQ_HZ, EQ_Q, fidelityOf } from "./contract";

type MixNode = { type?: string; target?: string; params?: Record<string, number> };
type MixLane = { id?: string; kind?: string; gain?: number; mute?: boolean; solo?: boolean; pan?: number };
type Stage = { input: AudioNode; output: AudioNode };

export type LiveHandle = {
  context: AudioContext;
  audio: HTMLAudioElement;
  analyser: AnalyserNode;
  stemKey: string;
  setLoopSeconds: (seconds: number | null) => void;
  setTrim: (value: number) => void;
  update: (lanes: MixLane[], nodes: MixNode[], intensity: number) => void;
  readLanePeaks: () => Record<string, number>;
  play: () => Promise<void>;
  pause: () => void;
  seekTo: (seconds: number) => void;
  getTime: () => number;
  getDuration: () => number;
  close: () => void;
};

let irBuffer: AudioBuffer | null = null;

async function loadIr(ctx: AudioContext) {
  if (irBuffer) return irBuffer;
  try {
    const res = await fetch(`${API_BASE}/workbench/studio-ir`);
    if (!res.ok) return null;
    irBuffer = await ctx.decodeAudioData((await res.arrayBuffer()).slice(0));
    return irBuffer;
  } catch {
    return null;
  }
}

function peaking(ctx: AudioContext, freq: number, q: number, gainDb: number): Stage {
  const filter = ctx.createBiquadFilter();
  filter.type = "peaking";
  filter.frequency.value = freq;
  filter.Q.value = q;
  filter.gain.value = gainDb;
  return { input: filter, output: filter };
}

function shelfPass(ctx: AudioContext, type: BiquadFilterType, hz: number): Stage {
  const filter = ctx.createBiquadFilter();
  filter.type = type;
  filter.frequency.value = hz;
  return { input: filter, output: filter };
}

function wetDry(ctx: AudioContext, wet: AudioNode, mix: number): Stage {
  const input = ctx.createGain();
  const dry = ctx.createGain();
  const wetGain = ctx.createGain();
  const output = ctx.createGain();
  dry.gain.value = 1 - mix;
  wetGain.gain.value = mix;
  input.connect(dry).connect(output);
  input.connect(wet);
  wet.connect(wetGain).connect(output);
  return { input, output };
}

function widenStage(ctx: AudioContext, width: number): Stage {
  const input = ctx.createGain();
  const splitter = ctx.createChannelSplitter(2);
  const merger = ctx.createChannelMerger(2);
  const mid = ctx.createGain();
  const sidePos = ctx.createGain();
  const sideNeg = ctx.createGain();
  mid.gain.value = 0.5;
  sidePos.gain.value = 0.5 * width;
  sideNeg.gain.value = -0.5 * width;
  input.connect(splitter);
  splitter.connect(mid, 0);
  splitter.connect(mid, 1);
  splitter.connect(sidePos, 0);
  splitter.connect(sideNeg, 1);
  mid.connect(merger, 0, 0);
  sidePos.connect(merger, 0, 0);
  mid.connect(merger, 0, 1);
  sideNeg.connect(merger, 0, 1);
  return { input, output: merger };
}

function audible(lanes: MixLane[]) {
  const solos = lanes.filter((lane) => lane.solo && !lane.mute);
  const active = solos.length ? solos : lanes.filter((lane) => !lane.mute);
  return active.length ? active : lanes;
}

export async function openLiveGraph(url: string): Promise<LiveHandle | null> {
  if (typeof window === "undefined" || !window.AudioContext) return null;
  const context = new window.AudioContext();
  if (context.state === "suspended") await context.resume();
  await loadIr(context);
  const audio = new Audio(url);
  audio.crossOrigin = "anonymous";
  const source = context.createMediaElementSource(audio);
  const master = context.createGain();
  const analyser = context.createAnalyser();
  analyser.fftSize = 2048;
  let built: AudioNode[] = [];
  let trim = 1;
  let laneGain = 1;

  function update(lanes: MixLane[], nodes: MixNode[], intensity: number) {
    built.forEach((node) => {
      try {
        node.disconnect();
      } catch {
        /* released */
      }
    });
    try {
      source.disconnect();
    } catch {
      /* first connect */
    }
    built = [];
    const lane = audible(lanes).find((row) => row.kind === "master") || audible(lanes)[0];
    const gain = Number(lane?.gain ?? 1);
    laneGain = Number.isFinite(gain) ? Math.max(0, Math.min(2, gain)) : 1;
    master.gain.value = laneGain * trim;
    const wet = Math.max(0, Math.min(1.5, intensity || 1));
    const target = lane?.id || "master";
    const stages: Stage[] = [];
    for (const node of nodes) {
      const aim = node.target || "master";
      if (aim !== target && aim !== "master") continue;
      if (fidelityOf(String(node.type || "")) === "render") continue;
      const params = node.params || {};
      if (node.type === "eq") {
        stages.push(peaking(context, EQ_HZ.low, EQ_Q.low, Number(params.low || 0) * wet));
        stages.push(peaking(context, EQ_HZ.mid, EQ_Q.mid, Number(params.mid || 0) * wet));
        stages.push(peaking(context, EQ_HZ.high, EQ_Q.high, Number(params.high || 0) * wet));
      } else if (node.type === "highpass") {
        stages.push(shelfPass(context, "highpass", Number(params.hz || 80)));
      } else if (node.type === "lowpass") {
        stages.push(shelfPass(context, "lowpass", Number(params.hz || 12000)));
      } else if (node.type === "delay") {
        const delay = context.createDelay(1);
        delay.delayTime.value = Math.max(0.04, Math.min(0.6, Number(params.ms || 180) / 1000));
        const feedback = context.createGain();
        feedback.gain.value = 0.28;
        delay.connect(feedback).connect(delay);
        const mix = Math.max(0, Math.min(0.6, Number(params.mix || 0.12) * wet));
        stages.push(wetDry(context, delay, mix));
        built.push(feedback);
      } else if (node.type === "reverb" && irBuffer) {
        const convolver = context.createConvolver();
        convolver.buffer = irBuffer;
        const mix = Math.max(0, Math.min(0.7, Number(params.mix || 0.2) * wet));
        stages.push(wetDry(context, convolver, mix));
      } else if (node.type === "compress" || node.type === "limiter") {
        const comp = context.createDynamicsCompressor();
        comp.threshold.value = node.type === "limiter" ? -6 : Number(params.threshold || -18);
        comp.ratio.value = node.type === "limiter" ? 20 : Number(params.ratio || 2);
        comp.attack.value = 0.01;
        comp.release.value = 0.12;
        stages.push({ input: comp, output: comp });
      } else if (node.type === "widen") {
        const width = Math.max(1, Math.min(2.2, 1 + 0.45 * wet * Number(params.amount || 1)));
        stages.push(widenStage(context, width));
      } else if (node.type === "loudness") {
        const makeup = context.createGain();
        makeup.gain.value = 1;
        stages.push({ input: makeup, output: makeup });
      }
    }
    const panner = context.createStereoPanner();
    panner.pan.value = Math.max(-1, Math.min(1, Number(lane?.pan || 0)));
    stages.push({ input: panner, output: panner });
    let cursor: AudioNode = source;
    for (const stage of stages) {
      cursor.connect(stage.input);
      cursor = stage.output;
      built.push(stage.input, stage.output);
    }
    cursor.connect(master);
    master.connect(analyser);
    analyser.connect(context.destination);
    built.push(master, analyser);
  }

  update([], [], 1);
  return {
    context,
    audio,
    analyser,
    stemKey: "",
    setLoopSeconds(seconds) {
      audio.loop = seconds == null;
      audio.ontimeupdate = () => {
        if (seconds != null && audio.currentTime >= seconds) audio.currentTime = 0;
      };
    },
    setTrim(value) {
      trim = Math.max(0.25, Math.min(4, value));
      master.gain.value = laneGain * trim;
    },
    update,
    readLanePeaks: () => ({}),
    play: () => audio.play(),
    pause: () => audio.pause(),
    seekTo(seconds) {
      audio.currentTime = seconds;
    },
    getTime: () => audio.currentTime || 0,
    getDuration: () => (Number.isFinite(audio.duration) ? audio.duration : 0),
    close() {
      audio.pause();
      void context.close();
    },
  };
}

const STEM_KINDS = ["vocal", "drums", "bass", "accompaniment", "guitar", "piano"];

async function decodeStem(context: AudioContext, url: string, windowSeconds: number | null) {
  const response = await fetch(url);
  if (!response.ok) return null;
  const decoded = await context.decodeAudioData((await response.arrayBuffer()).slice(0));
  if (!windowSeconds || decoded.duration <= windowSeconds) return decoded;
  const length = Math.max(1, Math.floor(windowSeconds * decoded.sampleRate));
  const slice = context.createBuffer(decoded.numberOfChannels, length, decoded.sampleRate);
  for (let channel = 0; channel < decoded.numberOfChannels; channel += 1) {
    slice.copyToChannel(decoded.getChannelData(channel).subarray(0, length), channel);
  }
  return slice;
}

export async function openStemGraph(
  laneUrls: Record<string, string>,
  options?: { windowSeconds?: number | null; kinds?: string[] },
): Promise<LiveHandle | null> {
  if (typeof window === "undefined" || !window.AudioContext) return null;
  const wanted = options?.kinds || STEM_KINDS;
  const entries = wanted
    .map((kind) => [kind, laneUrls[kind] || ""] as const)
    .filter((entry) => entry[1]);
  if (!entries.length) return null;
  const context = new window.AudioContext();
  if (context.state === "suspended") await context.resume();
  const ir = await loadIr(context);
  const buffers = await Promise.all(entries.map(async ([kind, url]) => [kind, await decodeStem(context, url, options?.windowSeconds ?? null)] as const));
  const ready = buffers.filter((row): row is readonly [string, AudioBuffer] => Boolean(row[1]));
  if (!ready.length) {
    await context.close();
    return null;
  }
  const master = context.createGain();
  const analyser = context.createAnalyser();
  analyser.fftSize = 2048;
  master.connect(analyser);
  analyser.connect(context.destination);
  const send = context.createGain();
  send.gain.value = 0;
  if (ir) {
    const convolver = context.createConvolver();
    convolver.buffer = ir;
    send.connect(convolver);
    convolver.connect(master);
  }
  type Voice = {
    kind: string;
    buffer: AudioBuffer;
    input: GainNode;
    gain: GainNode;
    panner: StereoPannerNode;
    meter: AnalyserNode;
    sendGain: GainNode;
    source: AudioBufferSourceNode | null;
    built: AudioNode[];
  };
  const voices: Voice[] = ready.map(([kind, buffer]) => {
    const input = context.createGain();
    const gain = context.createGain();
    const panner = context.createStereoPanner();
    const meter = context.createAnalyser();
    meter.fftSize = 256;
    const sendGain = context.createGain();
    sendGain.gain.value = 0;
    input.connect(gain);
    input.connect(sendGain);
    sendGain.connect(send);
    gain.connect(panner);
    panner.connect(meter);
    meter.connect(master);
    return { kind, buffer, input, gain, panner, meter, sendGain, source: null, built: [] };
  });
  const audio = new Audio();
  let offset = 0;
  let startedAt = 0;
  let playing = false;
  let loopSeconds = options?.windowSeconds ?? null;
  let trim = 1;
  const duration = Math.max(...voices.map((voice) => voice.buffer.duration));

  function stopSources() {
    if (playing) offset = currentOffset();
    playing = false;
    for (const voice of voices) {
      try {
        voice.source?.stop();
      } catch {
        /* already stopped */
      }
      try {
        voice.source?.disconnect();
      } catch {
        /* already disconnected */
      }
      voice.source = null;
    }
  }

  function currentOffset() {
    if (!playing) return offset;
    const elapsed = Math.max(0, context.currentTime - startedAt);
    const raw = offset + elapsed;
    if (loopSeconds && loopSeconds > 0) return raw % loopSeconds;
    return Math.min(raw, duration);
  }

  function startSources() {
    stopSources();
    const when = context.currentTime + 0.03;
    startedAt = when;
    for (const voice of voices) {
      const source = context.createBufferSource();
      source.buffer = voice.buffer;
      source.connect(voice.input);
      const at = Math.min(offset, Math.max(0, voice.buffer.duration - 0.05));
      if (loopSeconds && loopSeconds > 0) {
        source.loop = true;
        source.loopStart = 0;
        source.loopEnd = Math.min(loopSeconds, voice.buffer.duration);
      }
      source.start(when, at);
      voice.source = source;
    }
    playing = true;
  }

function samePart(kind: string, lane?: MixLane) {
  if (!lane) return false;
  const names = new Set([lane.kind, lane.id]);
  if (names.has(kind)) return true;
  const accompaniment = new Set(["accompaniment", "other"]);
  return accompaniment.has(kind) && [...names].some((name) => name && accompaniment.has(name));
}

function chainFor(kind: string, lanes: MixLane[], nodes: MixNode[], intensity: number) {
  const lane = lanes.find((row) => samePart(kind, row));
    const audibleLanes = audible(lanes).filter((row) => row.kind !== "master");
    const heard = !lane || audibleLanes.some((row) => row.id === lane.id || row.kind === lane.kind);
    const gain = heard ? Number(lane?.gain ?? 1) : 0;
    const stages: Stage[] = [];
    const wet = Math.max(0, Math.min(1.5, intensity || 1));
    let sendMix = 0;
    for (const node of nodes) {
      const aim = node.target || "master";
      if (aim === "master" || (!samePart(kind, { kind: aim, id: aim }) && aim !== lane?.id)) continue;
      if (fidelityOf(String(node.type || "")) === "render") continue;
      const params = node.params || {};
      if (node.type === "reverb") {
        sendMix = Math.max(sendMix, Number(params.mix || 0.2) * wet);
        continue;
      }
      if (node.type === "eq") {
        stages.push(peaking(context, EQ_HZ.low, EQ_Q.low, Number(params.low || 0) * wet));
        stages.push(peaking(context, EQ_HZ.mid, EQ_Q.mid, Number(params.mid || 0) * wet));
        stages.push(peaking(context, EQ_HZ.high, EQ_Q.high, Number(params.high || 0) * wet));
      } else if (node.type === "highpass") {
        stages.push(shelfPass(context, "highpass", Number(params.hz || 80)));
      } else if (node.type === "lowpass") {
        stages.push(shelfPass(context, "lowpass", Number(params.hz || 12000)));
      }
    }
    return { gain: Math.max(0, Math.min(2, gain)) * trim, pan: Number(lane?.pan || 0), stages, sendMix };
  }

  let lastLanes: MixLane[] = [];
  let lastNodes: MixNode[] = [];
  let lastIntensity = 1;

  function update(lanes: MixLane[], nodes: MixNode[], intensity: number) {
    lastLanes = lanes;
    lastNodes = nodes;
    lastIntensity = intensity;
    for (const voice of voices) {
      voice.built.forEach((node) => {
        try {
          node.disconnect();
        } catch {
          /* released */
        }
      });
      try {
        voice.input.disconnect();
      } catch {
        /* first connect */
      }
      const shaped = chainFor(voice.kind, lanes, nodes, intensity);
      voice.gain.gain.value = shaped.gain;
      voice.sendGain.gain.value = shaped.sendMix;
      voice.panner.pan.value = Math.max(-1, Math.min(1, shaped.pan));
      voice.built = [];
      voice.input.connect(voice.sendGain);
      let cursor: AudioNode = voice.input;
      for (const stage of shaped.stages) {
        cursor.connect(stage.input);
        cursor = stage.output;
        voice.built.push(stage.input, stage.output);
      }
      cursor.connect(voice.gain);
    }
  }

  update([], [], 1);
  return {
    context,
    audio,
    analyser,
    stemKey: entries.map((entry) => entry[0]).join(","),
    setLoopSeconds(seconds) {
      loopSeconds = seconds;
      if (playing) startSources();
    },
    setTrim(value) {
      trim = Math.max(0.25, Math.min(4, value));
      update(lastLanes, lastNodes, lastIntensity);
    },
    update,
    readLanePeaks() {
      const peaks: Record<string, number> = {};
      for (const voice of voices) peaks[voice.kind] = readPeak(voice.meter);
      return peaks;
    },
    async play() {
      if (context.state === "suspended") await context.resume();
      startSources();
    },
    pause() {
      stopSources();
    },
    seekTo(seconds) {
      offset = Math.max(0, Math.min(duration, seconds));
      if (playing) startSources();
    },
    getTime: () => currentOffset(),
    getDuration: () => duration,
    close() {
      stopSources();
      void context.close();
    },
  };
}

export function readPeak(analyser: AnalyserNode) {
  const data = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(data);
  let peak = 0;
  for (let i = 0; i < data.length; i += 8) {
    const sample = Math.abs(data[i] - 128) / 128;
    if (sample > peak) peak = sample;
  }
  return peak;
}
