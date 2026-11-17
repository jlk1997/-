import { useEffect, useMemo } from "react";
import { Canvas, Image, View } from "@tarojs/components";
import Taro from "@tarojs/taro";

function hashSeed(value: string) {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) hash = Math.imul(hash ^ value.charCodeAt(i), 16777619);
  return hash >>> 0;
}

function peakAmps(seed: string, count: number) {
  let cursor = hashSeed(seed);
  const bars: number[] = [];
  for (let i = 0; i < count; i += 1) {
    cursor = (cursor * 1664525 + 1013904223) >>> 0;
    const envelope = 0.28 + 0.72 * Math.abs(Math.sin((i / count) * Math.PI));
    bars.push(0.14 + ((cursor % 1000) / 1000) * 0.86 * envelope);
  }
  return bars;
}

export function LaneWaveform({
  laneId,
  laneKind,
  duration,
  waveformUrl,
}: {
  laneId: string;
  laneKind: string;
  duration: number;
  waveformUrl?: string;
}) {
  const canvasId = `wb-wave-${laneId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const usePhoto = laneKind === "master" && Boolean(waveformUrl);
  const bars = useMemo(() => peakAmps(`${laneId}-${laneKind}-${Math.round(duration)}`, 56), [duration, laneId, laneKind]);

  useEffect(() => {
    if (process.env.TARO_ENV !== "h5" || usePhoto) return undefined;
    const timer = setTimeout(() => {
      Taro.createSelectorQuery()
        .select(`#${canvasId}`)
        .fields({ node: true, size: true })
        .exec((res) => {
          const node = res?.[0]?.node as HTMLCanvasElement | undefined;
          const width = Number(res?.[0]?.width || 0);
          const height = Number(res?.[0]?.height || 0);
          if (!node || !width || !height) return;
          const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
          node.width = Math.round(width * dpr);
          node.height = Math.round(height * dpr);
          const ctx = node.getContext("2d");
          if (!ctx) return;
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, width, height);
          const gap = 1;
          const bw = Math.max(1, width / bars.length - gap);
          ctx.fillStyle = laneKind === "master" ? "rgba(212,175,106,0.78)" : "rgba(20,184,166,0.55)";
          bars.forEach((amp, index) => {
            const h = Math.max(2, amp * height * 0.9);
            ctx.fillRect(index * (bw + gap), (height - h) / 2, bw, h);
          });
        });
    }, 40);
    return () => clearTimeout(timer);
  }, [bars, canvasId, laneKind, usePhoto]);

  if (usePhoto && waveformUrl) {
    return <Image className="wb-timeline__wave" src={waveformUrl} mode="scaleToFill" />;
  }

  return (
    <View className="wb-timeline__wave-wrap">
      <View className="wb-timeline__peaks" aria-hidden>
        {bars.map((amp, index) => (
          <View key={`${laneId}-${index}`} className={`wb-timeline__peak${laneKind === "master" ? " is-master" : ""}`} style={{ height: `${Math.round(amp * 100)}%` }} />
        ))}
      </View>
      {process.env.TARO_ENV === "h5" ? <Canvas type="2d" id={canvasId} className="wb-timeline__canvas" /> : null}
    </View>
  );
}
