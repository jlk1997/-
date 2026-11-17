import { useEffect, useMemo, useRef, useState } from "react";
import Taro, { useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../../utils/auth";
import { usePlayer } from "../../../contexts/PlayerProvider";
import { useCreditsOptional } from "../../../contexts/CreditsProvider";
import { useActiveJobOptional } from "../../../contexts/ActiveJobProvider";
import { studioPage } from "../../../constants/routes";
import { persistActiveGeneration } from "../../../utils/restoreGeneration";
import { showError, showSuccess } from "../../../components/ui";
import { isWeapp, type Clip, type Lane, type Node, type Pack, type PackScope, type Session, type Variant } from "../types";

async function waitForJob(jobId: string) {
  for (let i = 0; i < 80; i += 1) {
    const job = await vibeApi.getJob(jobId);
    if (job.status === "failed" || job.status === "cancelled") throw new Error(job.status);
    if (job.status === "audio_ready" || job.status === "post_processing" || job.status === "completed") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 1400));
  }
  throw new Error("timeout");
}

export function useWorkbenchSession(variant: Variant) {
  const router = useRouter();
  const { copy, locale } = useLocale();
  const w = copy.workbenchUi;
  const { playTrack } = usePlayer();
  const creditsCtx = useCreditsOptional();
  const activeJobCtx = useActiveJobOptional();
  const workId = String(router.params.workId || "");
  const incomingPackId = String(router.params.packId || "");
  const incomingNeed = String(router.params.need || "");
  const wantPro = router.params.want === "pro";
  const appliedQueryPack = useRef(false);
  const [session, setSession] = useState<Session | null>(null);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [scope, setScope] = useState<PackScope>("official");
  const [need, setNeed] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [ab, setAb] = useState<"a" | "b" | "c">("a");
  const [heard, setHeard] = useState(false);
  const [rackOpen, setRackOpen] = useState(variant === "pro" ? false : true);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [pubTitle, setPubTitle] = useState("");
  const [pubDesc, setPubDesc] = useState("");
  const [pubPrice, setPubPrice] = useState("0");
  const [pubKind, setPubKind] = useState("scene");
  const [selectedClipId, setSelectedClipId] = useState("");
  const [regionStart, setRegionStart] = useState(0);
  const [regionEnd, setRegionEnd] = useState(8);
  const [demandBrief, setDemandBrief] = useState("");
  const [demandBid, setDemandBid] = useState("0");
  const [pubNeeds, setPubNeeds] = useState<string[]>([]);
  const [selectedLaneId, setSelectedLaneId] = useState("master");
  const [claimedDemands, setClaimedDemands] = useState<
    Array<{ id: string; brief: string; work_title?: string; bid_credits: number; status: string; claimed_by_id?: string | null }>
  >([]);
  const openedOnLanes = useRef(false);

  const nextUrl = studioPage("workbenchLite", { workId });

  useEffect(() => {
    bootstrapAuth();
    if (!workId) {
      setLoading(false);
      return;
    }
    if (!isLoggedIn()) {
      requireAuth(nextUrl);
      setLoading(false);
      return;
    }
    if (variant === "pro" && isWeapp) {
      Taro.redirectTo({
        url: studioPage("workbenchLite", { workId, ...(wantPro ? { want: "pro" } : {}) }),
      });
      return;
    }
    Promise.all([
      vibeApi.openWorkbenchSession(workId),
      vibeApi.listEffectPacks(isWeapp ? "official" : "all", isWeapp ? "weapp" : "h5"),
    ])
      .then(async ([sess, list]) => {
        setSession(sess as Session);
        setPacks(list);
        if (sess.last_result_audio_url) {
          setHeard(true);
          setAb("b");
        }
        if (incomingNeed) setNeed(incomingNeed);
        if (sess.mix_graph.nodes?.length) setRackOpen(true);
        if (incomingPackId && !appliedQueryPack.current) {
          const pack = list.find((row) => row.id === incomingPackId);
          if (pack && sess.applied_pack_id !== incomingPackId) {
            appliedQueryPack.current = true;
            try {
              const next = await vibeApi.applyEffectPack(sess.id, pack.id, sess.intensity ?? 1);
              setSession(next as Session);
              setRackOpen(true);
              showSuccess(w.applyOk);
            } catch {
              showError(w.applyFail);
            }
          } else if (pack) {
            appliedQueryPack.current = true;
          }
        }
        if (sess.last_render_job_id) {
          void followBenchJob(String(sess.last_render_job_id), sess.source_title || "", {
            healDone: !sess.last_result_work_id,
            sourceId: sess.source_work_id,
          });
        }
      })
      .catch(() => showError(w.loadFail))
      .finally(() => setLoading(false));
  }, [workId, variant, nextUrl, wantPro, w.loadFail, w.narrowProHint]);

  useEffect(() => {
    if (variant !== "pro" || isWeapp) return;
    void vibeApi
      .listPackDemands("mine")
      .then((rows) => setClaimedDemands(rows.filter((row) => row.status === "claimed")))
      .catch(() => setClaimedDemands([]));
  }, [variant, session?.id]);

  useEffect(() => {
    if (variant === "pro" && session?.edit_lanes?.ready && !openedOnLanes.current) {
      openedOnLanes.current = true;
      setTimelineOpen(true);
    }
  }, [variant, session?.edit_lanes?.ready]);

  const visiblePacks = useMemo(() => {
    return packs.filter((pack) => {
      if (isWeapp) return pack.is_official;
      if (need) {
        const tags = [...(pack.need_tags || []), ...(pack.tags || [])].map((tag) => String(tag).toLowerCase());
        if (!tags.includes(need)) return false;
      }
      if (scope === "official") return pack.is_official;
      if (scope === "community") return !pack.is_official && pack.status === "published";
      return !pack.is_official;
    });
  }, [packs, scope, need]);

  function packTitle(pack: Pack) {
    const keyed = pack.slug ? w.packs[pack.slug as keyof typeof w.packs] : undefined;
    if (keyed?.title) return keyed.title;
    return pack.locale_titles?.[locale] || pack.title;
  }

  function packHint(pack: Pack) {
    const keyed = pack.slug ? w.packs[pack.slug as keyof typeof w.packs] : undefined;
    return keyed?.hint || pack.description || "";
  }

  function persistBenchJob(jobId: string, title?: string, sourceId?: string) {
    const startedAt = new Date().toISOString();
    const source = sourceId || session?.source_work_id || workId;
    persistActiveGeneration({
      jobId,
      returnUrl: nextUrl,
      startedAt,
      jobType: "workbench",
      remixSource: { workId: source, title: title || session?.source_title || "", intent: "workbench" },
    });
    activeJobCtx?.setJob({
      jobId,
      progress: 0,
      status: "running",
      message: "",
      returnUrl: nextUrl,
      startedAt,
      jobType: "workbench",
      remixSourceTitle: title || session?.source_title,
    });
  }

  async function followBenchJob(jobId: string, title?: string, opts?: { healDone?: boolean; sourceId?: string }) {
    try {
      const job = await vibeApi.getJob(jobId);
      if (["failed", "cancelled"].includes(job.status)) {
        return;
      }
      if (["completed", "audio_ready", "post_processing"].includes(job.status)) {
        if (opts?.healDone) {
          const fresh = (await vibeApi.openWorkbenchSession(workId)) as Session;
          setSession(fresh);
          if (fresh.last_result_audio_url) {
            setHeard(true);
            setAb("b");
          }
        }
        return;
      }
      persistBenchJob(jobId, title, opts?.sourceId);
      setBusy("bounce");
      await waitForJob(jobId);
      const fresh = (await vibeApi.openWorkbenchSession(workId)) as Session;
      setSession(fresh);
      setAb("b");
      showSuccess(w.bounceOk);
    } catch {
      /* keep the last saved session */
    } finally {
      setBusy((cur) => (cur === "bounce" ? "" : cur));
    }
  }

  function playSource(which: "a" | "b" | "c") {
    if (!session) return;
    const after = which === "b" && Boolean(session.last_result_work_id && session.last_result_audio_url);
    const prev = which === "c" && Boolean(session.previous_result_work_id && session.previous_result_audio_url);
    if (which === "b" && !after) return;
    if (which === "c" && !prev) return;
    playTrack(
      workToPlayerTrack({
        id: after ? session.last_result_work_id || session.source_work_id : prev ? session.previous_result_work_id || session.source_work_id : session.source_work_id,
        title: after ? session.last_result_title || w.compareB : prev ? session.previous_result_title || w.compareC : session.source_title || w.compareA,
        audio_url: after
          ? session.last_result_audio_url || ""
          : prev
            ? session.previous_result_audio_url || ""
            : session.source_audio_url || "",
        cover_url: after ? session.last_result_cover_url || session.source_cover_url : session.source_cover_url,
      }),
    );
    setAb(which);
    setHeard(true);
  }

  async function refreshSession(next?: Session | Record<string, unknown>) {
    if (next && "id" in next && "mix_graph" in next) {
      setSession(next as Session);
      return;
    }
    if (!session) return;
    const fresh = (await vibeApi.openWorkbenchSession(workId)) as Session;
    setSession(fresh);
  }

  async function onApply(pack: Pack) {
    if (!session || !requireAuth(nextUrl)) return;
    setBusy(`pack-${pack.id}`);
    try {
      if (!pack.owned && (pack.price_credits || 0) > 0) {
        await vibeApi.purchaseEffectPack(pack.id);
        await creditsCtx?.refresh();
        setPacks((prev) => prev.map((row) => (row.id === pack.id ? { ...row, owned: true } : row)));
        showSuccess(w.buyOk);
      }
      const next = (await vibeApi.applyEffectPack(session.id, pack.id, session.intensity ?? 1)) as Session;
      await refreshSession(next);
      setRackOpen(true);
      showSuccess(next.lane_pack_degraded ? w.lanePackHint : w.applyOk);
    } catch (err) {
      const status = (err as { status?: number })?.status;
      showError(status === 402 ? w.insufficient : w.applyFail);
    } finally {
      setBusy("");
    }
  }

  async function onIntensity(value: number) {
    if (!session) return;
    const next = await vibeApi.patchWorkbenchSession(session.id, { intensity: value });
    await refreshSession(next);
  }

  async function onPreview(pack: Pack) {
    if (!requireAuth(nextUrl)) return;
    setBusy(`preview-${pack.id}`);
    try {
      const queued = await vibeApi.previewEffectPack(pack.id);
      let url = queued.preview_url;
      if (!url && queued.job_id) {
        showSuccess(w.previewing);
        const job = await waitForJob(queued.job_id);
        url = (job.result as { preview_url?: string } | null)?.preview_url;
        if (!url) {
          const again = await vibeApi.previewEffectPack(pack.id);
          url = again.preview_url;
        }
      }
      if (url) {
        playTrack(
          workToPlayerTrack({
            id: `pack-preview-${pack.id}`,
            title: packTitle(pack),
            audio_url: url,
            cover_url: session?.source_cover_url,
          }),
        );
      }
    } catch {
      showError(w.applyFail);
    } finally {
      setBusy("");
    }
  }

  async function onBounce() {
    if (!session || !requireAuth(nextUrl)) return;
    setBusy("bounce");
    try {
      const queued = await vibeApi.renderWorkbench(session.id);
      persistBenchJob(queued.job_id, session.source_title || "", session.source_work_id);
      showSuccess(w.bounceOk);
      await creditsCtx?.refresh();
      await waitForJob(queued.job_id);
      const fresh = (await vibeApi.openWorkbenchSession(workId)) as Session;
      setSession(fresh);
      setAb("b");
      setHeard(true);
    } catch (err) {
      const status = (err as { status?: number })?.status;
      showError(status === 402 ? w.insufficient : w.bounceFail);
    } finally {
      setBusy("");
    }
  }

  async function onRegen(kind: "extend" | "remelt" | "same_style", seconds = 15, withRegion = false) {
    if (!session || !requireAuth(nextUrl)) return;
    setBusy(`regen-${kind}-${seconds}`);
    try {
      const queued = await vibeApi.regenWorkbench(
        session.id,
        kind,
        seconds,
        withRegion ? { start: regionStart, end: regionEnd, id: "sel" } : undefined,
      );
      persistBenchJob(queued.job_id, session.source_title || "", session.source_work_id);
      showSuccess(w.regenQueued);
      await creditsCtx?.refresh();
      await waitForJob(queued.job_id);
      const fresh = (await vibeApi.openWorkbenchSession(workId)) as Session;
      setSession(fresh);
      const latestTake = [...(fresh.mix_graph.regions || [])]
        .flatMap((region) => region.takes || [])
        .filter((take) => take.audio_url)
        .at(-1);
      if (latestTake?.audio_url) {
        playTrack(
          workToPlayerTrack({
            id: latestTake.work_id || latestTake.id,
            title: latestTake.kind || w.takePreview,
            audio_url: latestTake.audio_url,
            cover_url: fresh.source_cover_url,
          }),
        );
        setHeard(true);
      }
    } catch (err) {
      const status = (err as { status?: number })?.status;
      showError(status === 402 ? w.insufficient : w.regenFail);
      await refreshSession();
    } finally {
      setBusy("");
    }
  }

  async function onUndo() {
    if (!session) return;
    try {
      const next = await vibeApi.undoWorkbenchSession(session.id);
      await refreshSession(next);
      setAb("a");
      showSuccess(session.can_undo ? w.undoStep : w.undoToA);
    } catch {
      const graph = { ...session.mix_graph, nodes: [], clips: [], intensity: 1 };
      const next = await vibeApi.patchWorkbenchSession(session.id, { mix_graph: graph, intensity: 1 });
      await refreshSession(next);
      setAb("a");
      showSuccess(w.undoToA);
    }
  }

  async function patchLanes(lanes: Lane[]) {
    if (!session) return;
    const next = await vibeApi.patchWorkbenchSession(session.id, { lanes });
    await refreshSession(next);
  }

  async function patchGraph(mix_graph: Session["mix_graph"]) {
    if (!session) return;
    const next = await vibeApi.patchWorkbenchSession(session.id, { mix_graph: mix_graph as unknown as Record<string, unknown> });
    await refreshSession(next);
  }

  async function patchNode(nodeId: string, params: Record<string, number>) {
    if (!session) return;
    const nodes = session.mix_graph.nodes.map((node) =>
      node.id === nodeId ? { ...node, params: { ...(node.params || {}), ...params } } : node,
    );
    await patchGraph({ ...session.mix_graph, nodes });
  }

  async function removeNode(nodeId: string) {
    if (!session) return;
    const nodes = session.mix_graph.nodes.filter((node) => node.id !== nodeId);
    await patchGraph({ ...session.mix_graph, nodes });
  }

  async function setVocalSend(amount: number) {
    if (!session) return;
    const mix = Math.max(0, Math.min(0.6, amount));
    const nodes = session.mix_graph.nodes.filter((node) => node.id !== "vocal-send");
    if (mix > 0.01) {
      nodes.push({ id: "vocal-send", type: "reverb", target: "vocal", origin: "user", params: { mix } });
    }
    await patchGraph({ ...session.mix_graph, nodes });
  }

  async function addNode(type: string, target?: string) {
    if (!session) return;
    const lane = target || selectedLaneId || "master";
    const id = `${type}-${lane}`.slice(0, 32);
    if (session.mix_graph.nodes.some((node) => node.id === id || (node.type === type && (node.target || "master") === lane))) return;
    const nodes = [...session.mix_graph.nodes, { id, type, target: lane, origin: "user", params: {} }];
    await patchGraph({ ...session.mix_graph, nodes });
    setRackOpen(true);
  }

  async function addAi(type: "ai_denoise" | "ai_vocal" | "ai_remaster") {
    await addNode(type, type === "ai_vocal" ? selectedLaneId || "master" : "master");
  }

  function playTake(take: { id: string; audio_url?: string }) {
    if (!take.audio_url || !session) return;
    playTrack(
      workToPlayerTrack({
        id: take.id,
        title: take.id,
        audio_url: take.audio_url,
        cover_url: session.source_cover_url,
      }),
    );
  }

  async function prepareLanes(profile: "full" | "vocals2" = "full") {
    if (!session) return;
    setBusy("lanes");
    try {
      const res = await vibeApi.separateWorkbenchLanes(session.id, profile);
      if (res.session) await refreshSession(res.session);
      else if (res.job_id) {
        showSuccess(w.lanesPending);
        await waitForJob(res.job_id);
        await refreshSession();
      }
      showSuccess(w.lanesReady);
    } catch {
      showError(w.lanesFail);
    } finally {
      setBusy("");
    }
  }

  async function onTrim(start: number, end: number) {
    if (!session) return;
    const next = await vibeApi.trimWorkbenchSession(session.id, start, end);
    await refreshSession(next);
  }

  async function onSplitSelected(at: number) {
    if (!session || !selectedClipId) return;
    const clips = [...(session.mix_graph.clips || [])];
    const index = clips.findIndex((clip) => clip.id === selectedClipId);
    if (index < 0) return;
    const clip = clips[index];
    if (!(clip.start + 0.08 < at && at < clip.end - 0.08)) return;
    const left = { ...clip, id: `${clip.id.slice(0, 28)}a`, end: Number(at.toFixed(3)) };
    const right = {
      ...clip,
      id: `${clip.id.slice(0, 28)}b`,
      start: Number(at.toFixed(3)),
      offset: Number((clip.offset + (at - clip.start)).toFixed(3)),
    };
    clips.splice(index, 1, left, right);
    await patchGraph({ ...session.mix_graph, clips });
    setSelectedClipId(left.id);
  }

  async function patchClip(clipId: string, patch: Partial<Clip>) {
    if (!session) return;
    const clips = (session.mix_graph.clips || []).map((clip) => {
      if (clip.id !== clipId) return clip;
      const next = { ...clip, ...patch };
      if (patch.start != null && patch.offset == null && (clip.src === "work" || clip.id === "master-trim")) {
        next.offset = patch.start;
      }
      return next;
    });
    await patchGraph({ ...session.mix_graph, clips });
  }

  function onPickRegion(time: number) {
    const start = Math.max(0, Number(time.toFixed(1)));
    const end = Math.min(Math.max(duration, start + 0.5), Number((start + 8).toFixed(1)));
    setRegionStart(start);
    setRegionEnd(Math.max(start + 0.5, end));
  }

  async function onActivateTake(regionId: string, takeId: string) {
    if (!session) return;
    setBusy(`take-${takeId}`);
    try {
      const next = await vibeApi.activateWorkbenchTake(session.id, regionId, takeId);
      await refreshSession(next);
      showSuccess(w.takeActive);
    } catch {
      showError(w.applyFail);
    } finally {
      setBusy("");
    }
  }

  async function onDeliverDemand(demandId: string) {
    if (!session) return;
    setBusy(`deliver-${demandId}`);
    try {
      await vibeApi.deliverPackDemand(demandId, { session_id: session.id });
      setClaimedDemands((rows) => rows.filter((row) => row.id !== demandId));
      showSuccess(w.deliverOk);
    } catch {
      showError(w.publishFail);
    } finally {
      setBusy("");
    }
  }

  async function onPublish() {
    if (!session) return;
    setBusy("publish");
    try {
      const pre = await vibeApi.publishEffectPackPreflight(session.id);
      if (pre.forbids_external_audio) {
        showError(w.publishNoExternal);
        return;
      }
      if (!pre.ok) {
        showError(w.publishFail);
        return;
      }
      await vibeApi.publishEffectPack(
        session.id,
        {
          title: pubTitle,
          description: pubDesc,
          price_credits: Number(pubPrice) || 0,
          kind: pubKind,
          need_tags: pubNeeds.length ? pubNeeds : need ? [need] : [],
        },
        "h5",
      );
      setPublishOpen(false);
      showSuccess(pre.has_clips ? w.publishHasClips : w.publishOk);
    } catch {
      showError(w.publishFail);
    } finally {
      setBusy("");
    }
  }

  async function onCreateDemand() {
    const sourceId = session?.source_work_id || workId;
    const brief = demandBrief.trim();
    if (!sourceId || !brief) return;
    if (brief.length < 4) {
      showError(w.demandTooShort);
      return;
    }
    setBusy("demand");
    try {
      await vibeApi.createPackDemand({
        work_id: sourceId,
        brief,
        need_tags: need ? [need] : [],
        bid_credits: Number(demandBid) || 0,
      });
      setDemandBrief("");
      showSuccess(w.demandOk);
    } catch {
      showError(w.publishFail);
    } finally {
      setBusy("");
    }
  }

  const nodes = session?.mix_graph.nodes || [];
  const lanes = session?.mix_graph.lanes || [];
  const clips = session?.mix_graph.clips || [];
  const coach = variant === "pro" && !nodes.length;
  const laneReady = Boolean(session?.edit_lanes?.ready);
  const appliedPack = packs.find((row) => row.id === session?.applied_pack_id);
  const appliedName = appliedPack ? packTitle(appliedPack) : session?.applied_pack_slug || "";
  const duration = Number(session?.source_duration || 30);
  const masterTrim = clips.find((clip) => clip.id === "master-trim" || clip.lane === "master");

  return {
    w,
    copy,
    variant,
    workId,
    session,
    packs,
    scope,
    setScope,
    need,
    setNeed,
    loading,
    busy,
    ab,
    rackOpen,
    setRackOpen,
    timelineOpen,
    setTimelineOpen,
    publishOpen,
    setPublishOpen,
    pubTitle,
    setPubTitle,
    pubDesc,
    setPubDesc,
    pubPrice,
    setPubPrice,
    pubKind,
    setPubKind,
    pubNeeds,
    setPubNeeds,
    selectedLaneId,
    setSelectedLaneId,
    selectedClipId,
    setSelectedClipId,
    regionStart,
    setRegionStart,
    regionEnd,
    setRegionEnd,
    demandBrief,
    setDemandBrief,
    demandBid,
    setDemandBid,
    claimedDemands,
    visiblePacks,
    nodes,
    lanes,
    clips,
    heard,
    coach,
    laneReady,
    appliedName,
    duration,
    masterTrim,
    packTitle,
    packHint,
    playSource,
    onApply,
    onIntensity,
    onPreview,
    onBounce,
    onRegen,
    onUndo,
    patchLanes,
    patchNode,
    removeNode,
    addAi,
    addNode,
    setVocalSend,
    playTake,
    prepareLanes,
    onTrim,
    onSplitSelected,
    patchClip,
    onPickRegion,
    onActivateTake,
    onDeliverDemand,
    onPublish,
    onCreateDemand,
  };
}

export type WorkbenchModel = ReturnType<typeof useWorkbenchSession>;
export type { Node, Lane, Clip, Pack };
