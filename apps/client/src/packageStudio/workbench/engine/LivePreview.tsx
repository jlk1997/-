import { useEffect, useRef, useState } from "react";
import { View, Text } from "@tarojs/components";
import { Button } from "../../../components/ui";
import { usePlayer } from "../../../contexts/PlayerProvider";
import type { WorkbenchModel } from "../hooks/useWorkbenchSession";
import { fidelityOf } from "./contract";
import { openLiveGraph, openStemGraph, readPeak, type LiveHandle } from "./liveGraph";
import { publishLanePeaks } from "./lanePeaks";

export function LivePreview({ model, variant }: { model: WorkbenchModel; variant: "lite" | "pro" }) {
  const w = model.w;
  const { stop } = usePlayer();
  const handle = useRef<LiveHandle | null>(null);
  const [on, setOn] = useState(false);
  const [peak, setPeak] = useState(0);
  const [time, setTime] = useState(0);
  const [compareGain, setCompareGain] = useState(1);
  const [lanePeaks, setLanePeaks] = useState<Record<string, number>>({});
  const loopSeconds = variant === "lite" ? 30 : null;
  const renderNodes = (model.nodes || []).filter((node) => fidelityOf(String(node.type || "")) === "render");

  useEffect(() => {
    handle.current?.update(model.lanes, model.nodes, Number(model.session?.intensity || 1));
  }, [model.lanes, model.nodes, model.session?.intensity]);

  useEffect(() => {
    return () => {
      handle.current?.close();
      handle.current = null;
    };
  }, []);

  useEffect(() => {
    if (!on || !handle.current) return;
    let frame = 0;
    const tick = () => {
      const live = handle.current;
      if (!live) return;
      setPeak(readPeak(live.analyser));
      const lanePeaks = live.readLanePeaks();
      setLanePeaks(lanePeaks);
      publishLanePeaks(lanePeaks);
      setTime(live.getTime());
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [on]);

  useEffect(() => {
    if (variant !== "pro" || typeof window === "undefined") return;
    function onKey(event: KeyboardEvent) {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (event.code === "Space") {
        event.preventDefault();
        void toggle();
      } else if ((event.key === "z" || event.key === "Z") && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        void model.onUndo();
      } else if (event.key === "b" || event.key === "B") {
        const next = model.ab === "a" ? "b" : "a";
        const audio = handle.current;
        const at = audio?.getTime() || 0;
        model.playSource(next);
        if (audio) audio.seekTo(at);
      } else if (event.key === "s" || event.key === "S" || event.key === "m" || event.key === "M") {
        const flag = event.key.toLowerCase() === "s" ? "solo" : "mute";
        const lanes = model.lanes.map((lane) =>
          lane.id === model.selectedLaneId ? { ...lane, [flag]: !lane[flag] } : lane,
        );
        void model.patchLanes(lanes);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function toggle() {
    if (on) {
      handle.current?.pause();
      setOn(false);
      return;
    }
    const url = model.ab === "b" ? model.session?.last_result_audio_url : model.session?.source_audio_url;
    if (!url) {
      model.playSource("a");
      return;
    }
    const laneUrls = (model.session?.edit_lanes?.urls || {}) as Record<string, string>;
    const stemKey = variant === "lite" ? "vocal,accompaniment" : Object.keys(laneUrls).sort().join(",");
    try {
      stop();
      if (!handle.current || handle.current.audio.src !== url || handle.current.stemKey !== stemKey) {
        handle.current?.close();
        const kinds = variant === "lite" ? ["vocal", "accompaniment"] : undefined;
        const stems = Object.keys(laneUrls).length ? await openStemGraph(laneUrls, { windowSeconds: loopSeconds, kinds }) : null;
        const next = stems || (await openLiveGraph(url));
        if (!next) {
          model.playSource("a");
          return;
        }
        next.setLoopSeconds(loopSeconds);
        next.update(model.lanes, model.nodes, Number(model.session?.intensity || 1));
        next.setTrim(compareGain);
        handle.current = next;
      }
      await handle.current.play();
      setOn(true);
    } catch {
      model.playSource("a");
      setOn(false);
    }
  }

  function seek(ratio: number) {
    const live = handle.current;
    const duration = live?.getDuration() || 0;
    if (!live || !duration) return;
    live.seekTo(Math.max(0, Math.min(duration, ratio * duration)));
  }

  const duration = handle.current?.getDuration() || model.duration || 0;
  const shown = duration ? `${time.toFixed(1)} / ${duration.toFixed(1)}` : "0.0";

  return (
    <View className={`wb-live wb-live--${variant}`}>
      <View className="wb-live__row">
        <Button size="sm" variant={on ? "secondary" : "primary"} onClick={() => void toggle()}>
          {on ? w.previewApproxStop : w.previewApprox}
        </Button>
        <Text className="wb-live__time">{shown}</Text>
        <View className="wb-live__meter" aria-hidden>
          <View className="wb-live__meter-fill" style={{ width: `${Math.round(peak * 100)}%` }} />
        </View>
      </View>
      {variant === "pro" ? (
        <View
          className="wb-live__seek"
          onClick={(event) => {
            const rect = (event.target as HTMLElement | null)?.getBoundingClientRect?.();
            if (!rect || !rect.width) return;
            const x = "clientX" in event ? Number((event as { clientX?: number }).clientX || 0) - rect.left : 0;
            seek(x / rect.width);
          }}
        >
          <View className="wb-live__seek-fill" style={{ width: duration ? `${(time / duration) * 100}%` : "0%" }} />
          {((model.session?.edit_lanes?.marks || []) as Array<{ tag?: string; start?: number }>).map((mark) => (
            <Text
              key={`${mark.tag}-${mark.start}`}
              className="wb-live__mark"
              style={{ left: duration ? `${((mark.start || 0) / duration) * 100}%` : "0%" }}
            >
              {mark.tag}
            </Text>
          ))}
        </View>
      ) : (
        <Text className="typo-meta">手机只循环前 30 秒的人声和伴奏，成品仍由服务器出。</Text>
      )}
      {model.session?.edit_lanes?.label ? <Text className="typo-meta">{model.session.edit_lanes.label}。段落位置是估计的。</Text> : null}
      {Object.keys(lanePeaks).length ? (
        <View className="wb-live__lanes">
          {Object.entries(lanePeaks).map(([kind, value]) => (
            <Text key={kind} className="typo-meta">
              {kind} {Math.round(value * 100)}
            </Text>
          ))}
        </View>
      ) : null}
      {renderNodes.length ? <Text className="typo-meta">变调、变速和智能处理要等服务器出成品，这里听不到。</Text> : null}
      {variant === "pro" ? (
        <Text className="typo-meta">空格播放 · S 独奏 · M 静音 · B 对比 · Ctrl+Z 撤销</Text>
      ) : null}
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          const next = compareGain === 1 ? 0.9 : 1;
          setCompareGain(next);
          handle.current?.setTrim(next);
        }}
      >
        {compareGain === 1 ? "对齐响度" : "响度已对齐"}
      </Button>
    </View>
  );
}
