import { vibeApi } from "@vibe-sorcery/api-client";
import { audioBufferToWav24, documentFromServer, documentToServer, emptyMix, MixEngine } from "@vibe-sorcery/mix-engine";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { deskCopy } from "../copy";
import { MixerDesk } from "../mixer/MixerDesk";
import { useMixStore } from "../mixer/store";

export function MixerPage() {
  const copy = deskCopy();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const workId = params.get("work") || "";
  const engine = useMemo(() => new MixEngine(), []);
  const doc = useMixStore((s) => s.doc);
  const loadDoc = useMixStore((s) => s.loadDoc);
  const markSaved = useMixStore((s) => s.markSaved);
  const undo = useMixStore((s) => s.undo);
  const redo = useMixStore((s) => s.redo);
  const toggleMixer = useMixStore((s) => s.toggleMixer);
  const toggleInspector = useMixStore((s) => s.toggleInspector);
  const toggleLoop = useMixStore((s) => s.toggleLoop);
  const splitAt = useMixStore((s) => s.splitAt);
  const selectedId = useMixStore((s) => s.selectedId);
  const liveChannel = useMixStore((s) => s.liveChannel);
  const [sessionId, setSessionId] = useState("");
  const [status, setStatus] = useState("");
  const [bounceOpen, setBounceOpen] = useState(false);
  const [audioRevision, setAudioRevision] = useState(0);
  const [bouncing, setBouncing] = useState(false);
  const works = useQuery({ queryKey: ["works"], queryFn: () => vibeApi.listWorks("newest", undefined, 20), enabled: !workId });

  useEffect(() => () => engine.dispose(), [engine]);

  useEffect(() => {
    if (!workId) return;
    let cancel = false;
    setStatus("打开工程…");
    void vibeApi.openWorkbenchSession(workId).then(async (session) => {
      if (cancel) return;
      const graph = documentFromServer(session.mix_graph, workId);
      if (session.source_title) {
        const reference = graph.channels.find((channel) => channel.kind === "reference");
        if (reference) reference.name = session.source_title;
      }
      loadDoc(graph);
      const bpm = Number(params.get("bpm"));
      const keyName = params.get("key");
      if (bpm >= 40 && bpm <= 240) useMixStore.getState().setTempo(bpm);
      if (keyName) useMixStore.setState((state) => ({ doc: { ...state.doc, tempo: { ...state.doc.tempo, key: keyName } } }));
      setSessionId(session.id);
      const lanes = session.edit_lanes as { urls?: Record<string, string>; flac_urls?: Record<string, string> };
      const urls = lanes.flac_urls && Object.keys(lanes.flac_urls).length ? lanes.flac_urls : lanes.urls || {};
      await Promise.all(
        Object.entries(urls).map(async ([name, url]) => {
          try {
            await engine.loadBuffer(name, url);
          } catch {
            /* a missing stem stays silent */
          }
        }),
      );
      if (session.source_audio_url) {
        try {
          await engine.loadBuffer("reference", session.source_audio_url);
        } catch {
          /* reference is optional */
        }
      }
      if (!Object.keys(urls).length && session.source_audio_url) {
        try {
          await engine.loadBuffer("other", session.source_audio_url);
        } catch {
          /* whole mix fallback */
        }
      }
      engine.setDocument(useMixStore.getState().doc);
      setAudioRevision((value) => value + 1);
      setStatus("");
    }).catch((err: Error) => setStatus(err.message || "工程没打开"));
    return () => {
      cancel = true;
    };
  }, [engine, loadDoc, workId]);

  useEffect(() => {
    if (!sessionId) return;
    const handle = window.setTimeout(() => {
      void vibeApi.patchWorkbenchSession(sessionId, { mix_graph: documentToServer(doc) }).then(() => markSaved()).catch(() => setStatus("自动保存失败，可手动再存"));
    }, 800);
    return () => window.clearTimeout(handle);
  }, [doc, markSaved, sessionId]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const meta = event.metaKey || event.ctrlKey;
      if (event.code === "Space") {
        event.preventDefault();
        if (engine.isPlaying()) engine.stop();
        else void engine.play();
      } else if (event.key === "Enter") engine.restart();
      else if (!meta && event.key.toLowerCase() === "c") toggleLoop();
      else if (!meta && event.key.toLowerCase() === "m") liveChannel(selectedId, { mute: !useMixStore.getState().doc.channels.find((c) => c.id === selectedId)?.mute });
      else if (!meta && event.key.toLowerCase() === "s") liveChannel(selectedId, { solo: !useMixStore.getState().doc.channels.find((c) => c.id === selectedId)?.solo });
      else if (!meta && event.key.toLowerCase() === "x") toggleMixer();
      else if (!meta && event.key.toLowerCase() === "i") toggleInspector();
      else if (meta && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      } else if (meta && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
      } else if (meta && event.key.toLowerCase() === "t") {
        event.preventDefault();
        splitAt(selectedId, engine.position(), engine.duration());
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [engine, liveChannel, redo, selectedId, splitAt, toggleInspector, toggleLoop, toggleMixer, undo]);

  async function save() {
    if (!sessionId) return;
    await vibeApi.patchWorkbenchSession(sessionId, { mix_graph: documentToServer(useMixStore.getState().doc) });
    markSaved();
    setStatus("已保存");
  }

  async function separate() {
    if (!sessionId) return;
    setStatus(copy.separating);
    const started = await vibeApi.separateWorkbenchLanes(sessionId);
    if (started.job_id) {
      await new Promise<void>((resolve) => {
        const stop = vibeApi.trackJob(started.job_id!, (data) => {
          if (data.status === "completed" || data.status === "failed") {
            stop();
            resolve();
          }
        });
      });
    }
    setStatus("分轨好了，重新打开这条音轨");
    navigate(`/mixer?work=${workId}&t=${Date.now()}`);
  }

  async function bounce(range: "all" | "loop") {
    setBouncing(true);
    try {
      const current = useMixStore.getState().doc;
      const start = range === "loop" && current.loop.enabled ? current.loop.start : 0;
      const end = range === "loop" && current.loop.enabled ? current.loop.end : engine.duration();
      const rendered = await engine.bounce(current, start, end || undefined);
      const blob = audioBufferToWav24(rendered);
      const result = await vibeApi.bounceWorkbench(sessionId, blob, `${current.channels[0] ? "" : ""}${workId ? "调音台" : "Bounce"}`);
      setStatus(`已打成新作品 ${result.title}。原曲没有被覆盖。`);
      setBounceOpen(false);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "打成失败");
    } finally {
      setBouncing(false);
    }
  }

  if (!workId) {
    return (
      <div className="panel">
        <h1>{copy.mixer}</h1>
        <p className="muted">{copy.honesty}</p>
        {(works.data || []).map((work) => (
          <button key={work.id} type="button" onClick={() => navigate(`/mixer?work=${work.id}`)}>{work.title}</button>
        ))}
      </div>
    );
  }

  return (
    <div className="mixer-page">
      <div className="row">
        <button type="button" onClick={() => void separate()}>{copy.separate}</button>
        {status ? <span className="muted">{status}</span> : null}
      </div>
      <MixerDesk engine={engine} audioRevision={audioRevision} onSave={() => void save()} onBounce={() => setBounceOpen(true)} />
      {bounceOpen ? (
        <div className="modal">
          <h2>{copy.bounce}</h2>
          <p>浏览器里打成你听到的声音，服务器只做响度检查和交付母带。结果是一首新的立体声，不覆盖原曲。</p>
          <div className="row">
            <button type="button" disabled={bouncing} onClick={() => void bounce("all")}>整首 WAV24 / MP3</button>
            <button type="button" disabled={bouncing} onClick={() => void bounce("loop")}>循环范围</button>
            <button type="button" onClick={() => setBounceOpen(false)}>取消</button>
          </div>
        </div>
      ) : null}
      {!doc.channels.length ? <p>{emptyMix().channels.length}</p> : null}
    </div>
  );
}
