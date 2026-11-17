/** 24-bit PCM WAV. The server turns this into the delivery master. */
export function audioBufferToWav24(buffer: AudioBuffer): Blob {
  const channels = Math.min(2, buffer.numberOfChannels);
  const frames = buffer.length;
  const bytesPerSample = 3;
  const block = channels * bytesPerSample;
  const dataSize = frames * block;
  const out = new ArrayBuffer(44 + dataSize);
  const view = new DataView(out);
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * block, true);
  view.setUint16(32, block, true);
  view.setUint16(34, 24, true);
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);
  const data = [buffer.getChannelData(0), channels > 1 ? buffer.getChannelData(1) : buffer.getChannelData(0)];
  let offset = 44;
  for (let i = 0; i < frames; i++) {
    for (let ch = 0; ch < channels; ch++) {
      const sample = Math.max(-1, Math.min(1, data[ch][i] || 0));
      const int = sample < 0 ? Math.round(sample * 0x800000) : Math.round(sample * 0x7fffff);
      view.setUint8(offset, int & 0xff);
      view.setUint8(offset + 1, (int >> 8) & 0xff);
      view.setUint8(offset + 2, (int >> 16) & 0xff);
      offset += 3;
    }
  }
  return new Blob([out], { type: "audio/wav" });
}

function writeString(view: DataView, offset: number, text: string) {
  for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
}
