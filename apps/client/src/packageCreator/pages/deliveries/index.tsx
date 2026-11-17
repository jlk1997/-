import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh, useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { AsyncPanel, Badge, Button, Collapsible, EmptyState, Input, SegmentedControl, StatusLine } from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { CREATOR_PAGE_ROUTES, creatorPage, socialPage } from "../../../constants/routes";
import { goSessionWaitCta, goShipBand } from "../../nextActionNav";
import {
  canRetryDelivery,
  channelName,
  channelPortal,
  connectorLiveLine,
  deliveryBuckets,
  groupDeliveries,
  confirmCreatorAction,
  humanizeDeliveryError,
  isFillIncomplete,
  isInReview,
  isLeaseWait,
  isLiveDelivery,
  isMetricsOnlyDelivery,
  isPublishingDelivery,
  isStoreAssist,
  isUploadWait,
  isWaitingLogin,
  layerKind,
  liveProgress,
  openExternal,
  releaseHasKit,
  sessionWaitCta,
  shouldShowDeliveryError,
  statusLabel,
  statusTone,
  storeRowMeta,
  type DeliveryRow,
  type ReleaseRow,
} from "../../lib";
import { saveOriginalityPack, saveReleaseKit } from "../../kitAction";
import { looksLikeStorePage } from "../../storeUrl";
import { JourneyProgress, buildCreatorJourney } from "../../JourneyProgress";
import { ChannelTimeline, connectorStepNowLabel } from "../../ChannelTimeline";
import { ChannelMark } from "../../ChannelMark";
import { AuthDesk } from "../../AuthDesk";
import { ShipCompleteCard } from "../../ShipCompleteCard";
import { listenExtensionEvents, sendPollToExtension } from "../../extensionPair";
import { type ConnectionCard } from "../../ConnectionsRow";
import { AssetChips } from "../../../components/studio/AssetLanes";
import { NextActionCard } from "../../NextActionCard";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import "../../creator.scss";
import "./index.scss";

export default function DeliveriesPage() {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const router = useRouter();
  const focusReleaseId = String(router.params.releaseId || router.params.release_id || "");
  const focusWorkId = String(router.params.workId || router.params.work_id || "");
  const [statusFilter, setStatusFilter] = useState<"all" | "publishing" | "live" | "rejected" | "taken_down">("all");
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState("");
  const [openId, setOpenId] = useState("");
  const [radioTrial, setRadioTrial] = useState<{
    live?: boolean;
    status?: string;
    station?: string;
    listen_completes?: number;
    work_id?: string;
  } | null>(null);
  const fetchState = useCallback(async () => {
    if (!requireAuth(creatorPage("deliveries", { workId: focusWorkId || undefined, releaseId: focusReleaseId || undefined }))) {
      return {
        rows: [] as ReleaseRow[],
        hasPayout: false,
        hasLabelStatement: false,
        hasLabelRelease: undefined as boolean | undefined,
        waitingForStatement: false,
        expectedEarliest: undefined as string | undefined,
        expectedLatest: undefined as string | undefined,
        works: 0,
        unpublishedCount: 0,
        connectorOnline: false,
        sessionWaitCount: 0,
        connections: [] as ConnectionCard[],
        connector: null as {
          last_delivery?: { channel_code?: string; event?: string; message?: string } | null;
          queue_count?: number;
        } | null,
      };
    }
    const [releases, deliveries, wallet, hub] = await Promise.all([
      vibeApi.listReleases().catch(() => ({ releases: [] })),
      vibeApi.listDeliveries().catch(() => ({ deliveries: [] })),
      vibeApi.getRoyaltyWallet().catch(() => null),
      vibeApi.getCreatorHub().catch(() => null),
    ]);
    const wallets = ((wallet as { wallets?: Array<{ available_minor?: number; pending_minor?: number }> } | null)?.wallets || []);
    const hubData = hub as {
      works?: number;
      unpublished_count?: number;
      connector_online?: boolean;
      session_wait_count?: number;
      connections?: ConnectionCard[];
      connector?: {
        last_delivery?: { channel_code?: string; event?: string; message?: string } | null;
        queue_count?: number;
      };
      has_label_statement?: boolean;
      has_label_release?: boolean;
      waiting_for_statement?: boolean;
      label_period?: { expected_earliest?: string; expected_latest?: string };
    } | null;
    return {
      rows: groupDeliveries((releases.releases || []) as ReleaseRow[], (deliveries.deliveries || []) as DeliveryRow[]),
      hasPayout: wallets.some((w) => (w.available_minor || 0) > 0 || (w.pending_minor || 0) > 0),
      hasLabelStatement: Boolean(hubData?.has_label_statement),
      hasLabelRelease: hubData?.has_label_release,
      waitingForStatement: Boolean(hubData?.waiting_for_statement),
      expectedEarliest: hubData?.label_period?.expected_earliest,
      expectedLatest: hubData?.label_period?.expected_latest,
      works: hubData?.works || 0,
      unpublishedCount: hubData?.unpublished_count || 0,
      connectorOnline: Boolean(hubData?.connector_online),
      sessionWaitCount: Number(hubData?.session_wait_count || 0),
      connections: hubData?.connections || [],
      connector: hubData?.connector || null,
    };
  }, [focusWorkId, focusReleaseId]);
  const { data, loading, error, reload, setData } = useAsyncQuery(fetchState, [fetchState]);

  useDidShow(() => {
    void reload();
    if (process.env.TARO_ENV === "h5") void sendPollToExtension();
  });
  useEffect(() => {
    if (process.env.TARO_ENV !== "h5") return undefined;
    const stop = listenExtensionEvents((event) => {
      if (event.type === "BITTUNE_DELIVERY" || event.type === "BITTUNE_SYNC") void reload(true);
    });
    return stop;
  }, [reload]);
  usePullDownRefresh(async () => {
    await reload(true);
    Taro.stopPullDownRefresh();
  });

  const rows = (data?.rows || []).filter((release) => {
    if (focusWorkId) {
      const match = release.work_id === focusWorkId || (release.deliveries || []).some((d) => d.work_id === focusWorkId);
      if (!match) return false;
    }
    if (statusFilter === "all") return true;
    const dels = release.deliveries || [];
    if (statusFilter === "live") return dels.some((d) => isLiveDelivery(d));
    if (statusFilter === "rejected") return dels.some((d) => d.status === "rejected");
    if (statusFilter === "taken_down") return dels.some((d) => d.status === "taken_down") || release.status === "taken_down";
    return dels.some((d) => isPublishingDelivery(d));
  });
  const allDeliveries = rows.flatMap((r) => r.deliveries || []);
  const shippable = allDeliveries.filter((d) => !isMetricsOnlyDelivery(d));
  const buckets = deliveryBuckets(allDeliveries);
  const firstWaiting = allDeliveries.find((d) => isStoreAssist(d.status, d.user_status, d.last_error));
  const autoOpened = useRef(false);
  const sessionWaitCount = Math.max(data?.sessionWaitCount || 0, buckets.login);
  const leaseWait = allDeliveries.some((d) => isLeaseWait(d.status, d.user_status, d.last_error));
  const weapp = process.env.TARO_ENV === "weapp";
  const waitCta =
    sessionWaitCount > 0
      ? sessionWaitCta(c, {
          weapp,
          connectorOnline: Boolean(data?.connectorOnline),
          leaseWait,
          waiting: sessionWaitCount,
        })
      : null;
  const stillPublishing = allDeliveries.some((d) =>
    ["submitting", "ops_queue", "awaiting_manual", "session_wait", "session_running", "needs_upload", "in_review", "needs_retry", "assisting"].includes(
      d.user_status || d.status,
    ) || ["session_wait", "session_running", "submitting"].includes(d.status),
  );

  const trialWorkId = focusWorkId || rows.find((r) => r.work_id)?.work_id || "";
  useEffect(() => {
    if (!trialWorkId) {
      setRadioTrial(null);
      return;
    }
    vibeApi
      .getRadioTrial(trialWorkId)
      .then((trial) => setRadioTrial(trial as typeof radioTrial))
      .catch(() => setRadioTrial(null));
  }, [trialWorkId]);

  useEffect(() => {
    if (autoOpened.current || openId || !firstWaiting?.id) return;
    autoOpened.current = true;
    setOpenId(firstWaiting.id);
  }, [firstWaiting?.id, openId]);

  const connectorBusy = Boolean(data?.connector?.queue_count || data?.connector?.last_delivery?.event);
  useEffect(() => {
    if (!stillPublishing && !connectorBusy) return;
    const timer = setInterval(() => {
      void fetchState().then((next) => {
        if (next) setData(next);
      });
    }, 8000);
    return () => clearInterval(timer);
  }, [stillPublishing, connectorBusy, fetchState, setData]);

  async function saveUrl(id: string) {
    if (busyId) return;
    if (weapp) {
      await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.deliveries);
      Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    const url = (urls[id] || "").trim();
    if (!url) return;
    if (!looksLikeStorePage(url)) {
      Taro.showToast({ title: c.notStorePage, icon: "none" });
      return;
    }
    setBusyId(id);
    try {
      const saved = (await vibeApi.setDeliveryStoreUrl(id, url)) as { status?: string };
      Taro.showToast({ title: saved?.status === "live" ? c.status.live : c.storeSaved, icon: "success" });
      void reload();
    } catch (err) {
      const msg = String((err as Error)?.message || "");
      Taro.showToast({ title: msg.includes("not a store page") ? c.notStorePage : copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusyId("");
    }
  }

  async function retry(d: DeliveryRow) {
    if (busyId) return;
    if (weapp) {
      await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.deliveries);
      Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    if (isFillIncomplete(d.last_error, d.user_status) || d.status === "rejected") {
      const ok = await confirmCreatorAction({
        title: c.retryFillTitle,
        content: c.retryFillHint,
        confirmText: c.confirmGo,
        cancelText: c.back,
      });
      if (!ok) return;
    }
    setBusyId(d.id);
    try {
      await vibeApi.retryDelivery(d.id);
      if (process.env.TARO_ENV === "h5") void sendPollToExtension();
      Taro.showToast({ title: c.retryOk, icon: "success" });
      void reload();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusyId("");
    }
  }

  async function takedown(releaseId: string) {
    if (busyId) return;
    if (weapp) {
      await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.deliveries);
      Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    const ok = await confirmCreatorAction({
      title: c.takedown,
      content: c.takedownConfirm,
      confirmText: c.confirmGo,
      cancelText: c.back,
    });
    if (!ok) return;
    setBusyId(releaseId);
    try {
      await vibeApi.takedownRelease(releaseId);
      Taro.showToast({ title: c.takedownOk, icon: "success" });
      void reload();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusyId("");
    }
  }

  async function downloadKit(releaseId: string) {
    if (busyId) return;
    setBusyId(releaseId);
    try {
      await saveReleaseKit(releaseId, c);
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusyId("");
    }
  }

  return (
    <PageShell title={c.goDeliveries} subtitle={c.navDeliveriesHint} ambient>
      <View className="creator">
        <WeappH5Bridge path={CREATOR_PAGE_ROUTES.deliveries} />
        {weapp ? <StatusLine tone="info" density="quiet">{c.weappDeskHint}</StatusLine> : null}
        {focusWorkId ? (
          <ShipCompleteCard
            workId={focusWorkId}
            surface="deliveries"
            connections={data?.connections}
            connector={data?.connector}
            weapp={process.env.TARO_ENV === "weapp"}
            embedAuth
            onChanged={() => {
              if (process.env.TARO_ENV === "h5") void sendPollToExtension();
              void reload();
            }}
          />
        ) : (
          <AuthDesk
            connections={data?.connections}
            weapp={process.env.TARO_ENV === "weapp"}
            onChanged={() => {
              if (process.env.TARO_ENV === "h5") void sendPollToExtension();
              void reload();
            }}
          />
        )}
        {connectorLiveLine(c, data?.connector) ? (
          <View className="creator-card creator-card--soft">
            <StatusLine tone={(data?.connector?.queue_count || 0) > 0 ? "info" : "success"} density="quiet">
              {connectorLiveLine(c, data?.connector)}
            </StatusLine>
          </View>
        ) : null}
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void reload()}
        >
          {(data?.rows || []).length > 0 && (
            <StatusLine tone="info" density="quiet">{c.watchAutoHint}</StatusLine>
          )}
          {(data?.rows || []).length > 0 && (
            <SegmentedControl
              options={[
                { value: "all", label: c.periodAll },
                { value: "publishing", label: c.filterPublishing },
                { value: "live", label: c.filterLive },
                { value: "rejected", label: c.filterRejected },
                { value: "taken_down", label: c.filterTakenDown },
              ]}
              value={statusFilter}
              onChange={setStatusFilter}
            />
          )}
          {waitCta ? (
            <NextActionCard
              kicker={c.waitingNow}
              title={waitCta.title}
              hint={waitCta.hint}
              go={waitCta.go}
              urgent
              onClick={() =>
                goSessionWaitCta(waitCta, {
                  weapp,
                  seatId:
                    (data?.connections || []).find((row) => row.channel_code === firstWaiting?.channel_code)?.seat_id ||
                    firstWaiting?.seat_id,
                })
              }
            />
          ) : leaseWait ? (
            <StatusLine tone="info">{c.machineUploadingHint}</StatusLine>
          ) : buckets.upload > 0 ? (
            <NextActionCard
              kicker={c.waitingNow}
              title={c.nextStoresUpload}
              hint={c.nextStoresUploadHint}
              go={c.nextGo}
              urgent
              onClick={() => {
                const row = firstWaiting && isUploadWait(firstWaiting.status, firstWaiting.user_status) ? firstWaiting : allDeliveries.find((d) => isUploadWait(d.status, d.user_status));
                if (row?.id) setOpenId(row.id);
              }}
            />
          ) : radioTrial?.live ? (
            <NextActionCard
              kicker={c.walletRadio}
              title={c.radioTrialLive}
              hint={`${c.radioTrialHint}${radioTrial.station ? ` · ${radioTrial.station}` : ""}`}
              go={c.goRadio}
              onClick={() => Taro.navigateTo({ url: socialPage("radio", { workId: String(radioTrial.work_id || router.params.workId || "") }) })}
            />
          ) : null}
          {rows.length > 0 && (
            <View className="creator-hero">
              <Text className="creator-hero__kicker">{c.goDeliveries}</Text>
              <Text className="creator-hero__title">{c.liveProgress.replace("{n}", String(buckets.live)).replace("{m}", String(shippable.length || 0))}</Text>
              <Text className="creator-hero__sub">{c.navDeliveriesHint}</Text>
              {shippable.length > 0 && (
                <View className="creator-progress">
                  <View
                    className="creator-progress__bar"
                    style={{
                      width: `${Math.round((buckets.live / shippable.length) * 100)}%`,
                    }}
                  />
                </View>
              )}
            </View>
          )}
          {rows.length > 0 && (
            <Collapsible label={copy.generation.progressLabel} storageKey="deliveries-progress" defaultOpen={false}>
              <View className="creator-metrics creator-metrics--quad">
                <View className="creator-stat">
                  <Text className="creator-stat__n">{buckets.pushing}</Text>
                  <Text className="creator-stat__l">{c.bucketPushing}</Text>
                </View>
                <View className={`creator-stat ${buckets.login ? "creator-stat--hot" : ""}`}>
                  <Text className="creator-stat__n">{buckets.login}</Text>
                  <Text className="creator-stat__l">{c.bucketLogin}</Text>
                </View>
                <View className={`creator-stat ${buckets.upload ? "creator-stat--hot" : ""}`}>
                  <Text className="creator-stat__n">{buckets.upload}</Text>
                  <Text className="creator-stat__l">{c.bucketUpload}</Text>
                </View>
                <View className="creator-stat">
                  <Text className="creator-stat__n">{buckets.live}</Text>
                  <Text className="creator-stat__l">{c.bucketLive}</Text>
                </View>
              </View>
              {data?.waitingForStatement || (buckets.live > 0 && !data?.hasLabelStatement) ? (
                <StatusLine tone="info" density="quiet">
                  {data?.expectedEarliest && data?.expectedLatest
                    ? c.harvestWindow.replace("{a}", data.expectedEarliest).replace("{b}", data.expectedLatest)
                    : c.waitHarvestShort}
                </StatusLine>
              ) : null}
              <JourneyProgress
                steps={buildCreatorJourney(
                  {
                    generate: c.journeyStepGenerate,
                    release: c.journeyStepRelease,
                    stores: c.journeyStepStores,
                    wait: c.journeyStepWait,
                    settle: c.journeyStepSettle,
                    payout: c.journeyStepPayout,
                  },
                  {
                    works: data?.works || rows.length,
                    releases: rows.length,
                    delivering: buckets.login + buckets.upload + buckets.pushing > 0,
                    hasReal: Boolean(data?.hasLabelStatement),
                    hasPayout: Boolean(data?.hasPayout),
                    unpublishedCount: data?.unpublishedCount || 0,
                    hasLive: buckets.live > 0,
                    hasLabelRelease: data?.hasLabelRelease,
                    waitingForStatement: data?.waitingForStatement,
                  },
                )}
              />
            </Collapsible>
          )}
          {rows.length === 0 && (
            <EmptyState
              iconName="feed"
              title={c.noDeliveries}
              description={c.journeyHint}
              actionLabel={c.goRelease}
              onAction={() => goShipBand()}
            />
          )}
          {[...rows]
            .sort((a, b) => (a.id === focusReleaseId ? -1 : b.id === focusReleaseId ? 1 : 0))
            .map((release) => {
            const dels = release.deliveries || [];
            const { live, total } = liveProgress(dels);
            const title = release.metadata?.title || c.releaseUntitled;
            const pct = total ? Math.round((live / total) * 100) : 0;
            return (
              <View key={release.id} className={release.id === focusReleaseId ? "creator-card creator-card--focus" : "creator-card"}>
                <View className="creator-release-head">
                  <View>
                    <Text className="creator-pick__title">{title}</Text>
                    <Text className="creator-pick__meta">
                      {release.mode === "self_release" ? c.modeA : c.modeB}
                      {total ? ` · ${c.liveProgress.replace("{n}", String(live)).replace("{m}", String(total))}` : ""}
                    </Text>
                  </View>
                  <Badge tone={statusTone(release.status)}>{statusLabel(release.status || "delivering", c.status)}</Badge>
                </View>
                {total > 0 && (
                  <View className="creator-progress">
                    <View className="creator-progress__bar" style={{ width: `${pct}%` }} />
                  </View>
                )}
                <ChannelTimeline
                  deliveries={dels}
                  labels={{
                    handoff: c.status.waiting_login,
                    assisting: c.status.assisting,
                    ops: c.status.ops_handling,
                    live: c.status.live,
                    timelineOpen: c.timelineOpen,
                    timelineFill: c.timelineFill,
                    timelineAttach: c.timelineAttach,
                    timelineSubmit: c.timelineSubmit,
                    timelineReceipt: c.timelineReceipt,
                    timelineNow: c.timelineNow,
                    ...c,
                  }}
                />
                {(() => {
                  const canPassport = Boolean(release.id) && (live > 0 || ["live", "delivering", "queued"].includes(release.status || ""));
                  const canKit = releaseHasKit(release);
                  const canWork = Boolean(release.work_id);
                  const canTakedown =
                    release.can_takedown ||
                    dels.some((d) =>
                      ["live", "submitting", "ops_queue", "awaiting_manual", "session_wait", "session_running", "in_review"].includes(d.status),
                    );
                  const primary: "passport" | "kit" | "work" | "takedown" | null = canPassport
                    ? "passport"
                    : canKit
                      ? "kit"
                      : canWork
                        ? "work"
                        : canTakedown
                          ? "takedown"
                          : null;
                  const moreCount = (canKit && primary !== "kit" ? 1 : 0) + (canWork && primary !== "work" ? 1 : 0) + (canTakedown && primary !== "takedown" ? 1 : 0);
                  return (
                    <>
                      {primary === "passport" && (
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => Taro.navigateTo({ url: creatorPage("passport", { releaseId: release.id, workId: release.work_id }) })}
                        >
                          {c.goPassport}
                        </Button>
                      )}
                      {primary === "kit" && (
                        <Button size="sm" variant="primary" loading={busyId === release.id} onClick={() => void downloadKit(release.id)}>
                          {c.kitShare}
                        </Button>
                      )}
                      {primary === "work" && (
                        <Button size="sm" variant="primary" onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId: release.work_id }) })}>
                          {c.workLedgerTitle}
                        </Button>
                      )}
                      {primary === "takedown" && (
                        <Button size="sm" variant="primary" loading={busyId === release.id} onClick={() => void takedown(release.id)}>
                          {c.takedown}
                        </Button>
                      )}
                      {moreCount > 0 && (
                        <Collapsible label={copy.actions.more} defaultOpen={false}>
                          <View className="creator-actions">
                            {canKit && primary !== "kit" && (
                              <Button size="sm" variant="secondary" loading={busyId === release.id} onClick={() => void downloadKit(release.id)}>
                                {c.kitShare}
                              </Button>
                            )}
                            {canWork && primary !== "work" && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId: release.work_id }) })}
                              >
                                {c.workLedgerTitle}
                              </Button>
                            )}
                            {canTakedown && primary !== "takedown" && (
                              <Button size="sm" variant="ghost" loading={busyId === release.id} onClick={() => void takedown(release.id)}>
                                {c.takedown}
                              </Button>
                            )}
                          </View>
                        </Collapsible>
                      )}
                    </>
                  );
                })()}
                {dels.map((d) => {
                  const expanded = openId === d.id;
                  const waiting = isStoreAssist(d.status, d.user_status, d.last_error);
                  const uploadWait = isUploadWait(d.status, d.user_status);
                  const reviewing = isInReview(d.status, d.user_status);
                  const machineRow = isLeaseWait(d.status, d.user_status, d.last_error);
                  const kind = layerKind(d.layer);
                  const portal = channelPortal(d.channel_code, d.upload_url);
                  const draft = urls[d.id] ?? d.store_url ?? "";
                  const urlOk = !draft.trim() || looksLikeStorePage(draft);
                  const meta = storeRowMeta(d, c);
                  const stepNow = connectorStepNowLabel([d], c);
                  const metricsOnly = isMetricsOnlyDelivery(d);
                  const rowMod = [
                    isLiveDelivery(d) ? "creator-channel--live" : "",
                    waiting ? "creator-channel--wait" : "",
                    kind === "ops" ? "creator-channel--ops" : "",
                    metricsOnly ? "creator-channel--metrics" : "",
                    expanded ? "creator-channel--open" : "",
                  ]
                    .filter(Boolean)
                    .join(" ");
                  const lastSubmit = [...(d.submissions || [])].reverse().find((row) => row.event === "platform_submit");
                  const needsStoreUrl =
                    uploadWait ||
                    d.status === "handed_to_extension" ||
                    d.user_status === "needs_upload" ||
                    String(d.last_error || "").includes("store_url");
                  const showPaste =
                    expanded &&
                    !reviewing &&
                    !isLiveDelivery(d) &&
                    (needsStoreUrl || d.status === "live") &&
                    !isWaitingLogin(d.status, d.user_status, d.last_error);
                  const needsChallenge =
                    d.status === "needs_challenge" ||
                    d.user_status === "needs_challenge" ||
                    Boolean((d as { needs_challenge?: boolean }).needs_challenge) ||
                    String(d.last_error || "").includes("needs_challenge");
                  return (
                    <View key={d.id}>
                      <View
                        className={`creator-channel creator-channel--tap ${rowMod}`.trim()}
                        onClick={() => {
                          Taro.vibrateShort({ type: "light" }).catch(() => undefined);
                          setOpenId((prev) => (prev === d.id ? "" : d.id));
                        }}
                      >
                        <View className="creator-channel__main">
                          <View className="creator-channel__head">
                            <ChannelMark code={d.channel_code} />
                            <View
                              className={`creator-channel__pip ${
                                isLiveDelivery(d)
                                  ? "creator-channel__pip--live"
                                  : d.status === "rejected" || d.status === "taken_down"
                                    ? "creator-channel__pip--warn"
                                    : waiting
                                      ? "creator-channel__pip--warn"
                                      : "creator-channel__pip--mute"
                              }`}
                            />
                            <Text className="creator-channel__name">{channelName(d.channel_code, c.channels)}</Text>
                            {kind ? (
                              <Text className={`creator-chip creator-chip--${kind}`}>
                                {kind === "ops" ? c.layerOps : kind === "session" ? c.layerSession : c.layerAggregator}
                              </Text>
                            ) : null}
                            {stepNow ? <Text className="creator-chip creator-chip--session">{stepNow}</Text> : null}
                          </View>
                          <Text className="creator-channel__meta">
                            {meta.line}
                            {d.sla_due_at && ["ops_queue", "awaiting_manual", "ops_handling", "submitting", "in_review", "session_wait", "session_running"].includes(d.status)
                              ? ` · ${d.sla_escalated ? c.slaEscalated : d.sla_overdue ? c.slaOverdue : c.slaDueAt.replace("{t}", d.sla_due_at.slice(0, 16).replace("T", " "))}`
                              : ""}
                            {lastSubmit
                              ? ` · ${c.platformSubmitHint}${
                                  lastSubmit.at
                                    ? ` · ${c.lastSubmitAt.replace("{t}", lastSubmit.at.slice(0, 16).replace("T", " "))}`
                                    : ""
                                }`
                              : ""}
                            {!expanded ? ` · ${c.tapRowHint}` : ""}
                          </Text>
                        </View>
                        <View className="creator-channel__side">
                          <Badge tone={statusTone(d.user_status || d.status)}>
                            {statusLabel(d.user_status || d.status, c.status)}
                          </Badge>
                          {waiting && portal ? (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={(e) => {
                                e.stopPropagation();
                                openExternal(portal);
                              }}
                            >
                              {uploadWait ? c.openPortal : c.openThisPortal}
                            </Button>
                          ) : d.store_url ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={(e) => {
                                e.stopPropagation();
                                openExternal(d.store_url);
                              }}
                            >
                              {c.openStore}
                            </Button>
                          ) : null}
                        </View>
                      </View>
                          {metricsOnly ? (
                        <StatusLine tone="info" density="quiet">{c.routePreviewMetrics}</StatusLine>
                      ) : null}
                          {d.degraded ? (
                        <StatusLine tone="info" density="quiet">{c.routePreviewDegraded}</StatusLine>
                      ) : null}
                      {needsChallenge ? (
                        <View className="creator-actions">
                          <StatusLine tone="warning" density="quiet">{c.needsChallengeHint}</StatusLine>
                          {portal ? (
                            <Button
                              size="sm"
                              variant="primary"
                              onClick={(e) => {
                                e.stopPropagation();
                                Taro.showToast({ title: c.shipOpenStore, icon: "none" });
                                openExternal(portal);
                              }}
                            >
                              {c.shipChallengeGo}
                            </Button>
                          ) : null}
                        </View>
                      ) : null}
                      {d.ops_honest || d.status === "ops_queue" ? (
                        <StatusLine tone="info" density="quiet">{c.opsQueueHonest}</StatusLine>
                      ) : null}
                      {d.reject_next?.next ? <Text className="typo-meta">{d.reject_next.next}</Text> : null}
                      {d.reject_reason && !d.reject_next?.next ? <Text className="typo-meta">{d.reject_reason}</Text> : null}
                      {shouldShowDeliveryError(d) ? (
                        <Text className="typo-meta">{humanizeDeliveryError(d.last_error, c)}</Text>
                      ) : null}
                      {machineRow ? <Text className="typo-meta">{c.leaseWaitHint}</Text> : null}
                      {expanded && (
                        <View className="creator-store">
                          {(d.sla_overdue || d.sla_escalated || d.sla_hours) ? (
                            <StatusLine tone={d.sla_overdue || d.sla_escalated ? "error" : "info"} density="quiet">
                              {d.sla_escalated
                                ? c.slaEscalated
                                : d.sla_overdue
                                  ? c.slaOverdue
                                  : c.slaEta.replace("{h}", String(d.sla_hours || 48))}
                            </StatusLine>
                          ) : null}
                          <AssetChips
                            evidence={Boolean(d.asset_profile?.needs_stems_evidence)}
                            clips={Boolean(d.asset_profile?.needs_clips)}
                            instrumental={Boolean(d.asset_profile?.needs_instrumental)}
                          />
                          {d.sop ? (
                            <View className="creator-sop">
                              <Text className="creator-sop__text">{d.sop}</Text>
                            </View>
                          ) : null}
                          {reviewing ? <Text className="typo-meta">{c.storeInReview}</Text> : null}
                          {uploadWait ? <Text className="typo-meta">{c.portalNotStore}</Text> : null}
                          {showPaste && !uploadWait ? <Text className="typo-meta">{c.pasteStoreFallback}</Text> : null}
                          {uploadWait && releaseHasKit(release) ? (
                            <Button size="sm" variant="secondary" loading={busyId === release.id} onClick={() => void downloadKit(release.id)}>
                              {c.downloadKit}
                            </Button>
                          ) : null}
                          {uploadWait && d.originality_zip_url && d.work_id ? (
                            <Button size="sm" variant="ghost" onClick={() => void saveOriginalityPack(d.work_id as string, c)}>
                              {c.downloadOriginality}
                            </Button>
                          ) : null}
                          {portal ? (
                            <Button size="sm" variant="ghost" onClick={() => openExternal(portal)}>
                              {c.openMusicianPortal}
                            </Button>
                          ) : null}
                          {d.store_url ? (
                            <Button size="sm" variant="ghost" onClick={() => openExternal(d.store_url)}>
                              {c.openStorePage}
                            </Button>
                          ) : null}
                          {showPaste ? (
                            <>
                          <Input
                            label={uploadWait ? c.fillStoreLabel : c.pasteStoreFallback}
                            value={draft}
                            onInput={(e) => setUrls((prev) => ({ ...prev, [d.id]: e.detail.value }))}
                          />
                          <Text className={draft.trim() ? (urlOk ? "creator-url-ok" : "creator-url-bad") : "typo-meta"}>
                            {draft.trim() ? (urlOk ? c.urlLooksGood : c.notStorePage) : c.storePasteHint}
                          </Text>
                          <View className="creator-actions">
                            <Button size="sm" variant="secondary" loading={busyId === d.id} onClick={() => void saveUrl(d.id)}>
                              {c.fillStore}
                            </Button>
                            {canRetryDelivery(d) ? (
                              <Button size="sm" variant="ghost" loading={busyId === d.id} onClick={() => void retry(d)}>
                                {c.retry}
                              </Button>
                            ) : null}
                          </View>
                            </>
                          ) : null}
                          {!showPaste && expanded && canRetryDelivery(d) ? (
                            <View className="creator-actions">
                              <Button size="sm" variant="secondary" loading={busyId === d.id} onClick={() => void retry(d)}>
                                {c.retry}
                              </Button>
                            </View>
                          ) : null}
                        </View>
                      )}
                    </View>
                  );
                })}
              </View>
            );
          })}
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
