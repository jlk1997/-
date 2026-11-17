import { useRef, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { Stepper } from "../shared";
import type { WorkbenchModel } from "../hooks/useWorkbenchSession";

function pageXOf(ev: { detail?: { x?: number }; touches?: Array<{ clientX: number }>; changedTouches?: Array<{ clientX: number }> }) {
  return ev.detail?.x ?? ev.touches?.[0]?.clientX ?? ev.changedTouches?.[0]?.clientX ?? 0;
}

export function TrimHandles({ model }: { model: WorkbenchModel }) {
  const start0 = model.masterTrim?.start ?? 0;
  const end0 = model.masterTrim?.end ?? model.duration;
  const [live, setLive] = useState<{ start: number; end: number } | null>(null);
  const drag = useRef<"start" | "end" | null>(null);
  const box = useRef<{ left: number; width: number } | null>(null);
  const start = live?.start ?? start0;
  const end = live?.end ?? end0;
  const duration = Math.max(model.duration, end, 0.1);

  function timeAt(pageX: number) {
    const rect = box.current;
    if (!rect?.width) return 0;
    return Number((Math.max(0, Math.min(1, (pageX - rect.left) / rect.width)) * duration).toFixed(2));
  }

  function begin(kind: "start" | "end", ev: { detail?: { x?: number }; touches?: Array<{ clientX: number }> }) {
    drag.current = kind;
    Taro.createSelectorQuery()
      .select("#wb-lite-trim")
      .boundingClientRect()
      .exec((res) => {
        const rect = res?.[0] as { left?: number; width?: number } | undefined;
        if (!rect?.width) return;
        box.current = { left: rect.left || 0, width: rect.width };
        move(ev);
      });
  }

  function move(ev: { detail?: { x?: number }; touches?: Array<{ clientX: number }> }) {
    if (!drag.current || !box.current) return;
    const time = timeAt(pageXOf(ev));
    if (drag.current === "start") {
      setLive({ start: Math.min(time, end - 0.2), end });
    } else {
      setLive({ start, end: Math.max(time, start + 0.2) });
    }
  }

  function finish() {
    const next = live;
    drag.current = null;
    box.current = null;
    setLive(null);
    if (!next) return;
    void model.onTrim(next.start, next.end);
  }

  return (
    <View className="wb__trim">
      <Text className="wb__section">{model.w.trimTitle}</Text>
      <Text className="typo-meta">{model.w.trimDragHint}</Text>
      <View
        id="wb-lite-trim"
        className="wb-trim-rail"
        onTouchMove={move}
        onTouchEnd={finish}
      >
        <View
          className="wb-trim-fill"
          style={{
            left: `${(start / duration) * 100}%`,
            width: `${((end - start) / duration) * 100}%`,
          }}
        />
        <View
          className="wb-trim-handle wb-trim-handle--start"
          style={{ left: `${(start / duration) * 100}%` }}
          onTouchStart={(ev) => begin("start", ev)}
        />
        <View
          className="wb-trim-handle wb-trim-handle--end"
          style={{ left: `${(end / duration) * 100}%` }}
          onTouchStart={(ev) => begin("end", ev)}
        />
      </View>
      <Stepper label={model.w.trimStart} value={start} min={0} max={Math.max(0, end - 0.2)} step={0.5} onChange={(value) => void model.onTrim(value, end)} />
      <Stepper label={model.w.trimEnd} value={end} min={start + 0.2} max={Math.max(model.duration, end)} step={0.5} onChange={(value) => void model.onTrim(start, value)} />
    </View>
  );
}
