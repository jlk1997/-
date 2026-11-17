import type { EqBand, MixBus, MixChannel, MixDocument, MixInsert } from "@vibe-sorcery/types";
import { dbToGain } from "./law";

export type MeterReading = { peak: number; rms: number; hold: number; gr: number };
export type LoudnessReading = { momentary: number; shortTerm: number; integrated: number; truePeak: number };

type Strip = {
  input: GainNode;
  eq: BiquadFilterNode[];
  dynamics: AudioWorkletNode | DynamicsCompressorNode;
  sendReverb: GainNode;
  sendDelay: GainNode;
  panner: StereoPannerNode;
  fader: GainNode;
  analyser: AnalyserNode;
  output: GainNode;
};

const dynamicsUrl = new URL("./worklets/dynamics.js", import.meta.url);
const meterUrl = new URL("./worklets/meter.js", import.meta.url);

export class MixEngine {
  private ctx: AudioContext | null = null;
  private offline = false;
  private doc: MixDocument | null = null;
  private strips = new Map<string, Strip>();
  private buses = new Map<string, { input: GainNode; fader: GainNode; convolver?: ConvolverNode; delay?: DelayNode }>();
  private masterIn: GainNode | null = null;
  private masterMeter: AudioWorkletNode | AnalyserNode | null = null;
  private sources: AudioBufferSourceNode[] = [];
  private buffers = new Map<string, AudioBuffer>();
  private peakCache = new Map<string, Float32Array>();
  private spectrumRaw = new Uint8Array(512);
  private meterScratch = new Float32Array(2048);
  private compare = false;
  private listen: "mix" | "forward" | "bed" | "original" = "mix";
  private startedAt = 0;
  private offset = 0;
  private playing = false;
  private workletsReady = false;
  readonly meters = new Map<string, MeterReading>();
  loudness: LoudnessReading = { momentary: -70, shortTerm: -70, integrated: -70, truePeak: -70 };

  async resume(): Promise<void> {
    const ctx = await this.context();
    if (ctx.state !== "running") await ctx.resume();
  }

  async context(): Promise<AudioContext> {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      await this.prepareWorklets(this.ctx);
    }
    return this.ctx;
  }

  setDocument(doc: MixDocument) {
    const wasPlaying = this.playing;
    const at = this.position();
    this.stopSources();
    this.playing = false;
    this.doc = doc;
    if (this.ctx) this.build(this.ctx, doc);
    this.offset = at;
    if (wasPlaying) void this.play();
  }

  /** Move faders, pans, sends and plugin knobs without tearing down the graph. */
  sync(doc: MixDocument) {
    this.doc = doc;
    for (const channel of doc.channels) {
      this.setInput(channel.id, channel.inputGain);
      if (channel.automationMode !== "read") this.setFader(channel.id, channel.faderDb);
      this.setPan(channel.id, channel.pan);
      for (const send of channel.sends) this.setSend(channel.id, send.bus, send.level);
      for (const insert of channel.inserts) this.setInsert(channel.id, insert, doc.tempo.bpm);
    }
    for (const bus of doc.buses) this.setFader(bus.id, bus.faderDb);
    this.applyAudibility(doc);
    const delay = this.buses.get("aux-delay")?.delay;
    const delayInsert = doc.buses.find((bus) => bus.id === "aux-delay")?.inserts.find((insert) => insert.type === "delay");
    if (delay) {
      const division = Number(delayInsert?.params.sync ?? 0.5);
      delay.delayTime.value = (60 / Math.max(40, doc.tempo.bpm)) * division;
    }
  }

  /** Read automation and region fades at the playhead. Fader drags stay live while automation is Off. */
  follow(time: number) {
    const doc = this.doc;
    if (!doc) return;
    if (this.playing && doc.loop.enabled && doc.loop.end > doc.loop.start && time >= doc.loop.end) {
      this.seek(doc.loop.start);
      return;
    }
    const anyoneSolo = doc.channels.some((channel) => channel.solo);
    for (const channel of doc.channels) {
      const strip = this.strips.get(channel.id);
      if (!strip) continue;
      if (channel.automationMode === "read" && this.listen !== "original") {
        if (channel.automation.volume.length >= 2) this.setFader(channel.id, sampleCurve(channel.automation.volume, time));
        if (channel.automation.pan.length >= 2) this.setPan(channel.id, samplePan(channel.automation.pan, time));
      }
      const audible = !channel.mute && (!anyoneSolo || channel.solo);
      const regions = doc.regions.filter((region) => region.channel === channel.id);
      strip.output.gain.value = listenGain(this.listen, channel.kind, channel.id, audible ? regionLevel(regions, time) : 0);
    }
  }

  async loadBuffer(channelId: string, url: string): Promise<void> {
    const ctx = await this.context();
    const response = await fetch(url);
    if (!response.ok) throw new Error("stem_fetch_failed");
    const audio = await ctx.decodeAudioData(await response.arrayBuffer());
    this.buffers.set(channelId, audio);
    this.peakCache.delete(channelId);
  }

  /** Min-max peaks for the arrange. Computed once per loaded buffer. */
  peaks(channelId: string, buckets = 960): Float32Array | null {
    const buffer = this.buffers.get(channelId);
    if (!buffer) return null;
    const cached = this.peakCache.get(channelId);
    if (cached && cached.length === buckets) return cached;
    const data = buffer.getChannelData(0);
    const peaks = new Float32Array(buckets);
    const size = Math.max(1, Math.floor(data.length / buckets));
    for (let i = 0; i < buckets; i++) {
      let peak = 0;
      const start = i * size;
      const end = Math.min(data.length, start + size);
      for (let j = start; j < end; j += 4) peak = Math.max(peak, Math.abs(data[j] || 0));
      peaks[i] = peak;
    }
    this.peakCache.set(channelId, peaks);
    return peaks;
  }

  /** Post-fader frequency bins, 0–255. The returned buffer is reused on the next call. */
  spectrum(channelId: string): Uint8Array | null {
    const analyser = this.strips.get(channelId)?.analyser;
    if (!analyser) return null;
    if (this.spectrumRaw.length !== analyser.frequencyBinCount) {
      this.spectrumRaw = new Uint8Array(analyser.frequencyBinCount);
    }
    analyser.getByteFrequencyData(this.spectrumRaw);
    return this.spectrumRaw;
  }

  sampleRate(): number {
    return this.ctx?.sampleRate ?? 48000;
  }

  setCompare(on: boolean) {
    this.setListen(on ? "original" : "mix");
  }

  setListen(mode: "mix" | "forward" | "bed" | "original") {
    this.listen = mode;
    this.compare = mode === "original";
  }

  isCompare() {
    return this.compare;
  }

  bufferFor(channelId: string): AudioBuffer | undefined {
    return this.buffers.get(channelId);
  }

  duration(): number {
    let max = 0;
    for (const buffer of this.buffers.values()) max = Math.max(max, buffer.duration);
    return max;
  }

  position(): number {
    if (!this.playing || !this.ctx) return this.offset;
    return this.offset + (this.ctx.currentTime - this.startedAt);
  }

  isPlaying(): boolean {
    return this.playing;
  }

  async play(): Promise<void> {
    const ctx = await this.context();
    if (!this.doc) return;
    await this.resume();
    this.stopSources();
    const start = this.offset;
    for (const channel of this.doc.channels) {
      const buffer = this.buffers.get(channel.id);
      const strip = this.strips.get(channel.id);
      if (!buffer || !strip) continue;
      const clips = this.doc.regions.filter((region) => region.channel === channel.id);
      this.scheduleBuffer(ctx, strip, buffer, clips, start, ctx.currentTime);
    }
    this.startedAt = ctx.currentTime;
    this.playing = true;
  }

  stop() {
    this.offset = this.playing ? this.position() : this.offset;
    this.stopSources();
    this.playing = false;
  }

  seek(seconds: number) {
    this.offset = Math.max(0, seconds);
    if (this.ctx) this.startedAt = this.ctx.currentTime;
    if (this.playing) void this.play();
  }

  restart() {
    this.offset = 0;
    if (this.playing) void this.play();
  }

  setFader(id: string, db: number) {
    const strip = this.strips.get(id);
    if (strip) {
      strip.fader.gain.value = dbToGain(db);
      return;
    }
    const bus = this.busFader(id);
    if (bus) bus.gain.value = dbToGain(db);
  }

  setInput(id: string, db: number) {
    const strip = this.strips.get(id);
    if (strip) strip.input.gain.value = dbToGain(db);
  }

  setPan(id: string, pan: number) {
    const strip = this.strips.get(id);
    if (strip) strip.panner.pan.value = pan;
  }

  setSend(id: string, bus: "aux-reverb" | "aux-delay", level: number) {
    const strip = this.strips.get(id);
    if (!strip) return;
    const node = bus === "aux-reverb" ? strip.sendReverb : strip.sendDelay;
    node.gain.value = level;
  }

  applyAudibility(doc: MixDocument) {
    const anyoneSolo = doc.channels.some((channel) => channel.solo);
    for (const channel of doc.channels) {
      const strip = this.strips.get(channel.id);
      if (!strip) continue;
      const audible = !channel.mute && (!anyoneSolo || channel.solo);
      strip.output.gain.value = audible ? 1 : 0;
    }
  }

  setInsert(channelId: string, insert: MixInsert, bpm = 120) {
    const strip = this.strips.get(channelId);
    if (!strip) return;
    if (insert.type === "eq") this.applyEq(strip.eq, insert);
    if (insert.type === "compressor" || insert.type === "gate" || insert.type === "deesser" || insert.type === "limiter") {
      this.applyDynamics(strip.dynamics, insert);
    }
    if (insert.type === "delay") this.applyDelay(insert, bpm);
  }

  sampleMeters() {
    for (const [id, strip] of this.strips) {
      const reading = this.meters.get(id) || { peak: -70, rms: -70, hold: -70, gr: 0 };
      const size = strip.analyser.fftSize;
      if (this.meterScratch.length < size) this.meterScratch = new Float32Array(size);
      const data = this.meterScratch.subarray(0, size);
      strip.analyser.getFloatTimeDomainData(data);
      let peak = 0;
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const value = Math.abs(data[i]);
        peak = Math.max(peak, value);
        sum += data[i] * data[i];
      }
      const peakDb = peak > 0.00001 ? 20 * Math.log10(peak) : -70;
      const rms = Math.sqrt(sum / data.length);
      const rmsDb = rms > 0.00001 ? 20 * Math.log10(rms) : -70;
      reading.peak = peakDb;
      reading.rms = rmsDb;
      reading.hold = Math.max(peakDb, reading.hold - 0.4);
      this.meters.set(id, reading);
    }
  }

  async bounce(doc: MixDocument, start = 0, end?: number): Promise<AudioBuffer> {
    const wasPlaying = this.playing;
    const at = this.position();
    this.stop();
    const live = await this.context();
    const length = Math.max(0.1, (end ?? this.duration()) - start);
    const offline = new OfflineAudioContext(2, Math.ceil(length * live.sampleRate), live.sampleRate);
    await this.prepareWorklets(offline);
    this.build(offline, doc);
    const bounceEnd = start + length;
    for (const channel of doc.channels) {
      const buffer = this.buffers.get(channel.id);
      const strip = this.strips.get(channel.id);
      if (!buffer || !strip) continue;
      const clips = doc.regions.filter((region) => region.channel === channel.id);
      this.scheduleBuffer(offline, strip, buffer, clips, start, 0, bounceEnd);
    }
    const rendered = await offline.startRendering();
    this.sources = [];
    if (this.ctx) this.build(this.ctx, doc);
    this.doc = doc;
    this.offset = at;
    this.playing = false;
    if (wasPlaying) await this.play();
    return rendered;
  }

  dispose() {
    this.stopSources();
    void this.ctx?.close();
    this.ctx = null;
  }

  /** Each clip carries its own audio. Moving it on the timeline moves the sound. */
  private scheduleBuffer(
    ctx: BaseAudioContext,
    strip: Strip,
    buffer: AudioBuffer,
    regions: MixDocument["regions"],
    transportStart: number,
    whenBase: number,
    transportEnd?: number,
  ) {
    const clips = regions.length
      ? regions
      : [{ id: "all", channel: "", start: 0, end: buffer.duration, offset: 0, fadeIn: 0, fadeOut: 0, mute: false }];
    const limit = transportEnd ?? Number.POSITIVE_INFINITY;
    for (const region of clips) {
      if (region.mute || region.end <= transportStart || region.start >= limit) continue;
      const visibleStart = Math.max(region.start, transportStart);
      const visibleEnd = Math.min(region.end, limit);
      const duration = visibleEnd - visibleStart;
      const offset = region.offset + (visibleStart - region.start);
      if (duration <= 0.01 || offset >= buffer.duration - 0.01) continue;
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(strip.input);
      source.start(whenBase + (visibleStart - transportStart), Math.max(0, offset), Math.min(duration, buffer.duration - Math.max(0, offset)));
      this.sources.push(source);
    }
  }

  private busFader(id: string): GainNode | null {
    return this.buses.get(id)?.fader || null;
  }

  private stopSources() {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
      source.disconnect();
    }
    this.sources = [];
  }

  private async prepareWorklets(ctx: BaseAudioContext) {
    if (this.workletsReady || !ctx.audioWorklet) return;
    try {
      await ctx.audioWorklet.addModule(dynamicsUrl);
      await ctx.audioWorklet.addModule(meterUrl);
      this.workletsReady = true;
    } catch {
      this.workletsReady = false;
    }
  }

  private build(ctx: BaseAudioContext, doc: MixDocument) {
    this.strips.forEach((strip) => strip.input.disconnect());
    this.buses.clear();
    this.strips.clear();
    const masterIn = ctx.createGain();
    const reverbIn = ctx.createGain();
    const delayIn = ctx.createGain();
    this.buses.set("aux-reverb", this.buildReverb(ctx, doc, reverbIn, masterIn));
    this.buses.set("aux-delay", this.buildDelay(ctx, doc, delayIn, masterIn));
    for (const channel of doc.channels) {
      this.strips.set(channel.id, this.buildStrip(ctx, channel, masterIn, reverbIn, delayIn, doc.tempo.bpm));
    }
    const master = doc.buses.find((bus) => bus.id === "master");
    const masterFader = ctx.createGain();
    masterFader.gain.value = dbToGain(master?.faderDb ?? 0);
    masterIn.connect(masterFader);
    this.masterMeter = this.makeMeter(ctx);
    masterFader.connect(this.masterMeter);
    this.masterMeter.connect(ctx.destination);
    this.masterIn = masterIn;
    this.buses.set("master", { input: masterIn, fader: masterFader });
    this.applyAudibility(doc);
  }

  private buildStrip(
    ctx: BaseAudioContext,
    channel: MixChannel,
    masterIn: GainNode,
    reverbIn: GainNode,
    delayIn: GainNode,
    bpm: number,
  ): Strip {
    const input = ctx.createGain();
    input.gain.value = dbToGain(channel.inputGain);
    const eq = this.makeEq(ctx, channel.inserts.find((insert) => insert.type === "eq"));
    let previous: AudioNode = input;
    for (const filter of eq) {
      previous.connect(filter);
      previous = filter;
    }
    const dynamics = this.makeDynamics(ctx, channel.inserts);
    previous.connect(dynamics);
    const sendReverb = ctx.createGain();
    const sendDelay = ctx.createGain();
    sendReverb.gain.value = channel.sends.find((send) => send.bus === "aux-reverb")?.level ?? 0;
    sendDelay.gain.value = channel.sends.find((send) => send.bus === "aux-delay")?.level ?? 0;
    dynamics.connect(sendReverb);
    dynamics.connect(sendDelay);
    sendReverb.connect(reverbIn);
    sendDelay.connect(delayIn);
    const panner = ctx.createStereoPanner();
    panner.pan.value = channel.pan;
    const fader = ctx.createGain();
    fader.gain.value = dbToGain(channel.faderDb);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    const output = ctx.createGain();
    dynamics.connect(panner);
    panner.connect(fader);
    fader.connect(analyser);
    analyser.connect(output);
    output.connect(masterIn);
    const widen = channel.inserts.find((insert) => insert.type === "widen");
    if (widen) this.applyDelay(widen, bpm);
    return { input, eq, dynamics, sendReverb, sendDelay, panner, fader, analyser, output };
  }

  private makeEq(ctx: BaseAudioContext, insert?: MixInsert): BiquadFilterNode[] {
    const bands = (insert?.params.bands as EqBand[] | undefined) || [];
    const filters = bands.map((band) => {
      const filter = ctx.createBiquadFilter();
      this.tuneBand(filter, band, Boolean(insert?.bypass));
      return filter;
    });
    return filters.length ? filters : [ctx.createBiquadFilter()];
  }

  private tuneBand(filter: BiquadFilterNode, band: EqBand, bypass: boolean) {
    const map: Record<EqBand["type"], BiquadFilterType> = {
      highpass: "highpass",
      lowshelf: "lowshelf",
      bell: "peaking",
      highshelf: "highshelf",
      lowpass: "lowpass",
    };
    filter.type = map[band.type] || "peaking";
    filter.frequency.value = band.freq;
    filter.Q.value = band.q;
    filter.gain.value = bypass || !band.enabled ? 0 : band.gain;
  }

  private applyEq(filters: BiquadFilterNode[], insert: MixInsert) {
    const bands = (insert.params.bands as EqBand[] | undefined) || [];
    bands.forEach((band, index) => {
      const filter = filters[index];
      if (filter) this.tuneBand(filter, band, insert.bypass);
    });
  }

  private makeDynamics(ctx: BaseAudioContext, inserts: MixInsert[]): AudioWorkletNode | DynamicsCompressorNode {
    const comp = inserts.find((insert) => insert.type === "compressor");
    if (ctx.audioWorklet && this.workletsReady) {
      try {
        const node = new AudioWorkletNode(ctx, "bittune-dynamics");
        node.port.onmessage = (event) => {
          const id = inserts[0] ? "dyn" : "dyn";
          void id;
          const reading = this.meters.get("master-gr") || { peak: -70, rms: -70, hold: -70, gr: 0 };
          reading.gr = Number(event.data?.gr || 0);
          this.meters.set("dynamics", reading);
        };
        this.pushDynamics(node, inserts);
        return node;
      } catch {
        /* fall through */
      }
    }
    const fallback = ctx.createDynamicsCompressor();
    fallback.threshold.value = Number(comp?.params.threshold ?? -18);
    fallback.ratio.value = Number(comp?.params.ratio ?? 2);
    fallback.attack.value = Number(comp?.params.attack ?? 0.01);
    fallback.release.value = Number(comp?.params.release ?? 0.12);
    fallback.knee.value = Number(comp?.params.knee ?? 6);
    return fallback;
  }

  private applyDynamics(node: AudioWorkletNode | DynamicsCompressorNode, insert: MixInsert) {
    if (node instanceof DynamicsCompressorNode) {
      if (insert.type !== "compressor") return;
      node.threshold.value = Number(insert.params.threshold ?? -18);
      node.ratio.value = Number(insert.params.ratio ?? 2);
      return;
    }
    this.pushDynamics(node, [insert]);
  }

  private pushDynamics(node: AudioWorkletNode, inserts: MixInsert[]) {
    const comp = inserts.find((insert) => insert.type === "compressor");
    const gate = inserts.find((insert) => insert.type === "gate");
    const deess = inserts.find((insert) => insert.type === "deesser");
    const limiter = inserts.find((insert) => insert.type === "limiter");
    node.port.postMessage({
      bypass: comp?.bypass && gate?.bypass ? 1 : 0,
      threshold: Number(comp?.params.threshold ?? -24),
      ratio: Number(comp?.params.ratio ?? 1.5),
      attack: Number(comp?.params.attack ?? 0.01),
      release: Number(comp?.params.release ?? 0.12),
      knee: Number(comp?.params.knee ?? 6),
      makeup: Number(comp?.params.makeup ?? 0),
      gate: gate && !gate.bypass ? Number(gate.params.threshold ?? -50) : -80,
      deess: deess && !deess.bypass ? Number(deess.params.amount ?? 0.4) : 0,
      ceiling: limiter && !limiter.bypass ? Number(limiter.params.ceiling ?? -1) : 0,
    });
  }

  private buildReverb(ctx: BaseAudioContext, doc: MixDocument, input: GainNode, master: GainNode) {
    const bus = doc.buses.find((item) => item.id === "aux-reverb");
    const insert = bus?.inserts.find((item) => item.type === "reverb");
    const convolver = ctx.createConvolver();
    convolver.buffer = impulse(ctx, Number(insert?.params.decay ?? 1.6));
    const fader = ctx.createGain();
    fader.gain.value = dbToGain(bus?.faderDb ?? 0);
    input.connect(convolver);
    convolver.connect(fader);
    fader.connect(master);
    return { input, fader, convolver };
  }

  private buildDelay(ctx: BaseAudioContext, doc: MixDocument, input: GainNode, master: GainNode) {
    const bus = doc.buses.find((item) => item.id === "aux-delay");
    const insert = bus?.inserts.find((item) => item.type === "delay");
    const delay = ctx.createDelay(2);
    const sync = Number(insert?.params.sync ?? 0.5);
    delay.delayTime.value = (60 / Math.max(40, doc.tempo.bpm)) * sync;
    const feedback = ctx.createGain();
    feedback.gain.value = Number(insert?.params.feedback ?? 0.35);
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = Number(insert?.params.cutoff ?? 6000);
    const fader = ctx.createGain();
    fader.gain.value = dbToGain(bus?.faderDb ?? 0);
    input.connect(delay);
    delay.connect(filter);
    filter.connect(feedback);
    feedback.connect(delay);
    filter.connect(fader);
    fader.connect(master);
    return { input, fader, delay };
  }

  private applyDelay(insert: MixInsert, bpm: number) {
    const bus = this.buses.get("aux-delay");
    if (!bus?.delay) return;
    const sync = Number(insert.params.sync ?? 0.5);
    bus.delay.delayTime.value = (60 / Math.max(40, bpm)) * sync;
  }

  private makeMeter(ctx: BaseAudioContext): AudioWorkletNode | AnalyserNode {
    if (ctx.audioWorklet && this.workletsReady) {
      try {
        const node = new AudioWorkletNode(ctx, "bittune-meter");
        node.port.onmessage = (event) => {
          const data = event.data || {};
          this.loudness = {
            momentary: Number(data.momentary ?? -70),
            shortTerm: Number(data.shortTerm ?? -70),
            integrated: Number(data.integrated ?? -70),
            truePeak: Number(data.truePeak ?? -70),
          };
          this.meters.set("master", {
            peak: this.loudness.truePeak,
            rms: this.loudness.shortTerm,
            hold: this.loudness.truePeak,
            gr: this.meters.get("dynamics")?.gr || 0,
          });
        };
        return node;
      } catch {
        /* analyser fallback */
      }
    }
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    return analyser;
  }
}

function listenGain(mode: "mix" | "forward" | "bed" | "original", kind: string, id: string, level: number): number {
  const vocal = kind === "vocal" || id === "vocal";
  const reference = kind === "reference" || id === "reference";
  if (mode === "original") return reference ? 1 : 0;
  if (mode === "bed") return vocal || reference ? 0 : level;
  if (mode === "forward") {
    if (reference) return 0;
    if (vocal) return level * dbToGain(4);
    return level * dbToGain(-6);
  }
  return level;
}

function samplePan(points: Array<{ t: number; pan: number }>, time: number): number {
  return sampleCurve(points.map((point) => ({ t: point.t, db: point.pan })), time);
}

function sampleCurve(points: Array<{ t: number; db: number }>, time: number): number {
  const sorted = [...points].sort((a, b) => a.t - b.t);
  if (time <= sorted[0].t) return sorted[0].db;
  const last = sorted[sorted.length - 1];
  if (time >= last.t) return last.db;
  for (let i = 1; i < sorted.length; i++) {
    const right = sorted[i];
    const left = sorted[i - 1];
    if (time <= right.t) {
      const span = Math.max(0.0001, right.t - left.t);
      const mix = (time - left.t) / span;
      return left.db + (right.db - left.db) * mix;
    }
  }
  return last.db;
}

function regionLevel(regions: MixDocument["regions"], time: number): number {
  if (!regions.length) return 1;
  const hit = regions.find((region) => time >= region.start && time < region.end);
  if (!hit || hit.mute) return 0;
  const into = time - hit.start;
  const left = hit.end - time;
  let level = 1;
  if (hit.fadeIn > 0) level = Math.min(level, into / hit.fadeIn);
  if (hit.fadeOut > 0) level = Math.min(level, left / hit.fadeOut);
  return Math.max(0, Math.min(1, level));
}

function impulse(ctx: BaseAudioContext, seconds: number): AudioBuffer {
  const length = Math.max(1, Math.floor(ctx.sampleRate * Math.max(0.2, Math.min(6, seconds))));
  const buffer = ctx.createBuffer(2, length, ctx.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const data = buffer.getChannelData(ch);
    for (let i = 0; i < length; i++) {
      const env = Math.pow(1 - i / length, 2.4);
      data[i] = (Math.random() * 2 - 1) * env * (ch === 0 ? 1 : 0.85);
    }
  }
  return buffer;
}

export function eqCurve(bands: EqBand[], width = 240, height = 80): string {
  const points: string[] = [];
  for (let x = 0; x <= width; x += 2) {
    const freq = 20 * Math.pow(1000, x / width);
    let db = 0;
    for (const band of bands) {
      if (!band.enabled) continue;
      const ratio = Math.log(freq / band.freq);
      const widthQ = 1 / Math.max(0.2, band.q);
      db += band.gain * Math.exp(-(ratio * ratio) / (2 * widthQ * widthQ));
    }
    const y = height / 2 - (db / 24) * (height / 2);
    points.push(`${x},${Math.max(0, Math.min(height, y))}`);
  }
  return points.join(" ");
}

export type { MixBus };
