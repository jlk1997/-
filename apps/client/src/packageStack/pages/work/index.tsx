import { useState, lazy, Suspense, useEffect, useRef } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro, { useRouter, useDidShow, useShareAppMessage } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { PageShell } from "../../../components/PageShell";
import { PublishDialog } from "../../../components/community/PublishDialog";
import { CommunityPostButton } from "../../../components/community/CommunityPostButton";
import { AiGeneratedBadge } from "../../../components/legal/AiGeneratedBadge";
import { RenameWorkSheet, type RenameWorkTarget } from "../../../components/community/RenameWorkSheet";
import type { DerivativeMode } from "../../../components/studio/DerivativeSheet";
import { ActionIconBar, Badge, BottomSheet, Button, Collapsible, Icon, Input, LoadingSkeleton, PostProcessBadges, ShareButton, Tag, showError, showSuccess, type ActionIconItem } from "../../../components/ui";
import { PlayTrackButton } from "../../../components/player/PlayTrackButton";
import { WorkLightEditor } from "../../../components/studio/WorkLightEditor";
import { WorkQualityCard } from "../../../components/studio/WorkQualityCard";
import { MoodVisualPreview } from "../../../components/studio/MoodVisualPreview";
import { MemberExportQuotas } from "../../../components/commercial/MemberExportQuotas";
import { TipSheet } from "../../../components/commercial/TipSheet";
import { saveFileFromUrl, saveVideoFromUrl } from "../../../platform/media";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../../utils/auth";
import { captureReferralFromQuery } from "../../../platform/referral";
import { useCreditsOptional } from "../../../contexts/CreditsProvider";
import { usePlayerTransport } from "../../../contexts/PlayerProvider";
import { syncAfterFeedMutation } from "../../../utils/feedMutationSync";
import { copyEmbedLink, shareWork, workSharePayload } from "../../../platform/share";
import { uploadFile } from "../../../platform/upload";
import { openWorkDetail } from "../../../utils/workNav";
import { commercePage, creatorPage, socialPage, stackPage, STUDIO_PAGE_ROUTES } from "../../../constants/routes";
import { canRemixWork } from "../../../utils/remixLicense";
import { showCoverUnavailable } from "../../../utils/coverUnavailable";
import { openRadioPage, openStackPage } from "../../../utils/navigation";
import { focusShipCompleteBand } from "../../../packageCreator/nextActionNav";
import { startSameStyle } from "../../../utils/sameStyleNav";
import { isDesktopWorkbench, openWorkbench } from "../../../utils/workbenchNav";
import { needsBeautifyMaster } from "../../../utils/workbenchWorks";
import { ShipCompleteCard } from "../../../packageCreator/ShipCompleteCard";
import { BeautifyDoorCard } from "../../../components/studio/BeautifyDoorCard";
import { SameStyleWall, type SameStyleWallItem } from "../../../components/community/SameStyleWall";
import { WorkReleaseTimeline } from "../../../components/studio/WorkReleaseTimeline";
import { hapticLight } from "../../../utils/haptic";
import { isPostProcessDegraded } from "../../../utils/postProcess";
import "./index.scss";

const LazyDerivativeSheet = lazy(() =>
  import("../../../components/studio/DerivativeSheet").then((m) => ({ default: m.DerivativeSheet }))
);

type WorkDetail = {
  id: string;
  title: string;
  description?: string;
  audio_url: string;
  hls_url?: string;
  cover_url?: string;
  moods?: string[];
  duration?: number;
  visibility?: string;
  parent_work_id?: string;
  arousal?: number;
  valence?: number;
  c2pa_verified?: boolean;
  c2pa_state?: string;
  post_process_status?: Record<string, unknown>;
  allow_remix?: boolean;
  license?: string;
  version?: number;
  release_status?: string;
  is_owner?: boolean;
  live_stores?: number;
  artist_name?: string;
  owner_username?: string;
  community_post_id?: string | null;
  community_caption?: string | null;
  from_workbench?: boolean;
  superseded_by_work_id?: string | null;
};

export default function WorkDetailPage() {
  const router = useRouter();
  const workId = router.params.workId || "";
  const { copy } = useLocale();
  const d = copy.workDetailUi;
  const w = copy.worksUi;
  const a = copy.actions;
  const creditsCtx = useCreditsOptional();
  const { patchTrackTitle, playTrack } = usePlayerTransport();
  const isH5 = process.env.TARO_ENV === "h5";

  const [work, setWork] = useState<WorkDetail | null>(null);
  const shipId = work?.superseded_by_work_id || work?.id || workId;
  const needsBeautify = work ? needsBeautifyMaster(work) : false;
  const autoPlayedRef = useRef("");

  useShareAppMessage(() =>
    work ? workSharePayload(work.id, work.title) : { title: copy.brand.name }
  );

  const [postId, setPostId] = useState<string | null>(null);
  const [postCaption, setPostCaption] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<RenameWorkTarget | null>(null);
  const [derivatives, setDerivatives] = useState<Array<{ id: string; title: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [publishOpen, setPublishOpen] = useState(false);
  const [derivative, setDerivative] = useState<{ mode: DerivativeMode } | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const [showMoodVisual, setShowMoodVisual] = useState(false);
  const [tipOpen, setTipOpen] = useState(false);
  const [duelSheetOpen, setDuelSheetOpen] = useState(false);
  const [duelOpponent, setDuelOpponent] = useState("");
  const [duelQuota, setDuelQuota] = useState<{ member_free_remaining?: number; pass_starts_remaining?: number; start_cost?: number } | null>(null);
  const [duelStarting, setDuelStarting] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [publicTips, setPublicTips] = useState<Array<{ username: string; credits: number; message?: string }>>([]);
  const [myUsername, setMyUsername] = useState<string | null>(null);
  const [authorUsername, setAuthorUsername] = useState<string | null>(null);
  const [remixChain, setRemixChain] = useState<{ chain_label: string; direct_remixes: number; generation_depth: number } | null>(null);
  const [engagementStats, setEngagementStats] = useState<{ listen_completes: number; resonance_avg: number } | null>(null);
  const [similar, setSimilar] = useState<SameStyleWallItem[]>([]);
  const [similarError, setSimilarError] = useState(false);
  const [timeline, setTimeline] = useState<{
    current_stage?: string;
    next_action?: { action?: string; label?: string };
    stages?: Array<{ stage: string; label: string; status: string; can_rerun?: boolean; has_receipt?: boolean }>;
  } | null>(null);
  const eco = copy.ecosystemUi;
  const social = copy.socialUi;
  const mv = copy.moodVisualUi;

  useDidShow(() => {
    captureReferralFromQuery(router.params as Record<string, unknown>);
    if (!workId) return;
    bootstrapAuth();
    setLoading(true);
    const loggedIn = isLoggedIn();
    Promise.all([
      vibeApi.getWork(workId) as Promise<WorkDetail>,
      loggedIn
        ? vibeApi.me().then((me) => {
            setMyUsername(me.username);
            return me;
          }).catch(() => null)
        : Promise.resolve(null),
      loggedIn ? vibeApi.getDerivatives(workId).catch(() => []) : Promise.resolve([]),
      vibeApi.getRemixChain(workId).catch(() => null),
      vibeApi.getPublicTips(workId).catch(() => ({ tips: [] })),
      vibeApi.getWorkEngagementStats(workId).catch(() => null),
      vibeApi.listSimilarWorks(workId).then((wall) => {
        setSimilarError(false);
        return wall;
      }).catch(() => {
        setSimilarError(true);
        return { works: [] };
      }),
    ])
      .then(([detail, _me, derivs, chain, tipsRes, stats, wall]) => {
        setWork(detail);
        setAuthorUsername(detail.owner_username || null);
        setPostId(detail.is_owner && detail.community_post_id ? detail.community_post_id : null);
        setPostCaption(detail.is_owner ? detail.community_caption ?? null : null);
        setDerivatives(derivs);
        if (chain) {
          setRemixChain({
            chain_label: chain.chain_label,
            direct_remixes: chain.direct_remixes,
            generation_depth: chain.generation_depth,
          });
        }
        setPublicTips(tipsRes.tips || []);
        if (stats) setEngagementStats({ listen_completes: stats.listen_completes, resonance_avg: stats.resonance_avg });
        setSimilar((wall.works || []).filter((row) => row.id !== workId));
        if (detail.is_owner && loggedIn) {
          vibeApi.getWorkTimeline(workId).then(setTimeline).catch(() => setTimeline(null));
        } else {
          setTimeline(null);
        }
        if (String(router.params.play || "") === "1" && detail.audio_url && autoPlayedRef.current !== detail.id) {
          autoPlayedRef.current = detail.id;
          playTrack(workToPlayerTrack(detail, { source: "works", isOwner: Boolean(detail.is_owner) }), { navigate: false });
        }
      })
      .catch(() => showError(d.loadFail))
      .finally(() => setLoading(false));
  });

  const published = work?.visibility === "public" || !!postId;
  const workNext = workId ? stackPage("work", { workId, play: "1" }) : undefined;
  const visibilityBadge =
    published ? "published" : work?.visibility === "unlisted" ? "unlisted" : "private";
  const track = work?.audio_url
    ? workToPlayerTrack(work, { source: "works", isOwner: Boolean(work.is_owner) })
    : undefined;

  async function publishWork(caption: string, opts: { allowRemix: boolean; license: string }) {
    if (!work || !requireAuth(workNext)) return;
    const post = await vibeApi.createPost(work.id, caption, {
      allow_remix: opts.allowRemix,
      license: opts.license,
      content_compliance_acknowledged: true,
    });
    setPostId(post.id || "1");
    await syncAfterFeedMutation(creditsCtx, post);
    showSuccess(w.publishSuccess);
    setPublishOpen(false);
  }

  async function unpublishWork() {
    if (!postId) return;
    const ok = await Taro.showModal({ title: w.unpublish, content: w.unpublishConfirm });
    if (!ok.confirm) return;
    try {
      await vibeApi.deletePost(postId);
      await syncAfterFeedMutation(creditsCtx);
      setPostId(null);
      showSuccess(w.unpublishSuccess);
    } catch {
      showError(w.deleteFail);
    }
  }

  async function deleteWork() {
    if (!work) return;
    const ok = await Taro.showModal({ title: d.deleteWork, content: d.deleteConfirm });
    if (!ok.confirm) return;
    try {
      await vibeApi.batchDeleteWorks([work.id]);
      showSuccess(w.deleteSuccess);
      Taro.navigateBack();
    } catch {
      showError(w.deleteFail);
    }
  }

  async function generateCover() {
    if (!work) return;
    try {
      await vibeApi.generateCoverImage(work.id);
      await creditsCtx?.refresh();
      showSuccess(w.coverSuccess);
      const refreshed = (await vibeApi.getWork(work.id)) as WorkDetail;
      setWork(refreshed);
    } catch {
      showError(w.deleteFail);
    }
  }

  async function uploadCover() {
    if (!work) return;
    let filePath: string | undefined;
    try {
      const pick = await Taro.chooseImage({ count: 1, sizeType: ["compressed"] });
      filePath = pick.tempFilePaths?.[0];
    } catch {
      return;
    }
    if (!filePath) return;
    try {
      Taro.showLoading({ title: w.coverUploading, mask: true });
      await uploadFile("/studio/cover-upload", filePath, "file", { work_id: work.id });
      Taro.hideLoading();
      showSuccess(w.coverUploaded);
      const refreshed = (await vibeApi.getWork(work.id)) as WorkDetail;
      setWork(refreshed);
    } catch {
      Taro.hideLoading();
      showError(w.coverUploadFail);
    }
  }

  async function triggerPostProcess() {
    if (!work || reprocessing) return;
    setReprocessing(true);
    hapticLight();
    try {
      if (isPostProcessDegraded(work.post_process_status)) {
        await vibeApi.reprocessWork(work.id).catch(() => vibeApi.triggerPostProcess(work.id));
      } else {
        await vibeApi.triggerPostProcess(work.id);
      }
      showSuccess(w.reprocessQueued);
      vibeApi.getWorkTimeline(work.id).then(setTimeline).catch(() => {});
    } catch {
      showError(w.reprocessFail);
    } finally {
      setReprocessing(false);
    }
  }

  function handleJourneyAction(action: string) {
    if (action === "reprocess") {
      void triggerPostProcess();
      return;
    }
    if (action === "beautify") {
      if (work?.id) openWorkbench(work.id);
      return;
    }
    if (action === "run_qc" || action === "release") {
      focusShipCompleteBand();
      return;
    }
    if (action === "wait" || action === "wait_review") {
      openStackPage(creatorPage("deliveries", { workId: shipId }));
      return;
    }
    if (action === "wait_revenue") {
      openStackPage(creatorPage("wallet"));
    }
  }

  async function doExportMv() {
    if (!work || !requireAuth(workNext)) return;
    setExporting("mv_video");
    try {
      const res = await vibeApi.exportMoodVisual(work.id);
      await creditsCtx?.refresh();
      if (process.env.TARO_ENV === "weapp") {
        await saveVideoFromUrl(res.download_url);
        showSuccess(mv.saveVideoSuccess);
      } else {
        await saveVideoFromUrl(res.download_url);
        showSuccess(mv.exportSuccess);
      }
    } catch (err: unknown) {
      const status = err && typeof err === "object" && "status" in err ? (err as { status?: number }).status : 0;
      const msg =
        status === 503
          ? mv.exportUnavailable
          : status === 400
            ? mv.exportNoContent
            : status === 402
              ? eco.exportFail
              : mv.exportFail;
      showError(msg);
    } finally {
      setExporting(null);
    }
  }

  async function doExport(exportType: "hq_mp3" | "hq_wav" | "stems" | "commercial_license") {
    if (!work || !requireAuth(workNext)) return;
    setExporting(exportType);
    try {
      const res = await vibeApi.exportWork(work.id, exportType);
      await creditsCtx?.refresh();
      if (exportType === "hq_wav") {
        const format = String(res.meta?.format || "");
        if (!res.download_url || format !== "wav" || res.meta?.fallback) {
          showError(eco.exportWavNotReady);
          return;
        }
        await saveFileFromUrl(res.download_url, `${work.title || "export"}.wav`);
      }
      if (exportType === "hq_mp3" && res.download_url) {
        await saveFileFromUrl(res.download_url, `${work.title || "export"}.mp3`);
      }
      if (exportType === "stems") {
        const isolation = String(res.meta?.isolation || "");
        const format = String(res.meta?.format || "");
        if (!res.download_url || format !== "zip" || isolation === "unavailable" || isolation === "full_mix_proxy") {
          showError(eco.exportStemsComingSoon);
          return;
        }
        await saveFileFromUrl(res.download_url, `${work.title || "export"}-stems.zip`);
      }
      if (res.license_id) {
        showSuccess(`${eco.exportSuccess}: ${res.license_id}`);
      } else {
        showSuccess(eco.exportSuccess);
      }
    } catch (err: unknown) {
      const status = err && typeof err === "object" && "status" in err ? (err as { status?: number }).status : 0;
      const msg =
        exportType === "stems" && (status === 400 || status === 501)
          ? eco.exportStemsComingSoon
          : exportType === "hq_wav" && (status === 400 || status === 503 || status === 501)
            ? eco.exportWavNotReady
          : status === 501
            ? eco.exportComingSoon
            : eco.exportFail;
      showError(msg);
    } finally {
      setExporting(null);
    }
  }

  function continueFromWork() {
    if (!work) return;
    startSameStyle(work.id, work.title);
  }

  async function refreshPublicTips() {
    if (!work?.id) return;
    const tipsRes = await vibeApi.getPublicTips(work.id).catch(() => ({ tips: [] }));
    setPublicTips(tipsRes.tips || []);
  }

  const canTip = !!authorUsername && !!myUsername && authorUsername !== myUsername;

  function goBack() {
    Taro.navigateBack().catch(() => Taro.switchTab({ url: "/pages/profile/index" }));
  }

  async function openDuelSheet() {
    if (!requireAuth(workNext) || !workId || !postId) {
      showError(social.duelStartFail);
      return;
    }
    setDuelSheetOpen(true);
    const q = await vibeApi.getDuelQuota().catch(() => null);
    setDuelQuota(q);
  }

  async function startDuel() {
    if (!requireAuth(workNext) || !workId || !postId) {
      showError(social.duelStartFail);
      return;
    }
    setDuelStarting(true);
    try {
      const opponent = duelOpponent.trim().replace(/^@/, "") || undefined;
      const res = await vibeApi.createDuel(workId, opponent);
      showSuccess(social.duelStarted);
      setDuelSheetOpen(false);
      setDuelOpponent("");
      Taro.navigateTo({ url: socialPage("duel", { id: res.duel_id }) });
    } catch {
      showError(social.duelStartFail);
    } finally {
      setDuelStarting(false);
    }
  }

  function buildActionItems(detail: WorkDetail): ActionIconItem[] {
    const items: ActionIconItem[] = [];
    if (detail.is_owner) {
      items.push({
        id: "rename",
        icon: "create",
        label: w.renameAction,
        onClick: () =>
          setRenameTarget({
            id: detail.id,
            title: detail.title,
            version: detail.version,
            postId,
            postCaption,
          }),
      });
    }
    if (canRemixWork(detail)) {
      items.push({ id: "remix", icon: "remix", label: copy.derivative.remix.short, onClick: () => setDerivative({ mode: "remix" }) });
    }
    items.push(
      { id: "cover", icon: "music", label: copy.derivative.cover.short, onClick: () => showCoverUnavailable() },
      { id: "prov", icon: "search", label: d.viewProvenance, onClick: () => Taro.navigateTo({ url: `${STUDIO_PAGE_ROUTES.provenance}?workId=${workId}` }) }
    );
    return items;
  }

  return (
    <PageShell title={work?.title || d.title} wide ambient hideHeader noPadTop>
      <View className="work-detail">
        <View className="work-detail__header">
          <View className="work-detail__back" onClick={goBack}>
            <Icon name="chevronLeft" size="sm" accent />
            <Text>{d.back}</Text>
          </View>
          <View className="work-detail__header-actions">
            {work && (
              <ShareButton className="work-detail__icon-btn" onShare={() => shareWork(work.id, work.title)}>
                <Icon name="share" size="sm" />
              </ShareButton>
            )}
          </View>
        </View>

        {loading && <LoadingSkeleton count={3} />}
        {!loading && work && (
          <>
            <View
              className="work-detail__hero"
              onClick={() => {
                if (!track) return;
                hapticLight();
                playTrack(track, { navigate: true });
              }}
            >
              {work.cover_url ? (
                <Image className="work-detail__cover" src={work.cover_url} mode="aspectFill" />
              ) : (
                <View className="work-detail__cover work-detail__cover--fallback">
                  <Icon name="music" size="xl" accent />
                </View>
              )}
              {track && (
                <View className="work-detail__play" onClick={(ev) => ev.stopPropagation()}>
                  <PlayTrackButton track={track} />
                </View>
              )}
            </View>

            <Text className="work-detail__title">{work.title}</Text>
            {work.from_workbench ? <Badge>{copy.worksUi.beautifyMaster}</Badge> : null}
            {work.superseded_by_work_id ? <Badge tone="warning">{copy.worksUi.hasBeautifyMaster}</Badge> : null}
            {work.is_owner ? (
              <Button variant="primary" block onClick={() => openStackPage(creatorPage("work", { workId: work.id }))}>
                打开作品台
              </Button>
            ) : null}
            {(work.artist_name || work.owner_username || authorUsername) && (
              <Text className="work-detail__moods">@{work.artist_name || work.owner_username || authorUsername}</Text>
            )}
            {work.moods?.length ? (
              <Text className="work-detail__moods">{work.moods.join(" · ")}</Text>
            ) : null}
            {!work.is_owner && isLoggedIn() && (
              <Button variant="primary" block onClick={() => startSameStyle(work.id, work.title)}>
                {copy.derivative.startSameStyle}
              </Button>
            )}
            {!isLoggedIn() && !work.is_owner ? (
              <>
                <Button variant="primary" block onClick={() => startSameStyle(work.id, work.title)}>
                  {copy.derivative.startSameStyle}
                </Button>
                <Text
                  className="work-detail__moods work-detail__login-soft"
                  onClick={() =>
                    Taro.navigateTo({
                      url: stackPage("login", {
                        next: stackPage("work", { workId: work.id, play: "1" }),
                      }),
                    })
                  }
                >
                  {d.guestLoginSoft}
                </Text>
              </>
            ) : null}
            <View className="work-detail__badges">
              <AiGeneratedBadge />
              {visibilityBadge === "published" ? (
                <Badge tone="accent">{w.published}</Badge>
              ) : (
                <Tag>{visibilityBadge === "unlisted" ? d.unlisted : d.private}</Tag>
              )}
            </View>
            <PostProcessBadges
              status={work.post_process_status}
              c2paVerified={work.c2pa_verified}
              c2paState={work.c2pa_state}
              onRetry={undefined}
              retrying={reprocessing}
            />
            {work.is_owner && isPostProcessDegraded(work.post_process_status) ? (
              <Button variant="primary" block loading={reprocessing} onClick={() => void triggerPostProcess()}>
                {reprocessing ? w.reprocessWorking : w.retryArtifacts}
              </Button>
            ) : null}
            {work.is_owner ? (
              <View className="work-workbench-entry">
                <BeautifyDoorCard
                  title={copy.workbenchUi.liteTitle}
                  hint={needsBeautify ? copy.creatorUi.nextBeautifyHint : copy.workbenchUi.hasMasterHint}
                  goLabel={copy.workbenchUi.doorGo}
                  songLabel={copy.workbenchUi.doorSong.replace("{title}", work.title)}
                  onClick={() => openWorkbench(work.id)}
                />
                {isDesktopWorkbench() ? (
                  <Button variant="ghost" size="sm" block onClick={() => openWorkbench(work.id, "pro")}>
                    {copy.lightEditorUi.openMixer}
                  </Button>
                ) : null}
                {!needsBeautify ? (
                  <WorkQualityCard workId={shipId} title={work.title} doorOnly onRemelt={() => openWorkbench(work.id)} />
                ) : null}
              </View>
            ) : null}
            {work.is_owner && timeline?.stages?.length && !isPostProcessDegraded(work.post_process_status) ? (
              <WorkReleaseTimeline
                stages={timeline.stages}
                nextAction={timeline.next_action}
                busy={reprocessing}
                copy={{
                  title: w.journeyTitle,
                  go: copy.creatorUi.nextGo,
                  waitHint: w.journeyWait,
                  doneHint: w.journeyDone,
                  statusDone: w.statusDone,
                  statusWait: w.statusWait,
                  statusNeed: w.statusNeed,
                  statusLive: w.statusLive,
                  statusFail: w.statusFail,
                }}
                onAction={handleJourneyAction}
              />
            ) : null}
            {work.is_owner && creditsCtx?.dspDistribution !== false && !needsBeautify && !isPostProcessDegraded(work.post_process_status) && (
              <>
                <ShipCompleteCard
                  workId={shipId}
                  surface="desk"
                  qcReady={["qc_ready", "queued", "delivering", "live"].includes(work.release_status || "")}
                  releaseStatus={work.release_status || ""}
                  embedAuth
                />
                {["live", "delivering", "queued"].includes(work.release_status || "") ? (
                  <Button
                    variant="primary"
                    block
                    onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { workId: shipId }) })}
                  >
                    {copy.creatorUi.viewProgress}
                  </Button>
                ) : null}
                <Collapsible label={d.tryRadioSync} defaultOpen={false}>
                  <View className="work-detail__verbs">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        void (async () => {
                          try {
                            const trial = (await vibeApi.startRadioTrial(shipId)) as {
                              work_id?: string;
                              station?: string;
                            };
                            showSuccess(copy.creatorUi.radioTrialLive);
                            openRadioPage({
                              workId: trial.work_id || shipId,
                              station: typeof trial.station === "string" ? trial.station : undefined,
                            });
                          } catch {
                            openRadioPage({ workId: shipId });
                          }
                        })();
                      }}
                    >
                      {copy.generation.reveal.radioNext}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        Taro.navigateTo({
                          url: commercePage("syncDesk", { workId: shipId }),
                        })
                      }
                    >
                      {copy.generation.reveal.syncLicense}
                    </Button>
                  </View>
                  <Text className="typo-meta">{d.nextHint}</Text>
                </Collapsible>
              </>
            )}

            <View className="work-detail__community">
              {remixChain && (
                <Text
                  className="work-detail__chain work-detail__chain--link"
                  onClick={() => Taro.navigateTo({ url: `${STUDIO_PAGE_ROUTES.provenance}?workId=${workId}` })}
                >
                  {social.remixChain}: {remixChain.chain_label}
                  {remixChain.direct_remixes > 0 ? ` · ${remixChain.direct_remixes} Remix` : ""}
                  {remixChain.generation_depth > 0 ? ` · ${social.viewLineage}` : ""}
                </Text>
              )}
              {engagementStats && (engagementStats.listen_completes > 0 || engagementStats.resonance_avg > 0) && (
                <Text className="work-detail__engagement-stats">
                  {social.workListenCompletes.replace("{n}", String(engagementStats.listen_completes))}
                  {engagementStats.resonance_avg > 0
                    ? ` · ${social.workResonanceAvg.replace("{n}", String(Math.round(engagementStats.resonance_avg * 100)))}`
                    : ""}
                </Text>
              )}
              {(work.is_owner || postId) && (
                <CommunityPostButton
                  postId={postId}
                  published={!!postId}
                  onPublish={work.is_owner ? () => setPublishOpen(true) : undefined}
                  block
                />
              )}
              {canTip && (
                <Button variant="ghost" size="sm" block onClick={() => setTipOpen(true)}>
                  {eco.tipTitle}
                </Button>
              )}
              {publicTips.length > 0 && (
                <View className="work-detail__tips-feed">
                  <Text className="work-detail__tips-title">{social.publicTipsTitle}</Text>
                  {publicTips.slice(0, 5).map((t, i) => (
                    <Text key={i} className="work-detail__tips-line">
                      @{t.username} +{t.credits}
                      {t.message ? `：${t.message}` : ""}
                    </Text>
                  ))}
                </View>
              )}
              {postId && myUsername && (
                <Button variant="secondary" size="sm" block onClick={() => void openDuelSheet()}>
                  {social.startDuel}
                </Button>
              )}
              {postId && work.is_owner && (
                <Text className="work-detail__unpublish" onClick={unpublishWork}>
                  {w.unpublish}
                </Text>
              )}
            </View>

            <View className="work-detail__actions">
              <ActionIconBar items={buildActionItems(work)} />
            </View>

            {work.is_owner ? (
              <Collapsible label={d.craftMore} defaultOpen={false}>
                <Button variant="secondary" size="sm" block onClick={continueFromWork}>
                  {copy.derivative.startSameStyle}
                </Button>
                {!work.cover_url && (
                  <Button variant="ghost" size="sm" block onClick={generateCover}>
                    {w.generateCover}
                  </Button>
                )}
                <Button variant="ghost" size="sm" block onClick={uploadCover}>
                  {w.coverUpload}
                </Button>
                {isH5 && (
                  <Button variant="ghost" size="sm" block onClick={() => copyEmbedLink(work.id)}>
                    {copy.navTitles.embed}
                  </Button>
                )}
              </Collapsible>
            ) : isH5 ? (
              <Button variant="ghost" size="sm" block onClick={() => copyEmbedLink(work.id)}>
                {copy.navTitles.embed}
              </Button>
            ) : null}

            {work.is_owner && (
              <Collapsible label={copy.lightEditorUi.title} storageKey={`work-light-${workId}`}>
                <WorkLightEditor
                  workId={work.id}
                  title={work.title}
                  arousal={work.arousal}
                  valence={work.valence}
                />
              </Collapsible>
            )}

            <Collapsible label={mv.title} storageKey={`work-mv-${workId}`}>
              {!showMoodVisual && (
                <Button variant="secondary" size="sm" block onClick={() => setShowMoodVisual(true)}>
                  {mv.preview}
                </Button>
              )}
              {showMoodVisual && (
                <MoodVisualPreview workId={work.id} onClose={() => setShowMoodVisual(false)} />
              )}
            </Collapsible>

            {work.is_owner && (
            <Collapsible label={eco.exportTitle} storageKey={`work-export-${workId}`}>
              <MemberExportQuotas />
              <View className="work-detail__export">
                <View className="work-detail__export-lane">
                  <Text className="work-detail__export-kicker">{eco.exportLaneMaster}</Text>
                  <Button variant="secondary" size="sm" loading={exporting === "hq_mp3"} onClick={() => void doExport("hq_mp3")}>
                    {eco.exportHq}
                  </Button>
                  <Button variant="ghost" size="sm" loading={exporting === "hq_wav"} onClick={() => void doExport("hq_wav")}>
                    {eco.exportWav}
                  </Button>
                </View>
                <View className="work-detail__export-lane">
                  <Text className="work-detail__export-kicker">{eco.exportLaneStems}</Text>
                  <Button variant="ghost" size="sm" loading={exporting === "stems"} onClick={() => void doExport("stems")}>
                    {eco.exportStems}
                  </Button>
                  <Text className="typo-meta">{eco.exportStemsHint}</Text>
                </View>
                <View className="work-detail__export-lane">
                  <Text className="work-detail__export-kicker">{eco.exportLaneLicense}</Text>
                  <Button variant="ghost" size="sm" loading={exporting === "commercial_license"} onClick={() => void doExport("commercial_license")}>
                    {eco.exportCommercial}
                  </Button>
                  <Button variant="ghost" size="sm" loading={exporting === "mv_video"} onClick={() => void doExportMv()}>
                    {mv.exportMp4}
                  </Button>
                </View>
              </View>
            </Collapsible>
            )}

            <Collapsible label={d.archive} storageKey={`work-archive-${workId}`}>
              {work.description && <Text className="work-detail__meta">{work.description}</Text>}
              {(work.arousal != null || work.valence != null) && (
                <Text className="work-detail__meta">
                  Arousal {work.arousal ?? "—"} · Valence {work.valence ?? "—"}
                </Text>
              )}
              {work.parent_work_id && (
                <Text className="work-detail__link" onClick={() => openWorkDetail(work.parent_work_id!)}>
                  {d.parentWork} →
                </Text>
              )}
            </Collapsible>

            <Collapsible label={d.derivatives} storageKey={`work-deriv-${workId}`} defaultOpen={!work.is_owner}>
              {derivatives.length === 0 && <Text className="typo-meta">{d.noDerivatives}</Text>}
              {derivatives.map((item) => (
                <View key={item.id} className="work-detail__deriv-row" onClick={() => openWorkDetail(item.id)}>
                  <Icon name="remix" size="sm" accent />
                  <Text className="work-detail__deriv-title">{item.title}</Text>
                </View>
              ))}
            </Collapsible>

            {work.is_owner && (
            <Button variant="danger" block className="work-detail__delete" onClick={deleteWork}>
              {d.deleteWork}
            </Button>
            )}
          </>
        )}
        <SameStyleWall
          works={similar}
          empty
          error={similarError}
          onRetry={() => {
            if (!workId) return;
            vibeApi
              .listSimilarWorks(workId)
              .then((wall) => {
                setSimilarError(false);
                setSimilar((wall.works || []).filter((row) => row.id !== workId));
              })
              .catch(() => setSimilarError(true));
          }}
        />
      </View>

      {renameTarget && (
        <RenameWorkSheet
          target={renameTarget}
          onClose={() => setRenameTarget(null)}
          onSaved={(result) => {
            setWork((prev) => (prev ? { ...prev, title: result.title, version: result.version } : prev));
            patchTrackTitle(result.id, result.title);
            if (result.postCaptionSynced) setPostCaption(result.title);
          }}
        />
      )}
      {publishOpen && work && (
        <PublishDialog
          workTitle={work.title}
          finishing={isPostProcessDegraded(work.post_process_status)}
          onClose={() => setPublishOpen(false)}
          onPublish={publishWork}
        />
      )}
      {derivative && work && (
        <Suspense fallback={null}>
          <LazyDerivativeSheet
            workId={work.id}
            workTitle={work.title}
            initialMode={derivative.mode}
            onClose={() => setDerivative(null)}
          />
        </Suspense>
      )}
      {work && (
        <TipSheet
          open={tipOpen}
          workId={work.id}
          workTitle={work.title}
          onClose={() => setTipOpen(false)}
          onDone={() => void refreshPublicTips()}
        />
      )}
      <BottomSheet open={duelSheetOpen} title={social.startDuel} onClose={() => setDuelSheetOpen(false)}>
        {duelQuota ? (
          <Text className="work-detail__duel-quota">
            {social.duelQuotaHint
              .replace("{free}", String(duelQuota.member_free_remaining ?? 0))
              .replace("{pass}", String(duelQuota.pass_starts_remaining ?? 0))
              .replace("{cost}", String(duelQuota.start_cost ?? 1))}
          </Text>
        ) : null}
        <Input
          label={social.duelOpponentLabel}
          placeholder={social.duelOpponentPlaceholder}
          value={duelOpponent}
          onInput={(e) => setDuelOpponent(e.detail.value)}
        />
        <Button variant="primary" block loading={duelStarting} onClick={() => void startDuel()}>
          {social.startDuel}
        </Button>
      </BottomSheet>
    </PageShell>
  );
}
