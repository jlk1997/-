import { useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh, useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { AsyncPanel, Badge, Button, Collapsible, EmptyState, Input, MetricCard, PostProcessBadges, SectionLabel, SegmentedControl, StatusLine } from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { creatorPage, socialPage, STACK_PAGE_ROUTES } from "../../../constants/routes";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { usePlayer } from "../../../contexts/PlayerProvider";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import {
  channelName,
  confirmCreatorAction,
  formatCount,
  humanizeDeliveryError,
  formatFen,
  formatPredictedRange,
  formatWarmup,
  isLiveDelivery,
  isMetricsOnlyDelivery,
  isStoreAssist,
  liveProgress,
  settlementSourceLabel,
  statusLabel,
  statusTone,
  storeRowMeta,
  type DeliveryRow,
  type ReleaseRow,
} from "../../lib";
import { ChannelMark } from "../../ChannelMark";
import { NextActionCard } from "../../NextActionCard";
import { saveClipPack, saveOriginalityPack } from "../../kitAction";
import { WorkReleaseTimeline, type JourneyNext, type JourneyStage } from "../../../components/studio/WorkReleaseTimeline";
import { WorkQualityCard } from "../../../components/studio/WorkQualityCard";
import { ProgressTimeline } from "../../../components/studio/ProgressTimeline";
import { AssetLanes } from "../../../components/studio/AssetLanes";
import { isPostProcessDegraded } from "../../../utils/postProcess";
import { hapticLight } from "../../../utils/haptic";
import { goCreatorAction, goShipBand } from "../../nextActionNav";
import { ShipCompleteCard } from "../../ShipCompleteCard";
import { openWorkbench } from "../../../utils/workbenchNav";
import "../../creator.scss";
import "./index.scss";

type SplitShare = { user_id: string; username?: string; role: string; percent: number };

type WorkLedger = {
  work?: {
    id: string;
    title?: string;
    cover_url?: string;
    release_status?: string;
    isrc?: string;
    live_stores?: number;
    audio_url?: string;
    from_workbench?: boolean;
    superseded_by_work_id?: string | null;
  };
  asset_status?: {
    listing?: { ready?: boolean; label?: string; wav?: boolean };
    evidence?: { needed?: boolean; ready?: boolean; label?: string; quality?: string };
    clips?: { needed?: boolean; ready?: boolean; key?: string };
    instrumental?: { needed?: boolean; ready?: boolean; work_id?: string; can_spawn?: boolean };
    needs_ai_musician?: boolean;
  };
  money_timeline?: {
    stages?: Array<{ id: string; done?: boolean; minor?: number }>;
    current?: number;
    predicted?: { low_minor?: number; high_minor?: number; currency?: string };
    display_only_prediction?: boolean;
    sources?: {
      radio_minor?: number;
      sync_minor?: number;
      embed_minor?: number;
      dsp_minor?: number;
      harvest_minor?: number;
    };
  };
  period_key?: string;
  streams?: number;
  display_streams?: number;
  revenue_minor?: number;
  predicted_revenue?: {
    low_minor?: number;
    mid_minor?: number;
    high_minor?: number;
    currency?: string;
    disclaimer?: string;
    geo_applied?: boolean;
    basis?: string;
  };
  store_compare?: {
    top_channel?: string;
    top_streams?: number;
    runner_up?: string;
  };
  has_real_data?: boolean;
  has_label_statement?: boolean;
  has_label_release?: boolean;
  waiting_for_statement?: boolean;
  label_period?: { expected_earliest?: string; expected_latest?: string };
  warmup_revenue_minor?: number;
  label_revenue_minor?: number;
  next_action?: "release" | "stores" | "import" | "wallet" | "settlements" | "watch_trial" | "radio_trial" | "sync" | "reprocess" | "beautify" | "fill_release";
  next_for_work?: { step?: string };
  requested_fields?: string[];
  versions?: Array<{ id: string; title?: string; label: string; version?: number; current?: boolean }>;
  unmatched_count?: number;
  radio_trial?: { status?: string; live?: boolean; station?: string; listen_completes?: number; channel_suggestion?: { reason?: string; channels?: string[] }; next_action?: string };
  channel_suggestion?: { reason?: string; channels?: string[] };
  by_channel?: Array<{
    channel_code: string;
    streams: number;
    display_streams?: number;
    revenue_minor: number;
    has_real?: boolean;
    predicted_revenue?: {
      low_minor?: number;
      high_minor?: number;
      currency?: string;
    };
  }>;
  releases?: ReleaseRow[];
  deliveries?: DeliveryRow[];
  settlement_lines?: Array<{
    period_key?: string;
    status?: string;
    withdrawable?: boolean;
    channel_code: string;
    source: string;
    accounting_subject?: string;
    net_minor: number;
    gross_minor?: number;
    commission_rate?: number;
    currency?: string;
  }>;
  clip_drops?: Array<{ id: string; portal_name?: string; url?: string; clip_length?: number; display_only?: boolean }>;
  clip_windows?: Array<{ length?: number; start?: number; end?: number }>;
  by_clip?: Array<{ length?: number; start?: number; end?: number; drops?: number; revenue_minor?: number; display_only?: boolean }>;
};

function goAction(action: WorkLedger["next_action"], workId: string, extra?: { stores?: string; station?: string }) {
  goCreatorAction(String(action || "settlements"), { workId, stores: extra?.stores, station: extra?.station });
}
export default function CreatorWorkPage() {
  const { copy, locale } = useLocale();
  const { playTrack } = usePlayer();
  const c = copy.creatorUi;
  const weapp = process.env.TARO_ENV === "weapp";
  const router = useRouter();
  const workId = String(router.params.workId || router.params.id || "");
  const compactWan = locale !== "en";
  const [splits, setSplits] = useState<SplitShare[]>([]);
  const [newName, setNewName] = useState("");
  const [newPercent, setNewPercent] = useState("10");
  const [splitBusy, setSplitBusy] = useState(false);
  const [playBusy, setPlayBusy] = useState("");
  const [clipUrl, setClipUrl] = useState("");
  const [syncEnabled, setSyncEnabled] = useState(false);
  const [syncTiers, setSyncTiers] = useState<string[]>(["personal", "short_video"]);
  const [syncCatalog, setSyncCatalog] = useState<Array<{ id: string; label: string; fiat_minor: number }>>([]);
  const [syncBusy, setSyncBusy] = useState(false);
  const [soldOrders, setSoldOrders] = useState<Array<{ id: string; work_id?: string; tier?: string; status?: string; seller_minor?: number; license_id?: string }>>([]);
  const [ledgerPane, setLedgerPane] = useState<"home" | "split" | "sync" | "radio" | "clips" | "ship">(() => {
    const pane = String(router.params.pane || "");
    if (pane === "release" || pane === "ship") return "ship";
    return pane === "split" || pane === "sync" || pane === "radio" || pane === "clips" ? pane : "home";
  });
  const [postProcess, setPostProcess] = useState<Record<string, unknown> | undefined>();
  const [timeline, setTimeline] = useState<{ stages?: JourneyStage[]; next_action?: JourneyNext | null } | null>(null);
  const [reprocessing, setReprocessing] = useState(false);
  const [spawningInstrumental, setSpawningInstrumental] = useState(false);
  const { data, loading, error, reload } = useAsyncQuery<WorkLedger | null>(async () => {
    if (!requireAuth(creatorPage("work", { workId })) || !workId) return null;
    const [ledger, splitRes, listing, tiers, sold, detail, journey] = await Promise.all([
      vibeApi.getCreatorWork(workId) as Promise<WorkLedger>,
      vibeApi.getWorkSplits(workId).catch(() => ({ shares: [] as SplitShare[] })),
      vibeApi.getSyncListing(workId).catch(() => ({ enabled: false, tiers: [] as string[] })),
      vibeApi.listSyncTiers().catch(() => ({ tiers: [] })),
      vibeApi.listSyncOrders("sold").catch(() => ({ orders: [] })),
      vibeApi.getWork(workId).catch(() => null),
      vibeApi.getWorkTimeline(workId).catch(() => null),
    ]);
    setSplits(splitRes.shares || []);
    setSyncEnabled(Boolean(listing.enabled));
    setSyncTiers(((listing.tiers as string[]) || []).filter(Boolean).length ? (listing.tiers as string[]) : ["personal", "short_video"]);
    setSyncCatalog((tiers.tiers || []).map((row) => ({ id: row.id, label: row.label, fiat_minor: row.fiat_minor })));
    setSoldOrders(((sold.orders || []) as typeof soldOrders).filter((row) => !row.work_id || row.work_id === workId));
    setPostProcess(detail?.post_process_status);
    setTimeline(journey ? { stages: journey.stages, next_action: journey.next_action } : null);
    return ledger;
  }, [workId]);

  useDidShow(() => {
    void reload();
  });
  usePullDownRefresh(async () => {
    await reload();
    Taro.stopPullDownRefresh();
  });

  const work = data?.work;
  const shipId = work?.superseded_by_work_id || workId;
  const hasMaster = Boolean(work?.from_workbench || work?.superseded_by_work_id);
  const deliveries = data?.deliveries || [];
  const { live, total } = liveProgress(deliveries);
  const liveNow = Number(work?.live_stores) > 0 || live > 0;
  const inFlight =
    ["delivering", "queued"].includes(work?.release_status || "") ||
    (work?.release_status === "live" && !liveNow) ||
    deliveries.some((d) => d.status === "live" && !isLiveDelivery(d));
  const shipped = liveNow || inFlight;
  const degraded = isPostProcessDegraded(postProcess);
  const action = (data?.next_for_work?.step ||
    (degraded ? "reprocess" : !hasMaster ? "beautify" : data?.next_action || "release")) as WorkLedger["next_action"];
  const uploadOnly = deliveries.some((d) => d.user_status === "needs_upload" || d.status === "needs_upload")
    && !deliveries.some((d) => ["session_wait", "session_running", "waiting_login", "assisting"].includes(d.user_status || d.status || ""));
  const nextCopy = {
    release: { title: c.readyToRelease, hint: c.nextReleaseHint },
    stores: uploadOnly
      ? { title: c.nextStoresUpload, hint: c.nextStoresUploadHint }
      : { title: c.nextStores, hint: c.nextStoresHint },
    import: { title: c.nextConnector, hint: c.nextConnectorHint.replace("{n}", "0") },
    settlements: { title: c.nextSettlements, hint: c.nextSettlementsHint },
    wallet:
      data?.has_label_release === false
        ? { title: c.nextSelfRelease, hint: c.nextSelfReleaseHint }
        : { title: c.nextWallet, hint: c.nextWalletHint },
    watch_trial: { title: c.radioTrialLive, hint: c.radioTrialHint },
    radio_trial: { title: c.radioTrialStart, hint: c.radioTrialHint },
    sync: { title: c.nextSync, hint: c.nextSyncHint },
    reprocess: { title: c.nextReprocess, hint: c.nextReprocessHint },
    beautify: { title: c.beautifyFirst, hint: copy.workbenchUi.honesty },
    fill_release: { title: c.shipOpenForm, hint: (data?.requested_fields || []).join("、") },
  }[action || "release"] || { title: c.nextSettlements, hint: c.nextSettlementsHint };
  const suggestedStores = (data?.channel_suggestion?.channels || data?.radio_trial?.channel_suggestion?.channels || []).map(
    (code) => channelName(code, c.channels),
  );
  const harvestMinor = data?.money_timeline?.sources?.harvest_minor || 0;
  const labelMinor = data?.label_revenue_minor || 0;
  const warmupMinor = data?.warmup_revenue_minor || 0;
  const hasHarvestMoney = Boolean(data?.has_label_statement) || harvestMinor > 0;

  async function runReprocess() {
    if (reprocessing) return;
    const ok = await confirmCreatorAction({
      title: c.reprocessConfirmTitle,
      content: c.reprocessConfirmHint,
      confirmText: c.confirmGo,
      cancelText: c.back,
    });
    if (!ok) return;
    setReprocessing(true);
    hapticLight();
    try {
      await vibeApi.reprocessWork(workId).catch(() => vibeApi.triggerPostProcess(workId));
      Taro.showToast({ title: copy.worksUi.reprocessQueued, icon: "success" });
      setPostProcess((prev) => ({ ...(prev || {}), state: "pending", failed: false }));
      void reload();
    } catch {
      Taro.showToast({ title: copy.worksUi.reprocessFail, icon: "none" });
    } finally {
      setReprocessing(false);
    }
  }

  async function handleNext() {
    if (action === "reprocess") {
      await runReprocess();
      return;
    }
    if (action === "fill_release") {
      Taro.navigateTo({ url: creatorPage("release", { workId: shipId }) });
      return;
    }
    const targetId = action === "beautify" || action === "reprocess" ? workId : shipId;
    goAction(action, targetId, {
      stores: (data?.channel_suggestion?.channels || data?.radio_trial?.channel_suggestion?.channels)?.join(","),
      station: data?.radio_trial?.station,
    });
  }

  return (
    <PageShell title={c.workLedgerTitle} subtitle={work?.title || c.hubSubtitle} ambient>
      <View className="creator">
        {(action === "stores" || action === "settlements") && (
          <WeappH5Bridge path={creatorPage("work", { workId: workId || undefined })} />
        )}
        {weapp ? <StatusLine tone="info" density="quiet">{c.weappDeskHint}</StatusLine> : null}
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void reload()}
          empty={!workId || (!loading && !work)}
          emptyTitle={c.emptyWorkLedger}
          emptyDescription={c.hubSubtitle}
        >
          <View className="creator-hub-tabs">
            <Button size="sm" variant={ledgerPane === "home" ? "primary" : "ghost"} onClick={() => setLedgerPane("home")}>
              听
            </Button>
            <Button size="sm" variant="ghost" onClick={() => openWorkbench(workId)}>
              修
            </Button>
            <Button size="sm" variant={ledgerPane === "ship" ? "primary" : "ghost"} onClick={() => setLedgerPane("ship")}>
              发行
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setLedgerPane("home")}>
              收入
            </Button>
          </View>
          {(data?.versions || []).length > 1 ? (
            <View className="creator-hub-tabs">
              {(data?.versions || []).map((version) => (
                <Button
                  key={version.id}
                  size="sm"
                  variant={version.current ? "secondary" : "ghost"}
                  onClick={() => {
                    if (!version.current) Taro.redirectTo({ url: creatorPage("work", { workId: version.id, pane: ledgerPane }) });
                  }}
                >
                  {`v${version.version || ""} ${version.label}`}
                </Button>
              ))}
            </View>
          ) : null}
          {(data?.requested_fields || []).length ? (
            <StatusLine tone="warning" onClick={() => Taro.navigateTo({ url: creatorPage("release", { workId: shipId }) })}>
              {`还差：${(data?.requested_fields || []).join("、")}。补上后我们继续交歌。`}
            </StatusLine>
          ) : null}
          <View className="creator-hero">
            <View
              className="creator-hero__art"
              onClick={() => {
                if (!work?.audio_url) return;
                playTrack(
                  workToPlayerTrack(
                    { id: workId, title: work.title || "", audio_url: work.audio_url, cover_url: work.cover_url },
                    { source: "studio" },
                  ),
                  { navigate: false },
                );
              }}
            >
              {work?.cover_url ? (
                <Image className="creator-hero__cover" src={work.cover_url} mode="aspectFill" />
              ) : (
                <View className="creator-hero__cover creator-hero__cover--empty" />
              )}
            </View>
            <Text className="creator-hero__kicker">{c.workLedgerTitle}</Text>
            <Text className="creator-hero__title">{work?.title || c.releaseUntitled}</Text>
            {work?.from_workbench ? (
              <Text className="creator-hero__sub">{copy.worksUi.beautifyMaster}</Text>
            ) : null}
            {work?.superseded_by_work_id ? (
              <StatusLine
                tone="info"
                onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId: work.superseded_by_work_id || "" }) })}
              >
                {c.releasePreferMaster}
              </StatusLine>
            ) : null}
            <Text className="creator-hero__sub">
              {work?.release_status ? statusLabel(work.release_status, c.status) : ""}
              {data?.period_key ? ` · ${data.period_key}` : ""}
            </Text>
            <NextActionCard
              kicker={c.nextAction}
              title={nextCopy.title}
              hint={nextCopy.hint}
              go={c.nextGo}
              coverUrl={work?.cover_url}
              urgent={action === "release" || action === "stores" || action === "reprocess"}
              waiting={reprocessing}
              chips={action === "release" || action === "stores" ? suggestedStores : action === "reprocess" ? [copy.worksUi.artifactsDegraded] : undefined}
              onClick={() => void handleNext()}
            />
            {hasMaster ? (
              <ShipCompleteCard
                workId={shipId}
                surface="desk"
                qcReady={["qc_ready", "queued", "delivering", "live"].includes(work?.release_status || "")}
                releaseStatus={work?.release_status || ""}
                embedAuth
                weapp={weapp}
              />
            ) : null}
          </View>

          {shipped ? (
            <View className="creator-card creator-card--soft">
              <Text className="creator-pick__title">
                {(Number(work?.live_stores) > 0
                  ? c.workGlanceLive
                  : c.workGlanceWarm
                )
                  .replace("{title}", work?.title || c.releaseUntitled)
                  .replace("{n}", String(work?.live_stores || live || 0))
                  .replace("{streams}", formatCount(data?.streams ?? data?.display_streams, compactWan))}
              </Text>
              {labelMinor > 0 ? (
                <Text className="creator-pick__meta">{c.workGlanceMoney.replace("{amount}", formatFen(labelMinor))}</Text>
              ) : null}
              {warmupMinor > 0 ? (
                <Text className="creator-pick__meta">{formatWarmup(warmupMinor, c.workGlanceWarmup)}</Text>
              ) : null}
              {labelMinor <= 0 && warmupMinor <= 0 ? <Text className="typo-meta">{c.waitHarvestShort}</Text> : null}
            </View>
          ) : null}

          {total > 0 && (
            <>
              <Text className="typo-meta">
                {c.liveProgress.replace("{n}", String(live)).replace("{m}", String(total))}
              </Text>
              <View className="creator-progress">
                <View className="creator-progress__bar" style={{ width: `${Math.round((live / total) * 100)}%` }} />
              </View>
              {deliveries.slice(0, 2).map((d) => {
                const meta = storeRowMeta(d, c);
                return (
                  <View
                    key={d.id}
                    className={`creator-channel creator-channel--tap ${isLiveDelivery(d) ? "creator-channel--live" : isStoreAssist(d.status, d.user_status) ? "creator-channel--wait" : isMetricsOnlyDelivery(d) ? "creator-channel--metrics" : ""}`.trim()}
                    onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { workId, releaseId: d.release_id }) })}
                  >
                    <View className="creator-channel__head">
                      <ChannelMark code={d.channel_code} />
                      <View>
                        <Text className="creator-channel__name">{channelName(d.channel_code, c.channels)}</Text>
                        <Text className="creator-channel__meta">{meta.line}</Text>
                      </View>
                    </View>
                    <Badge tone={statusTone(d.user_status || d.status)}>
                      {statusLabel(d.user_status || d.status, c.status)}
                    </Badge>
                  </View>
                );
              })}
              {deliveries.length > 2 ? (
                <Button size="sm" variant="ghost" onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { workId }) })}>
                  {c.goDeliveries}
                </Button>
              ) : null}
            </>
          )}
          {deliveries.some((d) => d.sla_escalated || d.sla_overdue) ? (
            <StatusLine tone="error">{deliveries.some((d) => d.sla_escalated) ? c.slaEscalated : c.slaOverdue}</StatusLine>
          ) : shipped && data?.has_label_release === false ? (
            <StatusLine tone="info" density="quiet">{c.selfReleaseHint}</StatusLine>
          ) : null}

          {shipped ? (
          <SegmentedControl
            className="creator-ledger-tabs"
            options={[
              { value: "home", label: c.workTabOverview },
              { value: "ship", label: c.shipBandTitle || "发行" },
              { value: "split", label: c.workTabSplit },
              { value: "sync", label: c.workTabSync },
              { value: "radio", label: c.workTabRadio },
              { value: "clips", label: c.workTabClips },
            ]}
            value={ledgerPane}
            onChange={(v) => setLedgerPane(v as typeof ledgerPane)}
          />
          ) : null}

          {ledgerPane === "home" && (
          <>
          {shipped ? (
            <View className="creator-actions">
              {liveNow ? (
                <Button size="sm" variant="secondary" onClick={() => Taro.navigateTo({ url: creatorPage("passport", { workId }) })}>
                  {c.goPassport}
                </Button>
              ) : (
                <Button size="sm" variant="secondary" onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { workId: shipId }) })}>
                  {c.viewProgress}
                </Button>
              )}
            </View>
          ) : (
            <View className="creator-actions">
              <Button size="sm" variant="ghost" onClick={() => Taro.navigateTo({ url: `${STACK_PAGE_ROUTES.work}?workId=${workId}` })}>
                {c.workOpenListen}
              </Button>
            </View>
          )}

          <PostProcessBadges
            status={postProcess}
            onRetry={undefined}
            retrying={reprocessing}
          />
          {data?.asset_status && !degraded ? (
            <AssetLanes
              density="full"
              status={data.asset_status}
              skuKind={String(postProcess?.sku_kind || "")}
              onDownloadOriginality={data.asset_status.evidence?.ready ? () => void saveOriginalityPack(workId, c) : undefined}
              onDownloadClips={shipped && data.asset_status.clips?.ready ? () => void saveClipPack(workId, c) : undefined}
              spawningInstrumental={spawningInstrumental}
              onSpawnInstrumental={() => {
                void (async () => {
                  setSpawningInstrumental(true);
                  try {
                    await vibeApi.spawnInstrumentalSku(workId);
                    Taro.showToast({ title: copy.lightEditorUi.instrumentalSkuOk, icon: "success" });
                    await reload();
                  } catch {
                    Taro.showToast({ title: copy.lightEditorUi.instrumentalSkuFail, icon: "none" });
                  } finally {
                    setSpawningInstrumental(false);
                  }
                })();
              }}
            />
          ) : null}
          {data?.money_timeline?.stages?.length ? (
            <View className="creator-card">
              <Text className="creator-pick__title">{c.moneyTimelineTitle}</Text>
              <ProgressTimeline
                steps={data.money_timeline.stages.map((stage) => ({
                  id: stage.id,
                  label:
                    {
                      live: c.moneyStageLive,
                      amount: c.moneyStageAmount,
                      commission: c.moneyStageCommission,
                      withdrawable: c.moneyStageWithdrawable,
                      paid: c.moneyStagePaid,
                    }[stage.id] || stage.id,
                }))}
                current={data.money_timeline.current || 0}
              />
              {hasHarvestMoney && data.money_timeline.predicted ? (
                <Text className="typo-meta">
                  {c.moneyPredictedHint}
                  {formatPredictedRange(data.money_timeline.predicted, c.predictedRange)
                    ? ` ${formatPredictedRange(data.money_timeline.predicted, c.predictedRange)}`
                    : ""}
                </Text>
              ) : null}
              {data.money_timeline.sources ? (
                <Text className="typo-meta">
                  {[
                    data.money_timeline.sources.dsp_minor
                      ? `${c.walletDsp} ${formatFen(data.money_timeline.sources.dsp_minor)}`
                      : "",
                    data.money_timeline.sources.harvest_minor
                      ? `${c.walletHarvest} ${formatFen(data.money_timeline.sources.harvest_minor)}`
                      : "",
                    data.money_timeline.sources.radio_minor
                      ? `${c.walletRadio} ${formatWarmup(data.money_timeline.sources.radio_minor, c.warmupNotCash)}`
                      : "",
                    data.money_timeline.sources.sync_minor
                      ? `${c.walletSync} ${formatFen(data.money_timeline.sources.sync_minor)}`
                      : "",
                    data.money_timeline.sources.embed_minor
                      ? `${c.walletEmbed} ${formatFen(data.money_timeline.sources.embed_minor)}`
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" · ") || c.moneySourcesHint}
                </Text>
              ) : null}
            </View>
          ) : null}
          {work?.id ? (
            <WorkQualityCard workId={shipId} title={work.title} doorOnly onRemelt={() => openWorkbench(workId)} />
          ) : null}
          {timeline?.stages?.length && !degraded ? (
            <WorkReleaseTimeline
              stages={timeline.stages}
              nextAction={timeline.next_action}
              busy={reprocessing}
              copy={{
                title: copy.worksUi.journeyTitle,
                go: c.nextGo,
                waitHint: copy.worksUi.journeyWait,
                doneHint: copy.worksUi.journeyDone,
                statusDone: copy.worksUi.statusDone,
                statusWait: copy.worksUi.statusWait,
                statusNeed: copy.worksUi.statusNeed,
                statusLive: copy.worksUi.statusLive,
                statusFail: copy.worksUi.statusFail,
              }}
              onAction={(act) => {
                if (act === "reprocess") {
                  void runReprocess();
                  return;
                }
                if (act === "beautify") {
                  goCreatorAction("beautify", { workId });
                  return;
                }
                const mapped: WorkLedger["next_action"] =
                  act === "run_qc" || act === "release"
                    ? "release"
                    : act === "wait_revenue"
                      ? "wallet"
                      : act === "wait" || act === "wait_review"
                        ? "stores"
                        : act === "sync"
                          ? "sync"
                          : "settlements";
                goAction(mapped, mapped === "beautify" ? workId : shipId);
              }}
            />
          ) : null}

          {shipped ? (
            <Collapsible label={c.workNumbersMore} defaultOpen={false}>
              <View className="creator-metrics">
                <MetricCard
                  icon="sigil"
                  label={c.walletDsp}
                  value={labelMinor > 0 ? formatFen(labelMinor) : c.waitHarvestShort}
                  variant="info"
                />
                <MetricCard icon="music" label={c.walletRadio} value={formatWarmup(data?.warmup_revenue_minor, c.warmupNotCash)} />
                <MetricCard icon="music" label={c.streams} value={formatCount(data?.streams, compactWan)} />
              </View>
              {hasHarvestMoney && (data?.predicted_revenue?.high_minor || 0) > 0 ? (
                <>
                  <MetricCard
                    icon="flask"
                    label={c.predictedRevenue}
                    value={formatPredictedRange(data?.predicted_revenue, c.predictedRange) || "—"}
                  />
                  <StatusLine tone="info" density="quiet">
                    {c.bookedVsPredicted
                      .replace("{booked}", formatFen(data?.revenue_minor))
                      .replace("{range}", formatPredictedRange(data?.predicted_revenue, c.predictedRange) || "—")}
                  </StatusLine>
                  <StatusLine tone="info" density="quiet">
                    {data?.predicted_revenue?.basis === "history" ? c.predictedBasisHistory : c.predictedBasisCatalog}
                    {data?.predicted_revenue?.geo_applied ? ` ${c.predictedGeo}` : ` ${c.predictedDisclaimer}`}
                  </StatusLine>
                  {data?.store_compare?.top_channel ? (
                    <StatusLine tone="info" density="quiet">
                      {c.storeCompareLine
                        .replace("{top}", channelName(data.store_compare.top_channel))
                        .replace("{n}", String(data.store_compare.top_streams || ""))}
                    </StatusLine>
                  ) : null}
                </>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { workId: shipId }) })}
              >
                {c.viewProgress}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => Taro.navigateTo({ url: `${STACK_PAGE_ROUTES.work}?workId=${workId}` })}>
                {copy.pages.works.title}
              </Button>
            </Collapsible>
          ) : null}
          </>
          )}

          {ledgerPane === "ship" && workId ? (
            <ShipCompleteCard workId={workId} surface="desk" embedAuth />
          ) : null}

          {ledgerPane === "split" && (
          <>
          <SectionLabel>{c.splitSheet}</SectionLabel>
          <StatusLine tone="info" density="quiet">{c.splitHint}</StatusLine>
          {splits.map((share, index) => (
            <View key={`${share.user_id}-${index}`} className="creator-channel">
              <View>
                <Text className="creator-channel__name">
                  {share.username || share.user_id.slice(0, 8)}
                </Text>
                <View className="creator-actions">
                  {(["owner", "parent", "collaborator"] as const).map((role) => (
                    <Button
                      key={role}
                      size="sm"
                      variant={share.role === role ? "primary" : "ghost"}
                      onClick={() => setSplits((prev) => prev.map((row, i) => (i === index ? { ...row, role } : row)))}
                    >
                      {role === "owner" ? c.splitRoleOwner : role === "parent" ? c.splitRoleParent : c.splitRoleCollaborator}
                    </Button>
                  ))}
                </View>
              </View>
              <Input
                label={c.splitPercent}
                value={String(share.percent)}
                onInput={(e) => {
                  const percent = Number(e.detail.value.replace(/[^\d]/g, "")) || 0;
                  setSplits((prev) => prev.map((row, i) => (i === index ? { ...row, percent } : row)));
                }}
              />
              {share.role !== "owner" && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setSplits((prev) => prev.filter((_, i) => i !== index))}
                >
                  {c.splitRemove}
                </Button>
              )}
            </View>
          ))}
          {splits.length < 4 && (
            <View className="creator-store">
              <Input label={c.splitUsername} value={newName} onInput={(e) => setNewName(e.detail.value)} />
              <Input label={c.splitPercent} value={newPercent} onInput={(e) => setNewPercent(e.detail.value)} />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  const percent = Number(newPercent) || 0;
                  if (!newName.trim() || percent <= 0) return;
                  setSplits((prev) => [...prev, { user_id: "", username: newName.trim(), role: "collaborator", percent }]);
                  setNewName("");
                }}
              >
                {c.splitAdd}
              </Button>
            </View>
          )}
          <Button
            size="sm"
            variant="secondary"
            loading={splitBusy}
            onClick={() => {
              void (async () => {
                if (weapp) {
                  await copyWeappCreatorLink(creatorPage("work", { workId }));
                  Taro.showToast({ title: c.weappDeskHint, icon: "none" });
                  return;
                }
                const total = splits.reduce((sum, row) => sum + Number(row.percent || 0), 0);
                if (total !== 100) {
                  Taro.showToast({ title: c.splitMust100, icon: "none" });
                  return;
                }
                setSplitBusy(true);
                try {
                  const saved = await vibeApi.saveWorkSplits(
                    workId,
                    splits.map((row) => ({
                      user_id: row.user_id || undefined,
                      username: row.username,
                      role: row.role,
                      percent: row.percent,
                    })),
                  );
                  setSplits(saved.shares || splits);
                  Taro.showToast({ title: c.splitSaved, icon: "success" });
                } catch {
                  Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                } finally {
                  setSplitBusy(false);
                }
              })();
            }}
          >
            {c.splitSave}
          </Button>
          </>
          )}

          {ledgerPane === "sync" && (
          <>
          <SectionLabel>{c.syncListingTitle}</SectionLabel>
          <StatusLine tone="info" density="quiet">{c.syncListingHint}</StatusLine>
          <Button
            size="sm"
            variant={syncEnabled ? "primary" : "secondary"}
            onClick={() => setSyncEnabled((prev) => !prev)}
          >
            {syncEnabled ? c.syncListingOn : c.syncListingOff}
          </Button>
          {syncEnabled && (
            <View className="creator-store">
              {syncCatalog.map((tier) => {
                const on = syncTiers.includes(tier.id);
                return (
                  <Button
                    key={tier.id}
                    size="sm"
                    variant={on ? "primary" : "ghost"}
                    onClick={() =>
                      setSyncTiers((prev) => (prev.includes(tier.id) ? prev.filter((id) => id !== tier.id) : [...prev, tier.id]))
                    }
                  >
                    {tier.label}
                    {tier.fiat_minor ? ` · ${formatFen(tier.fiat_minor)}` : ""}
                  </Button>
                );
              })}
            </View>
          )}
          <Button
            size="sm"
            variant="secondary"
            loading={syncBusy}
            onClick={() => {
              void (async () => {
                if (weapp) {
                  await copyWeappCreatorLink(creatorPage("work", { workId }));
                  Taro.showToast({ title: c.weappDeskHint, icon: "none" });
                  return;
                }
                setSyncBusy(true);
                try {
                  await vibeApi.saveSyncListing(workId, syncEnabled, syncTiers);
                  Taro.showToast({ title: c.splitSaved, icon: "success" });
                } catch {
                  Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                } finally {
                  setSyncBusy(false);
                }
              })();
            }}
          >
            {c.syncListingSave}
          </Button>
          {syncEnabled && soldOrders.length === 0 && <StatusLine tone="info">{c.soldEmpty}</StatusLine>}
          {soldOrders.length > 0 && (
            <>
              <SectionLabel>{c.soldOrders}</SectionLabel>
              {soldOrders.map((order) => (
                <View key={order.id} className="creator-channel">
                  <View>
                    <Text className="creator-channel__name">{order.license_id || order.id}</Text>
                    <Text className="creator-channel__meta">
                      {order.tier || "—"}
                      {order.seller_minor != null ? ` · ${formatFen(order.seller_minor)}` : ""}
                    </Text>
                  </View>
                  <Badge tone={statusTone(order.status)}>{statusLabel(order.status || "pending", c.status)}</Badge>
                </View>
              ))}
            </>
          )}

          </>
          )}

          {ledgerPane === "radio" && (
          <>
          <SectionLabel>{c.radioTrialTitle}</SectionLabel>
          <StatusLine tone="info" density="quiet">{c.radioTrialHint}</StatusLine>
          {data?.radio_trial?.live ? (
            <>
              <StatusLine tone="success">
                {[
                  c.radioTrialLive,
                  data.radio_trial.station,
                  copy.engagementUi.radioCompletes.replace("{n}", String(data.radio_trial.listen_completes || 0)),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </StatusLine>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  Taro.navigateTo({
                    url: socialPage("radio", { workId, station: data.radio_trial?.station }),
                  })
                }
              >
                {copy.engagementUi.radioOpen}
              </Button>
            </>
          ) : data?.radio_trial?.status === "ended" ? (
            <>
              <StatusLine tone="info">
                {[c.radioTrialEnded, data.radio_trial.channel_suggestion?.reason].filter(Boolean).join(" · ")}
              </StatusLine>
              {action === "sync" || action === "wallet" || action === "stores" ? (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() =>
                    goAction(action, workId, {
                      stores: (data?.channel_suggestion?.channels || data?.radio_trial?.channel_suggestion?.channels)?.join(","),
                      station: data?.radio_trial?.station,
                    })
                  }
                >
                  {nextCopy.title}
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="primary"
                  loading={playBusy === "release"}
                  onClick={() =>
                    goShipBand(workId)
                  }
                >
                  {c.trialEndedRelease}
                </Button>
              )}
              {(data.radio_trial.channel_suggestion?.channels || data.channel_suggestion?.channels || []).length > 0 ? (
                <View className="creator-actions">
                  {(data.radio_trial.channel_suggestion?.channels || data.channel_suggestion?.channels || []).map((code) => (
                    <Button
                      key={code}
                      size="sm"
                      variant="ghost"
                      onClick={() => goShipBand(workId)}
                    >
                      {channelName(code, c.channels)}
                    </Button>
                  ))}
                </View>
              ) : null}
            </>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              loading={playBusy === "trial"}
              onClick={() => {
                void (async () => {
                  const ok = await confirmCreatorAction({
                    title: c.radioTrialStart,
                    content: c.radioTrialConfirm,
                    confirmText: c.confirmGo,
                    cancelText: c.back,
                  });
                  if (!ok) return;
                  setPlayBusy("trial");
                  try {
                    const trial = (await vibeApi.startRadioTrial(
                      shipId,
                      data?.radio_trial?.station,
                    )) as { work_id?: string; station?: string };
                    Taro.showToast({ title: c.radioTrialLive, icon: "success" });
                    Taro.navigateTo({
                      url: socialPage("radio", {
                        workId: trial.work_id || shipId,
                        station: typeof trial.station === "string" ? trial.station : data?.radio_trial?.station,
                      }),
                    });
                    await reload();
                  } catch (err) {
                    Taro.showToast({
                      title: humanizeDeliveryError(String((err as Error)?.message || ""), c, copy.adminUi.actionFail) || copy.adminUi.actionFail,
                      icon: "none",
                    });
                  } finally {
                    setPlayBusy("");
                  }
                })();
              }}
            >
              {c.radioTrialStart}
            </Button>
          )}
          </>
          )}

          {ledgerPane === "clips" && (
          <>
          {(data?.by_clip || []).length > 0 && (
            <>
              <SectionLabel>{c.byClip}</SectionLabel>
              {(data?.by_clip || []).map((clip) => (
                <View key={`${clip.length}-${clip.start}`} className="creator-check">
                  <Text className="creator-check__label">{`${clip.length}s · ${clip.start}–${clip.end} · ${clip.drops || 0}`}</Text>
                  <Badge tone="accent">{c.displayOnlyBadge}</Badge>
                </View>
              ))}
            </>
          )}

          <SectionLabel>{c.clipDropTitle}</SectionLabel>
          <StatusLine tone="info" density="quiet">{c.clipWindowsHint}</StatusLine>
          {(data?.clip_windows || []).length > 0 && (
            <>
              <SectionLabel>{c.clipWindowsTitle}</SectionLabel>
              {(data?.clip_windows || []).map((clip) => (
                <View key={`${clip.length}-${clip.start}`} className="creator-check">
                  <Text className="creator-check__label">{`${clip.length}s · ${clip.start}–${clip.end}`}</Text>
                  <Badge tone="accent">{c.displayOnlyBadge}</Badge>
                  {work?.audio_url ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        playTrack(
                          workToPlayerTrack(
                            { id: workId, title: work.title || "", audio_url: work.audio_url || "", cover_url: work.cover_url },
                            { source: "studio" },
                          ),
                          { navigate: false, startAt: Number(clip.start) || 0 },
                        )
                      }
                    >
                      {c.clipPreview}
                    </Button>
                  ) : null}
                </View>
              ))}
            </>
          )}
          {(data?.clip_drops || []).length > 0
            ? (data?.clip_drops || []).map((drop) => (
                <View key={drop.id} className="creator-channel">
                  <View>
                    <Text className="creator-channel__name">{drop.portal_name || drop.url}</Text>
                    <Text className="creator-channel__meta">{`${drop.clip_length || 15}s · ${c.displayOnlyBadge}`}</Text>
                  </View>
                </View>
              ))
            : <StatusLine tone="info" density="quiet">{c.clipDropEmpty}</StatusLine>}
          <Button
            size="sm"
            variant="secondary"
            loading={playBusy === "clips"}
            onClick={() => {
              void (async () => {
                if (weapp) {
                  await copyWeappCreatorLink(creatorPage("work", { workId }));
                  Taro.showToast({ title: c.weappDeskHint, icon: "none" });
                  return;
                }
                setPlayBusy("clips");
                try {
                  await saveClipPack(workId, c);
                } catch {
                  Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                } finally {
                  setPlayBusy("");
                }
              })();
            }}
          >
            {c.downloadClipPack}
          </Button>
          <Input label={c.clipDropUrl} value={clipUrl} onInput={(e) => setClipUrl(e.detail.value)} />
          <Button
            size="sm"
            variant="ghost"
            loading={playBusy === "clip"}
            onClick={() => {
              void (async () => {
                if (weapp) {
                  await copyWeappCreatorLink(creatorPage("work", { workId }));
                  Taro.showToast({ title: c.weappDeskHint, icon: "none" });
                  return;
                }
                if (!clipUrl.trim()) return;
                setPlayBusy("clip");
                try {
                  await vibeApi.addClipDrop(workId, clipUrl.trim());
                  setClipUrl("");
                  Taro.showToast({ title: c.clipDropOk, icon: "success" });
                  await reload();
                } catch (err) {
                  Taro.showToast({
                    title: humanizeDeliveryError(String((err as Error)?.message || ""), c, copy.adminUi.actionFail) || copy.adminUi.actionFail,
                    icon: "none",
                  });
                } finally {
                  setPlayBusy("");
                }
              })();
            }}
          >
            {c.clipDropSave}
          </Button>
          </>
          )}

          {ledgerPane === "home" && (
          <>
          <SectionLabel>{c.byChannel}</SectionLabel>
          {(data?.by_channel || []).length === 0 && (
            <EmptyState
              iconName="music"
              title={c.emptyHub}
              description={c.dataHint}
              actionLabel={data?.has_label_release === false ? c.goWallet : c.goSettlements}
              onAction={() =>
                Taro.navigateTo({
                  url: creatorPage(data?.has_label_release === false ? "wallet" : "settlements"),
                })
              }
            />
          )}
          {(data?.by_channel || []).map((ch) => (
            <View
              key={ch.channel_code}
              className="creator-channel creator-channel--tap"
              onClick={() =>
                Taro.navigateTo({
                  url: creatorPage(
                    ch.has_real || data?.has_label_statement || data?.has_label_release || data?.waiting_for_statement
                      ? "settlements"
                      : "wallet",
                  ),
                })
              }
            >
              <View>
                <View className="creator-channel__head">
                  <ChannelMark code={ch.channel_code} />
                  <Text className="creator-channel__name">{channelName(ch.channel_code, c.channels)}</Text>
                </View>
                <Text className="creator-channel__meta">
                  {ch.streams ? `${c.streams} ${formatCount(ch.streams, compactWan)}` : c.waitingData}
                  {ch.display_streams ? ` · ${c.displayStreams} ${formatCount(ch.display_streams, compactWan)}` : ""}
                  {hasHarvestMoney && formatPredictedRange(ch.predicted_revenue, c.predictedRange)
                    ? ` · ${c.predictedRevenue} ${formatPredictedRange(ch.predicted_revenue, c.predictedRange)}`
                    : ""}
                </Text>
              </View>
              {ch.has_real ? (
                <View>
                  <Text className="creator-channel__name">{formatFen(ch.revenue_minor)}</Text>
                  {hasHarvestMoney && formatPredictedRange(ch.predicted_revenue, c.predictedRange) ? (
                    <Text className="creator-channel__meta">
                      {c.predictedRevenue} {formatPredictedRange(ch.predicted_revenue, c.predictedRange)}
                    </Text>
                  ) : null}
                </View>
              ) : (
                <Badge tone="accent">{c.displayOnlyBadge}</Badge>
              )}
            </View>
          ))}

          {(data?.releases || []).length > 0 && <SectionLabel>{c.recentReleases}</SectionLabel>}
          {(data?.releases || []).map((release) => {
            return (
              <View
                key={release.id}
                className="creator-card creator-card--tap"
                onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { releaseId: release.id, workId }) })}
              >
                <View className="creator-release-head">
                  <View>
                    <Text className="creator-pick__title">{release.metadata?.title || work?.title || c.releaseUntitled}</Text>
                    <Text className="creator-pick__meta">{release.mode === "self_release" ? c.modeA : c.modeB}</Text>
                  </View>
                  <Badge tone={statusTone(release.status)}>{statusLabel(release.status || "draft", c.status)}</Badge>
                </View>
              </View>
            );
          })}

          {(data?.settlement_lines || []).length > 0 && <SectionLabel>{c.goSettlements}</SectionLabel>}
          {(data?.settlement_lines || []).map((line, i) => (
            <View key={`${line.channel_code}-${i}`} className="creator-check">
              <View>
                <Text className="creator-check__label">
                  {channelName(line.channel_code, c.channels)}
                  {line.period_key ? ` · ${line.period_key}` : ""}
                </Text>
                <Text className="creator-channel__meta">
                  {c.sourceLabel.replace("{s}", settlementSourceLabel(line.source, c.sources))}
                  {line.accounting_subject === "warmup"
                    ? ` · ${c.walletRadio}`
                    : line.accounting_subject === "label_royalty"
                      ? ` · ${c.walletDsp}`
                      : ""}
                  {line.commission_rate ? ` · ${line.commission_rate}%` : ""}
                </Text>
              </View>
              <Text className="creator-channel__name">{formatFen(line.net_minor, line.currency)}</Text>
            </View>
          ))}
          </>
          )}
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
