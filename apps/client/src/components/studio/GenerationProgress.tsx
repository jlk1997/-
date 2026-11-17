import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { vibeApi } from "../../services/api";
import { usePlayerTransport } from "../../contexts/PlayerProvider";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { syncAfterFeedMutation } from "../../utils/feedMutationSync";
import { useActiveJobOptional } from "../../contexts/ActiveJobProvider";
import { PlayTrackButton } from "../player/PlayTrackButton";
import { Button, StatusLine, ProgressRail, RingGauge, CelebrationSheet, Icon, CreditsPaywallSheet, showSuccess, showError } from "../ui";
import { PublishDialog } from "../community/PublishDialog";
import { VariationPicker } from "./VariationPicker";
import { WorkQualityCard } from "./WorkQualityCard";
import { ProgressTimeline } from "./ProgressTimeline";
import { GenerationReveal } from "./GenerationReveal";
import { AiGeneratedBadge } from "../legal/AiGeneratedBadge";
import { clearActiveGeneration } from "../../utils/generationStorage";
import { setItem, getItem } from "../../platform/storage";
import { scheduleClearActiveGeneration } from "../../utils/restoreGeneration";
import type { RemixSourceSnapshot } from "../../utils/generationStorage";
import { openWorkDetail } from "../../utils/workNav";
import { openRadioPage } from "../../utils/navigation";
import { trackActivationOnce } from "../../utils/activationEvents";
import { hapticLight } from "../../utils/haptic";
import { copyWeappCreatorLink } from "../../packageCreator/WeappH5Bridge";
import { creatorPage, CREATOR_PAGE_ROUTES } from "../../constants/routes";
import { goShipBand } from "../../packageCreator/nextActionNav";
import { openWorkbench } from "../../utils/workbenchNav";
import {
  canPreview,
  COMPOSE_ETA_SECONDS,
  isSpuriousJobFailure,
  isTerminalJobStatus,
  phaseLabelKey,
  progressStepIndex,
} from "../../utils/generationPhases";
import { formatQueueWait, resolveGenerationError } from "../../utils/generationErrors";
import "./GenerationProgress.scss";

type CompletedStep = { work_id: string; step: number; audio_url?: string; title?: string };

type Props = {
  jobId: string;
  onComplete?: (result: { workIds?: string[]; playlistId?: string }) => void;
  onRetry?: () => void;
  onEditIntent?: () => void;
  showActions?: boolean;
  returnUrl?: string;
  startedAt?: string;
  jobType?: "single" | "playlist" | "variations" | "remix" | "workbench";
  remixSource?: RemixSourceSnapshot;
};

const STAGE_IDS = ["stageWrite", "stageArrange", "stageSing", "stageHear"] as const;

function stageIndex(phase: string | null | undefined): number {
  const step = progressStepIndex(phase);
  if (step <= 1) return 0;
  if (step === 2) return 1;
  if (step === 3) return 2;
  return 3;
}

export function GenerationProgress({
  jobId,
  onComplete,
  onRetry,
  onEditIntent,
  showActions = true,
  returnUrl = "/pages/create/index",
  startedAt: startedAtProp,
  jobType = "single",
  remixSource: remixSourceProp,
}: Props) {
  const { copy } = useLocale();
  const g = copy.generation;
  const ge = copy.generationErrors as Record<string, { title: string; body: string; primary: string; secondary?: string }>;
  const phases = g.phases as Record<string, string>;
  const { playTrack } = usePlayerTransport();
  const creditsCtx = useCreditsOptional();
  const activeJobCtx = useActiveJobOptional();
  const stopRef = useRef<(() => void) | null>(null);
  const startedAtRef = useRef(startedAtProp || new Date().toISOString());
  const mountedAtRef = useRef(Date.now());

  useEffect(() => {
    mountedAtRef.current = Date.now();
    startedAtRef.current = startedAtProp || new Date().toISOString();
    setStatus("running");
    setPhase("queued");
    setProgress(0);
    setStepLabel("");
    setMessage(g.running);
    setCompletedSteps([]);
    setResult(null);
    setError(null);
    setIsPartialFailure(false);
    setCancelling(false);
    setEtaSeconds(null);
    composingStartedRef.current = null;
    pendingFirstCelebrateRef.current = false;
    celebratedRef.current = false;
    queuedTwoTakesRef.current = false;
    setPreflightFail(false);
    setCelebrateOpen(false);
    setPickedWorkId(null);
  }, [jobId, g.running, startedAtProp]);

  const [status, setStatus] = useState("running");
  const [phase, setPhase] = useState<string | null>("queued");
  const [progress, setProgress] = useState(0);
  const [stepLabel, setStepLabel] = useState("");
  const [message, setMessage] = useState(g.running);
  const [completedSteps, setCompletedSteps] = useState<CompletedStep[]>([]);
  const [result, setResult] = useState<{
    workIds?: string[];
    playlistId?: string;
    workId?: string;
    audioUrl?: string;
    title?: string;
    coverUrl?: string;
    moods?: string[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [trackerWarning, setTrackerWarning] = useState(false);
  const [stalled, setStalled] = useState(false);
  const stalledRef = useRef(false);
  const [priorityLane, setPriorityLane] = useState(false);
  const [postProcessDegraded, setPostProcessDegraded] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [isPartialFailure, setIsPartialFailure] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null);
  const [queueLine, setQueueLine] = useState("");
  const [publishOpen, setPublishOpen] = useState(false);
  const [celebrateOpen, setCelebrateOpen] = useState(false);
  const [celebrateVariant, setCelebrateVariant] = useState<"publish" | "playlist" | "firstTrack">("publish");
  const celebratedRef = useRef(false);
  const queuedTwoTakesRef = useRef(false);
  const pendingFirstCelebrateRef = useRef(false);
  const [preflightFail, setPreflightFail] = useState(false);
  const composingStartedRef = useRef<string | null>(null);
  const [showMemberUpsell, setShowMemberUpsell] = useState(false);
  const [paywallOpen, setPaywallOpen] = useState(false);
  const [showFailMore, setShowFailMore] = useState(false);
  const [composeTipIndex, setComposeTipIndex] = useState(0);
  const [remixContext, setRemixContext] = useState<RemixSourceSnapshot | null>(remixSourceProp ?? null);
  const [pickedWorkId, setPickedWorkId] = useState<string | null>(null);

  const composeTips = useMemo(
    () => [g.composingTip1, g.composingTip2, g.composingTip3].filter(Boolean),
    [g.composingTip1, g.composingTip2, g.composingTip3]
  );

  useEffect(() => {
    if (phase !== "composing" && !phase?.startsWith("track_")) {
      setComposeTipIndex(0);
      return;
    }
    const id = setInterval(() => {
      setComposeTipIndex((i) => (i + 1) % Math.max(composeTips.length, 1));
    }, 8000);
    return () => clearInterval(id);
  }, [phase, composeTips.length]);

  const progressSteps = useMemo(
    () =>
      STAGE_IDS.map((id) => ({
        id,
        label: (g as Record<string, string>)[id] || id,
      })),
    [g]
  );

  const progressCurrent = stageIndex(phase);
  const gaugeLabel = phase ? phases[phaseLabelKey(phase)] || message : message;
  const previewReady = canPreview(phase, result as Record<string, unknown> | null);

  useEffect(() => {
    if (remixSourceProp) setRemixContext(remixSourceProp);
  }, [remixSourceProp]);

  useEffect(() => {
    if (remixContext?.title || !remixContext?.workId) return;
    let cancelled = false;
    vibeApi
      .getWork(remixContext.workId)
      .then((work) => {
        if (!cancelled) {
          setRemixContext((prev) => (prev ? { ...prev, title: work.title } : prev));
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [remixContext?.workId, remixContext?.title]);

  useEffect(() => {
    if (!activeJobCtx) return;
    const current = activeJobCtx.job;
    if (current?.jobId === jobId && !isTerminalJobStatus(current.status)) {
      activeJobCtx.patchJob({
        returnUrl,
        jobType,
        remixSourceTitle: remixContext?.title,
      });
      return;
    }
    activeJobCtx.setJob({
      jobId,
      progress: current?.jobId === jobId ? current.progress : 0,
      status: current?.jobId === jobId ? current.status : "running",
      message: current?.jobId === jobId ? current.message : g.running,
      returnUrl,
      phase: current?.jobId === jobId ? current.phase : "queued",
      startedAt: startedAtRef.current,
      jobType,
      remixSourceTitle: remixContext?.title,
    });
    // Only seed context once per job — ongoing updates come from trackJob patchJob
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  useEffect(() => {
    if (phase !== "composing" && !phase?.startsWith("track_")) {
      setEtaSeconds(null);
      return;
    }
    if (!composingStartedRef.current) {
      composingStartedRef.current = new Date().toISOString();
    }
    const tick = () => {
      const anchor = composingStartedRef.current || startedAtRef.current;
      const elapsed = (Date.now() - new Date(anchor).getTime()) / 1000;
      const remaining = Math.max(0, Math.round(COMPOSE_ETA_SECONDS - elapsed));
      setEtaSeconds(remaining);
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, [phase]);

  const onJobUpdateRef = useRef<(data: Parameters<Parameters<typeof vibeApi.trackJob>[1]>[0]) => void>(() => {});
  onJobUpdateRef.current = (data) => {
    if (data.tracker_error === "connection") {
      setTrackerWarning(true);
      return;
    }
    if (data.tracker_error === "not_found") {
      setError(g.failed);
      setErrorCode("GENERATION_FAILED");
      setStatus("failed");
      return;
    }
    setTrackerWarning(false);

    if (data.priority_lane) setPriorityLane(true);
    if (data.job_type === "remix" && data.remix_source?.work_id) {
      setRemixContext((prev) => ({
        workId: data.remix_source!.work_id,
        title: prev?.title || "",
        intent: data.remix_source!.remix_intent || prev?.intent,
      }));
    }
    setStatus(data.status);
    setPhase(data.phase ?? null);
    if (data.phase === "composing" || data.phase?.startsWith("track_")) {
      if (!composingStartedRef.current) composingStartedRef.current = new Date().toISOString();
    }
    const pct = Math.round((data.progress || 0) * 100);
    setProgress(pct);

    if (data.status === "running" || data.status === "pending" || data.status === "audio_ready" || data.status === "post_processing") {
      setError(null);
      setErrorCode(null);
      setIsPartialFailure(false);
    }

    if (
      data.status === "failed" &&
      isSpuriousJobFailure({
        status: data.status,
        progress: data.progress,
        error_message: data.error_message,
        error_code: data.error_code,
        startedMsAgo: Date.now() - mountedAtRef.current,
        trackerClosed: data.trackerClosed,
      })
    ) {
      return;
    }

    if (data.compose_eta_seconds != null && (data.phase === "composing" || data.phase?.startsWith("track_"))) {
      setEtaSeconds(Math.max(0, data.compose_eta_seconds));
    }
    const queued = data as { queue_ahead?: number | null; estimated_wait_seconds?: number | null };
    if (data.status === "pending" && queued.queue_ahead != null && queued.estimated_wait_seconds != null) {
      setQueueLine(formatQueueWait(g.queueWait, queued.queue_ahead, queued.estimated_wait_seconds));
    } else if (data.status !== "pending") {
      setQueueLine("");
    }
    if (data.current_step != null && data.total_steps != null) {
      setStepLabel(
        g.stepProgress.replace("{current}", String(data.current_step)).replace("{total}", String(data.total_steps))
      );
    }
    const waiting = data.status === "pending" || data.phase === "queued";
    const progressed =
      data.stalled !== true &&
      (data.progress !== undefined || data.phase) &&
      (data.phase !== phase || Math.round((data.progress || 0) * 100) !== progress || data.status !== status);
    const showStall = Boolean(data.stalled) || (stalledRef.current && !progressed && !isTerminalJobStatus(data.status));
    stalledRef.current = showStall;
    setStalled(showStall);
    const msg = showStall
      ? g.stillWorking
      : waiting
        ? g.waitingToStart
        : data.status_message || (data.status === "completed" ? g.completed : g.running);
    setMessage(msg);

    const workId = data.result?.work_id as string | undefined;
    const audioUrl = data.result?.audio_url as string | undefined;
    const title = data.result?.title as string | undefined;
    const coverUrl = data.result?.cover_url as string | undefined;
    const workIds = data.result?.work_ids as string[] | undefined;
    const playlistId = data.result?.playlist_id as string | undefined;
    const partial = Boolean(data.result?.partial);

    activeJobCtx?.patchJob({
      progress: pct,
      status: data.status,
      message: msg,
      phase: data.phase,
      workId: workId || workIds?.[0],
    });

    const steps = data.result?.completed_steps as CompletedStep[] | undefined;
    if (steps?.length) setCompletedSteps(steps);

    if (workId || workIds || playlistId) {
      setResult((prev) => ({
        ...prev,
        workIds: workIds ?? prev?.workIds,
        playlistId: playlistId ?? prev?.playlistId,
        workId: workId ?? prev?.workId,
        audioUrl: audioUrl ?? prev?.audioUrl,
        title: title ?? prev?.title,
        coverUrl: coverUrl ?? prev?.coverUrl,
      }));
    }

    if (data.status === "completed" || data.phase === "done") {
      const postState = data.result?.post_process_state as string | undefined;
      setPostProcessDegraded(postState === "pending" || postState === "degraded");
      if (data.result?.cover_url) {
        setResult((prev) => ({ ...prev, coverUrl: data.result?.cover_url as string }));
      }
      const res = {
        workIds: workIds ?? (workId ? [workId] : undefined),
        playlistId,
        workId,
        audioUrl,
        title,
        coverUrl,
      };
      setResult((prev) => ({ ...prev, ...res }));
      scheduleClearActiveGeneration();
      setTimeout(() => activeJobCtx?.setJob(null), 30_000);
      onComplete?.({ workIds: res.workIds, playlistId });
      const isFirstComplete = !getItem("activation:done:activation_first_generate_complete");
      void trackActivationOnce("activation_first_generate_complete", { job_id: jobId });
      const balance = creditsCtx?.balance ?? 0;
      const multiTake = (workIds?.length || 0) > 1;
      if (isFirstComplete && jobType === "single" && (!creditsCtx?.isMember || balance < 3) && !multiTake) {
        setShowMemberUpsell(true);
        pendingFirstCelebrateRef.current = true;
      } else if (multiTake) {
        pendingFirstCelebrateRef.current = false;
      }
      void creditsCtx?.refresh();
    }
    if (data.status === "failed") {
      const resolved = resolveGenerationError(ge, data.error_code, data.error_message);
      setError(resolved.title);
      setErrorCode(data.error_code || "GENERATION_FAILED");
      const delivered = (workIds?.length || 0) || (steps?.length || 0);
      if (partial && delivered > 0) {
        setIsPartialFailure(true);
      } else {
        setIsPartialFailure(false);
      }
      clearActiveGeneration();
      activeJobCtx?.patchJob({ status: "failed", message: resolved.title, phase: "failed" });
      void creditsCtx?.refresh();
    }
    if (data.status === "cancelled") {
      void creditsCtx?.refresh();
    }
  };

  useEffect(() => {
    stopRef.current?.();
    stopRef.current = vibeApi.trackJob(jobId, (data) => onJobUpdateRef.current(data));
    return () => {
      stopRef.current?.();
      stopRef.current = null;
    };
  }, [jobId]);

  const stepTitle = (step: number, title?: string) =>
    title || g.stepProgress.replace("{current}", String(step + 1)).replace("{total}", "?");

  const playerTracks = completedSteps
    .filter((s) => s.audio_url)
    .map((s) =>
      workToPlayerTrack(
        { id: s.work_id, title: stepTitle(s.step, s.title), audio_url: s.audio_url!, moods: [] },
        { source: "generation", isOwner: true }
      )
    );

  const isProcessing = !error && !isTerminalJobStatus(status);
  const showReveal = status === "completed" || phase === "done";
  const workIdCount = result?.workIds?.length ?? 0;
  const isPreviewPick = workIdCount > 1 && !pickedWorkId;
  const isTwoTakePick = workIdCount === 2 && !pickedWorkId;
  const singleWorkId = pickedWorkId || (isPreviewPick ? undefined : result?.workId || result?.workIds?.[0]);

  useEffect(() => {
    if (queuedTwoTakesRef.current) return;
    if (!showReveal || workIdCount !== 2 || playerTracks.length < 2) return;
    queuedTwoTakesRef.current = true;
    playTrack(playerTracks[0], { queue: playerTracks, navigate: false });
  }, [showReveal, workIdCount, playerTracks, playTrack]);

  useEffect(() => {
    if (!showReveal || celebratedRef.current) return;
    if (jobType === "playlist" && result?.playlistId) {
      celebratedRef.current = true;
      setCelebrateVariant("playlist");
      setCelebrateOpen(true);
    }
  }, [showReveal, jobType, result?.playlistId]);

  async function cancelJob() {
    const confirm = await Taro.showModal({
      title: g.cancelJob,
      content: phase === "composing" ? g.running : g.cancelJob,
    });
    if (!confirm.confirm) return;
    setCancelling(true);
    try {
      await vibeApi.cancelJob(jobId);
      stopRef.current?.();
      setStatus("cancelled");
      setMessage(g.cancelledProgress);
      clearActiveGeneration();
      activeJobCtx?.setJob(null);
      void creditsCtx?.refresh();
      Taro.showToast({ title: g.cancelled, icon: "none" });
    } catch {
      Taro.showToast({ title: g.cancelFail, icon: "none" });
    } finally {
      setCancelling(false);
    }
  }

  function listenFirst() {
    trackActivationOnce("activation_first_listen", { job_id: jobId });
    const first = playerTracks[0];
    if (first) {
      playTrack(first, { queue: playerTracks, navigate: true });
      return;
    }
    if (result?.audioUrl && singleWorkId) {
      playTrack(
        workToPlayerTrack(
          { id: singleWorkId, title: result.title || "Track", audio_url: result.audioUrl, moods: result.moods || [] },
          { source: "generation", isOwner: true }
        ),
        { navigate: true }
      );
      return;
    }
    if (singleWorkId) {
      vibeApi.getWork(singleWorkId).then((w) => {
        playTrack(workToPlayerTrack(w, { source: "generation", isOwner: true }), { navigate: true });
      });
    }
  }

  function tryVariations() {
    if (!singleWorkId) return;
    setItem("create:seedWorkId", singleWorkId);
    setItem("create:mode", "variation");
    if (result?.title) setItem("create:seedIntent", result.title);
    Taro.switchTab({ url: "/pages/create/index" });
  }

  const errorDetail = errorCode ? resolveGenerationError(ge, errorCode, error).body : "";
  const failedPrimary = errorCode ? resolveGenerationError(ge, errorCode, error).primary : g.retry;
  const failedSecondary = errorCode && ge[errorCode]?.secondary ? ge[errorCode].secondary! : null;

  function backToCreate() {
    // 清理当前失败任务并回到创作首页，避免用户卡死在失败界面。
    // onEditIntent 会清掉 activeJob → 创作页自动切回输入表单（即创作首页）。
    clearActiveGeneration();
    activeJobCtx?.setJob(null);
    if (onEditIntent) {
      onEditIntent();
      return;
    }
    stopRef.current?.();
    Taro.switchTab({ url: "/pages/create/index" }).catch(() => {
      Taro.reLaunch({ url: "/pages/create/index" }).catch(() => {});
    });
  }

  function handleFailedSecondary() {
    if (errorCode === "QUEUE_TIMEOUT") {
      void Taro.showModal({
        title: ge.QUEUE_TIMEOUT?.title || g.failed,
        content: g.queueTimeoutHelp,
        showCancel: false,
      });
      return;
    }
    if (errorCode === "MINIMAX_CONTENT") {
      onEditIntent?.();
    }
  }

  const sublabel = message || stepLabel || phases[phaseLabelKey(phase)] || g.running;
  const etaLabel = etaSeconds != null && etaSeconds > 0 ? g.etaRemaining.replace("{n}", String(etaSeconds)) : "";
  const remixBannerTitle = g.remixBasedOn.replace(
    "{title}",
    remixContext?.title?.trim() || "…"
  );

  return (
    <View className="gen-progress">
      <AiGeneratedBadge className="gen-progress__ai-badge" prominent />
      {remixContext?.workId && (
        <View className="gen-progress__remix" onClick={() => openWorkDetail(remixContext.workId)}>
          <View className="gen-progress__remix-icon">
            <Icon name="remix" size="sm" accent />
          </View>
          <View className="gen-progress__remix-text">
            <Text className="gen-progress__remix-title">{remixBannerTitle}</Text>
            {remixContext.intent?.trim() && (
              <Text className="gen-progress__remix-intent">
                {g.remixIntentLine.replace("{intent}", remixContext.intent.trim())}
              </Text>
            )}
          </View>
          <Text className="gen-progress__remix-link">{g.remixViewSource}</Text>
        </View>
      )}

      {!showReveal && (
      <View className="gen-progress__orbs">
        <View className="gen-progress__orb gen-progress__orb--1" />
        <View className="gen-progress__orb gen-progress__orb--2" />
      </View>
      )}

      {isPartialFailure && (completedSteps.length || result?.workIds?.length || 0) > 0 ? (
        <>
          <StatusLine tone="info">{jobType === "playlist" ? g.partialPlaylistTitle : g.partialTakesTitle}</StatusLine>
          <Text className="gen-progress__partial-body typo-meta">
            {(jobType === "playlist" ? g.partialPlaylistBody : g.partialTakesBody).replace(
              "{n}",
              String(completedSteps.length || result?.workIds?.length || 0),
            )}
          </Text>
        </>
      ) : error ? (
        <>
          <StatusLine tone="error">{error}</StatusLine>
          {errorDetail ? <Text className="gen-progress__refund typo-meta">{errorDetail}</Text> : null}
          {errorCode === "MINIMAX_BALANCE" ? null : <Text className="gen-progress__refund typo-meta">{g.creditsRefunded}</Text>}
        </>
      ) : status === "cancelled" ? (
        <StatusLine tone="info">{g.cancelledProgress}</StatusLine>
      ) : showReveal ? null : (
        <StatusLine tone="loading">{message}</StatusLine>
      )}

      {!showReveal && !error && (
      <View className="gen-progress__layout">
        <ProgressTimeline steps={progressSteps} current={progressCurrent} className="gen-progress__timeline" />

        <View className="gen-progress__main">
          <View className={phase === "composing" ? "gen-progress__viz gen-progress__viz--composing" : "gen-progress__viz"}>
            <RingGauge value={progress} max={100} label={gaugeLabel} sublabel={sublabel} />
            <ProgressRail pct={progress} className="gen-progress__rail" />
          </View>
          <View className="gen-progress__meta">
            <Text className="typo-meta">{sublabel}</Text>
            <Text className="typo-meta">{(status === "pending" || phase === "queued") && progress === 0 ? g.waitingToStart : `${progress}%`}</Text>
          </View>
          {isProcessing && showActions ? (
            <Button variant="ghost" size="sm" loading={cancelling} onClick={cancelJob}>
              {g.cancelJob}
            </Button>
          ) : null}
          {priorityLane && status === "pending" && (
            <Text className="gen-progress__priority typo-meta">{g.priorityLane}</Text>
          )}
          {trackerWarning && (
            <Text className="gen-progress__tracker-warn typo-meta">{g.trackerReconnecting}</Text>
          )}
          {stalled && !error && (
            <Text className="gen-progress__tracker-warn typo-meta">{g.stillWorking}</Text>
          )}
          {queueLine ? <Text className="gen-progress__eta typo-meta">{queueLine}</Text> : null}
          {etaLabel && <Text className="gen-progress__eta typo-meta">{etaLabel}</Text>}
          {(phase === "composing" || phase?.startsWith("track_")) && composeTips.length > 0 && (
            <Text className="gen-progress__tip typo-meta">{composeTips[composeTipIndex]}</Text>
          )}

          {previewReady && singleWorkId && result?.audioUrl && isProcessing && (
            <View className="gen-progress__preview">
              <View className="gen-progress__preview-cover">
                {result.coverUrl ? (
                  <Image className="gen-progress__preview-img" src={result.coverUrl} mode="aspectFill" />
                ) : (
                  <View className="gen-progress__preview-img gen-progress__preview-img--placeholder" />
                )}
              </View>
              <Text className="gen-progress__preview-hint">{g.previewReady}</Text>
              <PlayTrackButton
                track={workToPlayerTrack(
                  {
                    id: singleWorkId,
                    title: result.title || "Track",
                    audio_url: result.audioUrl,
                    moods: result.moods || [],
                  },
                  { source: "generation", isOwner: true }
                )}
                label={g.previewListen}
              />
            </View>
          )}
        </View>
      </View>
      )}

      {completedSteps.length > 0 && isProcessing && (jobType === "playlist" || jobType === "variations") && (
        <Text className="gen-progress__incremental typo-meta">
          {g.incrementalPreview.replace("{n}", String(completedSteps.length))}
        </Text>
      )}

      {completedSteps.length > 0 && (
        <View className="gen-progress__steps">
          {completedSteps.map((s) => (
            <View key={s.work_id} className="gen-progress__step">
              <Text className="gen-progress__step-title">{s.title || `#${s.step + 1}`}</Text>
              {s.audio_url && (
                <PlayTrackButton
                  track={workToPlayerTrack(
                    { id: s.work_id, title: stepTitle(s.step, s.title), audio_url: s.audio_url, moods: [] },
                    { source: "generation", isOwner: true }
                  )}
                  queue={playerTracks}
                  label={g.previewStep}
                />
              )}
            </View>
          ))}
        </View>
      )}

      {error && !isPartialFailure && (
        <View className="gen-progress__actions">
          {onRetry && (
            <Button variant="primary" size="sm" onClick={onRetry}>
              {failedPrimary}
            </Button>
          )}
          {jobType === "workbench" ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={() =>
                returnUrl.includes("workbench")
                  ? Taro.navigateTo({ url: returnUrl })
                  : openWorkbench(remixContext?.workId || singleWorkId || "")
              }
            >
              {copy.workbenchUi.staySession}
            </Button>
          ) : null}
          {showFailMore ? (
            <>
              {failedSecondary && (
                <Button variant="ghost" size="sm" onClick={handleFailedSecondary}>
                  {failedSecondary}
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={backToCreate}>
                {g.backToCreate}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => openRadioPage()}>
                {g.failRadio}
              </Button>
            </>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setShowFailMore(true)}>
              {g.failMore}
            </Button>
          )}
        </View>
      )}

      {isPartialFailure && (
        <View className="gen-progress__actions">
          {completedSteps.length > 0 && (
            <Button variant="primary" size="sm" onClick={listenFirst}>
              {g.listenNow}
            </Button>
          )}
          {showFailMore ? (
            <>
              {result?.playlistId && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => Taro.navigateTo({ url: `/pages/playlist/index?id=${result.playlistId}` })}
                >
                  {g.savePartialPlaylist}
                </Button>
              )}
              {onRetry && (
                <Button variant="ghost" size="sm" onClick={onRetry}>
                  {g.retry}
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={backToCreate}>
                {g.backToCreate}
              </Button>
            </>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setShowFailMore(true)}>
              {g.failMore}
            </Button>
          )}
        </View>
      )}

      {showReveal && singleWorkId && jobType !== "playlist" && !isPreviewPick && (
        <GenerationReveal
          workId={singleWorkId}
          title={result?.title}
          coverUrl={result?.coverUrl}
          moods={result?.moods}
          fromWorkbench={jobType === "workbench"}
          sourceWorkId={remixContext?.workId}
          onTitleChange={(nextTitle) => setResult((prev) => (prev ? { ...prev, title: nextTitle } : prev))}
        />
      )}

      {showReveal && isTwoTakePick && (
        <View className="gen-progress__two-take-hero">
          <Text className="gen-progress__listen-hero-title">{g.reveal.pickTwo}</Text>
          <Text className="gen-progress__listen-hero-hint">{g.reveal.nextHint}</Text>
        </View>
      )}

      {showActions && showReveal && result?.workIds && result.workIds.length > 1 && (
        <VariationPicker
          jobId={jobId}
          workIds={result.workIds}
          hero={workIdCount === 2}
          showNext
          onPicked={(workId) => {
            setPickedWorkId(workId);
            pendingFirstCelebrateRef.current = false;
          }}
        />
      )}

      {showReveal && postProcessDegraded && (
        <View className="gen-progress__degraded-card">
          <StatusLine tone="warning">{g.postProcessDegraded}</StatusLine>
          {singleWorkId ? (
            <Button
              variant="secondary"
              size="sm"
              loading={reprocessing}
              onClick={async () => {
                if (!singleWorkId || reprocessing) return;
                setReprocessing(true);
                hapticLight();
                try {
                  await vibeApi.reprocessWork(singleWorkId).catch(() => vibeApi.triggerPostProcess(singleWorkId));
                  showSuccess(copy.worksUi.reprocessQueued);
                  setPostProcessDegraded(false);
                } catch {
                  showError(copy.worksUi.deleteFail);
                } finally {
                  setReprocessing(false);
                }
              }}
            >
              {g.postProcessFix}
            </Button>
          ) : null}
        </View>
      )}

      {showActions && showReveal && singleWorkId && jobType !== "playlist" && !isPreviewPick && (
        <WorkQualityCard
          workId={singleWorkId}
          title={result?.title}
          moods={result?.moods}
          doorOnly
          onScores={(s) => {
            const originalityRisk = Number(s.preflight?.originality_risk || 0);
            const fail =
              s.suggestion_key === "loudness" ||
              s.suggestion_key === "duration" ||
              s.suggestion_key === "originality" ||
              originalityRisk >= 80;
            setPreflightFail(fail);
            if (fail) {
              pendingFirstCelebrateRef.current = false;
              setCelebrateOpen(false);
              return;
            }
            if (pendingFirstCelebrateRef.current) {
              pendingFirstCelebrateRef.current = false;
              setCelebrateVariant("firstTrack");
              setCelebrateOpen(true);
            }
          }}
          onLab={
            jobId && (result?.workIds?.length || 0) > 1
              ? () => Taro.navigateTo({ url: `/packageStudio/pages/variation-lab/index?jobId=${jobId}` })
              : () => tryVariations()
          }
          onOptimize={(hint) => {
            setItem("create:optimizeHint", hint);
            tryVariations();
          }}
          onRemelt={() => {
            const benchId = (jobType === "workbench" && remixContext?.workId) || singleWorkId;
            if (benchId) openWorkbench(benchId);
          }}
        />
      )}
      {showActions && showReveal && preflightFail && (
        <StatusLine tone="error">{g.preflightFail}</StatusLine>
      )}

      {showActions && showReveal && jobType === "playlist" && (
        <View className="gen-progress__actions">
          <Button variant="primary" size="sm" onClick={listenFirst}>
            {g.listenNow}
          </Button>
          {result?.playlistId && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => Taro.navigateTo({ url: `/pages/playlist/index?id=${result.playlistId}` })}
            >
              {g.viewPlaylist}
            </Button>
          )}
        </View>
      )}

      {showActions && showReveal && singleWorkId && jobType === "single" && result?.playlistId && (
        <View className="gen-progress__actions">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => Taro.navigateTo({ url: `/pages/playlist/index?id=${result.playlistId}` })}
          >
            {g.viewPlaylist}
          </Button>
        </View>
      )}

      {publishOpen && singleWorkId && (
        <PublishDialog
          workTitle={result?.title || "Track"}
          onClose={() => setPublishOpen(false)}
          onPublish={async (caption, opts) => {
            const post = await vibeApi.createPost(singleWorkId, caption, {
              allow_remix: opts.allowRemix,
              license: opts.license,
              content_compliance_acknowledged: opts.contentComplianceAcknowledged,
            });
            await syncAfterFeedMutation(creditsCtx, post);
            trackActivationOnce("activation_first_publish", { work_id: singleWorkId });
            Taro.showToast({ title: g.publishSuccess, icon: "success" });
            setPublishOpen(false);
            setCelebrateVariant("publish");
            setCelebrateOpen(true);
          }}
        />
      )}

      <CelebrationSheet
        open={celebrateOpen}
        variant={celebrateVariant}
        onClose={() => {
          setCelebrateOpen(false);
          setShowMemberUpsell(false);
        }}
        shareTitle={result?.title}
        workId={singleWorkId}
        beautifyLabel={celebrateVariant === "firstTrack" && singleWorkId ? copy.generation.reveal.beautify : undefined}
        onBeautify={
          celebrateVariant === "firstTrack" && singleWorkId
            ? () => {
                const id = singleWorkId;
                setCelebrateOpen(false);
                openWorkbench(id);
              }
            : undefined
        }
        releaseLabel={singleWorkId ? copy.generation.reveal.shipToStores : undefined}
        releaseDisabled={preflightFail}
        releaseHint={preflightFail ? g.preflightFail : undefined}
        onRelease={
          singleWorkId
            ? () => {
                setCelebrateOpen(false);
                goShipBand(singleWorkId);
              }
            : undefined
        }
        communityLabel={celebrateVariant !== "publish" && singleWorkId ? copy.celebrationUi.goCommunity : undefined}
        onCommunity={
          celebrateVariant !== "publish" && singleWorkId
            ? () => {
                setCelebrateOpen(false);
                setPublishOpen(true);
              }
            : undefined
        }
        clipsLabel={singleWorkId ? copy.celebrationUi.goClips : undefined}
        onClips={
          singleWorkId
            ? () => {
                const id = singleWorkId;
                setCelebrateOpen(false);
                Taro.navigateTo({ url: creatorPage("work", { workId: id }) });
              }
            : undefined
        }
        radioLabel={singleWorkId ? copy.celebrationUi.goRadio : undefined}
        onRadio={
          singleWorkId
            ? () => {
                const id = singleWorkId;
                setCelebrateOpen(false);
                void (async () => {
                  let station: string | undefined;
                  try {
                    const trial = (await vibeApi.startRadioTrial(id)) as { work_id?: string; station?: string };
                    station = typeof trial.station === "string" ? trial.station : undefined;
                    Taro.showToast({ title: copy.creatorUi.radioTrialLive, icon: "success" });
                    openRadioPage({ workId: trial.work_id || id, station });
                    return;
                  } catch {
                    /* still open the station so the creator can hear it */
                  }
                  openRadioPage({ workId: id, station });
                })();
              }
            : undefined
        }
        labLabel={jobId && (jobType === "variations" || (result?.workIds?.length || 0) > 1) ? copy.celebrationUi.goLab : undefined}
        onLab={
          jobId && (jobType === "variations" || (result?.workIds?.length || 0) > 1)
            ? () => {
                setCelebrateOpen(false);
                Taro.navigateTo({ url: `/packageStudio/pages/variation-lab/index?jobId=${jobId}` });
              }
            : undefined
        }
        passportLabel={celebrateVariant === "publish" && singleWorkId ? copy.celebrationUi.goPassport : undefined}
        onPassport={
          celebrateVariant === "publish" && singleWorkId
            ? () => {
                setCelebrateOpen(false);
                Taro.navigateTo({ url: creatorPage("passport", { workId: singleWorkId }) });
              }
            : undefined
        }
        connectorLabel={copy.celebrationUi.goConnector}
        onConnector={() => {
          setCelebrateOpen(false);
          if (process.env.TARO_ENV === "weapp") {
            void copyWeappCreatorLink(CREATOR_PAGE_ROUTES.accounts);
            return;
          }
          Taro.navigateTo({ url: creatorPage("accounts") });
        }}
        upsellLabel={showMemberUpsell ? copy.celebrationUi.memberUpsell : undefined}
        onUpsell={
          showMemberUpsell
            ? () => {
                setCelebrateOpen(false);
                setShowMemberUpsell(false);
                setPaywallOpen(true);
              }
            : undefined
        }
      />

      <CreditsPaywallSheet
        open={paywallOpen}
        requiredCredits={3}
        source="create_post_generate"
        initialTab="member"
        returnPath={returnUrl}
        onClose={() => setPaywallOpen(false)}
        onSuccess={() => setPaywallOpen(false)}
      />
    </View>
  );
}
