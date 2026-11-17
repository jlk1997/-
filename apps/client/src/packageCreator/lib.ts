import Taro from "@tarojs/taro";
import { getItem } from "../platform/storage";
import { looksLikeStorePage } from "./storeUrl";

function clipModalLabel(value: string) {
  return Array.from((value || "").trim()).slice(0, 4).join("");
}

export async function confirmCreatorAction(opts: {
  title: string;
  content: string;
  confirmText?: string;
  cancelText?: string;
}): Promise<boolean> {
  const payload: { title: string; content: string; confirmText?: string; cancelText?: string } = {
    title: opts.title,
    content: opts.content,
  };
  const confirmText = clipModalLabel(opts.confirmText || "");
  const cancelText = clipModalLabel(opts.cancelText || "");
  if (confirmText) payload.confirmText = confirmText;
  if (cancelText) payload.cancelText = cancelText;
  const res = await Taro.showModal(payload);
  return Boolean(res.confirm);
}

export function formatCount(n?: number | null, compactWan = true) {
  const v = n || 0;
  if (compactWan && v >= 10000) return `${(v / 10000).toFixed(v >= 100000 ? 0 : 1)}万`;
  if (!compactWan && v >= 1000) return `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k`;
  return String(v);
}

export type CreatorNextStep = "generate" | "beautify" | "connector" | "release" | "stores" | "import" | "settlements" | "wallet" | "sync" | "reprocess" | "qc" | "wait_review" | "claim";

export function parkedStepCopy(
  step: CreatorNextStep,
  c: {
    parkYou: string;
    parkOps: string;
    parkStore: string;
    parkSystem: string;
    parkBuyer: string;
    stopGenerate: string;
    stopBeautify: string;
    stopConnector: string;
    stopRelease: string;
    stopReceipt: string;
    stopReconcile: string;
    stopSettle: string;
    stopPayout: string;
    stopInvoice: string;
    stopReview: string;
    stopQc: string;
  },
): { who: string; park: string } {
  const map: Record<CreatorNextStep, { who: string; park: string }> = {
    generate: { who: c.parkYou, park: c.stopGenerate },
    beautify: { who: c.parkYou, park: c.stopBeautify },
    connector: { who: c.parkYou, park: c.stopConnector },
    release: { who: c.parkYou, park: c.stopRelease },
    stores: { who: c.parkStore, park: c.stopReceipt },
    import: { who: c.parkYou, park: c.stopReconcile },
    settlements: { who: c.parkOps, park: c.stopSettle },
    wallet: { who: c.parkOps, park: c.stopPayout },
    sync: { who: c.parkBuyer, park: c.stopInvoice },
    reprocess: { who: c.parkSystem, park: c.stopQc },
    qc: { who: c.parkSystem, park: c.stopQc },
    wait_review: { who: c.parkStore, park: c.stopReview },
    claim: { who: c.parkYou, park: c.stopReconcile },
  };
  return map[step] || { who: c.parkYou, park: c.stopRelease };
}

export const LAUNCH_HANDOFF_CHANNELS = ["netease", "spotify", "wechat_channels"] as const;
export const DEFAULT_UPLOAD_CHANNELS = ["netease"] as const;
export const FILLABLE_SHIP_CHANNELS = ["netease", "qq_music", "kugou", "kuwo", "qishui", "bilibili"] as const;
export const METRICS_SHIP_CHANNELS = ["spotify", "apple_music", "tiktok_music", "amazon_music", "deezer"] as const;

export type ShipChannelGroup = "fill" | "metrics" | "ops";

export function shipChannelGroup(code?: string, automation?: string): ShipChannelGroup {
  const key = String(code || "");
  if (automation === "metrics_only" || (METRICS_SHIP_CHANNELS as readonly string[]).includes(key)) return "metrics";
  if (automation === "ops_only") return "ops";
  if ((FILLABLE_SHIP_CHANNELS as readonly string[]).includes(key) || automation === "connector_full" || automation === "connector_assist") {
    return "fill";
  }
  return "ops";
}

export function defaultCheckedShipChannels(codes: string[], connected: string[] = []): string[] {
  const handed = new Set(connected);
  const out: string[] = [];
  for (const code of DEFAULT_UPLOAD_CHANNELS) {
    if (!out.includes(code)) out.push(code);
  }
  for (const code of codes) {
    if (out.includes(code)) continue;
    if (shipChannelGroup(code) !== "fill") continue;
    if (handed.has(code)) out.push(code);
  }
  return out;
}

export function leaseOwnerLabel(
  row: { last_error?: string; lease_owner?: string; status?: string },
  c: { shipLeaseExtension: string; shipLeaseFarm: string; shipLeaseWait: string },
  farmOn?: boolean,
) {
  if (!farmOn) return c.shipLeaseExtension;
  const owner = String(row.lease_owner || "");
  if (owner === "farm") return c.shipLeaseFarm;
  if (owner === "extension") return c.shipLeaseExtension;
  return c.shipLeaseWait;
}

export function isVolumeConnection(row: { delivery_mode?: string }) {
  return row.delivery_mode !== "session_assist";
}

function launchRank(code?: string) {
  const index = (LAUNCH_HANDOFF_CHANNELS as readonly string[]).indexOf(code || "");
  return index >= 0 ? index : 99;
}

export function pickNextAuthStore<
  T extends { status?: string; suggest_connector?: boolean; delivery_mode?: string; channel_code?: string },
>(connections?: T[] | null): T | null {
  const rows = [...(connections || [])];
  const statusRank = (row: T) => {
    if (row.status === "needs_login") return 0;
    if (row.status === "disconnected" && row.suggest_connector) return 1;
    if (row.status === "disconnected") return 2;
    return 9;
  };
  const candidates = rows.filter((row) => statusRank(row) < 9);
  candidates.sort((a, b) => statusRank(a) * 100 + launchRank(a.channel_code) - (statusRank(b) * 100 + launchRank(b.channel_code)));
  return candidates[0] || null;
}

export function hasHandedVolumeStore(connections?: { status?: string; delivery_mode?: string }[] | null) {
  return (connections || []).some((row) => row.status === "metrics" || row.status === "settle");
}

export type ConnectorLiveState = {
  online?: boolean;
  version?: string;
  last_seen_at?: string;
  period_key?: string;
  last_harvest?: { channel?: string; count?: number; matched?: number; unclaimed?: number } | null;
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
  degraded_count?: number;
};

export function connectorEventLabel(event: string | undefined, c: Record<string, string>) {
  const map: Record<string, string> = {
    opening: c.connectorEventOpening,
    planted: c.connectorEventPlanted,
    master_planted: c.connectorEventPlanted,
    fields_filled: c.connectorEventFilled,
    master_attached: c.connectorEventAttached,
    submitted: c.connectorEventSubmitted,
    receipt: c.connectorEventReceipt,
    needs_challenge: c.connectorEventChallenge,
    fill_incomplete: c.connectorEventFillIncomplete,
    assist_skip_attach: c.routePreviewAssist,
    metrics_only: c.routePreviewMetrics,
    progress: c.connectorEventProgress,
  };
  if (event && map[event]) return map[event];
  if (event && /^[a-z0-9_]+$/i.test(event)) return c.connectorEventProgress || "";
  return event || "";
}

export function connectorLiveLine(
  c: Record<string, string> & { channels?: Record<string, string> },
  connector?: ConnectorLiveState | null,
) {
  const n = Number(connector?.queue_count || 0);
  const last = connector?.last_delivery;
  const step = connectorEventLabel(last?.event, c);
  const parts: string[] = [];
  if (n > 0) parts.push(c.connectorQueueCount.replace("{n}", String(n)));
  if ((connector?.degraded_count || 0) > 0 && c.routePreviewDegraded) parts.push(c.routePreviewDegraded);
  if (step || last?.message) {
    const raw = last?.message ? String(last.message) : "";
    const shown = raw ? humanizeDeliveryError(raw, c) || raw : "";
    const msg = shown ? ` · ${shown.slice(0, 72)}` : "";
    parts.push(
      c.connectorLastDelivery
        .replace("{name}", channelName(String(last?.channel_code || ""), c.channels || {}))
        .replace("{event}", step)
        .replace("{msg}", msg),
    );
  }
  return parts.filter(Boolean).join(" · ");
}

export function nextCreatorStep(state: {
  works: number;
  releases: number;
  delivering: boolean;
  hasReal: boolean;
  hasPending?: boolean;
  hasAvailable?: boolean;
  dspOn?: boolean;
  unpublishedCount?: number;
  sessionWait?: number;
  uploadWait?: number;
  connectorOnline?: boolean;
  weapp?: boolean;
  hasLive?: boolean;
  hasLabelRelease?: boolean;
  unmatchedCount?: number;
  degradedCount?: number;
  qcPendingCount?: number;
  inReviewCount?: number;
  needsBeautifyCount?: number;
  canAutoShip?: boolean;
}): CreatorNextStep {
  if (state.works <= 0) return "generate";
  // Degraded works need reprocessing first
  if ((state.degradedCount || 0) > 0) return "reprocess";
  // Work A without a stereo master: beautify before QC / store release
  if ((state.needsBeautifyCount || 0) > 0) return "beautify";
  // QC pending
  if ((state.qcPendingCount || 0) > 0) return "qc";
  const unpublished = (state.unpublishedCount || 0) > 0 || state.releases <= 0;
  if (unpublished) return "release";
  const loginWait = (state.sessionWait || 0) > 0;
  const uploadOnly = (state.uploadWait || 0) > 0 && !loginWait;
  if (uploadOnly && state.delivering) return "stores";
  if (loginWait && state.delivering) return "connector";
  if ((state.inReviewCount || 0) > 0) return "wait_review";
  if (!state.delivering || state.hasLive === false) return "stores";
  if ((state.unmatchedCount || 0) > 0) return "import";
  if (state.hasLive && !state.hasAvailable && !state.hasPending) return "sync";
  return "wallet";
}

export function ledgerTypeLabel(type: string | undefined, labels: Record<string, string>) {
  return labels[type || ""] || type || "—";
}

export function settlementSourceLabel(source: string | undefined, labels: Record<string, string>) {
  const key = (source || "").trim();
  return labels[key] || labels.other || source || "—";
}

export function formatPayoutCountdown(
  cal:
    | {
        next_payout_date?: string;
        weekday_label?: string;
        days_until_payout?: number;
        is_payout_day?: boolean;
      }
    | null
    | undefined,
  c: { nextPayout: string; payoutFriday: string; payoutToday: string; payoutInDays: string },
) {
  if (!cal?.next_payout_date) return "";
  const datePart = c.nextPayout.replace("{d}", cal.next_payout_date);
  if (cal.is_payout_day || cal.days_until_payout === 0) return `${datePart} · ${c.payoutToday}`;
  if (typeof cal.days_until_payout === "number") {
    return `${datePart} · ${c.payoutInDays.replace("{n}", String(cal.days_until_payout))}`;
  }
  return cal.weekday_label ? `${datePart} · ${c.payoutFriday}` : datePart;
}

function moneyLocale(explicit?: string) {
  if (explicit === "en" || explicit === "zh") return explicit;
  try {
    const stored = getItem("vibe-locale");
    return stored === "en" || stored === "zh" ? stored : undefined;
  } catch {
    return undefined;
  }
}

export function formatFen(n?: number | null, currency = "CNY", locale?: string) {
  const v = (n || 0) / 100;
  if (currency === "USD") return `$${v.toFixed(2)}`;
  if (moneyLocale(locale) === "en") return `CNY ${v.toFixed(2)}`;
  return `¥${v.toFixed(2)}`;
}

export function formatWarmup(n?: number | null, template = "{amount}") {
  const fen = n || 0;
  const shown = (fen / 100).toFixed(fen % 100 === 0 ? 0 : 2);
  return template.replace("{amount}", shown);
}

export type PredictedRevenue = {
  low_minor?: number;
  mid_minor?: number;
  high_minor?: number;
  currency?: string;
  confidence?: number;
  streams?: number;
  disclaimer?: string;
  geo_applied?: boolean;
};

export function formatPredictedRange(pred?: PredictedRevenue | null, template = "{low} – {high}") {
  if (!pred || (!(pred.high_minor || 0) && !(pred.low_minor || 0))) return "";
  return template
    .replace("{low}", formatFen(pred.low_minor, pred.currency))
    .replace("{high}", formatFen(pred.high_minor, pred.currency));
}

export function formatMoneyMap(
  rows?: Array<{
    currency?: string;
    available_minor?: number;
    pending_minor?: number;
    net_minor?: number;
    revenue_minor?: number;
    gross_minor?: number;
    lifetime_earned_minor?: number;
  } | null> | null,
  field:
    | "available_minor"
    | "pending_minor"
    | "net_minor"
    | "revenue_minor"
    | "gross_minor"
    | "lifetime_earned_minor" = "net_minor",
) {
  const parts = (rows || [])
    .map((row) => formatFen(Number(row?.[field] || 0), row?.currency || "CNY"))
    .filter(Boolean);
  return parts.length ? parts.join(" · ") : formatFen(0);
}

export function yuanToFen(raw: string) {
  const n = Number(String(raw).replace(/[^\d.]/g, ""));
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.round(n * 100);
}

export function statusTone(status?: string): "accent" | "success" | "warning" | "danger" {
  const s = (status || "").toLowerCase();
  if (["live", "confirmed", "paid", "paid_manual", "passed", "available"].includes(s)) return "success";
  if (["rejected", "failed", "error", "taken_down", "voided"].includes(s)) return "danger";
  if (["pending", "submitted", "awaiting_manual", "ops_queue", "session_wait", "session_running", "waiting_login", "assisting", "needs_upload", "needs_retry", "ops_handling", "publishing", "frozen", "review", "qc", "queued", "delivering", "submitting", "in_review", "pending_license", "pending_invoice", "approved"].includes(s)) {
    return "warning";
  }
  return "accent";
}

export function statusLineTone(status?: string): "info" | "success" | "error" | "loading" {
  const tone = statusTone(status);
  if (tone === "success") return "success";
  if (tone === "danger") return "error";
  if (tone === "warning") return "loading";
  return "info";
}

export function channelName(code: string, names: Record<string, string>) {
  return names[code] || code;
}

export function statusLabel(status: string, labels: Record<string, string>) {
  const key = String(status || "").trim();
  if (!key) return labels.pending || labels.publishing || "";
  return labels[key] || labels.pending || labels.publishing || "";
}

export function payoutChannelLabel(
  channel: string,
  c: { channelAlipay?: string; channelWechat?: string; channelPaypal?: string; channelBank?: string },
) {
  if (channel === "alipay") return c.channelAlipay || channel;
  if (channel === "wechat") return c.channelWechat || channel;
  if (channel === "paypal") return c.channelPaypal || channel;
  if (channel === "bank") return c.channelBank || channel;
  return channel;
}

export function isUploadWait(status?: string, userStatus?: string) {
  const key = userStatus || status || "";
  return key === "needs_upload" || status === "awaiting_manual" || status === "needs_upload";
}

export function isInReview(status?: string, userStatus?: string) {
  return (userStatus || status) === "in_review";
}

export function isFillIncomplete(lastError?: string, userStatus?: string) {
  return userStatus === "needs_retry" || String(lastError || "").includes("fill_incomplete");
}

export function canRetryDelivery(row: {
  status?: string;
  user_status?: string;
  last_error?: string;
  store_url?: string;
  has_live_receipt?: boolean;
  automation_level?: string;
}) {
  if (row.status === "live" || row.user_status === "live" || row.has_live_receipt) return false;
  if (row.status === "metrics_only" || row.user_status === "metrics_only" || row.automation_level === "metrics_only") return false;
  if (row.status === "in_review" || row.user_status === "in_review") return false;
  if (isFillIncomplete(row.last_error, row.user_status)) return true;
  return ["submitting", "rejected"].includes(row.status || "");
}

export function isLeaseWait(status?: string, userStatus?: string, lastError?: string) {
  if (isFillIncomplete(lastError, userStatus)) return false;
  if (String(lastError || "").includes("farm_or_extension_lease_wait")) return true;
  const key = userStatus || status || "";
  return key === "assisting" || status === "session_running";
}

export function isWaitingLogin(status?: string, userStatus?: string, lastError?: string) {
  if (isUploadWait(status, userStatus) || isLeaseWait(status, userStatus, lastError)) return false;
  return ["session_wait", "waiting_login"].includes(userStatus || status || "");
}

export function isLoginAssist(status?: string, userStatus?: string, lastError?: string) {
  if (isLeaseWait(status, userStatus, lastError) || isWaitingLogin(status, userStatus, lastError)) return true;
  return ["session_wait", "session_running", "waiting_login", "assisting"].includes(userStatus || status || "");
}

export function isStoreAssist(status?: string, userStatus?: string, lastError?: string) {
  return (
    isLoginAssist(status, userStatus, lastError) ||
    isUploadWait(status, userStatus) ||
    isFillIncomplete(lastError, userStatus)
  );
}

export function mapSeatError(
  lastError?: string | null,
  c?: { harvestFailHint?: string; seatExpiredHint?: string },
) {
  const code = String(lastError || "").toLowerCase();
  if (!code) return "";
  if (
    code.includes("no_rows") ||
    code.includes("selector_broke") ||
    code.includes("needs_runtime") ||
    code.includes("harvest") ||
    code.includes("job_failed") ||
    code.includes("dashboard")
  ) {
    return c?.harvestFailHint || "";
  }
  if (code.includes("expired") || code.includes("challenge")) {
    return c?.seatExpiredHint || "";
  }
  return c?.harvestFailHint || "";
}

export function seatPhase(seat: {
  status?: string;
  has_session?: boolean;
  last_harvest_at?: string | null;
  last_upload_at?: string | null;
  remote_status?: string;
  last_error?: string | null;
}) {
  if (seat.status === "disconnected") return "need_login";
  if (seat.status === "needs_challenge") return "challenge";
  if (seat.status === "expired") return "expired";
  if (seat.has_session && seat.last_harvest_at) return "harvested";
  if (seat.has_session || seat.status === "live") return "waiting_harvest";
  if (seat.remote_status === "waiting_login" || seat.remote_status === "awaiting_user" || seat.remote_status === "user_finished") {
    return "need_login";
  }
  return "connecting";
}

export function sessionWaitCta(
  c: {
    installConnectorCta: string;
    openRemoteLogin: string;
    seatWeappHint: string;
    sessionWaitHint: string;
    leaseWaitHint: string;
    machineUploading: string;
    needLoginStores: string;
    nextGo: string;
  },
  opts: { weapp: boolean; connectorOnline: boolean; leaseWait?: boolean; waiting: number },
) {
  if (opts.weapp) {
    return { title: c.openRemoteLogin, hint: c.seatWeappHint, go: c.nextGo, to: "remote" as const };
  }
  if (opts.leaseWait) {
    return {
      title: c.machineUploading,
      hint: c.leaseWaitHint,
      go: c.nextGo,
      to: "accounts" as const,
    };
  }
  if (!opts.connectorOnline) {
    return {
      title: c.installConnectorCta,
      hint: c.sessionWaitHint,
      go: c.nextGo,
      to: "accounts" as const,
    };
  }
  return {
    title: c.needLoginStores.replace("{n}", String(opts.waiting)),
    hint: c.sessionWaitHint,
    go: c.nextGo,
    to: "accounts" as const,
  };
}

export function layerKind(layer?: string): "aggregator" | "session" | "ops" | "" {
  if (layer === "ops") return "ops";
  if (layer === "session_assist" || layer === "session") return "session";
  if (layer === "aggregator") return "aggregator";
  return "";
}

export type LiveHint = {
  status?: string;
  user_status?: string;
  store_url?: string;
  external_id?: string;
  has_receipt?: boolean;
  last_error?: string;
  automation_level?: string;
};

export function hasLiveReceipt(d: LiveHint) {
  if (typeof d.has_receipt === "boolean") return d.has_receipt;
  const url = (d.store_url || "").trim();
  if (url) return looksLikeStorePage(url);
  const ext = (d.external_id || "").trim();
  if (!ext) return false;
  if (ext.startsWith("http://") || ext.startsWith("https://")) return looksLikeStorePage(ext);
  return true;
}

export function isLiveDelivery(d: LiveHint) {
  return d.status === "live" && hasLiveReceipt(d);
}

export function isMetricsOnlyDelivery(row: { status?: string; user_status?: string; automation_level?: string }) {
  return row.status === "metrics_only" || row.user_status === "metrics_only" || row.automation_level === "metrics_only";
}

export function humanizeDeliveryError(
  lastError?: string | null,
  c?: {
    connectorEventFillIncomplete?: string;
    needsChallengeHint?: string;
    leaseWaitHint?: string;
    routePreviewMetrics?: string;
    connSaveFail?: string;
    expandStore?: string;
  },
  fallback?: string,
) {
  const raw = String(lastError || "").trim();
  if (!raw || !c) return "";
  if (raw.includes("fill_incomplete")) return c.connectorEventFillIncomplete || raw;
  if (raw.includes("needs_challenge")) return c.needsChallengeHint || raw;
  if (raw.includes("farm_or_extension_lease_wait") || raw.includes("lease_wait")) return c.leaseWaitHint || raw;
  if (raw === "metrics_only" || raw.includes("metrics_only")) return c.routePreviewMetrics || raw;
  if (raw === "scope_revoked") return c.connSaveFail || raw;
  if (/^[a-z0-9_]+$/i.test(raw)) return c.expandStore || fallback || raw;
  if (fallback && /[A-Za-z]/.test(raw) && !/[\u4e00-\u9fff]/.test(raw)) return fallback;
  return raw;
}

export function shouldShowDeliveryError(d: LiveHint) {
  if (!d.last_error || d.status === "live") return false;
  if (isFillIncomplete(d.last_error, d.user_status)) return false;
  if (isLeaseWait(d.status, d.user_status, d.last_error)) return false;
  if (String(d.last_error).includes("needs_challenge")) return false;
  if (isMetricsOnlyDelivery(d)) return false;
  return true;
}

export function isPublishingDelivery(row: { status?: string; user_status?: string; automation_level?: string }) {
  if (isMetricsOnlyDelivery(row)) return false;
  const key = row.user_status || row.status || "";
  return [
    "submitting",
    "ops_queue",
    "awaiting_manual",
    "session_wait",
    "session_running",
    "needs_upload",
    "in_review",
    "needs_retry",
    "assisting",
    "handed_to_extension",
  ].includes(key);
}

export function routePreviewLabel(
  row: { route?: string; automation_level?: string; degraded?: boolean },
  c: {
    routePreviewPartner: string;
    routePreviewOps: string;
    routePreviewMetrics: string;
    routePreviewDegraded: string;
    routePreviewAssist: string;
    routePreviewConnector: string;
  },
) {
  if (row.route === "partner") return c.routePreviewPartner;
  if (row.route === "ops") return c.routePreviewOps;
  if (row.automation_level === "metrics_only" || row.route === "metrics") return c.routePreviewMetrics;
  if (row.degraded) return c.routePreviewDegraded;
  if (row.automation_level === "connector_assist") return c.routePreviewAssist;
  return c.routePreviewConnector;
}

export function storeRowMeta(
  d: LiveHint,
  c: {
    machineUploading: string;
    openRemoteLogin: string;
    storeNeedLink: string;
    openStore: string;
    expandStore: string;
    fillStoreLabel: string;
    storeInReview: string;
    connectorEventFillIncomplete?: string;
    routePreviewMetrics?: string;
  },
) {
  if (isMetricsOnlyDelivery(d)) return { line: c.routePreviewMetrics || c.expandStore, kind: "metrics" as const };
  if (d.store_url) return { line: d.store_url, kind: "store" as const };
  if (isInReview(d.status, d.user_status)) return { line: c.storeInReview, kind: "review" as const };
  if (isFillIncomplete(d.last_error, d.user_status)) {
    return { line: c.connectorEventFillIncomplete || c.machineUploading, kind: "retry" as const };
  }
  if (isUploadWait(d.status, d.user_status)) return { line: c.fillStoreLabel, kind: "upload" as const };
  if (isLeaseWait(d.status, d.user_status, d.last_error)) return { line: c.machineUploading, kind: "machine" as const };
  if (isWaitingLogin(d.status, d.user_status, d.last_error)) return { line: c.openRemoteLogin, kind: "login" as const };
  if (isLoginAssist(d.status, d.user_status, d.last_error)) return { line: c.machineUploading, kind: "machine" as const };
  if (isLiveDelivery(d)) return { line: c.openStore, kind: "live" as const };
  if (d.status === "live") return { line: c.storeNeedLink, kind: "upload" as const };
  return { line: c.expandStore, kind: "other" as const };
}

export function timelineReviewLabel(
  deliveries: Array<{ status?: string; user_status?: string }>,
  labels: { login: string; upload: string },
) {
  return deliveries.some((d) => isUploadWait(d.status, d.user_status)) ? labels.upload : labels.login;
}

export function deliveryBuckets(rows: LiveHint[]) {
  let live = 0;
  let login = 0;
  let upload = 0;
  let pushing = 0;
  for (const row of rows) {
    if (isLiveDelivery(row)) live += 1;
    else if (isMetricsOnlyDelivery(row)) continue;
    else if (isUploadWait(row.status, row.user_status)) upload += 1;
    else if (isWaitingLogin(row.status, row.user_status, row.last_error)) login += 1;
    else if (!["rejected", "taken_down", "failed"].includes(row.status || "")) pushing += 1;
  }
  return { live, login, upload, pushing };
}

export function openExternal(url?: string) {
  const href = (url || "").trim();
  if (!href) return;
  if (process.env.TARO_ENV === "h5" && typeof window !== "undefined") {
    window.open(href, "_blank", "noopener,noreferrer");
    return;
  }
  void Taro.setClipboardData({ data: href });
}

export type WorkPick = {
  id: string;
  title: string;
  cover_url?: string;
  audio_url?: string;
  release_status?: string;
  artist_name?: string;
  parent_work_id?: string | null;
  post_process_status?: Record<string, unknown> | null;
  from_workbench?: boolean;
  superseded_by_work_id?: string | null;
};

export type DeliveryRow = {
  id: string;
  release_id?: string;
  work_id?: string;
  channel_code: string;
  status: string;
  user_status?: string;
  degraded?: boolean;
  automation_level?: string;
  reject_reason?: string;
  reject_next?: { code?: string; next?: string | null; message?: string | null };
  ops_honest?: boolean;
  store_url?: string;
  external_id?: string;
  has_receipt?: boolean;
  upload_url?: string;
  delivery_mode?: string;
  layer?: string;
  last_error?: string;
  sla_hours?: number;
  sla_due_at?: string | null;
  sla_overdue?: boolean;
  sla_escalated?: boolean;
  sop?: string;
  originality_zip_url?: string;
  listing_asset?: string;
  asset_profile?: { needs_stems_evidence?: boolean; needs_clips?: boolean; needs_instrumental?: boolean };
  submissions?: Array<{ event?: string; at?: string; message?: string }>;
  lease_owner?: string | null;
  needs_challenge?: boolean;
  seat_id?: string | null;
};

export function isChallengeDelivery(row: Pick<DeliveryRow, "needs_challenge" | "status" | "user_status" | "last_error">) {
  return Boolean(
    row.needs_challenge ||
      row.status === "needs_challenge" ||
      row.user_status === "needs_challenge" ||
      String(row.last_error || "").includes("needs_challenge"),
  );
}

export function isDegradedAssist(
  row: Pick<DeliveryRow, "degraded" | "automation_level" | "last_error" | "status" | "user_status" | "store_url" | "has_receipt">,
) {
  if (isLiveDelivery(row) || isMetricsOnlyDelivery(row)) return false;
  if (row.degraded) return true;
  if (String(row.last_error || "").includes("degraded")) return true;
  return row.automation_level === "connector_assist" && isUploadWait(row.status, row.user_status);
}

export type ShipBandKind =
  | "challenge"
  | "incomplete"
  | "degraded"
  | "ghost_live"
  | "install"
  | "wait_login"
  | "lease"
  | "filling"
  | "ops"
  | "live_settle"
  | "ready";

export type ShipBandAction = {
  kind: ShipBandKind;
  row?: DeliveryRow;
};

export function pickShipBandAction(opts: {
  deliveries: DeliveryRow[];
  connectorOnline?: boolean;
  weapp?: boolean;
}): ShipBandAction {
  const rows = opts.deliveries || [];
  const challenge = rows.find(isChallengeDelivery);
  if (challenge) return { kind: "challenge", row: challenge };
  const incomplete = rows.find((row) => isFillIncomplete(row.last_error, row.user_status));
  if (incomplete) return { kind: "incomplete", row: incomplete };
  const degraded = rows.find(isDegradedAssist);
  if (degraded) return { kind: "degraded", row: degraded };
  const ghost = rows.find((row) => row.status === "live" && !isLiveDelivery(row));
  if (ghost) return { kind: "ghost_live", row: ghost };
  const waiting = rows.find((row) => isWaitingLogin(row.status, row.user_status, row.last_error));
  if (waiting && !opts.weapp && !opts.connectorOnline) return { kind: "install", row: waiting };
  if (waiting) return { kind: "wait_login", row: waiting };
  const lease = rows.find((row) => isLeaseWait(row.status, row.user_status, row.last_error));
  if (lease) return { kind: "lease", row: lease };
  const filling = rows.find((row) => ["session_running", "assisting"].includes(String(row.user_status || row.status || "")));
  if (filling) return { kind: "filling", row: filling };
  const ops = rows.find((row) => row.status === "ops_queue" || row.user_status === "ops_handling");
  if (ops) return { kind: "ops", row: ops };
  const live = rows.find((row) => isLiveDelivery(row));
  if (live) return { kind: "live_settle", row: live };
  return { kind: "ready" };
}

export const CHANNEL_PORTALS: Record<string, string> = {
  netease: "https://music.163.com/st/musician",
  qq_music: "https://y.qq.com/portal/",
  kugou: "https://www.kugou.com/musician/",
  kuwo: "https://www.kuwo.cn/musician",
  qishui: "https://music.douyin.com/",
  bilibili: "https://member.bilibili.com/",
  spotify: "https://artists.spotify.com/",
  apple_music: "https://artists.apple.com/",
  youtube_music: "https://studio.youtube.com/",
  tiktok_music: "https://www.tiktok.com/studio",
  amazon_music: "https://artists.amazon.com/",
  deezer: "https://www.deezer.com/",
  wechat_channels: "https://channels.weixin.qq.com/",
  douyin_musician: "https://creator.douyin.com/",
  kuaishou_musician: "https://cp.kuaishou.com/",
  soundcloud: "https://soundcloud.com/upload",
  bandcamp: "https://bandcamp.com/",
};

export function channelPortal(code: string, uploadUrl?: string) {
  return uploadUrl || CHANNEL_PORTALS[code] || "";
}

export type ReleaseRow = {
  id: string;
  work_id?: string;
  mode?: string;
  status?: string;
  kit_url?: string;
  has_kit?: boolean;
  can_takedown?: boolean;
  already_active?: boolean;
  metadata?: { title?: string | null };
  deliveries?: DeliveryRow[];
  progress?: { live?: number; total?: number; publishing?: number; rejected?: number };
};

export function releaseHasKit(row: ReleaseRow) {
  return Boolean(row.has_kit || row.kit_url) || row.mode === "self_release";
}

export type SyncResultRow = {
  provider?: string;
  source?: string;
  synced?: number;
  reason?: string;
};

type SyncCopy = {
  sourceYoutube: string;
  sourceChartmetric: string;
  sourceChartmetricArtist: string;
  sourceCsv: string;
  noPublicApi: string;
  noPartnerEndpoint?: string;
  syncReasonOk: string;
  syncReasonNotConfigured: string;
  syncReasonNotBound: string;
  syncReasonNoIsrc: string;
  syncReasonTokenExpired: string;
  syncReasonNoData: string;
  syncReasonNoMatch: string;
  syncReasonProviderError: string;
};

export function syncProviderLabel(row: SyncResultRow, c: SyncCopy) {
  const key = `${row.provider || ""} ${row.source || ""}`.toLowerCase();
  if (key.includes("chartmetric_artist")) return c.sourceChartmetricArtist;
  if (key.includes("chartmetric")) return c.sourceChartmetric;
  if (key.includes("youtube")) return c.sourceYoutube;
  if (key.includes("csv") || key.includes("distributor")) return c.sourceCsv;
  return row.provider || row.source || "—";
}

export function syncReasonLabel(reason: string | undefined, c: SyncCopy) {
  const map: Record<string, string> = {
    ok: c.syncReasonOk,
    not_configured: c.syncReasonNotConfigured,
    not_bound: c.syncReasonNotBound,
    no_isrc: c.syncReasonNoIsrc,
    token_expired: c.syncReasonTokenExpired,
    no_data: c.syncReasonNoData,
    no_match: c.syncReasonNoMatch,
    provider_error: c.syncReasonProviderError,
    configured_no_public_earnings_api: c.noPublicApi,
    configured_no_endpoint: c.noPartnerEndpoint || c.noPublicApi,
  };
  return map[reason || ""] || reason || "";
}

export function liveProgress(deliveries: DeliveryRow[]) {
  const shippable = deliveries.filter((d) => !isMetricsOnlyDelivery(d));
  const total = shippable.length;
  const live = shippable.filter((d) => isLiveDelivery(d)).length;
  return { live, total };
}

export function groupDeliveries(releases: ReleaseRow[], deliveries: DeliveryRow[]): ReleaseRow[] {
  const byRelease = new Map<string, DeliveryRow[]>();
  for (const d of deliveries) {
    const key = d.release_id || "unknown";
    const list = byRelease.get(key) || [];
    list.push(d);
    byRelease.set(key, list);
  }
  const rows = releases.map((r) => ({
    ...r,
    deliveries: r.deliveries?.length ? r.deliveries : byRelease.get(r.id) || [],
  }));
  const known = new Set(rows.map((r) => r.id));
  for (const [id, list] of byRelease) {
    if (id !== "unknown" && !known.has(id)) {
      rows.push({ id, status: "delivering", deliveries: list });
    }
  }
  return rows.filter((r) => (r.deliveries || []).length > 0 || ["queued", "delivering", "live", "ops_queue", "session_wait", "session_running", "taken_down"].includes(r.status || ""));
}
