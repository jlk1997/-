class DynamicsProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.env = 0;
    this.gr = 0;
    this.block = 0;
    this.p = {
      bypass: 0,
      threshold: -18,
      ratio: 2,
      attack: 0.01,
      release: 0.12,
      knee: 6,
      makeup: 0,
      gate: -70,
      deess: 0,
      ceiling: -1,
    };
    this.port.onmessage = (event) => {
      if (event.data && typeof event.data === "object") Object.assign(this.p, event.data);
    };
  }

  process(inputs, outputs) {
    const input = inputs[0];
    const output = outputs[0];
    if (!input || !input[0] || !output || !output[0]) return true;
    const attack = Math.exp(-1 / (Math.max(0.001, this.p.attack) * sampleRate));
    const release = Math.exp(-1 / (Math.max(0.01, this.p.release) * sampleRate));
    const ceiling = Math.pow(10, this.p.ceiling / 20);
    let peakGr = 0;
    for (let i = 0; i < input[0].length; i++) {
      let peak = 0;
      for (let ch = 0; ch < input.length; ch++) peak = Math.max(peak, Math.abs(input[ch][i] || 0));
      const db = peak > 0.00001 ? 20 * Math.log10(peak) : -100;
      this.env = db > this.env ? attack * this.env + (1 - attack) * db : release * this.env + (1 - release) * db;
      let gainDb = 0;
      if (this.env < this.p.gate) gainDb -= 40;
      const over = this.env - this.p.threshold;
      if (over > 0 && this.p.ratio > 1) {
        const knee = Math.max(0, this.p.knee);
        const excess = over < knee ? (over * over) / (knee * 2 || 1) : over - knee / 2;
        gainDb -= excess * (1 - 1 / this.p.ratio);
      }
      if (this.p.deess > 0 && this.env > this.p.threshold + 2) gainDb -= this.p.deess * 4;
      gainDb += this.p.makeup;
      peakGr = Math.min(peakGr, gainDb);
      const gain = this.p.bypass ? 1 : Math.pow(10, gainDb / 20);
      for (let ch = 0; ch < output.length; ch++) {
        const src = input[ch] ? input[ch][i] : input[0][i];
        let sample = src * gain;
        if (!this.p.bypass && this.p.ceiling < 0 && Math.abs(sample) > ceiling) {
          sample = Math.sign(sample) * ceiling;
        }
        output[ch][i] = sample;
      }
    }
    this.gr = peakGr;
    this.block += 1;
    if (this.block % 8 === 0) this.port.postMessage({ gr: this.gr });
    return true;
  }
}

registerProcessor("bittune-dynamics", DynamicsProcessor);
