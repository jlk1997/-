import { MixEngine, barsBeats, dbToFader, faderToDb, formatDb, formatTimecode, snapUnity } from "@vibe-sorcery/mix-engine";
import { useEffect, useRef, useState } from "react";
import { deskCopy } from "../copy";
import { PluginWindow } from "./Plugins";
import { useMixStore } from "./store";

export function MixerDesk({ engine, onSave, onBounce, audioRevision = 0 }: { engine: MixEngine; onSave: () => void; onBounce: () => void; audioRevision?: number }) {
  const copy = deskCopy();
  const doc = useMixStore((s) => s.doc);
  const mixerOpen = useMixStore((s) => s.mixerOpen);
  const inspectorOpen = useMixStore((s) => s.inspectorOpen);
  const lcdMode = useMixStore((s) => s.lcdMode);
  const selectedId = useMixStore((s) => s.selectedId);
  const select = useMixStore((s) => s.select);
  const liveChannel = useMixStore((s) => s.liveChannel);
  const patchChannel = useMixStore((s) => s.patchChannel);
  const toggleLoop = useMixStore((s) => s.toggleLoop);
  const setLcd = useMixStore((s) => s.setLcd);
  const openPlugin = useMixStore((s) => s.openPlugin);
  const toggleBypass = useMixStore((s) => s.toggleBypass);
  const moveInsert = useMixStore((s) => s.moveInsert);
  const splitAt = useMixStore((s) => s.splitAt);
  const setRegion = useMixStore((s) => s.setRegion);
  const addInsert = useMixStore((s) => s.addInsert);
  const setTempo = useMixStore((s) => s.setTempo);
  const setLoop = useMixStore((s) => s.setLoop);
  const [listen, setListen] = useState<"mix" | "forward" | "bed" | "original">("mix");
  const [zoom, setZoom] = useState(1);
  const [snap, setSnap] = useState(true);
  const [followPlay, setFollowPlay] = useState(true);
  const fpsRead = useRef<HTMLSpanElement>(null);
  const lcd = useRef<HTMLSpanElement>(null);
  const load = useRef<HTMLSpanElement>(null);
  const arrange = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const playhead = useRef<HTMLDivElement>(null);
  const structure = doc.channels.map((channel) => `${channel.id}:${channel.inserts.map((insert) => insert.id).join(",")}`).join("|")
    + doc.buses.map((bus) => `${bus.id}:${bus.inserts.map((insert) => insert.id).join(",")}`).join("|");
  const loopKey = `${doc.loop.enabled}:${doc.loop.start}:${doc.loop.end}`;

  useEffect(() => {
    engine.setDocument(useMixStore.getState().doc);
  }, [engine, structure]);

  useEffect(() => {
    engine.sync(doc);
  }, [doc, engine]);

  const regionKey = doc.regions.map((region) => `${region.id}:${region.start}:${region.end}:${region.offset}:${region.mute}`).join("|");

  useEffect(() => {
    if (engine.isPlaying()) engine.seek(engine.position());
  }, [engine, loopKey, regionKey]);

  useEffect(() => {
    let frame = 0;
    let frames = 0;
    let stamp = performance.now();
    const tick = () => {
      engine.sampleMeters();
      engine.follow(engine.position());
      const pos = engine.position();
      const duration = Math.max(engine.duration(), 0.01);
      if (playhead.current) playhead.current.style.left = `${Math.min(100, (pos / duration) * 100)}%`;
      if (followPlay && engine.isPlaying() && arrange.current && sheet.current) {
        const view = arrange.current.clientWidth;
        const playX = (pos / duration) * sheet.current.offsetWidth;
        const left = arrange.current.scrollLeft;
        if (playX < left + 40 || playX > left + view * 0.75) {
          arrange.current.scrollLeft = Math.max(0, playX - view * 0.3);
        }
      }
      if (lcd.current) {
        lcd.current.textContent = lcdMode === "bars" ? barsBeats(pos, doc.tempo.bpm, doc.tempo.beatsPerBar) : formatTimecode(pos);
      }
      if (load.current) load.current.textContent = `${Math.min(99, Math.round((engine.loudness.truePeak + 70) / 0.7))}%`;
      frames += 1;
      const now = performance.now();
      if (now - stamp >= 500 && fpsRead.current) {
        fpsRead.current.textContent = String(Math.round((frames * 1000) / (now - stamp)));
        frames = 0;
        stamp = now;
      }
      const playBtn = document.getElementById("play-btn");
      if (playBtn) playBtn.textContent = engine.isPlaying() ? copy.stop : copy.play;
      document.querySelectorAll<HTMLCanvasElement>("canvas.meter").forEach((canvas) => {
        const reading = engine.meters.get(canvas.dataset.id || "") || { peak: -70, rms: -70, hold: -70, gr: 0 };
        paintMeter(canvas, reading);
      });
      const lufs = document.getElementById("lufs-readout");
      if (lufs) {
        lufs.textContent = `M ${engine.loudness.momentary.toFixed(1)}  S ${engine.loudness.shortTerm.toFixed(1)}  I ${engine.loudness.integrated.toFixed(1)}  TP ${engine.loudness.truePeak.toFixed(1)}`;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [copy.play, copy.stop, doc.tempo.beatsPerBar, doc.tempo.bpm, engine, followPlay, lcdMode]);

  function timeFromClient(clientX: number) {
    const rect = sheet.current?.getBoundingClientRect();
    const duration = Math.max(1, engine.duration());
    if (!rect || rect.width <= 0) return 0;
    const raw = Math.max(0, Math.min(duration, ((clientX - rect.left) / rect.width) * duration));
    if (!snap) return raw;
    const bar = (60 / Math.max(40, doc.tempo.bpm)) * doc.tempo.beatsPerBar;
    return Math.max(0, Math.min(duration, Math.round(raw / bar) * bar));
  }

  function seekFromEvent(event: React.PointerEvent) {
    if ((event.target as HTMLElement).closest(".fade-handle, .loop-brace")) return;
    engine.seek(timeFromClient(event.clientX));
  }

  function nudgeZoom(dir: number) {
    setZoom((value) => Math.max(1, Math.min(16, Math.round(value * (dir > 0 ? 1.25 : 0.8) * 100) / 100)));
  }

  const selected = doc.channels.find((channel) => channel.id === selectedId) || doc.channels[0];

  return (
    <div className="daw">
      <div className="transport">
        <button type="button" onClick={() => engine.restart()}>|◀</button>
        <button id="play-btn" type="button" onClick={() => (engine.isPlaying() ? engine.stop() : void engine.play())}>{copy.play}</button>
        <button type="button" className={doc.loop.enabled ? "is-on" : ""} onClick={toggleLoop}>{copy.loop}</button>
        {([
          ["mix", copy.listenMix],
          ["forward", copy.listenForward],
          ["bed", copy.listenBed],
          ["original", copy.listenOriginal],
        ] as const).map(([mode, label]) => (
          <button
            key={mode}
            type="button"
            className={listen === mode ? "is-on" : ""}
            onClick={() => {
              setListen(mode);
              engine.setListen(mode);
            }}
          >
            {label}
          </button>
        ))}
        <button type="button" onClick={() => nudgeZoom(-1)}>{copy.zoomOut}</button>
        <button type="button" onClick={() => nudgeZoom(1)}>{copy.zoomIn}</button>
        <button type="button" className={snap ? "is-on" : ""} onClick={() => setSnap((value) => !value)}>{copy.snap}</button>
        <button type="button" className={followPlay ? "is-on" : ""} onClick={() => setFollowPlay((value) => !value)}>{copy.followPlay}</button>
        <button type="button" className="lcd" onClick={() => setLcd(lcdMode === "bars" ? "time" : "bars")}><span ref={lcd}>1.1.000</span></button>
        <label className="tempo">BPM
          <input type="number" min={40} max={240} value={doc.tempo.bpm} onChange={(event) => setTempo(Number(event.target.value))} />
        </label>
        <span>{doc.tempo.key || "—"}</span>
        <span>{copy.load} <span ref={load}>0%</span></span>
        <span>{copy.meter} <span ref={fpsRead}>—</span></span>
        <canvas className="meter meter--wide" data-id="master" width={12} height={48} />
        <button type="button" onClick={onSave}>{copy.save}</button>
        <button type="button" className="primary" onClick={onBounce}>{copy.bounce}</button>
      </div>
      <div className="arrange">
        <div className="arrange-names">
          <span className="ruler-pad" />
          {doc.channels.map((channel) => (
            <em key={channel.id} style={{ color: channel.color }}>{channel.name}</em>
          ))}
        </div>
        <div
          className="arrange-scroll"
          ref={arrange}
          onWheel={(event) => {
            if (!event.ctrlKey && !event.metaKey) return;
            event.preventDefault();
            nudgeZoom(event.deltaY < 0 ? 1 : -1);
          }}
          onPointerDown={seekFromEvent}
        >
          <div className="arrange-sheet" ref={sheet} style={{ width: `${zoom * 100}%` }}>
            <div className="playhead" ref={playhead} />
            {doc.loop.enabled ? (
              <div
                className="loop-brace"
                style={{
                  left: `${(doc.loop.start / Math.max(engine.duration(), 1)) * 100}%`,
                  width: `${Math.max(0, doc.loop.end - doc.loop.start) / Math.max(engine.duration(), 1) * 100}%`,
                }}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  const width = sheet.current?.getBoundingClientRect().width || 1;
                  const duration = Math.max(1, engine.duration());
                  const origin = event.clientX;
                  const start = doc.loop.start;
                  const end = doc.loop.end;
                  const move = (ev: PointerEvent) => {
                    const delta = ((ev.clientX - origin) / width) * duration;
                    const snapped = snap ? (60 / Math.max(40, doc.tempo.bpm)) * doc.tempo.beatsPerBar : 0;
                    const shift = snapped ? Math.round(delta / snapped) * snapped : delta;
                    setLoop({ start: Math.max(0, start + shift), end: Math.max(start + shift + 0.1, end + shift) });
                  };
                  const up = () => {
                    window.removeEventListener("pointermove", move);
                    window.removeEventListener("pointerup", up);
                  };
                  window.addEventListener("pointermove", move);
                  window.addEventListener("pointerup", up);
                }}
              />
            ) : null}
            <div className="ruler">
              {barMarks(Math.max(engine.duration(), 1), doc.tempo.bpm, doc.tempo.beatsPerBar, zoom).map((mark) => (
                <span key={mark.bar} style={{ left: `${mark.left}%` }}>{mark.bar}</span>
              ))}
            </div>
            {doc.channels.map((channel) => {
              const regions = doc.regions.filter((region) => region.channel === channel.id);
              const song = Math.max(engine.duration(), 1);
              const shown = regions.length ? regions : [{ id: `${channel.id}-all`, start: 0, end: song, mute: false, fadeIn: 0, fadeOut: 0, offset: 0, channel: channel.id }];
              return (
                <div key={channel.id} className="lane" onClick={() => select(channel.id)}>
                  <div
                    className="lane-body"
                    onPointerDownCapture={(event) => {
                      if (!event.altKey) return;
                      event.stopPropagation();
                      event.preventDefault();
                      if (event.shiftKey) drawPan(engine, channel.id, event, snap, doc.tempo.bpm, doc.tempo.beatsPerBar);
                      else drawVolume(engine, channel.id, event, snap, doc.tempo.bpm, doc.tempo.beatsPerBar);
                    }}
                  >
                    <LaneWave engine={engine} channelId={channel.id} color={channel.color} revision={audioRevision} />
                    <AutoLine points={channel.automation.volume} duration={song} />
                    <PanLine points={channel.automation.pan} duration={song} />
                    {shown.map((region) => {
                      const span = Math.max(0.05, region.end - region.start);
                      const real = regions.some((item) => item.id === region.id);
                      return (
                        <button
                          key={region.id}
                          type="button"
                          className={region.mute ? "region is-mute" : "region"}
                          style={{
                            left: `${(region.start / song) * 100}%`,
                            width: `${(span / song) * 100}%`,
                            background: `linear-gradient(90deg, transparent, ${channel.color} ${(region.fadeIn / span) * 100}%, ${channel.color} ${100 - (region.fadeOut / span) * 100}%, transparent)`,
                          }}
                          onPointerDown={(event) => {
                            if (!real) return;
                            if ((event.target as HTMLElement).closest(".fade-handle")) return;
                            event.stopPropagation();
                            dragMove(event, region, song, snap, doc.tempo.bpm, doc.tempo.beatsPerBar);
                          }}
                          onDoubleClick={() => splitAt(channel.id, snapTime(engine.position(), snap, doc.tempo.bpm, doc.tempo.beatsPerBar, song), song)}
                        >
                          {real ? (
                            <i
                              className="fade-handle left"
                              onPointerDown={(event) => {
                                if (event.shiftKey) trimEdge(event, region, "start", song, snap, doc.tempo.bpm, doc.tempo.beatsPerBar);
                                else dragFade(event, region.id, "fadeIn", region);
                              }}
                            />
                          ) : null}
                          {real ? (
                            <i
                              className="fade-handle right"
                              onPointerDown={(event) => {
                                if (event.shiftKey) trimEdge(event, region, "end", song, snap, doc.tempo.bpm, doc.tempo.beatsPerBar);
                                else dragFade(event, region.id, "fadeOut", region);
                              }}
                            />
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {mixerOpen ? (
        <div className="console">
          {doc.channels.map((channel) => (
            <Strip key={channel.id} channelId={channel.id} engine={engine} selected={selectedId === channel.id} onSelect={() => select(channel.id)} onLive={liveChannel} onCommit={patchChannel} onOpen={openPlugin} onBypass={toggleBypass} onMove={moveInsert} />
          ))}
          {doc.buses.map((bus) => (
            <div key={bus.id} className="strip strip--bus">
              <strong>{bus.name}</strong>
              {bus.inserts.map((insert) => (
                <button key={insert.id} type="button" className={insert.bypass ? "slot is-bypass" : "slot"} onClick={() => openPlugin(bus.id, insert.id)}>{insert.type}</button>
              ))}
              <canvas className="meter" data-id={bus.id === "master" ? "master" : bus.id} width={10} height={120} />
              {bus.id === "master" ? <div id="lufs-readout" className="lufs">LUFS</div> : null}
            </div>
          ))}
        </div>
      ) : null}
      {inspectorOpen && selected ? (
        <aside className="inspector">
          <h3>{selected.name}</h3>
          <p>输入 {formatDb(selected.inputGain)} dB</p>
          <p>推子 {formatDb(selected.faderDb)} dB</p>
          <p>声像 {selected.pan.toFixed(2)}</p>
          <p>自动化 {selected.automationMode}</p>
          <button type="button" onClick={() => patchChannel(selected.id, { automationMode: selected.automationMode === "read" ? "off" : "read" })}>Read / Off</button>
        </aside>
      ) : null}
      <PluginWindow engine={engine} onChange={(insert) => engine.setInsert(selectedId, insert, doc.tempo.bpm)} />
      <p className="honesty">{copy.drawVolume}。{copy.drawPan}。{copy.moveClip}。{copy.honesty}</p>
    </div>
  );
}

function snapTime(time: number, snap: boolean, bpm: number, beatsPerBar: number, duration: number) {
  if (!snap) return Math.max(0, Math.min(duration, time));
  const bar = (60 / Math.max(40, bpm)) * beatsPerBar;
  return Math.max(0, Math.min(duration, Math.round(time / bar) * bar));
}

function barMarks(duration: number, bpm: number, beatsPerBar: number, zoom: number) {
  const bar = (60 / Math.max(40, bpm)) * beatsPerBar;
  const total = Math.max(1, Math.ceil(duration / bar));
  const step = zoom < 2 ? 4 : zoom < 6 ? 2 : 1;
  const marks: Array<{ bar: number; left: number }> = [];
  for (let i = 0; i < total; i += step) {
    marks.push({ bar: i + 1, left: ((i * bar) / duration) * 100 });
  }
  return marks;
}

function dragMove(
  event: React.PointerEvent,
  region: { id: string; start: number; end: number; mute: boolean },
  song: number,
  snap: boolean,
  bpm: number,
  beatsPerBar: number,
) {
  const width = event.currentTarget.parentElement?.getBoundingClientRect().width || 1;
  const origin = event.clientX;
  const start0 = region.start;
  const end0 = region.end;
  let moved = false;
  let stamped = false;
  const move = (ev: PointerEvent) => {
    const dx = ev.clientX - origin;
    if (Math.abs(dx) < 4) return;
    if (!stamped) {
      useMixStore.getState().checkpoint();
      stamped = true;
    }
    moved = true;
    let delta = (dx / width) * song;
    if (snap) {
      const bar = (60 / Math.max(40, bpm)) * beatsPerBar;
      delta = Math.round(delta / bar) * bar;
    }
    let start = start0 + delta;
    let end = end0 + delta;
    if (start < 0) {
      end -= start;
      start = 0;
    }
    if (end > song) {
      start -= end - song;
      end = song;
    }
    useMixStore.getState().setRegion(region.id, { start: roundTime(start), end: roundTime(end) });
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    if (!moved) useMixStore.getState().setRegion(region.id, { mute: !region.mute });
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function trimEdge(
  event: React.PointerEvent,
  region: { id: string; start: number; end: number; offset: number },
  edge: "start" | "end",
  song: number,
  snap: boolean,
  bpm: number,
  beatsPerBar: number,
) {
  event.stopPropagation();
  event.preventDefault();
  const width = event.currentTarget.parentElement?.getBoundingClientRect().width || 1;
  const span = Math.max(0.05, region.end - region.start);
  const origin = event.clientX;
  const initial = edge === "start" ? region.start : region.end;
  const offset0 = region.offset;
  useMixStore.getState().checkpoint();
  const move = (ev: PointerEvent) => {
    const delta = ((ev.clientX - origin) / width) * span;
    const next = snapTime(initial + delta, snap, bpm, beatsPerBar, song);
    if (edge === "start") {
      const start = Math.min(region.end - 0.05, next);
      useMixStore.getState().setRegion(region.id, { start, offset: Math.max(0, offset0 + (start - region.start)) });
    } else {
      useMixStore.getState().setRegion(region.id, { end: Math.max(region.start + 0.05, next) });
    }
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function roundTime(value: number) {
  return Math.round(value * 1000) / 1000;
}

function dragFade(
  event: React.PointerEvent,
  regionId: string,
  edge: "fadeIn" | "fadeOut",
  region: { start: number; end: number; fadeIn: number; fadeOut: number },
) {
  event.stopPropagation();
  event.preventDefault();
  const span = Math.max(0.05, region.end - region.start);
  const width = (event.currentTarget.parentElement?.getBoundingClientRect().width || 1);
  const origin = event.clientX;
  const initial = edge === "fadeIn" ? region.fadeIn : region.fadeOut;
  useMixStore.getState().checkpoint();
  const move = (ev: PointerEvent) => {
    const delta = ((ev.clientX - origin) / width) * span;
    const next = Math.max(0, Math.min(span / 2, initial + (edge === "fadeIn" ? delta : -delta)));
    useMixStore.getState().setRegion(regionId, { [edge]: Math.round(next * 100) / 100 });
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function drawVolume(engine: MixEngine, channelId: string, event: React.PointerEvent<HTMLDivElement>, snap = false, bpm = 120, beatsPerBar = 4) {
  const body = event.currentTarget;
  const rect = body.getBoundingClientRect();
  const channel = useMixStore.getState().doc.channels.find((item) => item.id === channelId);
  const song = Math.max(1, engine.duration());
  useMixStore.getState().checkpoint();
  let points = channel && channel.automation.volume.length >= 2
    ? [...channel.automation.volume]
    : [{ t: 0, db: channel?.faderDb ?? 0 }, { t: song, db: channel?.faderDb ?? 0 }];
  const apply = (ev: PointerEvent) => {
    const length = Math.max(song, 1);
    const raw = Math.max(0, Math.min(length, ((ev.clientX - rect.left) / Math.max(rect.width, 1)) * length));
    const t = snapTime(raw, snap, bpm, beatsPerBar, length);
    const db = Math.max(-24, Math.min(6, ((rect.bottom - ev.clientY) / Math.max(rect.height, 1)) * 30 - 24));
    const q = Math.round(t * 20) / 20;
    const next = points.filter((point) => Math.abs(point.t - q) > 0.045);
    next.push({ t: q, db: Math.round(db * 10) / 10 });
    next.sort((a, b) => a.t - b.t);
    points = next;
    useMixStore.getState().liveVolume(channelId, points);
  };
  apply(event.nativeEvent);
  const move = (ev: PointerEvent) => apply(ev);
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function LaneWave({ engine, channelId, color, revision }: { engine: MixEngine; channelId: string; color: string; revision: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const peaks = engine.peaks(channelId);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const width = canvas.clientWidth || 600;
    const height = canvas.clientHeight || 48;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (!peaks) return;
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.85;
    const mid = height / 2;
    for (let x = 0; x < width; x++) {
      const peak = peaks[Math.floor((x / width) * peaks.length)] || 0;
      const bar = Math.max(1, peak * mid);
      ctx.fillRect(x, mid - bar, 1, bar * 2);
    }
  }, [channelId, color, engine, revision]);
  return <canvas ref={ref} className="lane-wave" />;
}

function AutoLine({ points, duration }: { points: Array<{ t: number; db: number }>; duration: number }) {
  if (points.length < 2) return null;
  const line = points
    .map((point) => {
      const x = (point.t / duration) * 100;
      const y = (1 - (point.db + 24) / 30) * 100;
      return `${x},${Math.max(0, Math.min(100, y))}`;
    })
    .join(" ");
  return (
    <svg className="auto-line" viewBox="0 0 100 100" preserveAspectRatio="none">
      <polyline points={line} fill="none" stroke="#f5f5f5" strokeWidth="0.8" />
    </svg>
  );
}

function PanLine({ points, duration }: { points: Array<{ t: number; pan: number }>; duration: number }) {
  if (points.length < 2) return null;
  const line = points
    .map((point) => {
      const x = (point.t / duration) * 100;
      const y = (1 - (point.pan + 1) / 2) * 100;
      return `${x},${Math.max(0, Math.min(100, y))}`;
    })
    .join(" ");
  return (
    <svg className="auto-line" viewBox="0 0 100 100" preserveAspectRatio="none">
      <polyline points={line} fill="none" stroke="#7aa2ff" strokeWidth="0.8" />
    </svg>
  );
}

function drawPan(engine: MixEngine, channelId: string, event: React.PointerEvent<HTMLDivElement>, snap = false, bpm = 120, beatsPerBar = 4) {
  const rect = event.currentTarget.getBoundingClientRect();
  const channel = useMixStore.getState().doc.channels.find((item) => item.id === channelId);
  const song = Math.max(1, engine.duration());
  useMixStore.getState().checkpoint();
  let points = channel && channel.automation.pan.length >= 2 ? [...channel.automation.pan] : [{ t: 0, pan: channel?.pan ?? 0 }, { t: song, pan: channel?.pan ?? 0 }];
  const apply = (ev: PointerEvent) => {
    const raw = Math.max(0, Math.min(song, ((ev.clientX - rect.left) / Math.max(rect.width, 1)) * song));
    const t = snapTime(raw, snap, bpm, beatsPerBar, song);
    const pan = Math.max(-1, Math.min(1, ((rect.bottom - ev.clientY) / Math.max(rect.height, 1)) * 2 - 1));
    const q = Math.round(t * 20) / 20;
    const next = points.filter((point) => Math.abs(point.t - q) > 0.045);
    next.push({ t: q, pan: Math.round(pan * 100) / 100 });
    next.sort((a, b) => a.t - b.t);
    points = next;
    useMixStore.getState().livePan(channelId, points);
  };
  apply(event.nativeEvent);
  const move = (ev: PointerEvent) => apply(ev);
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function Strip({
  channelId,
  engine,
  selected,
  onSelect,
  onLive,
  onCommit,
  onOpen,
  onBypass,
  onMove,
}: {
  channelId: string;
  engine: MixEngine;
  selected: boolean;
  onSelect: () => void;
  onLive: (id: string, patch: { faderDb?: number; pan?: number; mute?: boolean; solo?: boolean; inputGain?: number }) => void;
  onCommit: (id: string, patch: { faderDb?: number; pan?: number }) => void;
  onOpen: (channelId: string, insertId: string) => void;
  onBypass: (channelId: string, insertId: string) => void;
  onMove: (channelId: string, insertId: string, dir: -1 | 1) => void;
}) {
  const channel = useMixStore((s) => s.doc.channels.find((item) => item.id === channelId));
  const addInsert = useMixStore((s) => s.addInsert);
  if (!channel) return null;
  function dragFader(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const apply = (clientY: number, alt: boolean, shift: boolean) => {
      if (alt) {
        engine.setFader(channel!.id, 0);
        onLive(channel!.id, { faderDb: 0 });
        return;
      }
      const position = 1 - (clientY - rect.top) / rect.height;
      const db = snapUnity(shift ? channel!.faderDb : faderToDb(position));
      engine.setFader(channel!.id, db);
      onLive(channel!.id, { faderDb: db });
    };
    apply(event.clientY, event.altKey, false);
    const move = (ev: PointerEvent) => apply(ev.clientY, ev.altKey, ev.shiftKey);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      onCommit(channel!.id, { faderDb: useMixStore.getState().doc.channels.find((item) => item.id === channelId)?.faderDb || 0 });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  return (
    <div className={selected ? "strip is-on" : "strip"} onClick={onSelect}>
      <strong style={{ color: channel.color }}>{channel.name}</strong>
      <button type="button" className="slot" onClick={() => onOpen(channel.id, channel.inserts[0]?.id || "")}>EQ</button>
      {channel.inserts.slice(0, 8).map((insert) => (
        <button key={insert.id} type="button" draggable className={insert.bypass ? "slot is-bypass" : "slot"} onClick={() => onOpen(channel.id, insert.id)} onDoubleClick={() => onBypass(channel.id, insert.id)} onDragStart={(event) => event.dataTransfer.setData("text/plain", insert.id)} onDrop={(event) => { event.preventDefault(); onMove(channel.id, event.dataTransfer.getData("text/plain"), -1); }}>
          {insert.type}
        </button>
      ))}
      {channel.sends.map((send) => (
        <label key={send.id} className="send">{send.bus === "aux-reverb" ? "R" : "D"}
          <input type="range" min={0} max={1} step={0.01} value={send.level} onChange={(e) => {
            const level = Number(e.target.value);
            engine.setSend(channel.id, send.bus, level);
            onLive(channel.id, {});
            useMixStore.setState((state) => ({
              doc: {
                ...state.doc,
                channels: state.doc.channels.map((item) => item.id === channel.id ? { ...item, sends: item.sends.map((row) => row.id === send.id ? { ...row, level } : row) } : item),
              },
            }));
          }} />
        </label>
      ))}
      <div className="pan">{channel.pan.toFixed(2)}</div>
      <input type="range" min={-1} max={1} step={0.01} value={channel.pan} onChange={(e) => { const pan = Number(e.target.value); engine.setPan(channel.id, pan); onLive(channel.id, { pan }); }} />
      <div className="fader-read">{formatDb(channel.faderDb)}</div>
      <div className="fader-row">
        <div className="fader" onPointerDown={dragFader} onDoubleClick={() => { engine.setFader(channel.id, 0); onCommit(channel.id, { faderDb: 0 }); }}>
          <i style={{ bottom: `${dbToFader(channel.faderDb) * 100}%` }} />
        </div>
        <canvas className="meter" data-id={channel.id} width={10} height={140} />
      </div>
      <select
        className="add-insert"
        value=""
        onChange={(event) => {
          const type = event.target.value as "compressor" | "gate" | "deesser" | "limiter" | "reverb" | "delay" | "widen";
          if (type) addInsert(channel.id, type);
        }}
      >
        <option value="">+ 效果</option>
        <option value="compressor">压缩</option>
        <option value="gate">噪声门</option>
        <option value="deesser">齿音</option>
        <option value="limiter">限幅</option>
        <option value="reverb">混响</option>
        <option value="delay">延迟</option>
        <option value="widen">宽度</option>
      </select>
      <div className="ms">
        <button type="button" className={channel.mute ? "is-on" : ""} onClick={() => { onCommit(channel.id, {}); onLive(channel.id, { mute: !channel.mute }); }}>M</button>
        <button type="button" className={channel.solo ? "is-on solo" : ""} onClick={() => onLive(channel.id, { solo: !channel.solo })}>S</button>
      </div>
    </div>
  );
}

function paintMeter(canvas: HTMLCanvasElement, reading: { peak: number; rms: number; hold: number }) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#111";
  ctx.fillRect(0, 0, w, h);
  const peakY = dbToY(reading.peak, h);
  const rmsY = dbToY(reading.rms, h);
  ctx.fillStyle = "#30d158";
  ctx.fillRect(0, peakY, w / 2, h - peakY);
  ctx.fillStyle = "#ffd60a";
  ctx.fillRect(w / 2, rmsY, w / 2, h - rmsY);
  if (reading.peak > 0) {
    ctx.fillStyle = "#ff453a";
    ctx.fillRect(0, 0, w, 4);
  }
}

function dbToY(db: number, height: number) {
  const clamped = Math.max(-60, Math.min(6, db));
  return height - ((clamped + 60) / 66) * height;
}
