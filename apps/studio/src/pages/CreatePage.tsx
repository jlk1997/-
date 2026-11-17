import { generateIdempotencyKey, generationStateFromJob, vibeApi } from "@vibe-sorcery/api-client";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deskCopy } from "../copy";
import { useDeskPlayer } from "../player";

const MOODS = ["平静", "热烈", "忧郁", "明亮", "深夜"];

type Take = { id: string; title: string; url?: string };

export function CreatePage() {
  const copy = deskCopy();
  const navigate = useNavigate();
  const player = useDeskPlayer();
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => vibeApi.getPresets() });
  const [prompt, setPrompt] = useState("");
  const [preset, setPreset] = useState("");
  const [mood, setMood] = useState("平静");
  const [vocal, setVocal] = useState("female");
  const [bpm, setBpm] = useState(92);
  const [keyName, setKeyName] = useState("C");
  const [lyrics, setLyrics] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState<{ status?: string; progress?: number; phase?: string | null; result?: Record<string, unknown>; stalled?: boolean; status_message?: string } | null>(null);
  const stopRef = useRef<(() => void) | null>(null);
  useEffect(() => () => stopRef.current?.(), []);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("studio:draft") || "{}") as Partial<{ prompt: string; preset: string; mood: string; vocal: string; bpm: number; keyName: string; lyrics: string }>;
      if (saved.prompt) setPrompt(saved.prompt);
      if (saved.preset) setPreset(saved.preset);
      if (saved.mood) setMood(saved.mood);
      if (saved.vocal) setVocal(saved.vocal);
      if (saved.bpm) setBpm(saved.bpm);
      if (saved.keyName) setKeyName(saved.keyName);
      if (saved.lyrics) setLyrics(saved.lyrics);
    } catch {
      /* empty draft */
    }
  }, []);
  useEffect(() => {
    localStorage.setItem("studio:draft", JSON.stringify({ prompt, preset, mood, vocal, bpm, keyName, lyrics }));
  }, [bpm, keyName, lyrics, mood, preset, prompt, vocal]);

  const view = generationStateFromJob(job, { submitting });
  const takes = takesFrom(job?.result);

  async function generate() {
    if (!prompt.trim() || submitting) return;
    setSubmitting(true);
    setError("");
    setJob({ status: "pending", progress: 0, phase: "queued" });
    try {
      const created = await vibeApi.generateSingle({
        text_intent: prompt.trim(),
        lyrics: lyrics.trim() || undefined,
        lyrics_optimizer: !lyrics.trim(),
        bpm,
        key: keyName,
        moods: [mood],
        vocal: { vocal_gender: vocal, language: "zh" },
        preview_pick_count: 2,
        idempotencyKey: generateIdempotencyKey(),
        creative_spec: preset ? { preset_id: preset } : undefined,
      });
      setSubmitting(false);
      stopRef.current?.();
      stopRef.current = vibeApi.trackJob(created.id, (data) => {
        setJob(data);
      });
    } catch (err) {
      setSubmitting(false);
      setJob(null);
      setError(err instanceof Error ? err.message : copy.failed);
    }
  }

  function openMixer(workId: string) {
    navigate(`/mixer?work=${workId}&bpm=${bpm}&key=${encodeURIComponent(keyName)}`);
  }

  const stageIndex = view === "queued" || view === "submitting" ? 0 : view === "running" ? 1 : view === "takes_ready" ? 3 : view === "finalizing" || view === "done" ? 3 : 0;

  return (
    <div className="create">
      <section className="panel">
        <h1>{copy.create}</h1>
        <label>{copy.prompt}<textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="下雨夜的钢琴，人声很近" /></label>
        <div className="row wrap">
          <label>{copy.style}
            <select value={preset} onChange={(e) => setPreset(e.target.value)}>
              <option value="">不指定</option>
              {(presets.data || []).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label>{copy.mood}
            <select value={mood} onChange={(e) => setMood(e.target.value)}>{MOODS.map((item) => <option key={item}>{item}</option>)}</select>
          </label>
          <label>{copy.vocal}
            <select value={vocal} onChange={(e) => setVocal(e.target.value)}>
              <option value="female">女声</option>
              <option value="male">男声</option>
            </select>
          </label>
          <label>{copy.tempo}<input type="number" min={60} max={180} value={bpm} onChange={(e) => setBpm(Number(e.target.value) || 92)} /></label>
          <label>{copy.key}
            <select value={keyName} onChange={(e) => setKeyName(e.target.value)}>
              {["C", "D", "E", "F", "G", "A", "Am", "Em"].map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
        </div>
        <label>{copy.lyrics}<textarea rows={8} value={lyrics} onChange={(e) => setLyrics(e.target.value)} placeholder="留空就由引擎写词" /></label>
        {error ? <p className="error">{error}</p> : null}
        <button type="button" className="primary" disabled={submitting || !prompt.trim()} onClick={() => void generate()}>{copy.generate}</button>
      </section>
      <section className="panel">
        <h2>{view === "idle" ? copy.hold : copy.generating}</h2>
        {view === "idle" ? <p className="muted">{copy.studioLead}</p> : (
          <ol className="stages">
            {copy.stages.map((label, index) => (
              <li key={label} className={index <= stageIndex && view !== "failed" ? "is-on" : ""}>{label}</li>
            ))}
          </ol>
        )}
        {view === "stalled" ? <p>{copy.stalled}</p> : null}
        {view === "failed" ? <p className="error">{job?.status_message || copy.failed}</p> : null}
        {view !== "idle" && view !== "failed" ? <p className="muted">{job?.status_message || copy.generating} · {Math.round((job?.progress || 0) * 100)}%</p> : null}
        {takes.length > 0 ? <h3>{copy.takes}</h3> : null}
        <p className="muted">这次：{mood} · {vocal === "female" ? "女声" : "男声"} · {bpm} BPM · {keyName}{lyrics.trim() ? " · 已写词" : ""}</p>
        {takes.map((take) => (
          <article key={take.id} className="take">
            <strong>{take.title}</strong>
            {take.url ? <audio controls src={take.url} preload="none" /> : null}
            <div className="row">
              {take.url ? <button type="button" onClick={() => player.play({ id: take.id, title: take.title, url: take.url! })}>{copy.play}</button> : null}
              <button type="button" onClick={() => openMixer(take.id)}>{copy.openMixer}</button>
              <button type="button" onClick={() => navigate(`/release?work=${take.id}`)}>{copy.ship}</button>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}

function takesFrom(result: Record<string, unknown> | undefined): Take[] {
  if (!result) return [];
  const steps = result.completed_steps;
  if (Array.isArray(steps)) {
    return steps.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const row = item as { work_id?: string; title?: string; audio_url?: string };
      if (!row.work_id) return [];
      return [{ id: row.work_id, title: row.title || "Take", url: row.audio_url }];
    });
  }
  if (typeof result.work_id === "string") {
    return [{ id: result.work_id, title: String(result.title || "Take"), url: typeof result.audio_url === "string" ? result.audio_url : undefined }];
  }
  const ids = result.work_ids;
  if (Array.isArray(ids)) return ids.filter((id): id is string => typeof id === "string").map((id, index) => ({ id, title: `Take ${index + 1}` }));
  return [];
}
