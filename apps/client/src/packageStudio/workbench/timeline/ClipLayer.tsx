import { useRef, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import type { Clip } from "../types";

export function pct(time: number, duration: number) {
  return `${Math.max(0, Math.min(100, (time / Math.max(duration, 0.1)) * 100))}%`;
}

function pageXOf(ev: { detail?: { x?: number }; touches?: Array<{ clientX: number }>; changedTouches?: Array<{ clientX: number }> }) {
  return ev.detail?.x ?? ev.touches?.[0]?.clientX ?? ev.changedTouches?.[0]?.clientX ?? 0;
}

function timeFromRect(pageX: number, rect: { left: number; width: number }, duration: number) {
  const ratio = Math.max(0, Math.min(1, (pageX - rect.left) / rect.width));
  return Number((ratio * duration).toFixed(3));
}

export function pickTrackTime(
  selector: string,
  duration: number,
  ev: { detail?: { x?: number }; touches?: Array<{ clientX: number }>; changedTouches?: Array<{ clientX: number }> },
  cb: (time: number) => void,
) {
  Taro.createSelectorQuery()
    .select(selector)
    .boundingClientRect()
    .exec((res) => {
      const rect = res?.[0] as { left?: number; width?: number } | undefined;
      if (!rect?.width) return;
      cb(timeFromRect(pageXOf(ev), { left: rect.left || 0, width: rect.width }, duration));
    });
}

type DragKind = "move" | "start" | "end";

type DragState = {
  kind: DragKind;
  start: number;
  end: number;
  offset: number;
  originTime: number;
  rect: { left: number; width: number };
};

function nextFromDrag(drag: DragState, time: number) {
  const delta = time - drag.originTime;
  if (drag.kind === "move") {
    const length = Math.max(0.05, drag.end - drag.start);
    const start = Math.max(0, Math.min(600 - length, drag.start + delta));
    return { start: Number(start.toFixed(3)), end: Number((start + length).toFixed(3)), offset: drag.offset };
  }
  if (drag.kind === "start") {
    const start = Math.max(0, Math.min(drag.end - 0.05, drag.start + delta));
    return {
      start: Number(start.toFixed(3)),
      end: drag.end,
      offset: Number(Math.max(0, drag.offset + (start - drag.start)).toFixed(3)),
    };
  }
  const end = Math.max(drag.start + 0.05, Math.min(600, drag.end + delta));
  return { start: drag.start, end: Number(end.toFixed(3)), offset: drag.offset };
}

export function ClipBlock({
  clip,
  duration,
  selected,
  label,
  trackSelector,
  onSelect,
  onCommit,
}: {
  clip: Clip;
  duration: number;
  selected: boolean;
  label: string;
  trackSelector: string;
  onSelect: () => void;
  onCommit: (clipId: string, next: { start: number; end: number; offset: number }) => void;
}) {
  const drag = useRef<DragState | null>(null);
  const [live, setLive] = useState<{ start: number; end: number; offset: number } | null>(null);
  const start = live?.start ?? clip.start;
  const end = live?.end ?? clip.end;

  function begin(kind: DragKind, ev: { stopPropagation?: () => void; detail?: { x?: number }; touches?: Array<{ clientX: number }> }) {
    ev.stopPropagation?.();
    Taro.createSelectorQuery()
      .select(trackSelector)
      .boundingClientRect()
      .exec((res) => {
        const rect = res?.[0] as { left?: number; width?: number } | undefined;
        if (!rect?.width) return;
        const box = { left: rect.left || 0, width: rect.width };
        drag.current = {
          kind,
          start: clip.start,
          end: clip.end,
          offset: clip.offset,
          originTime: timeFromRect(pageXOf(ev), box, duration),
          rect: box,
        };
      });
  }

  function move(ev: { detail?: { x?: number }; touches?: Array<{ clientX: number }> }) {
    const current = drag.current;
    if (!current) return;
    setLive(nextFromDrag(current, timeFromRect(pageXOf(ev), current.rect, duration)));
  }

  function finish() {
    const current = drag.current;
    const next = live;
    drag.current = null;
    setLive(null);
    if (!current || !next) return;
    if (Math.abs(next.start - current.start) < 0.01 && Math.abs(next.end - current.end) < 0.01) {
      onSelect();
      return;
    }
    onCommit(clip.id, next);
  }

  return (
    <View
      className={selected ? "wb-clip is-selected" : "wb-clip"}
      style={{ left: pct(start, duration), width: pct(end - start, duration) }}
      onClick={(ev) => {
        ev.stopPropagation?.();
        onSelect();
      }}
      onTouchStart={(ev) => begin("move", ev)}
      onTouchMove={move}
      onTouchEnd={finish}
    >
      <View
        className="wb-clip__handle wb-clip__handle--start"
        onTouchStart={(ev) => begin("start", ev)}
        onTouchMove={move}
        onTouchEnd={finish}
      />
      <Text className="wb-clip__label">{label}</Text>
      <View
        className="wb-clip__handle wb-clip__handle--end"
        onTouchStart={(ev) => begin("end", ev)}
        onTouchMove={move}
        onTouchEnd={finish}
      />
    </View>
  );
}
