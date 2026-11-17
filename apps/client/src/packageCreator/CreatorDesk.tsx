import { View, Text, Image } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../components/PageShell";
import { AsyncPanel, Badge, Button, Collapsible, EmptyState, Icon, LoadingSkeleton, MetricCard, NavTile, SectionLabel, SegmentedControl, StatusLine } from "../components/ui";
import { useEffect, useState, type ReactNode } from "react";
import { useAsyncQuery } from "../hooks/useAsyncQuery";
import { vibeApi } from "../services/api";
import { isLoggedIn, requireAuth } from "../utils/auth";
import {
  CREATOR_PAGE_ROUTES,
  CREATOR_PANE_KEY,
  CREATOR_SHIP_WORK_KEY,
  CREATOR_TAB_ROUTE,
  clearShipFocus,
  commercePage,
  creatorPage,
  openCreatorDesk,
  socialPage,
  stackPage,
  type CreatorDeskPane,
} from "../constants/routes";
import { LEGAL_ROUTES } from "../utils/legal";
import { getItem, setItem } from "../platform/storage";
import { clsx } from "../utils/clsx";
import { CoachMarks } from "../components/onboarding/CoachMarks";
import { useCreditsOptional } from "../contexts/CreditsProvider";
import {
  channelName,
  confirmCreatorAction,
  connectorLiveLine,
  humanizeDeliveryError,
  formatCount,
  formatFen,
  formatWarmup,
  formatMoneyMap,
  formatPayoutCountdown,
  isLiveDelivery,
  liveProgress,
  nextCreatorStep,
  parkedStepCopy,
  seatPhase,
  statusLabel,
  statusTone,
  type CreatorNextStep,
  type DeliveryRow,
  type ReleaseRow,
} from "./lib";
import { downloadCreatorStatement, downloadProExport } from "./exportReports";
import { MoneySplit } from "./MoneySplit";
import { SeatLamps, type SeatLamp } from "./SeatLamps";
import { JourneyProgress, buildCreatorJourney } from "./JourneyProgress";
import { ChannelMark } from "./ChannelMark";
import { NextActionCard } from "./NextActionCard";
import { copyWeappCreatorLink, WeappH5Bridge } from "./WeappH5Bridge";
import { type ConnectionCard } from "./ConnectionsRow";
import { AuthDesk } from "./AuthDesk";
import { ConnectorInstall } from "./ConnectorInstall";
import { ShipCompleteCard } from "./ShipCompleteCard";
import { listenExtensionEvents, markBittunePage, probeExtensionStatus, sendPollToExtension } from "./extensionPair";
import { LaunchHonestyBanner } from "../components/commercial/LaunchHonestyBanner";
import { focusShipCompleteBand, goCreatorAction, goShipBand } from "./nextActionNav";
import { peekPendingRelease, resumePendingQuickRelease } from "./quickReleaseAction";
import { goWorkCoreDoor } from "../utils/coreDoorNav";
import { needsBeautifyMaster, resolveWorkCoreDoor } from "../utils/workbenchWorks";
import { creatorOsH5Ready, creatorOsH5Url } from "../platform/platformConfig";
import { openWorkbench } from "../utils/workbenchNav";
import "../styles/tab-page.scss";
import "./creator.scss";

type DeskPane = CreatorDeskPane;

function readPane(): DeskPane {
  const value = getItem(CREATOR_PANE_KEY);
  if (value === "release" || value === "money" || value === "tools") return value;
  return "release";
}

type Hub = {
  works: number;
  releases: number;
  total_streams: number;
  display_streams?: number;
  settlement_revenue_minor: number;
  display_revenue_minor?: number;
  warmup_revenue_minor?: number;
  label_revenue_minor?: number;
  period_warmup_revenue_minor?: number;
  has_real_data: boolean;
  has_live?: boolean;
  has_label_release?: boolean;
  has_label_statement?: boolean;
  waiting_for_statement?: boolean;
  seats?: SeatLamp[];
  connections?: ConnectionCard[];
  predicted_revenue?: {
    low_minor?: number;
    mid_minor?: number;
    high_minor?: number;
    currency?: string;
    disclaimer?: string;
    geo_applied?: boolean;
  };
  store_compare?: {
    top_channel?: string;
    runner_up?: string;
    top_streams?: number;
    reason_id?: string;
  } | null;
  label_period?: {
    period_key?: string;
    waiting?: boolean;
    expected_earliest?: string;
    expected_latest?: string;
    gross_minor?: number;
    commission_minor?: number;
    net_minor?: number;
    currency?: string;
  };
  synced_at?: string | null;
  by_channel: Array<{
    channel_code: string;
    streams: number;
    display_streams?: number;
    revenue_minor: number;
    period_streams?: number;
    period_display_streams?: number;
    period_revenue_minor?: number;
    has_real: boolean;
    sources: string[];
    predicted_revenue?: {
      low_minor?: number;
      high_minor?: number;
      mid_minor?: number;
      currency?: string;
    };
  }>;
  by_work?: Array<{
    work_id: string;
    title?: string;
    cover_url?: string;
    streams: number;
    display_streams?: number;
    revenue_minor: number;
    period_streams?: number;
    period_display_streams?: number;
    period_revenue_minor?: number;
    live_stores?: number;
    has_real?: boolean;
    predicted_revenue?: {
      low_minor?: number;
      high_minor?: number;
      currency?: string;
    };
  }>;
  unclaimed_count?: number;
  unpublished_works?: Array<{
    work_id: string;
    title?: string;
    cover_url?: string;
    hint?: { id?: string } | null;
    priority?: { score?: number; reason?: string } | null;
    qc_ready?: boolean;
    channel_suggestion?: { reason?: string; region?: string; channels?: string[] } | null;
    from_workbench?: boolean;
    release_status?: string | null;
    degraded?: boolean;
    superseded_by_work_id?: string | null;
  }>;
  unpublished_count?: number;
  auto_ship_count?: number;
  needs_beautify_count?: number;
  degraded_count?: number;
  qc_pending_count?: number;
  unmatched_count?: number;
  primary_next?: { step?: string; source?: string };
  harvest_health?: {
    state?: "unmatched" | "needs_login" | "ready" | "idle" | "withdrawable" | "pending" | "draft";
    cta?: "attach" | "accounts" | "wallet" | "settlements" | null;
    unmatched_count?: number;
    needs_login?: number;
    can_harvest?: number;
    farm_ok?: boolean;
    farm_rows?: number;
    pending_minor?: number;
    available_minor?: number;
    zero_rows_success?: boolean;
  };
  isrc_blocked_count?: number;
  auto_release?: { enabled?: boolean; consented_at?: string | null };
  release_calendar?: Array<{
    work_id: string;
    title?: string;
    cover_url?: string;
    why?: string;
    qc_ready?: boolean;
    hint?: { id?: string } | null;
    channel_suggestion?: { reason?: string } | null;
  }>;
  publishing_count?: number;
  rejected_count?: number;
  pending_confirm_count?: number;
  lifetime_earned_minor?: number;
  period_key?: string;
  period_streams?: number;
  period_display_streams?: number;
  period_revenue_minor?: number;
  kyc_status?: string;
  alerts?: Array<{ id: string; level?: string; count?: number }>;
  connector_online?: boolean;
  has_distribution_license?: boolean;
  next_action?: string;
  connector?: {
    online?: boolean;
    version?: string;
    last_seen_at?: string;
    period_key?: string;
    last_harvest?: {
      channel?: string;
      count?: number;
      matched?: number;
      unclaimed?: number;
      at?: string;
      source?: string;
    } | null;
    last_delivery?: {
      channel_code?: string;
      event?: string;
      message?: string;
      at?: string;
      status?: string;
      live?: boolean;
    } | null;
    queue_count?: number;
    upload_queue?: Array<{ id?: string; channel_code?: string; status?: string; title?: string }>;
  };
  session_wait_count?: number;
  upload_wait_count?: number;
  automation?: {
    farm_navigate?: boolean;
    partners_configured?: boolean;
    ops_queue?: number;
    session_wait?: number;
    handed_to_extension?: number;
    payout_mode?: string;
  };
  available_minor?: number;
  pending_minor?: number;
  available_currency?: string;
  available_by_currency?: Array<{ currency?: string; available_minor?: number; pending_minor?: number; lifetime_earned_minor?: number }>;
  fiat_wallet?: {
    wallets?: Array<{ currency?: string; available_minor?: number; pending_minor?: number }>;
    enabled?: boolean;
  };
  distribution_enabled?: boolean;
  wallet_enabled?: boolean;
  payout_calendar?: { next_payout_date?: string; weekday_label?: string; days_until_payout?: number; is_payout_day?: boolean };
  wallet_split?: {
    credits?: { balance?: number; lifetime?: number };
    fiat?: { available_minor?: number; pending_minor?: number; currency?: string };
    sources?: { radio_minor?: number; sync_minor?: number; embed_minor?: number; dsp_minor?: number; harvest_minor?: number };
  };
  sold_orders?: Array<{ id: string; work_id?: string; tier?: string; status?: string; seller_minor?: number; license_id?: string }>;
  commune?: { name?: string; member_count?: number } | null;
  radio_chart?: Array<{ rank?: number; work_id: string; title?: string; completes?: number }>;
  week_drop?: {
    station?: string;
    station_name?: string;
    why?: string;
    next_action?: string;
    work?: { work_id: string; title?: string; cover_url?: string; from_workbench?: boolean } | null;
  } | null;
  clip_drops?: Array<{ id: string; work_id: string; portal_name?: string; url?: string; clip_length?: number }>;
  radio_trials?: Array<{ work_id: string; title?: string; live?: boolean; station?: string; ends_at?: string }>;
  publishing_rights?: { enabled?: boolean; status?: string };
  delivering?: boolean;
  recent?: ReleaseRow[];
};

const H5_BRIDGE_STEPS: CreatorNextStep[] = [
  "connector",
  "import",
  "stores",
  "settlements",
  "wallet",
  "release",
  "qc",
  "reprocess",
];

function h5BridgePath(step: CreatorNextStep) {
  if (step === "connector") return CREATOR_TAB_ROUTE;
  if (step === "import") return CREATOR_PAGE_ROUTES.dataImport;
  if (step === "stores") return CREATOR_PAGE_ROUTES.deliveries;
  if (step === "settlements") return CREATOR_PAGE_ROUTES.settlements;
  if (step === "release" || step === "qc" || step === "reprocess") return CREATOR_TAB_ROUTE;
  return CREATOR_PAGE_ROUTES.wallet;
}

function showWeappH5Bridge(step: CreatorNextStep) {
  if (process.env.TARO_ENV !== "weapp") return false;
  if (H5_BRIDGE_STEPS.includes(step)) return true;
  return !creatorOsH5Ready(CREATOR_TAB_ROUTE);
}

function unpublishedAsWork(work: {
  work_id: string;
  from_workbench?: boolean;
  release_status?: string | null;
  degraded?: boolean;
  superseded_by_work_id?: string | null;
}) {
  return {
    id: work.work_id,
    from_workbench: work.from_workbench,
    release_status: work.release_status,
    degraded: work.degraded,
    superseded_by_work_id: work.superseded_by_work_id,
  };
}

function goNext(step: ReturnType<typeof nextCreatorStep>, workId?: string) {
  goCreatorAction(step, { workId });
}

function goAlert(id: string, hub?: Hub | null) {
  if (id === "unpublished") {
    goShipBand();
    return;
  }
  if (id === "publishing" || id === "rejected" || id === "sla_overdue") {
    Taro.navigateTo({ url: creatorPage("deliveries") });
    return;
  }
  if (id === "connector_offline") {
    openCreatorDesk("today");
    return;
  }
  if (id === "isrc_blocked" || id === "unmatched" || id === "unclaimed") {
    Taro.navigateTo({ url: creatorPage("dataImport") });
    return;
  }
  if (id === "pending_confirm") {
    Taro.navigateTo({ url: creatorPage("settlements") });
    return;
  }
  if (id === "no_payout") {
    Taro.navigateTo({ url: creatorPage("accounts") });
    return;
  }
  if (id === "kyc") {
    Taro.navigateTo({ url: LEGAL_ROUTES.royaltyPayout });
    return;
  }
  if (id === "payout_today") {
    Taro.navigateTo({ url: creatorPage("wallet") });
    return;
  }
  if (id === "trial_ending") {
    const trial = hub?.radio_trials?.find((row) => row.live) || hub?.radio_trials?.[0];
    Taro.navigateTo({
      url: trial?.work_id
        ? socialPage("radio", { workId: trial.work_id, station: trial.station })
        : socialPage("radio"),
    });
    return;
  }
  if (id === "clip_inbox") {
    const workId = hub?.clip_drops?.[0]?.work_id;
    Taro.navigateTo({ url: workId ? creatorPage("work", { workId }) : creatorPage("help") });
    return;
  }
  Taro.navigateTo({ url: creatorPage("wallet") });
}

function openHelp() {
  Taro.navigateTo({ url: creatorPage("help") });
}

function CreatorDeskFrame({
  tabVariant,
  pane,
  onPaneChange,
  title,
  today,
  release,
  money,
  tools,
  hideTabs,
  children,
}: {
  tabVariant: boolean;
  pane: DeskPane;
  onPaneChange: (pane: DeskPane) => void;
  title: string;
  today: string;
  release: string;
  money: string;
  tools: string;
  hideTabs?: boolean;
  children: ReactNode;
}) {
  return (
    <View className={clsx("tab-page creator-desk", tabVariant && "creator-desk--tab")}>
      <View className="creator">
        {tabVariant ? (
          <View className="creator-desk__head">
            <View className="creator-desk__head-row">
              <View className="creator-desk__brand">
                <View className="creator-desk__icon">
                  <Icon name="sigil" accent size="sm" />
                </View>
                <Text className="creator-desk__title">{title}</Text>
              </View>
              <View className="creator-desk__help" onClick={openHelp}>
                <Icon name="info" size="md" />
              </View>
            </View>
          </View>
        ) : null}
        {hideTabs ? null : (
        <View className="creator-desk__tabs">
          <SegmentedControl<DeskPane>
            options={[
              { value: "today", label: today },
              { value: "release", label: release },
              { value: "money", label: money },
              { value: "tools", label: tools },
            ]}
            value={pane}
            onChange={onPaneChange}
          />
        </View>
        )}
        {children}
        {tabVariant ? <CoachMarks page="creator" /> : null}
      </View>
    </View>
  );
}

type Props = {
  tabVariant?: boolean;
};

export function CreatorDesk({ tabVariant = false }: Props) {
  const { copy, locale } = useLocale();
  const c = copy.creatorUi;
  const credits = useCreditsOptional();
  const [pane, setPane] = useState<DeskPane>(readPane);
  const [scope, setScope] = useState<"all" | "period">("all");
  const [releaseInbox, setReleaseInbox] = useState<"queue" | "recent" | "trials" | "clips">("queue");
  const [tapBusy, setTapBusy] = useState("");
  const [extensionOn, setExtensionOn] = useState(false);
  const [shipFocusId, setShipFocusId] = useState(() => getItem(CREATOR_SHIP_WORK_KEY) || "");
  void extensionOn;
  const loggedIn = isLoggedIn();

  function changePane(next: DeskPane) {
    setPane(next);
    setItem(CREATOR_PANE_KEY, next);
    if (next !== "today" && next !== "release") {
      clearShipFocus();
      setShipFocusId("");
    }
  }

  function whyLabel(why?: string) {
    if (why === "winner") return c.whyWinner;
    if (why === "listens") return c.whyListens;
    if (why === "qc_ready") return c.whyQc;
    if (why === "weekend") return c.whyWeekend;
    if (why === "emotion_week") return c.whyEmotion;
    return c.whyUnpublished;
  }

  const { data, loading, error, reload } = useAsyncQuery<Hub | null>(
    async () => {
      if (!isLoggedIn()) return null;
      const [hub, releases, deliveries, sold] = await Promise.all([
        vibeApi.getCreatorHub() as Promise<Hub>,
        vibeApi.listReleases().catch(() => ({ releases: [] })),
        vibeApi.listDeliveries().catch(() => ({ deliveries: [] })),
        vibeApi.listSyncOrders("sold").catch(() => ({ orders: [] })),
      ]);
      const rows = (releases.releases || []) as ReleaseRow[];
      const dels = (deliveries.deliveries || []) as DeliveryRow[];
      const delivering =
        rows.some((r) => ["queued", "delivering"].includes(r.status || "")) ||
        dels.some(
          (d) =>
            ["ops_queue", "awaiting_manual", "session_wait", "session_running", "submitting", "in_review"].includes(d.status) ||
            (d.status === "live" && !isLiveDelivery(d)),
        );
      return { ...hub, delivering, recent: rows.slice(0, 5), sold_orders: (sold.orders || []) as Hub["sold_orders"] };
    },
    [],
    { staleMs: 15_000 },
  );

  function openReleaseDesk(workId: string) {
    setItem(CREATOR_SHIP_WORK_KEY, workId);
    setShipFocusId(workId);
    changePane("today");
    focusShipCompleteBand();
  }

  async function toggleAutoRelease() {
    if (weapp) {
      const copied = await copyWeappCreatorLink(CREATOR_TAB_ROUTE);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    const next = !data?.auto_release?.enabled;
    if (next) {
      const confirm = await confirmCreatorAction({
        title: c.autoReleaseTitle,
        content: c.autoReleaseConfirm,
        confirmText: c.autoReleaseConfirmBtn,
        cancelText: c.back,
      });
      if (!confirm) return;
    }
    try {
      await vibeApi.setAutoRelease(next);
      Taro.showToast({ title: next ? c.autoReleaseEnabled : c.autoReleaseDisabled, icon: "success" });
      await reload(true);
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    }
  }

  async function wakeHarvest() {
    if (weapp) {
      const copied = await copyWeappCreatorLink(CREATOR_TAB_ROUTE);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    const sent = await sendPollToExtension();
    Taro.showToast({ title: sent ? c.harvestWakeSent : c.shipFarmLocal, icon: sent ? "success" : "none" });
  }

  function resumeShipIfPending() {
    if (process.env.TARO_ENV !== "h5" || !peekPendingRelease()) return;
    void resumePendingQuickRelease(
      {
        confirmOnce: c.confirmOnce,
        confirmOnceHint: c.confirmOnceHint,
        confirmGo: c.confirmGo,
        labelHint: c.labelHint,
        back: c.back,
        oneTapOk: c.oneTapResumeOk || c.oneTapOk,
      },
      copy.adminUi.actionFail,
    );
  }

  useDidShow(() => {
    setPane(readPane());
    const focus = getItem(CREATOR_SHIP_WORK_KEY) || "";
    if (focus) {
      setShipFocusId(focus);
      focusShipCompleteBand();
    }
    void reload();
    if (process.env.TARO_ENV === "h5") {
      void sendPollToExtension();
      void probeExtensionStatus().then((status) => {
        setExtensionOn(status.installed);
        if (status.installed) resumeShipIfPending();
      });
    }
  });
  useEffect(() => {
    markBittunePage();
    if (process.env.TARO_ENV === "h5") {
      void probeExtensionStatus().then((status) => setExtensionOn(status.installed));
    }
    const stop = listenExtensionEvents((event) => {
      if (event.type === "BITTUNE_UNPAIRED") setExtensionOn(false);
      if (event.type === "BITTUNE_SYNC" || event.type === "BITTUNE_UNPAIRED" || event.type === "BITTUNE_DELIVERY") {
        if (process.env.TARO_ENV === "h5" && event.type !== "BITTUNE_UNPAIRED") void sendPollToExtension();
        void reload(true);
      }
    });
    const onVis = () => {
      if (typeof document === "undefined" || document.hidden) return;
      void reload();
      if (process.env.TARO_ENV === "h5") void sendPollToExtension();
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVis);
    return () => {
      stop();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVis);
    };
  }, [reload]);
  useEffect(() => {
    if (!data?.connector?.queue_count && !data?.connector?.last_delivery?.event) return;
    const timer = setInterval(() => void reload(true), 8000);
    return () => clearInterval(timer);
  }, [data?.connector?.queue_count, data?.connector?.last_delivery?.event, reload]);
  usePullDownRefresh(async () => {
    await reload(true);
    Taro.stopPullDownRefresh();
  });

  const channels = data?.by_channel || [];
  const dspOn = credits?.dspDistribution !== false && data?.distribution_enabled !== false;
  const walletOn = credits?.royaltyWallet !== false && data?.wallet_enabled !== false;
  const wallets = data?.fiat_wallet?.wallets || [];
  const hasPending = wallets.some((w) => (w.pending_minor || 0) > 0);
  const hasAvailable = wallets.some((w) => (w.available_minor || 0) > 0);
  const weapp = process.env.TARO_ENV === "weapp";
  const worksCount = data?.works || 0;
  const canAutoShip = (data?.auto_ship_count || 0) > 0;
  const localStep = nextCreatorStep({
    works: worksCount,
    releases: data?.releases || 0,
    delivering: Boolean(data?.delivering),
    hasReal: Boolean(data?.has_real_data || data?.has_label_statement),
    hasPending,
    hasAvailable,
    dspOn,
    unpublishedCount: data?.unpublished_count || 0,
    sessionWait: data?.session_wait_count || 0,
    uploadWait: data?.upload_wait_count || 0,
    unmatchedCount: data?.unmatched_count || 0,
    connectorOnline: data?.connector_online,
    weapp,
    hasLive: data?.has_live,
    hasLabelRelease: data?.has_label_release,
    degradedCount: data?.degraded_count || 0,
    qcPendingCount: data?.qc_pending_count || 0,
    needsBeautifyCount: data?.needs_beautify_count || 0,
    canAutoShip,
  });
  const serverStep = data?.primary_next?.step;
  const step = serverStep || localStep;
  const noPayout = (data?.alerts || []).some((alert) => alert.id === "no_payout");
  const payoutFirst = step === "wallet" && noPayout;
  const nextCopy =
    {
      generate: { title: c.nextGenerate, hint: c.nextGenerateHint },
      beautify: { title: c.nextBeautify, hint: c.nextBeautifyHint },
      connector: weapp
        ? { title: c.openRemoteLogin, hint: c.seatWeappHint }
        : canAutoShip
          ? {
              title: c.nextConnector,
              hint: c.nextConnectorHint.replace("{n}", String(data?.session_wait_count || 0)),
            }
          : { title: c.nextAuthFirst, hint: c.nextAuthFirstHint },
      release:
        (data?.session_wait_count || 0) > 0
          ? { title: c.shipOpenStore, hint: c.sessionWaitHint }
          : { title: c.nextRelease, hint: c.nextReleaseHint },
      stores:
        (data?.upload_wait_count || 0) > 0 && !(data?.session_wait_count || 0)
          ? { title: c.nextStoresUpload, hint: c.nextStoresUploadHint }
          : { title: c.nextStores, hint: c.nextStoresHint },
      import: { title: c.nextImport, hint: c.nextImportHint },
      settlements: { title: c.nextSettlements, hint: c.nextSettlementsHint },
      wallet:
        data?.has_label_release === false
          ? { title: c.nextSelfRelease, hint: c.nextSelfReleaseHint }
          : payoutFirst
            ? { title: c.addPayout, hint: c.alertNoPayout }
            : { title: c.nextWallet, hint: c.nextWalletHint },
      sync: { title: c.nextSync, hint: c.nextSyncHint },
      reprocess: { title: c.nextReprocess, hint: c.nextReprocessHint },
      qc: { title: c.nextQc, hint: c.nextQcHint },
      wait_review: { title: c.nextWaitReview, hint: c.nextWaitReviewHint },
      claim: { title: c.nextImport, hint: c.nextImportHint },
    }[step] || { title: c.nextSettlements, hint: c.nextSettlementsHint };
  const compactWan = locale !== "en";
  const periodOn = scope === "period";
  const alertCopy: Record<string, string> = {
    unpublished: c.alertUnpublished,
    publishing: c.alertPublishing,
    rejected: c.alertRejected,
    unclaimed: c.alertUnclaimed,
    unmatched: c.alertUnmatched,
    isrc_blocked: c.alertIsrcBlocked,
    pending_confirm: c.alertPendingConfirm,
    no_payout: c.alertNoPayout,
    kyc: c.alertKyc,
    sla_overdue: c.alertSlaOverdue,
    connector_offline: c.alertConnectorOffline,
    payout_today: c.alertPayoutToday,
    trial_ending: c.alertTrialEnding,
    clip_inbox: c.clipInbox,
  };

  const unpublished = data?.unpublished_works || [];
  const shipRow =
    unpublished.find((row) => row.work_id === shipFocusId || row.superseded_by_work_id === shipFocusId) ||
    unpublished.find((row) => row.from_workbench || row.superseded_by_work_id) ||
    unpublished[0];
  const shipWorkId = shipFocusId || shipRow?.superseded_by_work_id || shipRow?.work_id;
  const showShip = dspOn && Boolean(shipWorkId || data?.delivering);
  useEffect(() => {
    if (!shipFocusId || !data) return;
    const inbox = data.unpublished_works || [];
    const recent = data.recent || [];
    const known =
      inbox.some((row) => row.work_id === shipFocusId || row.superseded_by_work_id === shipFocusId) ||
      recent.some((row) => row.work_id === shipFocusId);
    if (known || (!inbox.length && !recent.length)) return;
    clearShipFocus();
    setShipFocusId("");
  }, [data, shipFocusId]);
  const topWork = [...(data?.by_work || [])].sort(
    (a, b) =>
      (periodOn ? b.period_revenue_minor : b.revenue_minor) - (periodOn ? a.period_revenue_minor : a.revenue_minor),
  )[0];
  const topStore = [...channels].sort(
    (a, b) =>
      (periodOn ? b.period_revenue_minor : b.revenue_minor) - (periodOn ? a.period_revenue_minor : a.revenue_minor),
  )[0];
  const glanceAmount = formatFen(
    periodOn
      ? topWork?.period_revenue_minor ?? topStore?.period_revenue_minor
      : topWork?.revenue_minor ?? topStore?.revenue_minor,
    data?.available_currency,
  );
  const sourceSplit = data?.wallet_split?.sources;
  const hasSourceMoney = [
    sourceSplit?.radio_minor,
    sourceSplit?.sync_minor,
    sourceSplit?.embed_minor,
    sourceSplit?.dsp_minor,
    sourceSplit?.harvest_minor,
  ].some((n) => (n || 0) > 0);
  const journeyLabels = {
    generate: c.journeyStepGenerate,
    release: c.journeyStepRelease,
    stores: c.journeyStepStores,
    wait: c.journeyStepWait,
    settle: c.journeyStepSettle,
    payout: c.journeyStepPayout,
  };

  function handleNext() {
    if (weapp && step !== "generate" && step !== "beautify") {
      void copyWeappCreatorLink(h5BridgePath(step));
      return;
    }
    if (payoutFirst) {
      Taro.navigateTo({ url: creatorPage("accounts") });
      return;
    }
    if (step === "beautify") {
      const raw = unpublished.find((row) => !row.from_workbench) || unpublished[0];
      goCreatorAction("beautify", { workId: raw?.work_id });
      return;
    }
    if (step === "connector" || step === "release" || step === "qc") {
      if (pane !== "today") changePane("today");
      focusShipCompleteBand();
      return;
    }
    if (step === "settlements") {
      changePane("money");
      return;
    }
    goNext(step, unpublished[0]?.work_id);
  }

  function handleAlert(id: string) {
    if (weapp) {
      void copyWeappCreatorLink(id === "unpublished" ? CREATOR_TAB_ROUTE : CREATOR_PAGE_ROUTES.wallet);
      return;
    }
    if (id === "unpublished") {
      const id = unpublished[0]?.work_id;
      if (id) openReleaseDesk(id);
      else {
        changePane("today");
        focusShipCompleteBand();
      }
      return;
    }
    if (id === "payout_today" || id === "pending_confirm") {
      changePane("money");
      return;
    }
    goAlert(id, data);
  }

  function unpublishedRow(work: NonNullable<Hub["unpublished_works"]>[number]) {
    const doorWork = unpublishedAsWork(work);
    const { door, workId: shipId } = resolveWorkCoreDoor(doorWork);
    const winner = work.priority?.reason === "duel_winner" || work.priority?.reason === "challenge_winner";
    const primaryLabel =
      door === "beautify"
        ? c.beautifyFirst
        : door === "fix"
          ? c.nextReprocess
          : door === "deliveries"
            ? c.nextStores
            : door === "radio"
              ? c.radioTrialStart
              : winner || work.qc_ready
                ? c.confirmOnce
                : c.goRelease;
    return (
      <View
        key={work.work_id}
        className="creator-pick"
        onClick={() => goWorkCoreDoor(doorWork)}
      >
        <View className="creator-pick__cover">
          {work.cover_url ? <Image className="creator-pick__cover-img" src={work.cover_url} mode="aspectFill" /> : null}
        </View>
        <View className="creator-pick__body">
          <Text className="creator-pick__title">{work.title || c.releaseUntitled}</Text>
          <Text className="creator-pick__meta">
            {door === "beautify"
              ? c.beautifyFirst
              : winner
                ? c.whyWinner
                : work.hint?.id === "priority"
                  ? c.hintPriority
                  : work.hint?.id === "listen"
                    ? c.hintListen
                    : work.hint?.id === "quality"
                      ? c.hintQuality
                      : work.qc_ready
                        ? c.hintQcReady
                        : c.readyToRelease}
            {work.channel_suggestion?.reason ? ` · ${work.channel_suggestion.reason}` : ""}
          </Text>
        </View>
        <View className="creator-pick__actions" onClick={(ev) => ev.stopPropagation()}>
          {door === "beautify" ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={(ev) => {
                ev.stopPropagation?.();
                goCreatorAction("release", { workId: work.work_id });
              }}
            >
              {c.goRelease}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={(ev) => {
                ev.stopPropagation?.();
                openWorkbench(work.work_id);
              }}
            >
              {c.beautifyFirst}
            </Button>
          )}
          <Button
            size="sm"
            variant={door === "beautify" || door === "fix" || winner || work.qc_ready ? "primary" : "secondary"}
            onClick={(ev) => {
              ev.stopPropagation?.();
              if (door === "release") {
                openReleaseDesk(shipId);
                return;
              }
              goWorkCoreDoor(doorWork);
            }}
          >
            {primaryLabel}
          </Button>
        </View>
      </View>
    );
  }

  const shellProps = tabVariant
    ? { title: copy.tabBar.creator, ambient: true, tabVariant: true, wide: true, noPadTop: true, hideHeader: true }
    : { title: c.hubTitle, subtitle: c.hubSubtitle, ambient: true };

  const frameProps = {
    tabVariant,
    pane,
    onPaneChange: changePane,
    title: copy.tabBar.creator,
    today: c.deskToday,
    release: c.deskRelease,
    money: c.deskMoney,
    tools: c.deskTools,
    hideTabs: weapp || tabVariant,
  };

  if (!loggedIn) {
    return (
      <PageShell {...shellProps}>
        <CreatorDeskFrame {...frameProps} hideTabs>
          <EmptyState
            iconName="create"
            title={c.deskGuestTitle}
            description={c.deskGuestHint}
            actionLabel={copy.profileUi.loginButton}
            onAction={() => requireAuth(CREATOR_TAB_ROUTE)}
          />
          <Button variant="ghost" block onClick={() => Taro.switchTab({ url: "/pages/create/index" })}>
            {copy.profileUi.guestTryCreate}
          </Button>
        </CreatorDeskFrame>
      </PageShell>
    );
  }

  if (loading && !data) {
    return (
      <PageShell {...shellProps}>
        <CreatorDeskFrame {...frameProps} hideTabs>
          <LoadingSkeleton count={2} />
        </CreatorDeskFrame>
      </PageShell>
    );
  }

  if (worksCount === 0) {
    return (
      <PageShell {...shellProps}>
        <CreatorDeskFrame {...frameProps} hideTabs>
          {weapp ? <WeappH5Bridge path={CREATOR_TAB_ROUTE} /> : null}
          {weapp ? <StatusLine tone="info" density="quiet">{c.weappDeskHint}</StatusLine> : null}
          <EmptyState
            iconName="create"
            title={c.deskFirstTitle}
            description={c.deskFirstHint}
            actionLabel={c.goCreate}
            onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
          />
        </CreatorDeskFrame>
      </PageShell>
    );
  }

  const releaseHasRows =
    Boolean(data?.week_drop?.work) ||
    (data?.release_calendar || []).length > 0 ||
    unpublished.length > 0 ||
    (data?.recent || []).length > 0 ||
    (data?.sold_orders || []).length > 0 ||
    (data?.radio_trials || []).length > 0 ||
    (data?.clip_drops || []).length > 0;

  const weekDrop = data?.week_drop;
  const shipHeroId =
    weekDrop?.work?.work_id || data?.release_calendar?.[0]?.work_id || unpublished[0]?.work_id || "";
  const queueCalendar = (data?.release_calendar || []).filter((w) => w.work_id !== shipHeroId);
  const queueUnpublished = unpublished.filter((w) => w.work_id !== shipHeroId);

  function weekDropPrimary() {
    const id = weekDrop?.work?.work_id;
    if (!id) return null;
    const action = weekDrop?.next_action;
    if (action === "watch_trial") {
      return (
        <Button
          size="sm"
          variant="primary"
          onClick={() =>
            Taro.navigateTo({
              url: socialPage("radio", { workId: id, station: weekDrop?.station }),
            })
          }
        >
          {c.goRadio}
        </Button>
      );
    }
    if (action === "radio_trial") {
      return (
        <Button
          size="sm"
          variant="primary"
          loading={tapBusy === `trial-${id}`}
          onClick={() => {
            void (async () => {
              const ok = await confirmCreatorAction({
                title: c.radioTrialStart,
                content: c.radioTrialConfirm,
                confirmText: c.confirmGo,
                cancelText: c.back,
              });
              if (!ok) return;
              setTapBusy(`trial-${id}`);
              try {
                const trial = (await vibeApi.startRadioTrial(id, weekDrop?.station)) as {
                  work_id?: string;
                  station?: string;
                };
                Taro.showToast({ title: c.radioTrialLive, icon: "success" });
                Taro.navigateTo({
                  url: socialPage("radio", {
                    workId: trial.work_id || id,
                    station: typeof trial.station === "string" ? trial.station : weekDrop?.station,
                  }),
                });
                await reload();
              } catch (err) {
                Taro.showToast({
                  title: humanizeDeliveryError(String((err as Error)?.message || ""), c, copy.adminUi.actionFail) || copy.adminUi.actionFail,
                  icon: "none",
                });
              } finally {
                setTapBusy("");
              }
            })();
          }}
        >
          {c.radioTrialStart}
        </Button>
      );
    }
    if (action === "sync") {
      return (
        <Button size="sm" variant="primary" onClick={() => Taro.navigateTo({ url: commercePage("syncDesk", { workId: id }) })}>
          {c.nextSync}
        </Button>
      );
    }
    if (action === "wallet") {
      return (
        <Button size="sm" variant="primary" onClick={() => Taro.navigateTo({ url: creatorPage("wallet") })}>
          {c.nextWallet}
        </Button>
      );
    }
    if (action === "stores") {
      return (
        <Button size="sm" variant="primary" onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { workId: id }) })}>
          {c.nextStores}
        </Button>
      );
    }
    if (action === "beautify" || weekDrop?.work?.from_workbench === false) {
      return (
        <Button size="sm" variant="primary" onClick={() => openWorkbench(id)}>
          {c.beautifyFirst}
        </Button>
      );
    }
    return (
      <Button
        size="sm"
        variant="primary"
        onClick={() => openReleaseDesk(id)}
      >
        {action === "release" ? c.trialEndedRelease : c.goRelease}
      </Button>
    );
  }

  return (
    <PageShell {...shellProps}>
      <CreatorDeskFrame {...frameProps}>
        <LaunchHonestyBanner surface="hub" />
        {weapp ? <WeappH5Bridge path={CREATOR_TAB_ROUTE} /> : showWeappH5Bridge(step) ? <WeappH5Bridge path={h5BridgePath(step)} /> : null}
        {weapp ? <StatusLine tone="info" density="quiet">{c.weappDeskHint}</StatusLine> : null}
        {data?.automation && (data.automation.ops_queue || data.automation.session_wait) ? (
          <StatusLine tone="warning" density="quiet">
            {c.automationQueueHint
              .replace("{ops}", String(data.automation.ops_queue || 0))
              .replace("{wait}", String(data.automation.session_wait || 0))}
          </StatusLine>
        ) : null}
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void reload()}
          skeletonCount={4}
        >
          {pane === "today" && (
            <>
              {weapp ? (
                <View className="creator-weapp-glance">
                  <MetricCard label={c.glanceCredits} value={String(data?.wallet_split?.credits?.balance ?? 0)} />
                  <MetricCard
                    label={c.glanceFiat}
                    value={formatFen(data?.available_minor || 0, data?.available_currency || "CNY", locale)}
                  />
                  {(sourceSplit?.radio_minor || 0) > 0 ? (
                    <StatusLine tone="info" density="quiet">
                      {`${c.walletRadio} ${formatWarmup(sourceSplit?.radio_minor, c.warmupNotCash)}`}
                    </StatusLine>
                  ) : null}
                  {data?.payout_calendar?.next_payout_date ? (
                    <StatusLine tone="info" density="quiet">
                      {formatPayoutCountdown(data.payout_calendar, c)}
                    </StatusLine>
                  ) : (
                    <StatusLine tone="info" density="quiet">{c.moneyFriday}</StatusLine>
                  )}
                  <Button variant="secondary" block onClick={() => void copyWeappCreatorLink(CREATOR_TAB_ROUTE)}>
                    {c.weappGoRelease}
                  </Button>
                  <Button variant="secondary" block onClick={() => void copyWeappCreatorLink(CREATOR_PAGE_ROUTES.wallet)}>
                    {c.weappGoWallet}
                  </Button>
                </View>
              ) : null}
              {showShip ? (
                <ShipCompleteCard
                  workId={shipWorkId}
                  surface="desk"
                  qcReady={shipRow?.qc_ready}
                  releaseStatus={shipRow?.release_status || ""}
                  needsBeautify={needsBeautifyMaster({
                    from_workbench: shipRow?.from_workbench,
                    superseded_by_work_id: shipRow?.superseded_by_work_id,
                  })}
                  onBeautify={() => {
                    const raw = unpublished.find((row) => !row.from_workbench) || unpublished[0];
                    goCreatorAction("beautify", { workId: raw?.work_id });
                  }}
                  connections={data?.connections}
                  connector={data?.connector}
                  weapp={weapp}
                  embedAuth
                  farmNavigate={Boolean(data?.automation?.farm_navigate)}
                  partnersConfigured={Boolean(data?.automation?.partners_configured)}
                  hasLicense={Boolean(data?.has_distribution_license)}
                  onChanged={() => {
                    if (process.env.TARO_ENV === "h5") void sendPollToExtension();
                    void reload(true);
                  }}
                />
              ) : (
                <AuthDesk
                  connections={data?.connections}
                  weapp={weapp}
                  onChanged={() => {
                    if (process.env.TARO_ENV === "h5") void sendPollToExtension();
                    void reload(true);
                  }}
                />
              )}
              {!weapp && connectorLiveLine(c, data?.connector) ? (
                <View className="creator-card--tap" onClick={() => Taro.navigateTo({ url: creatorPage("deliveries") })}>
                  <StatusLine tone={(data?.connector?.queue_count || 0) > 0 ? "info" : "success"} density="quiet">
                    {connectorLiveLine(c, data?.connector)}
                  </StatusLine>
                  <Text className="typo-meta">{c.connectorLiveHint}</Text>
                </View>
              ) : null}
              <View className="coach-anchor-next">
              <NextActionCard
                kicker={c.nextAction}
                title={nextCopy.title}
                hint={nextCopy.hint}
                who={parkedStepCopy(step, c).who}
                park={parkedStepCopy(step, c).park}
                go={weapp && step !== "generate" && step !== "beautify" ? c.weappH5Hint : c.nextGo}
                urgent={step === "connector" || step === "stores" || step === "reprocess" || payoutFirst}
                waiting={step === "wait_review"}
                chips={
                  step === "release"
                    ? (unpublished[0]?.channel_suggestion?.channels || []).map((code) => channelName(code, c.channels))
                    : step === "reprocess" && data?.degraded_count
                      ? [String(data.degraded_count)]
                      : undefined
                }
                onClick={handleNext}
              />
              </View>
              {!weapp && (data?.connector?.last_harvest?.unclaimed || 0) > 0 ? (
                <View
                  className="creator-card--tap"
                  onClick={() => Taro.navigateTo({ url: creatorPage("dataImport") })}
                >
                  <StatusLine tone="error" density="quiet">
                    {`${c.connectorLastHarvest
                      .replace("{name}", String(data?.connector?.last_harvest?.channel || ""))
                      .replace("{n}", String(data?.connector?.last_harvest?.count || 0))
                      .replace("{m}", String(data?.connector?.last_harvest?.matched ?? 0))}${c.connectorHarvestUnclaimed.replace(
                      "{u}",
                      String(data?.connector?.last_harvest?.unclaimed),
                    )}`}
                  </StatusLine>
                </View>
              ) : null}
              {!weapp && (step === "connector" || step === "stores") && (
                <View className="coach-anchor-lamps">
                  <SeatLamps
                    seats={(data?.seats || []).filter((s) => {
                      const phase = seatPhase(s);
                      return phase === "challenge" || phase === "expired" || phase === "need_login";
                    }).slice(0, 3)}
                    copy={c}
                    onOpen={(seat) => {
                      if (seat.id) Taro.navigateTo({ url: creatorPage("remoteLogin", { seatId: seat.id }) });
                      else Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.accounts });
                    }}
                  />
                </View>
              )}
              {!dspOn && <StatusLine tone="info" density="quiet">{c.featureOff}</StatusLine>}
              {!weapp && dspOn && step === "release" && unpublished.length > 0 && (
                <View className="coach-anchor-ship">{unpublished.slice(0, 1).map(unpublishedRow)}</View>
              )}
              {!weapp && <Collapsible label={c.deskTodayMore} defaultOpen={false}>
                {data?.connector_online && !(data?.connector?.last_harvest?.unclaimed || 0) ? (
                  <View className="creator-card--tap" onClick={() => Taro.navigateTo({ url: creatorPage("accounts") })}>
                    <StatusLine tone="success" density="quiet">
                      {data.connector?.version ? c.connectorVersion.replace("{v}", data.connector.version) : c.connectorOnline}
                    </StatusLine>
                  </View>
                ) : null}
                {step !== "connector" && step !== "stores" ? (
                  <View className="coach-anchor-lamps">
                    <SeatLamps
                      seats={(data?.seats || []).filter((s) => {
                        const phase = seatPhase(s);
                        return phase === "challenge" || phase === "expired" || phase === "need_login";
                      }).slice(0, 3)}
                      copy={c}
                      onOpen={(seat) => {
                        if (seat.id) Taro.navigateTo({ url: creatorPage("remoteLogin", { seatId: seat.id }) });
                        else Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.accounts });
                      }}
                    />
                  </View>
                ) : null}
                <JourneyProgress
                  steps={buildCreatorJourney(
                    journeyLabels,
                    {
                      works: worksCount,
                      releases: data?.releases || 0,
                      delivering: Boolean(data?.delivering),
                      hasReal: Boolean(data?.has_real_data || data?.has_label_statement),
                      hasPayout: hasAvailable,
                      unpublishedCount: data?.unpublished_count || 0,
                      hasLive: data?.has_live,
                      hasLabelRelease: data?.has_label_release,
                      waitingForStatement: data?.waiting_for_statement,
                    },
                  )}
                  onStepClick={(id) => {
                    if (id === "generate") Taro.switchTab({ url: "/pages/create/index" });
                    if (id === "release" && dspOn) {
                      if (shipWorkId) openReleaseDesk(shipWorkId);
                      else focusShipCompleteBand();
                    }
                    if (id === "stores") Taro.navigateTo({ url: creatorPage("deliveries") });
                    if (id === "wait" || id === "settle" || id === "payout") changePane("money");
                  }}
                />
                {(data?.alerts || []).length > 0 && (
                  <View className="creator-alert-strip">
                    {(data?.alerts || []).map((alert) => (
                      <View
                        key={alert.id}
                        className={alert.level === "warning" ? "creator-alert creator-alert--warn" : "creator-alert"}
                        onClick={() => handleAlert(alert.id)}
                      >
                        <Text className="creator-alert__text">
                          {(alertCopy[alert.id] || alert.id).replace("{n}", String(alert.count || 0))}
                          {` · ${c.alertTap}`}
                        </Text>
                      </View>
                    ))}
                  </View>
                )}
                {dspOn && step !== "release" && unpublished.length > 0 && (
                  <Button size="sm" variant="ghost" onClick={() => changePane("release")}>
                    {c.goRelease}
                  </Button>
                )}
              </Collapsible>}
            </>
          )}

          {!weapp && pane === "release" && (
            <>
              {showShip ? (
                <ShipCompleteCard
                  workId={shipWorkId}
                  surface="desk"
                  qcReady={shipRow?.qc_ready}
                  releaseStatus={shipRow?.release_status || ""}
                  needsBeautify={needsBeautifyMaster({
                    from_workbench: shipRow?.from_workbench,
                    superseded_by_work_id: shipRow?.superseded_by_work_id,
                  })}
                  onBeautify={() => {
                    const raw = unpublished.find((row) => !row.from_workbench) || unpublished[0];
                    goCreatorAction("beautify", { workId: raw?.work_id });
                  }}
                  connections={data?.connections}
                  connector={data?.connector}
                  weapp={weapp}
                  embedAuth
                  farmNavigate={Boolean(data?.automation?.farm_navigate)}
                  partnersConfigured={Boolean(data?.automation?.partners_configured)}
                  hasLicense={Boolean(data?.has_distribution_license)}
                  onChanged={() => {
                    if (process.env.TARO_ENV === "h5") void sendPollToExtension();
                    void reload(true);
                  }}
                />
              ) : null}
              {weekDrop?.work && (
                <>
                  <SectionLabel>{c.weekDropTitle}</SectionLabel>
                  <View className="creator-pick coach-anchor-ship">
                    <View className="creator-pick__cover">
                      {weekDrop.work.cover_url ? (
                        <Image className="creator-pick__cover-img" src={weekDrop.work.cover_url} mode="aspectFill" />
                      ) : null}
                    </View>
                    <View className="creator-pick__body">
                      <Text className="creator-pick__title">{weekDrop.work.title || c.releaseUntitled}</Text>
                      <Text className="creator-pick__meta">
                        {whyLabel(weekDrop.why)}
                        {weekDrop.station_name ? ` · ${weekDrop.station_name}` : ""}
                        {weekDrop.work.from_workbench ? ` · ${copy.worksUi.beautifyMaster}` : ""}
                      </Text>
                    </View>
                    {weekDropPrimary()}
                  </View>
                </>
              )}

              {!weekDrop?.work && dspOn && data?.release_calendar?.[0] && (
                <>
                  <SectionLabel>{c.calendarThisWeek}</SectionLabel>
                  <View className="creator-pick coach-anchor-ship">
                    <View className="creator-pick__cover">
                      {data.release_calendar[0].cover_url ? (
                        <Image className="creator-pick__cover-img" src={data.release_calendar[0].cover_url} mode="aspectFill" />
                      ) : null}
                    </View>
                    <View className="creator-pick__body">
                      <Text className="creator-pick__title">{data.release_calendar[0].title || c.releaseUntitled}</Text>
                      <Text className="creator-pick__meta">
                        {whyLabel(data.release_calendar[0].why)}
                        {data.release_calendar[0].channel_suggestion?.reason
                          ? ` · ${data.release_calendar[0].channel_suggestion.reason}`
                          : ""}
                      </Text>
                    </View>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => openReleaseDesk(data.release_calendar![0].work_id)}
                    >
                      {c.confirmOnce}
                    </Button>
                  </View>
                </>
              )}

              {!weekDrop?.work && !data?.release_calendar?.[0] && dspOn && unpublished[0] && (
                <>
                  <SectionLabel>{c.unpublishedWorks}</SectionLabel>
                  <View className="coach-anchor-ship">{unpublishedRow(unpublished[0])}</View>
                </>
              )}

              {worksCount > 0 && (
                <SegmentedControl
                  options={[
                    { value: "queue", label: c.deskInboxQueue },
                    { value: "recent", label: c.deskInboxRecent },
                    { value: "trials", label: c.deskInboxTrials },
                    { value: "clips", label: c.deskInboxClips },
                  ]}
                  value={releaseInbox}
                  onChange={(v) => setReleaseInbox(v as typeof releaseInbox)}
                />
              )}

              {releaseInbox === "queue" && (
                <>
                  {dspOn && queueCalendar.length > 0 && (
                    <>
                      <SectionLabel>{c.calendarThisWeek}</SectionLabel>
                      {queueCalendar.slice(0, 5).map((work) => (
                        <View key={`cal-${work.work_id}`} className="creator-pick">
                          <View className="creator-pick__cover">
                            {work.cover_url ? (
                              <Image className="creator-pick__cover-img" src={work.cover_url} mode="aspectFill" />
                            ) : null}
                          </View>
                          <View className="creator-pick__body">
                            <Text className="creator-pick__title">{work.title || c.releaseUntitled}</Text>
                            <Text className="creator-pick__meta">
                              {whyLabel(work.why)}
                              {work.channel_suggestion?.reason ? ` · ${work.channel_suggestion.reason}` : ""}
                            </Text>
                          </View>
                          <Button
                            size="sm"
                            variant="primary"
                            onClick={() => openReleaseDesk(work.work_id)}
                          >
                            {c.confirmOnce}
                          </Button>
                        </View>
                      ))}
                    </>
                  )}
                  {dspOn && queueUnpublished.length > 0 && (
                    <>
                      <SectionLabel>{c.unpublishedWorks}</SectionLabel>
                      {queueUnpublished.slice(0, 5).map(unpublishedRow)}
                    </>
                  )}
                  {dspOn && worksCount > 0 && (
                    <Collapsible label={c.autoReleaseTitle} defaultOpen={false}>
                      <Text className="creator-note">{c.autoReleaseHint}</Text>
                      <Button
                        block
                        variant={data?.auto_release?.enabled ? "ghost" : "primary"}
                        onClick={() => void toggleAutoRelease()}
                      >
                        {data?.auto_release?.enabled ? c.autoReleaseEnabled : c.autoReleaseOff}
                      </Button>
                      <ConnectorInstall weapp={weapp} />
                    </Collapsible>
                  )}
                  {worksCount > 0 &&
                    queueCalendar.length === 0 &&
                    queueUnpublished.length === 0 &&
                    !shipHeroId && (
                      <EmptyState
                        iconName="music"
                        title={c.emptyRelease}
                        description={c.emptyReleaseHint}
                        actionLabel={c.goCreate}
                        onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
                      />
                    )}
                </>
              )}

              {releaseInbox === "recent" && (data?.recent || []).length > 0 && (
                <>
                  <SectionLabel>{c.recentReleases}</SectionLabel>
                  {(data?.recent || []).map((release) => {
                    const dels = release.deliveries || [];
                    const { live, total } = liveProgress(dels);
                    const pct = total ? Math.round((live / total) * 100) : 0;
                    return (
                      <View
                        key={release.id}
                        className="creator-card creator-card--tap"
                        onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { releaseId: release.id }) })}
                      >
                        <View className="creator-release-head">
                          <View>
                            <Text className="creator-pick__title">{release.metadata?.title || c.releaseUntitled}</Text>
                            <Text className="creator-pick__meta">
                              {release.mode === "self_release" ? c.modeA : c.modeB}
                              {total ? ` · ${c.liveProgress.replace("{n}", String(live)).replace("{m}", String(total))}` : ""}
                            </Text>
                          </View>
                          <Badge tone={statusTone(release.status)}>{statusLabel(release.status || "draft", c.status)}</Badge>
                        </View>
                        {total > 0 && (
                          <View className="creator-progress">
                            <View className="creator-progress__bar" style={{ width: `${pct}%` }} />
                          </View>
                        )}
                        {dels.some((d) => d.sla_escalated) ? (
                          <StatusLine tone="error">{c.slaEscalated}</StatusLine>
                        ) : dels.some((d) => d.sla_overdue) ? (
                          <StatusLine tone="error">{c.slaOverdue}</StatusLine>
                        ) : null}
                      </View>
                    );
                  })}
                </>
              )}

              {releaseInbox === "recent" && (data?.sold_orders || []).length > 0 && (
                <>
                  <SectionLabel>{c.soldOrders}</SectionLabel>
                  {(data?.sold_orders || []).slice(0, 6).map((order) => (
                    <View
                      key={order.id}
                      className="creator-channel creator-channel--tap"
                      onClick={() => {
                        if (order.work_id) Taro.navigateTo({ url: creatorPage("work", { workId: order.work_id }) });
                      }}
                    >
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

              {releaseInbox === "recent" &&
                (data?.recent || []).length === 0 &&
                (data?.sold_orders || []).length === 0 && (
                  <EmptyState
                    iconName="music"
                    title={c.emptyRelease}
                    description={c.emptyReleaseHint}
                    actionLabel={c.goCreate}
                    onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
                  />
                )}

              {releaseInbox === "trials" && (data?.radio_trials || []).length > 0 && (
                <>
                  <SectionLabel>{c.radioTrialTitle}</SectionLabel>
                  {(data?.radio_trials || []).map((row) => (
                    <View
                      key={row.work_id}
                      className="creator-channel creator-channel--tap"
                      onClick={() =>
                        Taro.navigateTo({
                          url: row.live
                            ? socialPage("radio", { workId: row.work_id, station: row.station })
                            : creatorPage("work", { workId: row.work_id }),
                        })
                      }
                    >
                      <View>
                        <Text className="creator-channel__name">{row.title || c.releaseUntitled}</Text>
                        <Text className="creator-channel__meta">
                          {row.live ? c.radioTrialLive : c.radioTrialEnded}
                          {row.station ? ` · ${row.station}` : ""}
                        </Text>
                      </View>
                    </View>
                  ))}
                </>
              )}

              {releaseInbox === "trials" && (data?.radio_trials || []).length === 0 && (
                <EmptyState
                  iconName="music"
                  title={c.emptyRadioTrial}
                  description={c.emptyRadioTrialHint}
                  actionLabel={c.goCreate}
                  onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
                />
              )}

              {releaseInbox === "clips" && (data?.clip_drops || []).length > 0 && (
                <>
                  <SectionLabel>{c.clipInbox}</SectionLabel>
                  {(data?.clip_drops || []).map((row) => (
                    <View
                      key={row.id}
                      className="creator-channel creator-channel--tap"
                      onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId: row.work_id }) })}
                    >
                      <View>
                        <Text className="creator-channel__name">{row.portal_name || row.url}</Text>
                        <Text className="creator-channel__meta">{`${row.clip_length || 15}s · ${c.clipDropTitle}`}</Text>
                      </View>
                    </View>
                  ))}
                </>
              )}

              {releaseInbox === "clips" && (data?.clip_drops || []).length === 0 && (
                <EmptyState
                  iconName="music"
                  title={c.emptyClips}
                  description={c.emptyClipsHint}
                  actionLabel={c.goCreate}
                  onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
                />
              )}

              {worksCount === 0 ? (
                <EmptyState
                  iconName="music"
                  title={c.emptyHub}
                  description={c.deskGuestHint}
                  actionLabel={c.goCreate}
                  onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
                />
              ) : !releaseHasRows && releaseInbox === "queue" ? (
                <EmptyState
                  iconName="music"
                  title={c.emptyRelease}
                  description={c.emptyReleaseHint}
                  actionLabel={c.goCreate}
                  onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
                />
              ) : null}
              {tabVariant ? (
                <View className="creator-actions">
                  <Button size="sm" variant="ghost" onClick={() => changePane("money")}>{c.deskMoney}</Button>
                  <Button size="sm" variant="ghost" onClick={() => changePane("tools")}>{c.deskTools}</Button>
                </View>
              ) : null}
            </>
          )}

          {!weapp && pane === "money" && (
            <>
              {tabVariant ? (
                <Button size="sm" variant="ghost" onClick={() => changePane("release")}>{c.deskRelease}</Button>
              ) : null}
              {(() => {
                const health = data?.harvest_health;
                const unmatchedN = health?.unmatched_count || data?.unmatched_count || 0;
                const healthState = health?.state || (unmatchedN > 0 ? "unmatched" : hasAvailable ? "withdrawable" : hasPending ? "pending" : "idle");
                const harvestOnExtension = healthState === "ready" && health?.farm_ok === false;
                const healthCopy =
                  {
                    unmatched: c.harvestHealthUnmatched,
                    needs_login: c.harvestHealthLogin,
                    ready: c.harvestHealthReady,
                    idle: c.harvestHealthIdle,
                    withdrawable: c.harvestHealthWithdrawable,
                    pending: c.harvestHealthPending,
                    draft: c.harvestHealthDraft,
                  }[healthState] || c.harvestHealthIdle;
                const goMoney = () => {
                  if (harvestOnExtension) {
                    void wakeHarvest();
                    return;
                  }
                  if (unmatchedN > 0 || health?.cta === "attach") {
                    Taro.navigateTo({ url: creatorPage("dataImport") });
                    return;
                  }
                  if (health?.cta === "accounts") {
                    Taro.navigateTo({ url: creatorPage("accounts") });
                    return;
                  }
                  if (health?.cta === "settlements") {
                    Taro.navigateTo({ url: creatorPage("settlements") });
                    return;
                  }
                  if (topWork?.work_id) {
                    Taro.navigateTo({ url: creatorPage("work", { workId: topWork.work_id }) });
                    return;
                  }
                  Taro.navigateTo({ url: creatorPage("wallet") });
                };
                const primaryLabel = harvestOnExtension
                  ? c.harvestWake
                  : unmatchedN > 0 || health?.cta === "attach"
                    ? c.attachUnmatchedCta
                    : health?.cta === "accounts"
                      ? c.moneyDoorAccounts
                      : health?.cta === "settlements"
                        ? c.goSettlements
                        : health?.cta === "wallet"
                          ? c.nextWallet
                          : c.goWallet;
                return (
                  <>
                    <View className="creator-card creator-card--tap" onClick={goMoney}>
                      <Text className="creator-pick__title">{c.moneyGlance}</Text>
                      <StatusLine
                        tone={healthState === "unmatched" || healthState === "needs_login" ? "error" : "info"}
                        density="quiet"
                      >
                        {healthCopy}
                      </StatusLine>
                      <Text className="typo-meta">
                        {topWork
                          ? c.moneyGlanceWork
                              .replace("{title}", topWork.title || c.releaseUntitled)
                              .replace("{amount}", glanceAmount)
                          : c.moneyFriday}
                      </Text>
                      {data?.payout_calendar?.next_payout_date ? (
                        <StatusLine tone="info" density="quiet">
                          {formatPayoutCountdown(data.payout_calendar, c)}
                        </StatusLine>
                      ) : null}
                      {sourceSplit ? (
                        <Text className="typo-meta">
                          {[
                            `${c.walletRadio} ${formatWarmup(sourceSplit.radio_minor, c.warmupNotCash)}`,
                            `${c.walletSync} ${formatFen(sourceSplit.sync_minor)}`,
                            `${c.walletDsp} ${formatFen(sourceSplit.dsp_minor)}`,
                          ].join(" · ")}
                        </Text>
                      ) : null}
                    </View>
                    <View className="creator-metrics creator-metrics--pair">
                      <MetricCard
                        icon="sigil"
                        label={c.moneyLineWithdrawable}
                        value={
                          (data?.available_by_currency || []).length > 1
                            ? formatMoneyMap(data?.available_by_currency, "available_minor")
                            : formatFen(data?.available_minor, data?.available_currency)
                        }
                        variant="info"
                        onClick={() => Taro.navigateTo({ url: creatorPage("wallet") })}
                      />
                      <MetricCard
                        icon="bookmark"
                        label={c.moneyLinePending}
                        value={formatFen(data?.pending_minor, data?.available_currency)}
                        onClick={() => Taro.navigateTo({ url: creatorPage("settlements") })}
                      />
                      <MetricCard
                        icon="search"
                        label={c.moneyLineUnmatched}
                        value={String(unmatchedN)}
                        onClick={() => Taro.navigateTo({ url: creatorPage("dataImport") })}
                      />
                    </View>
                    <View className="creator-actions">
                      <Button size="sm" variant="primary" onClick={goMoney}>
                        {primaryLabel}
                      </Button>
                    </View>
                  </>
                );
              })()}
              <Collapsible label={c.moneyBreakdown} defaultOpen={false}>
                <SegmentedControl<"all" | "period">
                  options={[
                    { value: "all", label: c.periodAll },
                    { value: "period", label: c.periodThis.replace("{p}", data?.period_key || "—") },
                  ]}
                  value={scope}
                  onChange={setScope}
                />
                {(data?.label_period?.gross_minor || 0) > 0 ? (
                  <MoneySplit
                    gross={data?.label_period?.gross_minor || 0}
                    take={data?.label_period?.commission_minor || 0}
                    net={data?.label_period?.net_minor || 0}
                    currency={data?.label_period?.currency}
                    labels={{ gross: c.splitGross, take: c.splitTake, net: c.splitNet }}
                  />
                ) : null}
                {hasSourceMoney ? (
                  <View className="creator-metrics creator-metrics--pair">
                    <MetricCard icon="music" label={c.walletRadio} value={formatWarmup(sourceSplit?.radio_minor, c.warmupNotCash)} />
                    <MetricCard icon="flask" label={c.walletSync} value={formatFen(sourceSplit?.sync_minor)} />
                    <MetricCard icon="feed" label={c.walletEmbed} value={formatFen(sourceSplit?.embed_minor)} />
                    <MetricCard icon="bookmark" label={c.walletDsp} value={formatFen(sourceSplit?.dsp_minor)} />
                    {(sourceSplit?.harvest_minor || 0) > 0 ? (
                      <MetricCard icon="sigil" label={c.walletHarvest} value={formatFen(sourceSplit?.harvest_minor)} />
                    ) : null}
                  </View>
                ) : null}
                {channels.length > 0 && <SectionLabel>{c.byChannel}</SectionLabel>}
                {channels.slice(0, 3).map((ch) => (
                  <View
                    key={ch.channel_code}
                    className="creator-channel creator-channel--tap"
                    onClick={() =>
                      Taro.navigateTo({
                        url: creatorPage(
                          ch.has_real || data?.waiting_for_statement || data?.has_label_release ? "settlements" : "wallet",
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
                        {(periodOn ? ch.period_streams : ch.streams)
                          ? `${c.streams} ${formatCount(periodOn ? ch.period_streams : ch.streams, compactWan)}`
                          : c.waitingData}
                      </Text>
                    </View>
                    {ch.has_real ? (
                      <Text className="creator-channel__name">{formatFen(periodOn ? ch.period_revenue_minor : ch.revenue_minor)}</Text>
                    ) : (
                      <Badge tone="accent">{c.displayOnlyBadge}</Badge>
                    )}
                  </View>
                ))}
                {(data?.by_work || []).length > 0 && <SectionLabel>{c.byWork}</SectionLabel>}
                {(data?.by_work || []).slice(0, 3).map((wk) => (
                  <View
                    key={wk.work_id}
                    className="creator-channel creator-channel--tap"
                    onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId: wk.work_id }) })}
                  >
                    <View className="creator-channel__head">
                      {wk.cover_url ? (
                        <Image className="creator-channel__cover" src={wk.cover_url} mode="aspectFill" />
                      ) : (
                        <View className="creator-channel__cover" />
                      )}
                      <View>
                        <Text className="creator-channel__name">{wk.title || c.releaseUntitled}</Text>
                        <Text className="creator-channel__meta">
                          {c.streams} {formatCount(periodOn ? wk.period_streams : wk.streams, compactWan)}
                        </Text>
                      </View>
                    </View>
                    {wk.has_real ? (
                      <Text className="creator-channel__name">{formatFen(periodOn ? wk.period_revenue_minor : wk.revenue_minor)}</Text>
                    ) : (
                      <Badge tone="accent">{c.displayOnlyBadge}</Badge>
                    )}
                  </View>
                ))}
              </Collapsible>
              {!hasAvailable && !hasPending && !(data?.unmatched_count) && (
                <EmptyState
                  iconName="profile"
                  title={c.emptyWalletShort}
                  description={c.waitHarvestShort}
                  actionLabel={c.seeHelp}
                  onAction={openHelp}
                />
              )}
              {walletOn && (
                <Collapsible label={c.moneyExports} defaultOpen={false}>
                  <View className="creator-actions">
                    <Button size="sm" variant="ghost" onClick={() => void downloadCreatorStatement(c)}>
                      {c.exportCsv}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => void downloadProExport(c)}>
                      {c.proExport}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={openHelp}>
                      {c.seeHelp}
                    </Button>
                  </View>
                </Collapsible>
              )}
              {data?.synced_at && <Text className="typo-meta">{c.syncedAt.replace("{t}", data.synced_at)}</Text>}
            </>
          )}

          {!weapp && pane === "tools" && (
            <>
              {tabVariant ? (
                <Button size="sm" variant="ghost" onClick={() => changePane("release")}>{c.deskRelease}</Button>
              ) : null}
              <Text className="typo-meta">{c.toolsEmptyHint}</Text>
              {(() => {
                const needImport = (data?.unmatched_count || 0) > 0 || Boolean(data?.waiting_for_statement);
                const conns = data?.connections || [];
                const needConnect =
                  conns.length === 0 ||
                  conns.every((row) => row.status === "disconnected" || row.status === "needs_login" || !row.status);
                const primary = needImport
                  ? {
                      icon: "search" as const,
                      label: c.toolsDoorImport,
                      tone: "accent" as const,
                      go: () => Taro.navigateTo({ url: creatorPage("dataImport") }),
                    }
                  : needConnect
                    ? {
                        icon: "bookmark" as const,
                        label: c.deskConnect,
                        tone: "accent" as const,
                        go: () => changePane("today"),
                      }
                    : {
                        icon: "flask" as const,
                        label: c.toolsDoorSync,
                        tone: "accent" as const,
                        go: () => Taro.navigateTo({ url: commercePage("syncDesk") }),
                      };
                return (
                  <>
                    <View className="creator-nav">
                      <NavTile icon={primary.icon} label={primary.label} tone={primary.tone} onClick={primary.go} />
                    </View>
                    <Collapsible label={c.toolsMoreDoors} defaultOpen={false}>
                      <View className="creator-nav">
                        {!needImport ? (
                          <NavTile
                            icon="search"
                            label={c.toolsDoorImport}
                            tone="neutral"
                            onClick={() => Taro.navigateTo({ url: creatorPage("dataImport") })}
                          />
                        ) : null}
                        {needConnect || needImport ? (
                          <NavTile
                            icon="flask"
                            label={c.toolsDoorSync}
                            tone="neutral"
                            onClick={() => Taro.navigateTo({ url: commercePage("syncDesk") })}
                          />
                        ) : null}
                        {!needConnect ? (
                          <NavTile
                            icon="bookmark"
                            label={c.deskConnect}
                            tone="neutral"
                            onClick={() => changePane("today")}
                          />
                        ) : null}
                        <NavTile
                          icon="profile"
                          label={c.toolsDoorCommune}
                          tone="warm"
                          onClick={() => Taro.navigateTo({ url: creatorPage("commune") })}
                        />
                      </View>
                    </Collapsible>
                  </>
                );
              })()}
            </>
          )}
        </AsyncPanel>
      </CreatorDeskFrame>
    </PageShell>
  );
}
