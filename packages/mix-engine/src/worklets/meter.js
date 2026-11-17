class MeterProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = 0;
    this.momentary = [];
    this.shortTerm = [];
    this.integrated = [];
    this.hp = { x1: 0, x2: 0, y1: 0, y2: 0 };
    this.hs = { x1: 0, x2: 0, y1: 0, y2: 0 };
  }

  kWeight(sample) {
    const sr = sampleRate;
    const hp = this.biquad(this.hp, sample, { type: "highpass", freq: 60, q: 0.5, gain: 0, sr });
    return this.biquad(this.hs, hp, { type: "highshelf", freq: 1500, q: 0.7, gain: 4, sr });
  }

  biquad(state, x0, spec) {
    const w0 = (2 * Math.PI * spec.freq) / spec.sr;
    const cos = Math.cos(w0);
    const sin = Math.sin(w0);
    const alpha = sin / (2 * spec.q);
    let b0 = 1;
    let b1 = 0;
    let b2 = 0;
    let a0 = 1;
    let a1 = 0;
    let a2 = 0;
    if (spec.type === "highpass") {
      b0 = (1 + cos) / 2;
      b1 = -(1 + cos);
      b2 = (1 + cos) / 2;
      a0 = 1 + alpha;
      a1 = -2 * cos;
      a2 = 1 - alpha;
    } else {
      const A = Math.pow(10, spec.gain / 40);
      b0 = A * (A + 1 + (A - 1) * cos + 2 * Math.sqrt(A) * alpha);
      b1 = -2 * A * (A - 1 + (A + 1) * cos);
      b2 = A * (A + 1 + (A - 1) * cos - 2 * Math.sqrt(A) * alpha);
      a0 = A + 1 - (A - 1) * cos + 2 * Math.sqrt(A) * alpha;
      a1 = 2 * (A - 1 - (A + 1) * cos);
      a2 = A + 1 - (A - 1) * cos - 2 * Math.sqrt(A) * alpha;
    }
    const y0 = (b0 / a0) * x0 + (b1 / a0) * state.x1 + (b2 / a0) * state.x2 - (a1 / a0) * state.y1 - (a2 / a0) * state.y2;
    state.x2 = state.x1;
    state.x1 = x0;
    state.y2 = state.y1;
    state.y1 = y0;
    return y0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    let peak = 0;
    let sum = 0;
    let weighted = 0;
    const n = input[0].length;
    for (let i = 0; i < n; i++) {
      let p = 0;
      let mono = 0;
      for (let ch = 0; ch < input.length; ch++) {
        const sample = input[ch][i] || 0;
        p = Math.max(p, Math.abs(sample));
        mono += sample;
      }
      mono /= input.length;
      peak = Math.max(peak, p);
      sum += mono * mono;
      const w = this.kWeight(mono);
      weighted += w * w;
    }
    const rms = Math.sqrt(sum / n);
    const power = weighted / n;
    this.momentary.push(power);
    this.shortTerm.push(power);
    const momentaryBlocks = Math.max(1, Math.round((0.4 * sampleRate) / n));
    const shortBlocks = Math.max(1, Math.round((3 * sampleRate) / n));
    if (this.momentary.length > momentaryBlocks) this.momentary.shift();
    if (this.shortTerm.length > shortBlocks) this.shortTerm.shift();
    this.block += 1;
    if (this.block % 8 !== 0) return true;
    const mean = (list) => list.reduce((acc, value) => acc + value, 0) / list.length;
    const toLufs = (value) => (value > 1e-12 ? -0.691 + 10 * Math.log10(value) : -70);
    const momentary = toLufs(mean(this.momentary));
    if (momentary > -70) this.integrated.push(momentary);
    if (this.integrated.length > 4000) this.integrated.shift();
    const gated = this.integrated.filter((value) => value > -70);
    const ungated = gated.length ? gated.reduce((acc, value) => acc + value, 0) / gated.length : -70;
    const relative = gated.filter((value) => value > ungated - 10);
    const integrated = relative.length ? relative.reduce((acc, value) => acc + value, 0) / relative.length : ungated;
    this.port.postMessage({
      peak: peak > 0.00001 ? 20 * Math.log10(peak) : -70,
      rms: rms > 0.00001 ? 20 * Math.log10(rms) : -70,
      momentary,
      shortTerm: toLufs(mean(this.shortTerm)),
      integrated,
      truePeak: peak > 0.00001 ? 20 * Math.log10(peak) : -70,
    });
    return true;
  }
}

registerProcessor("bittune-meter", MeterProcessor);
