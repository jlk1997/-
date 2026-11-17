import { useEffect, useRef, useState } from "react";
import { View, Text } from "@tarojs/components";
import { Button } from "../../components/ui";
import { usePlayer } from "../../contexts/PlayerProvider";
import type { WorkbenchModel } from "./hooks/useWorkbenchSession";

function approxGain(lanes: WorkbenchModel["lanes"]) {
  const solo = lanes.filter((lane) => lane.solo && !lane.mute);
  const active = solo.length ? solo : lanes.filter((lane) => !lane.mute);
  if (!active.length) return 0;
  const master = active.find((lane) => lane.kind === "master") || active[0];
  const value = Number(master.gain ?? 1);
  return Number.isFinite(value) ? Math.max(0, Math.min(2, value)) : 1;
}

export function ApproxPreview({ model }: { model: WorkbenchModel }) {
  const w = model.w;
  const { stop } = usePlayer();
  const [on, setOn] = useState(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
      void ctxRef.current?.close();
      ctxRef.current = null;
      audioRef.current = null;
    };
  }, []);

  async function toggle() {
    if (on) {
      audioRef.current?.pause();
      setOn(false);
      return;
    }
    const url = model.session?.source_audio_url;
    if (!url || typeof window === "undefined" || !window.AudioContext) {
      model.playSource("a");
      return;
    }
    try {
      stop();
      const ctx = ctxRef.current || new window.AudioContext();
      ctxRef.current = ctx;
      if (ctx.state === "suspended") await ctx.resume();
      const audio = new Audio(url);
      audio.crossOrigin = "anonymous";
      audio.loop = true;
      const src = ctx.createMediaElementSource(audio);
      const gain = ctx.createGain();
      gain.gain.value = approxGain(model.lanes);
      src.connect(gain).connect(ctx.destination);
      await audio.play();
      audioRef.current = audio;
      setOn(true);
    } catch {
      model.playSource("a");
      setOn(false);
    }
  }

  return (
    <View className="wb-approx">
      <Text className="typo-meta">{w.previewApproxSoon}</Text>
      <Button size="sm" variant={on ? "secondary" : "ghost"} onClick={() => void toggle()}>
        {on ? w.previewApproxStop : w.previewApprox}
      </Button>
    </View>
  );
}
