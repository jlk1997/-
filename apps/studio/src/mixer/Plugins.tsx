import type { EqBand, MixInsert } from "@vibe-sorcery/types";
import { eqCurve, MixEngine } from "@vibe-sorcery/mix-engine";
import { useEffect, useRef, useState } from "react";
import { bandsOf, useMixStore } from "./store";

export function PluginWindow({ engine, onChange }: { engine: MixEngine; onChange: (insert: MixInsert) => void }) {
  const plugin = useMixStore((s) => s.plugin);
  const doc = useMixStore((s) => s.doc);
  const close = useMixStore((s) => s.closePlugin);
  const patchInsert = useMixStore((s) => s.patchInsert);
  const [frame, setFrame] = useState({ x: 280, y: 84, w: 440 });
  if (!plugin) return null;
  const channel = doc.channels.find((item) => item.id === plugin.channelId);
  const bus = doc.buses.find((item) => item.id === plugin.channelId);
  const insert = channel?.inserts.find((item) => item.id === plugin.insertId) || bus?.inserts.find((item) => item.id === plugin.insertId);
  if (!insert) return null;

  function dragHeader(event: React.PointerEvent) {
    if ((event.target as HTMLElement).closest("button")) return;
    const ox = event.clientX - frame.x;
    const oy = event.clientY - frame.y;
    const move = (ev: PointerEvent) => setFrame((current) => ({ ...current, x: ev.clientX - ox, y: Math.max(48, ev.clientY - oy) }));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function resize(event: React.PointerEvent) {
    event.stopPropagation();
    const ox = event.clientX;
    const ow = frame.w;
    const move = (ev: PointerEvent) => setFrame((current) => ({ ...current, w: Math.max(320, Math.min(720, ow + ev.clientX - ox)) }));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function setParam(key: string, value: number | string | boolean | EqBand[]) {
    const params = { ...insert!.params, [key]: value };
    patchInsert(plugin!.channelId, insert!.id, params);
    onChange({ ...insert!, params });
  }

  return (
    <div className="plugin" role="dialog" style={{ left: frame.x, top: frame.y, width: frame.w, right: "auto" }}>
      <header onPointerDown={dragHeader}>
        <strong>{insert.type.toUpperCase()}</strong>
        <span>{channel?.name || bus?.name}</span>
        <button type="button" onClick={close}>关闭</button>
      </header>
      {insert.type === "eq" ? (
        <div className="eq-stage">
          <Spectrum engine={engine} channelId={plugin.channelId} layout="eq" />
          <EqEditor bands={bandsOf(insert)} onChange={(bands) => setParam("bands", bands)} />
        </div>
      ) : (
        <Spectrum engine={engine} channelId={plugin.channelId} layout="bars" />
      )}
      {insert.type === "compressor" ? (
        <KnobRow
          rows={[
            ["threshold", -40, 0],
            ["ratio", 1, 12],
            ["attack", 0.001, 0.2],
            ["release", 0.02, 1],
            ["knee", 0, 24],
            ["makeup", 0, 12],
          ]}
          params={insert.params}
          onChange={setParam}
        />
      ) : null}
      {insert.type === "gate" ? <KnobRow rows={[["threshold", -80, 0], ["ratio", 1, 8]]} params={insert.params} onChange={setParam} /> : null}
      {insert.type === "deesser" ? <KnobRow rows={[["amount", 0, 1], ["freq", 2000, 12000]]} params={insert.params} onChange={setParam} /> : null}
      {insert.type === "limiter" ? <KnobRow rows={[["ceiling", -12, -0.1]]} params={insert.params} onChange={setParam} /> : null}
      {insert.type === "reverb" ? (
        <div>
          <select value={String(insert.params.preset || "hall")} onChange={(e) => setParam("preset", e.target.value)}>
            <option value="room">Room</option>
            <option value="hall">Hall</option>
            <option value="plate">Plate</option>
          </select>
          <KnobRow rows={[["decay", 0.2, 5], ["predelay", 0, 0.08], ["mix", 0, 1]]} params={insert.params} onChange={setParam} />
        </div>
      ) : null}
      {insert.type === "delay" ? <KnobRow rows={[["sync", 0.125, 1], ["feedback", 0, 0.9], ["cutoff", 400, 12000], ["mix", 0, 1]]} params={insert.params} onChange={setParam} /> : null}
      {insert.type === "widen" ? <KnobRow rows={[["amount", 0, 2]]} params={insert.params} onChange={setParam} /> : null}
      <i className="plugin-resize" onPointerDown={resize} />
    </div>
  );
}

function EqEditor({ bands, onChange }: { bands: EqBand[]; onChange: (bands: EqBand[]) => void }) {
  const points = eqCurve(bands, 360, 120);
  function drag(index: number, event: React.PointerEvent<SVGCircleElement>) {
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const move = (ev: PointerEvent) => {
      const x = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
      const y = Math.max(0, Math.min(rect.height, ev.clientY - rect.top));
      const freq = Math.round(20 * Math.pow(1000, x / rect.width));
      const gain = Math.round(((rect.height / 2 - y) / (rect.height / 2)) * 24);
      onChange(bands.map((band, i) => (i === index ? { ...band, freq, gain, enabled: true } : band)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  return (
    <svg className="eq" viewBox="0 0 360 120">
      <polyline points={points} fill="none" stroke="#4c8dff" strokeWidth="2" />
      {bands.map((band, index) => {
        const x = (Math.log(band.freq / 20) / Math.log(1000)) * 360;
        const y = 60 - (band.gain / 24) * 60;
        return <circle key={band.type + index} cx={x} cy={y} r="6" fill={band.enabled ? "#fff" : "#666"} onPointerDown={(event) => drag(index, event)} />;
      })}
    </svg>
  );
}

function Spectrum({ engine, channelId, layout }: { engine: MixEngine; channelId: string; layout: "bars" | "eq" }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let frame = 0;
    const draw = () => {
      const canvas = ref.current;
      const bins = canvas ? engine.spectrum(channelId) : null;
      const ctx = canvas?.getContext("2d");
      if (canvas && ctx && bins) {
        const width = canvas.width;
        const height = canvas.height;
        ctx.clearRect(0, 0, width, height);
        if (layout === "eq") {
          const nyquist = engine.sampleRate() / 2;
          ctx.beginPath();
          ctx.moveTo(0, height);
          for (let x = 0; x <= width; x += 2) {
            const freq = 20 * Math.pow(1000, x / width);
            let mag = 0;
            if (freq < nyquist && bins.length > 1) {
              const index = Math.min(bins.length - 1, Math.round((freq / nyquist) * (bins.length - 1)));
              mag = bins[index] / 255;
            }
            ctx.lineTo(x, height - mag * height);
          }
          ctx.lineTo(width, height);
          ctx.closePath();
          ctx.fillStyle = "rgba(76, 141, 255, 0.38)";
          ctx.fill();
        } else {
          const bars = 48;
          const step = Math.max(1, Math.floor(bins.length / bars));
          const barWidth = width / bars;
          for (let i = 0; i < bars; i++) {
            let peak = 0;
            const start = i * step;
            for (let j = start; j < start + step && j < bins.length; j++) peak = Math.max(peak, bins[j]);
            const barHeight = (peak / 255) * height;
            ctx.fillStyle = peak > 220 ? "#ff6b4a" : "rgba(76, 141, 255, 0.75)";
            ctx.fillRect(i * barWidth, height - barHeight, Math.max(1, barWidth - 1), barHeight);
          }
        }
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [engine, channelId, layout]);
  return <canvas ref={ref} className="plugin-spectrum" width={360} height={layout === "eq" ? 120 : 72} />;
}

function KnobRow({
  rows,
  params,
  onChange,
}: {
  rows: Array<[string, number, number]>;
  params: MixInsert["params"];
  onChange: (key: string, value: number) => void;
}) {
  return (
    <div className="knobs">
      {rows.map(([key, min, max]) => (
        <label key={key}>
          {key}
          <input type="range" min={min} max={max} step={(max - min) / 100} value={Number(params[key] ?? min)} onChange={(e) => onChange(key, Number(e.target.value))} />
          <span>{Number(params[key] ?? 0).toFixed(2)}</span>
        </label>
      ))}
    </div>
  );
}
