import { useEffect, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro, { useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { AuthBanner, Button, ChipGroup, Input } from "../../../components/ui";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../../utils/auth";
import { formatFen, statusLabel } from "../../../packageCreator/lib";
import { looksLikeStorePage } from "../../../packageCreator/storeUrl";
import { AssetLanes } from "../../../components/studio/AssetLanes";
import "./index.scss";

type Tab =
  | "stats"
  | "commercial"
  | "reports"
  | "flags"
  | "tenants"
  | "challenges"
  | "presets"
  | "activation"
  | "tickets"
  | "moderation"
  | "distribution"
  | "settlement"
  | "sync"
  | "keys";

export default function AdminPage() {
  const { copy } = useLocale();
  const a = copy.adminUi;
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("settlement");
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [stats, setStats] = useState<{ users: number; works: number; jobs: number } | null>(null);
  const [commercial, setCommercial] = useState<Awaited<ReturnType<typeof vibeApi.adminCommercial>> | null>(null);
  const [pendingPacks, setPendingPacks] = useState<Awaited<ReturnType<typeof vibeApi.listPendingEffectPacks>>>([]);
  const [packBusy, setPackBusy] = useState("");
  const [usage, setUsage] = useState<Record<string, unknown> | null>(null);
  const [reports, setReports] = useState<
    Array<{
      id: string;
      reason: string;
      status: string;
      comment_id?: string | null;
      comment_preview?: string | null;
      post_id?: string | null;
    }>
  >([]);
  const [flags, setFlags] = useState<Array<{ key: string; enabled: boolean; description?: string }>>([]);
  const [tenants, setTenants] = useState<Array<{ tenant_id: string; users: number; works: number; posts: number }>>([]);
  const [grantEmail, setGrantEmail] = useState("");
  const [grantAmount, setGrantAmount] = useState("10");
  const [tenantId, setTenantId] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [tenantInvite, setTenantInvite] = useState("");
  const [tenantInitialCredits, setTenantInitialCredits] = useState("100");
  const [grantPoolTenantId, setGrantPoolTenantId] = useState("");
  const [grantPoolAmount, setGrantPoolAmount] = useState("50");
  const [chSlug, setChSlug] = useState("");
  const [chTitle, setChTitle] = useState("");
  const [chHashtag, setChHashtag] = useState("");
  const [chPrizePool, setChPrizePool] = useState("30");
  const [chDuration, setChDuration] = useState("14");
  const [chSponsor, setChSponsor] = useState("");
  const [distributeChallengeId, setDistributeChallengeId] = useState("");
  const [stylePresets, setStylePresets] = useState<Array<{ id: string; label: string; category: string; enabled: boolean }>>([]);
  const [presetId, setPresetId] = useState("");
  const [presetLabel, setPresetLabel] = useState("");
  const [presetCategory, setPresetCategory] = useState("scene");
  const [presetExampleIntent, setPresetExampleIntent] = useState("");
  const [presetDescription, setPresetDescription] = useState("");
  const [activationFunnel, setActivationFunnel] = useState<Awaited<ReturnType<typeof vibeApi.adminActivationFunnel>> | null>(null);
  const [auditLogs, setAuditLogs] = useState<Array<{ id: string; action: string; target?: string; created_at?: string }>>([]);
  const [tickets, setTickets] = useState<
    Array<{
      id: string;
      category: string;
      subject: string;
      body: string;
      status: string;
      order_id?: string;
      user_email?: string;
      created_at?: string;
    }>
  >([]);
  const [resolveTicketId, setResolveTicketId] = useState("");
  const [resolveCredits, setResolveCredits] = useState("0");
  const [resolveNote, setResolveNote] = useState("");
  const [resolveRefund, setResolveRefund] = useState(false);
  const [resolveResolution, setResolveResolution] = useState<"approved" | "rejected" | "credits_granted" | "stripe_refunded">("approved");
  const [waitlist, setWaitlist] = useState<Array<{ user_id: string; email?: string; channel: string; created_at?: string }>>([]);
  const [modWords, setModWords] = useState<Array<{ id: string; pattern: string; level: string; enabled: boolean }>>([]);
  const [modPattern, setModPattern] = useState("");
  const [modLevel, setModLevel] = useState<"block" | "mask">("block");
  const [deliveries, setDeliveries] = useState<
    Array<{
      id: string;
      release_id?: string;
      channel_code: string;
      status: string;
      reject_reason?: string;
      last_error?: string;
      retry_count?: number;
      claimed_email?: string;
      claim_active?: boolean;
      store_url?: string;
      external_id?: string;
      title?: string;
      owner_email?: string;
      mode?: string;
      sla_due_at?: string | null;
      sla_overdue?: boolean;
      sla_escalated?: boolean;
      sla_hours?: number;
      sop?: string;
      upload_url?: string;
      delivery_mode?: string;
      layer?: string;
      priority_score?: number;
      priority_reason?: string;
      submissions?: Array<{ event?: string; at?: string; message?: string; actor?: string }>;
    }>
  >([]);
  const [workbenchId, setWorkbenchId] = useState("");
  const [workbench, setWorkbench] = useState<{
    id?: string;
    sla_hours?: number;
    sla_due_at?: string | null;
    sla_overdue?: boolean;
    kit_url?: string;
    cover_url?: string;
    clip_pack_url?: string;
    originality_zip_url?: string;
    handoff?: Array<{ field?: string; label?: string; value?: string; filled?: boolean }>;
    listing_asset?: string;
    asset_status?: {
      listing?: { label?: string; ready?: boolean };
      evidence?: { label?: string; needed?: boolean; ready?: boolean };
      clips?: { needed?: boolean; ready?: boolean };
      needs_ai_musician?: boolean;
    };
    clip_windows?: Array<{ length?: number; start?: number; end?: number }>;
    ops_steps?: string[];
    metadata?: Record<string, unknown>;
    deliveries?: Array<Record<string, unknown>>;
    mode?: string;
    status?: string;
  } | null>(null);
  const [reportInbox, setReportInbox] = useState<
    Array<{
      id: string;
      filename?: string;
      source?: string;
      status?: string;
      row_count?: number;
      created_at?: string;
      skipped_no_isrc?: number;
      unmatched_rows?: number;
    }>
  >([]);
  const [partners, setPartners] = useState<{
    partners?: Array<{ code?: string; name?: string; region?: string; configured?: boolean; settlement_path?: string }>;
    global_ready?: boolean;
    cn_ready?: boolean;
    stub_enabled?: boolean;
    note?: string;
  } | null>(null);
  const [officialUnmatched, setOfficialUnmatched] = useState<
    Array<{
      id: string;
      title?: string;
      isrc?: string;
      channel_code?: string;
      period_key?: string;
      work_id?: string;
      work_title?: string;
      suggested_work_id?: string;
      reason?: string;
    }>
  >([]);
  const [attachWorkIds, setAttachWorkIds] = useState<Record<string, string>>({});
  const [storeUrls, setStoreUrls] = useState<Record<string, string>>({});
  const [externalIds, setExternalIds] = useState<Record<string, string>>({});
  const [queueOnly, setQueueOnly] = useState(true);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [connectorBatches, setConnectorBatches] = useState<
    Array<{ id: string; source?: string; status?: string; matched_count?: number; unmatched_count?: number }>
  >([]);
  const [connectorClaims, setConnectorClaims] = useState<
    Array<{ id: string; title?: string; channel_code?: string; period_key?: string; streams?: number }>
  >([]);
  const [claimWorkIds, setClaimWorkIds] = useState<Record<string, string>>({});
  const [harvestUnmatched, setHarvestUnmatched] = useState<
    Array<{ id: string; title?: string; channel_code?: string; period_key?: string; streams?: number; revenue_minor?: number }>
  >([]);
  const [harvestWorkIds, setHarvestWorkIds] = useState<Record<string, string>>({});
  const [opsDigest, setOpsDigest] = useState<{
    total_actionable?: number;
    actionable?: {
      unmatched_claims?: number;
      harvest_unmatched?: number;
      unattached_snapshots?: number;
      selector_broke?: number;
      login_wall_seats?: number;
      sla_overdue?: number;
      session_expired?: number;
      harvest_failed?: number;
      patrol_failed?: number;
      pending_payouts?: number;
      pending_kyc?: number;
      settlement_drafts?: number;
      pending_invoices?: number;
    };
    friday_queue?: {
      settlement_drafts?: number;
      pending_invoices?: number;
      pending_kyc?: number;
      pending_payouts?: number;
      auto_payout?: boolean;
    };
    friday_total?: number;
  } | null>(null);
  const [farmHealth, setFarmHealth] = useState<{
    queued?: number;
    failed?: number;
    selector_broke?: number;
    login_wall?: number;
    patrol_failed?: number;
    seats?: Array<{
      channel_code?: string;
      ownership?: string;
      status?: string;
      farm_health?: { rows?: number; matched?: number; elapsed_ms?: number; session_expired?: boolean };
      playbook_health?: { ok?: boolean; issues?: string[]; statsUrls?: string[]; alternateSelectors?: string[] };
    }>;
  } | null>(null);
  const [kycQueue, setKycQueue] = useState<Array<{ id?: string; email?: string; username?: string; kyc_status?: string }>>([]);
  const [userQuery, setUserQuery] = useState("");
  const [userHits, setUserHits] = useState<Array<{ id: string; email?: string; username?: string; is_active?: boolean; kyc_status?: string }>>([]);
  const [debugOn, setDebugOn] = useState(false);
  const [distHealth, setDistHealth] = useState<{
    submitting?: number;
    ops_queue?: number;
    session_wait?: number;
    session_running?: number;
    stale_submitting?: number;
    queued_without_deliveries?: number;
    sla_overdue?: number;
    healthy?: boolean;
    partner_ready?: string[];
    partner_count?: number;
  } | null>(null);
  const [adminNote, setAdminNote] = useState("");
  const [syncNote, setSyncNote] = useState("");
  const [batches, setBatches] = useState<
    Array<{
      batch_id?: string;
      id?: string;
      period_key?: string;
      status?: string;
      gross_minor?: number;
      commission_minor?: number;
      net_minor?: number;
      line_count?: number;
      user_count?: number;
      by_currency?: Array<{ currency?: string; gross_minor?: number; commission_minor?: number; net_minor?: number }>;
    }>
  >([]);
  const [openBatchId, setOpenBatchId] = useState("");
  const [batchDetail, setBatchDetail] = useState<{
    lines?: Array<{
      user_email?: string;
      work_title?: string;
      channel_code?: string;
      source?: string;
      commission_rate?: number;
      currency?: string;
      gross_minor?: number;
      commission_minor?: number;
      net_minor?: number;
    }>;
    by_user?: Array<{ user_email?: string; line_count?: number; net_minor?: number; commission_minor?: number }>;
    by_currency?: Array<{ currency?: string; gross_minor?: number; commission_minor?: number; net_minor?: number }>;
    by_rate?: Array<{ rate?: number; count?: number; net_minor?: number }>;
  } | null>(null);
  const [settlementPreview, setSettlementPreview] = useState<{
    period_key?: string;
    unsettled_for_period?: number;
    unsettled_other_periods?: Array<{ period_key?: string; count?: number; revenue_minor?: number }>;
    needs_confirm?: boolean;
    pending_ops_connector_batches?: number;
    pending_user_connector_batches?: number;
    gross_minor_for_period?: number;
    commission_minor_for_period?: number;
    net_minor_for_period?: number;
    by_rate?: Array<{ rate?: number; count?: number }>;
    by_currency?: Array<{ currency?: string; gross_minor?: number; commission_minor?: number; net_minor?: number }>;
    skipped?: { self_release?: number; below_minimum?: number; already_in_batch?: number; no_license?: number };
    supplemental?: boolean;
    has_confirmed_batch?: boolean;
  } | null>(null);
  const [syncInvoices, setSyncInvoices] = useState<
    Array<{
      id: string;
      work_id?: string;
      tier?: string;
      status?: string;
      gross_minor?: number;
      seller_minor?: number;
      currency?: string;
      license_id?: string;
    }>
  >([]);
  const [vendorKeys, setVendorKeys] = useState<
    Array<{
      id: string;
      vendor: string;
      capability: string;
      key_prefix: string;
      model?: string | null;
      enabled: boolean;
      last_error?: string | null;
      inflight?: number;
      max_inflight?: number;
      daily_used?: number;
      daily_quota?: number | null;
    }>
  >([]);
  const [newVendor, setNewVendor] = useState("mureka");
  const [newCapability, setNewCapability] = useState("music");
  const [newApiKey, setNewApiKey] = useState("");
  const [probingKeyId, setProbingKeyId] = useState("");
  const [withdrawals, setWithdrawals] = useState<
    Array<{
      id: string;
      status: string;
      amount_minor: number;
      currency?: string;
      fee_minor?: number;
      receipt_no?: string;
      user_id?: string;
      user_email?: string;
      risk_flag?: boolean;
      kyc_status?: string;
    }>
  >([]);

  async function loadAdminData() {
    vibeApi.adminOpsDashboard().then(setOpsDigest).catch(() => {});
    vibeApi
      .adminStats()
      .then((s) => setStats({ users: Number(s.users ?? 0), works: Number(s.works ?? 0), jobs: Number(s.jobs ?? 0) }))
      .catch(() => Taro.showToast({ title: a.noPermission, icon: "none" }));
    vibeApi.adminUsage().then(setUsage).catch(() => {});
    vibeApi.adminReports().then(setReports).catch(() => {});
    vibeApi.adminFlags().then(setFlags).catch(() => {});
    vibeApi.adminTenants().then(setTenants).catch(() => {});
    vibeApi.adminListPresets().then(setStylePresets).catch(() => {});
    vibeApi.adminCommercial().then(setCommercial).catch(() => {});
    vibeApi.listPendingEffectPacks().then(setPendingPacks).catch(() => {});
    vibeApi.adminActivationFunnel(30).then(setActivationFunnel).catch(() => {});
    vibeApi.adminAuditLogs(30).then(setAuditLogs).catch(() => {});
    vibeApi.adminListSupportTickets().then((r) => setTickets(r.tickets || [])).catch(() => {});
    vibeApi.adminCnRecurringWaitlist().then((r) => setWaitlist(r.entries || [])).catch(() => {});
    vibeApi.adminListModerationWords().then(setModWords).catch(() => {});
    const loadDeliveries = queueOnly ? vibeApi.adminDistributionQueue() : vibeApi.adminDistributionDeliveries();
    loadDeliveries.then((r) => setDeliveries((r.deliveries || []) as typeof deliveries)).catch(() => {});
    vibeApi.adminRoyaltyReports().then((r) => setReportInbox((r.imports || []) as typeof reportInbox)).catch(() => {});
    vibeApi.adminDistributionPartners().then(setPartners).catch(() => {});
    vibeApi.adminUnmatchedOfficial().then((r) => {
      const snaps = (r.snapshots || []) as typeof officialUnmatched;
      setOfficialUnmatched(snaps);
      setAttachWorkIds((prev) => {
        const next = { ...prev };
        for (const row of snaps) {
          if ((row.suggested_work_id || row.work_id) && !next[row.id]) next[row.id] = row.suggested_work_id || row.work_id || "";
        }
        return next;
      });
    }).catch(() => {});
    vibeApi.adminConnectorBatches().then((r) => setConnectorBatches((r.batches || []) as typeof connectorBatches)).catch(() => {});
    vibeApi.adminDistributionHealth().then(setDistHealth).catch(() => {});
    vibeApi.adminConnectorClaims().then((r) => setConnectorClaims((r.claims || []) as typeof connectorClaims)).catch(() => {});
    vibeApi.adminHarvestUnmatched().then((r) => setHarvestUnmatched((r.rows || []) as typeof harvestUnmatched)).catch(() => {});
    vibeApi.adminSeatsHealth().then(setFarmHealth).catch(() => {});
    vibeApi.adminSettlementBatches().then((r) => setBatches((r.batches || []) as typeof batches)).catch(() => {});
    vibeApi.adminSettlementPreview().then(setSettlementPreview).catch(() => {});
    vibeApi.adminWithdrawals().then((r) => setWithdrawals((r.withdrawals || []) as typeof withdrawals)).catch(() => {});
    vibeApi.adminKycQueue("pending").then((r) => setKycQueue(r.users || [])).catch(() => {});
    vibeApi.getPlatformConfig().then((cfg) => setDebugOn(Boolean(cfg.debug))).catch(() => {});
    vibeApi.listSyncPendingInvoices().then((r) => setSyncInvoices(r.orders || [])).catch(() => {});
    vibeApi.adminVendorKeys().then((r) => setVendorKeys(r.keys || [])).catch(() => {});
  }

  useEffect(() => {
    if (process.env.TARO_ENV !== "h5") {
      Taro.showToast({ title: a.h5Only, icon: "none" });
      return;
    }
    bootstrapAuth();
    if (!isLoggedIn()) return;
    vibeApi
      .me()
      .then((u) => {
        setIsAdmin(!!u.is_admin);
        if (u.is_admin) void loadAdminData();
      })
      .catch(() => setIsAdmin(false));
  }, [a.h5Only, a.noPermission]);

  useEffect(() => {
    if (!isAdmin) return;
    const nextTab = String(router.params.tab || "");
    if (nextTab === "distribution" || nextTab === "settlement" || nextTab === "sync") {
      setTab(nextTab);
    }
    const releaseId = String(router.params.releaseId || router.params.release_id || "");
    if (!releaseId) return;
    setTab("distribution");
    vibeApi
      .adminReleaseWorkbench(releaseId)
      .then((wb) => {
        setWorkbenchId(releaseId);
        setWorkbench(wb);
      })
      .catch(() => {});
  }, [isAdmin, router.params.tab, router.params.releaseId, router.params.release_id]);

  async function resolveReport(id: string, action: "hide_post" | "hide_comment" | "dismiss" | "ban_user") {
    if (!requireAuth("/packageOps/pages/admin/index")) return;
    if (action === "ban_user") {
      const confirm = await Taro.showModal({ title: a.banUser, content: a.banConfirm });
      if (!confirm.confirm) return;
    }
    try {
      await vibeApi.adminResolveReport(id, action);
      setReports((prev) => prev.filter((r) => r.id !== id));
      Taro.showToast({ title: a.resolved, icon: "success" });
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  async function toggleFlag(key: string, enabled: boolean) {
    if (!requireAuth("/packageOps/pages/admin/index")) return;
    try {
      await vibeApi.adminToggleFlag(key, !enabled);
      setFlags((prev) => prev.map((f) => (f.key === key ? { ...f, enabled: !enabled } : f)));
    } catch {
      Taro.showToast({ title: a.updateFail, icon: "none" });
    }
  }

  async function grantCredits() {
    if (!requireAuth("/packageOps/pages/admin/index")) return;
    try {
      await vibeApi.adminGrantCredits({ email: grantEmail.trim(), amount: Number(grantAmount) || 0 });
      Taro.showToast({ title: a.grantSuccess, icon: "success" });
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  async function createTenant() {
    if (!requireAuth("/packageOps/pages/admin/index")) return;
    try {
      await vibeApi.adminCreateTenant({
        tenant_id: tenantId.trim(),
        name: tenantName.trim(),
        invite_code: tenantInvite.trim() || undefined,
        initial_credits: Number(tenantInitialCredits) || 0,
      });
      Taro.showToast({ title: a.grantSuccess, icon: "success" });
      setTenants(await vibeApi.adminTenants());
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  async function grantTenantPool() {
    if (!requireAuth("/packageOps/pages/admin/index") || !grantPoolTenantId.trim()) return;
    try {
      await vibeApi.adminGrantTenantPool(grantPoolTenantId.trim(), Number(grantPoolAmount) || 0);
      Taro.showToast({ title: a.grantSuccess, icon: "success" });
      setTenants(await vibeApi.adminTenants());
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  async function createChallenge() {
    if (!requireAuth("/packageOps/pages/admin/index")) return;
    try {
      await vibeApi.createChallenge({
        slug: chSlug.trim(),
        title: chTitle.trim(),
        hashtag: chHashtag.trim() || chSlug.trim(),
        prize_pool_credits: Number(chPrizePool) || 0,
        sponsor_label: chSponsor.trim() || undefined,
        duration_days: Number(chDuration) || 14,
      });
      Taro.showToast({ title: a.grantSuccess, icon: "success" });
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  async function distributePrizes() {
    if (!requireAuth("/packageOps/pages/admin/index") || !distributeChallengeId.trim()) return;
    try {
      await vibeApi.adminDistributeChallengePrizes(distributeChallengeId.trim());
      Taro.showToast({ title: a.grantSuccess, icon: "success" });
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  async function createPreset() {
    if (!requireAuth("/packageOps/pages/admin/index") || !presetId.trim() || !presetLabel.trim()) return;
    try {
      await vibeApi.adminCreatePreset({
        id: presetId.trim(),
        label: presetLabel.trim(),
        category: presetCategory.trim() || "scene",
        description: presetDescription.trim() || undefined,
        example_intent: presetExampleIntent.trim() || undefined,
      });
      Taro.showToast({ title: a.presetCreated, icon: "success" });
      setPresetId("");
      setPresetLabel("");
      setPresetExampleIntent("");
      setPresetDescription("");
      setStylePresets(await vibeApi.adminListPresets());
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  async function resolveTicket() {
    if (!requireAuth("/packageOps/pages/admin/index") || !resolveTicketId.trim()) return;
    try {
      await vibeApi.adminResolveSupportTicket(resolveTicketId.trim(), {
        resolution: resolveResolution,
        admin_note: resolveNote.trim() || undefined,
        credits_compensation: Number(resolveCredits) || 0,
        attempt_stripe_refund: resolveRefund,
      });
      Taro.showToast({ title: a.ticketResolved, icon: "success" });
      setResolveTicketId("");
      setResolveNote("");
      setResolveCredits("0");
      setResolveRefund(false);
      const res = await vibeApi.adminListSupportTickets();
      setTickets(res.tickets || []);
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  async function seedDefaults() {
    try {
      await vibeApi.adminSeed();
      Taro.showToast({ title: a.seedDone, icon: "success" });
    } catch {
      Taro.showToast({ title: a.actionFail, icon: "none" });
    }
  }

  if (process.env.TARO_ENV !== "h5") {
    return (
      <PageShell title={a.title} subtitle={a.h5Only} ambient>
        <Text className="typo-meta">{a.h5Only}</Text>
      </PageShell>
    );
  }

  if (!isLoggedIn()) {
    return (
      <PageShell title={a.title} subtitle={a.loginSubtitle} showCredits={false} ambient>
        <AuthBanner message={copy.settingsUi.authBanner} loginLabel={copy.loginUi.login} next="/packageOps/pages/admin/index" />
        <Button variant="primary" block className="auth-gate__cta" onClick={() => requireAuth("/packageOps/pages/admin/index")}>
          {copy.loginUi.login}
        </Button>
      </PageShell>
    );
  }

  if (isAdmin === false) {
    return (
      <PageShell title={a.title} subtitle={a.noPermission} showCredits={false} ambient>
        <Text className="typo-meta">{a.noPermission}</Text>
      </PageShell>
    );
  }

  if (isAdmin === null) {
    return (
      <PageShell title={a.title} subtitle={a.subtitle} wide ambient>
        <Text className="typo-meta">{copy.provenanceUi.loading}</Text>
      </PageShell>
    );
  }

  return (
    <PageShell title={a.title} subtitle={a.subtitle} wide ambient noPadTop showCredits={false}>
      <ChipGroup
        options={[
          { value: "settlement", label: a.tabSettlement },
          { value: "distribution", label: a.tabDistribution },
          { value: "stats", label: a.tabStats },
          { value: "commercial", label: a.tabCommercial },
          { value: "reports", label: a.tabReports },
          { value: "flags", label: a.tabFlags },
          { value: "tenants", label: a.tabTenants },
          { value: "challenges", label: a.tabChallenges },
          { value: "presets", label: a.tabPresets || "Presets" },
          { value: "activation", label: a.tabActivation },
          { value: "tickets", label: a.tabTickets },
          { value: "moderation", label: a.tabModeration },
          { value: "sync", label: a.tabSync },
          { value: "keys", label: a.tabKeys },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "commercial" && commercial && (
        <View className="admin-stats">
          <View className="admin-stat">
            <Text className="admin-stat__n">¥{commercial.billing_30d.revenue_yuan}</Text>
            <Text>{a.commercialGmv}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">¥{commercial.billing_30d.mrr_yuan ?? 0}</Text>
            <Text>{a.commercialMrr}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">¥{commercial.billing_30d.ltv_estimate_yuan ?? 0}</Text>
            <Text>{a.commercialLtv}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">{commercial.billing_30d.active_subscriptions ?? 0}</Text>
            <Text>{a.commercialActiveSubs}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">{commercial.billing_30d.churned_subscriptions ?? 0}</Text>
            <Text>{a.commercialChurn}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">{commercial.billing_30d.paid_orders}</Text>
            <Text>{a.commercialOrders}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">{commercial.total_credits_spent}</Text>
            <Text>{a.commercialSpent}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">{commercial.users}</Text>
            <Text>{a.commercialUsers}</Text>
          </View>
          {"duel_starts_count" in commercial && (
            <View className="admin-stat">
              <Text className="admin-stat__n">{commercial.duel_starts_count}</Text>
              <Text>{a.duelStarts}</Text>
            </View>
          )}
        </View>
      )}
      {tab === "commercial" && commercial && (
        <>
          <Text className="typo-meta">{a.packDistribution}</Text>
          {Object.entries(commercial.pack_distribution).map(([pid, count]) => (
            <View key={pid} className="admin-row">
              <Text>{pid}</Text>
              <Text className="typo-meta">{count}</Text>
            </View>
          ))}
          <Text className="typo-meta">{a.grantSources}</Text>
          {Object.entries(commercial.credit_grants_by_source).map(([src, total]) => (
            <View key={src} className="admin-row">
              <Text>{src}</Text>
              <Text className="typo-meta">+{total}</Text>
            </View>
          ))}
          {commercial.conversion_funnel_30d && (
            <>
              <Text className="typo-meta admin-funnel__title">{a.funnelTitle}</Text>
              <View className="admin-funnel">
                {(
                  [
                    ["registered", a.funnelRegistered],
                    ["first_generate", a.funnelGenerate],
                    ["work_published", a.funnelPublish],
                    ["402_insufficient", a.funnel402],
                    ["paywall_view", a.funnelPaywall],
                    ["paywall_purchase_start", a.funnelPaywallBuy],
                    ["payment_start", a.funnelPayStart],
                    ["payment_success", a.funnelPaySuccess],
                  ] as const
                ).map(([key, label]) => (
                  <View key={key} className="admin-funnel__row">
                    <Text className="admin-funnel__label">{label}</Text>
                    <Text className="admin-funnel__n">{commercial.conversion_funnel_30d[key] ?? 0}</Text>
                  </View>
                ))}
              </View>
            </>
          )}
          <Text className="typo-meta admin-funnel__title">{a.waitlistTitle}</Text>
          {waitlist.length === 0 && <Text className="typo-meta">{a.ticketEmpty}</Text>}
          {waitlist.map((w) => (
            <View key={`${w.user_id}-${w.channel}`} className="admin-row">
              <Text>{w.email || w.user_id}</Text>
              <Text className="typo-meta">
                {a.waitlistChannel}: {w.channel}
                {w.created_at ? ` · ${w.created_at.slice(0, 10)}` : ""}
              </Text>
            </View>
          ))}
        </>
      )}
      {tab === "commercial" && (
        <>
          <Text className="typo-meta admin-funnel__title">{a.effectPacksTitle}</Text>
          {pendingPacks.length === 0 && <Text className="typo-meta">{a.effectPacksEmpty}</Text>}
          {pendingPacks.map((pack) => (
            <View key={pack.id} className="admin-row">
              <Text>{pack.title}</Text>
              <Text className="typo-meta">
                {pack.author_username || ""} · {pack.price_credits} · {pack.status}
              </Text>
              <View className="admin-row__actions">
                <Button
                  size="sm"
                  variant="secondary"
                  loading={packBusy === `${pack.id}-published`}
                  onClick={async () => {
                    setPackBusy(`${pack.id}-published`);
                    try {
                      await vibeApi.reviewEffectPack(pack.id, "published");
                      setPendingPacks((prev) => prev.filter((row) => row.id !== pack.id));
                    } catch {
                      Taro.showToast({ title: a.actionFail, icon: "none" });
                    } finally {
                      setPackBusy("");
                    }
                  }}
                >
                  {a.effectPackPublish}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  loading={packBusy === `${pack.id}-rejected`}
                  onClick={async () => {
                    setPackBusy(`${pack.id}-rejected`);
                    try {
                      await vibeApi.reviewEffectPack(pack.id, "rejected");
                      setPendingPacks((prev) => prev.filter((row) => row.id !== pack.id));
                    } catch {
                      Taro.showToast({ title: a.actionFail, icon: "none" });
                    } finally {
                      setPackBusy("");
                    }
                  }}
                >
                  {a.effectPackReject}
                </Button>
              </View>
            </View>
          ))}
        </>
      )}

      {tab === "stats" && stats && (
        <View className="admin-stats">
          <View className="admin-stat">
            <Text className="admin-stat__n">{stats.users}</Text>
            <Text>{a.users}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">{stats.works}</Text>
            <Text>{a.works}</Text>
          </View>
          <View className="admin-stat">
            <Text className="admin-stat__n">{stats.jobs}</Text>
            <Text>{a.jobs}</Text>
          </View>
        </View>
      )}
      {tab === "stats" && usage && (
        <Text className="typo-meta" style={{ marginTop: "16rpx", display: "block" }}>
          {a.usageSummary}{JSON.stringify(usage).slice(0, 120)}…
        </Text>
      )}

      {tab === "reports" &&
        reports.map((r) => (
          <View key={r.id} className="admin-row">
            <View>
              <Text>{r.reason}</Text>
              {r.comment_preview ? (
                <Text className="admin-row__status">{r.comment_preview}</Text>
              ) : null}
            </View>
            <Text className="admin-row__status">{r.status}</Text>
            {r.comment_id ? (
              <Button size="sm" variant="danger" onClick={() => resolveReport(r.id, "hide_comment")}>
                {a.hideComment}
              </Button>
            ) : r.post_id ? (
              <Button size="sm" variant="danger" onClick={() => resolveReport(r.id, "hide_post")}>
                {a.hidePost}
              </Button>
            ) : null}
            <Button size="sm" variant="danger" onClick={() => resolveReport(r.id, "ban_user")}>
              {a.banUser}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => resolveReport(r.id, "dismiss")}>
              {a.dismissReport}
            </Button>
          </View>
        ))}

      {tab === "flags" &&
        flags.map((f) => (
          <View key={f.key} className="admin-row">
            <View>
              <Text className="admin-row__key">{f.key}</Text>
              {f.description && <Text className="admin-row__desc">{f.description}</Text>}
            </View>
            <Button size="sm" variant="secondary" onClick={() => toggleFlag(f.key, f.enabled)}>
              {f.enabled ? a.toggleOff : a.toggleOn}
            </Button>
          </View>
        ))}

      {tab === "tenants" && (
        <>
          {tenants.map((tn) => (
            <View key={tn.tenant_id} className="admin-row">
              <Text>{tn.tenant_id}</Text>
              <Text className="admin-row__status">
                {tn.users} users · {tn.works} works · {tn.posts} posts
              </Text>
            </View>
          ))}
          <Input label={a.tenantId} value={tenantId} onInput={(e) => setTenantId(e.detail.value)} />
          <Input label={a.tenantName} value={tenantName} onInput={(e) => setTenantName(e.detail.value)} />
          <Input label={a.tenantInvite} value={tenantInvite} onInput={(e) => setTenantInvite(e.detail.value)} />
          <Input label={a.tenantInitialCredits} value={tenantInitialCredits} onInput={(e) => setTenantInitialCredits(e.detail.value)} />
          <Button variant="primary" block onClick={createTenant}>
            {a.createTenant}
          </Button>
          <Input label={a.tenantId} value={grantPoolTenantId} onInput={(e) => setGrantPoolTenantId(e.detail.value)} />
          <Input label={a.grantPoolAmount} value={grantPoolAmount} onInput={(e) => setGrantPoolAmount(e.detail.value)} />
          <Button variant="secondary" block onClick={grantTenantPool}>
            {a.grantCredits}
          </Button>
          <Input label={a.grantEmail} value={grantEmail} onInput={(e) => setGrantEmail(e.detail.value)} />
          <Input label={a.grantAmount} value={grantAmount} onInput={(e) => setGrantAmount(e.detail.value)} />
          <Button variant="primary" block onClick={grantCredits}>
            {a.grantCredits}
          </Button>
          {debugOn ? (
            <Button variant="ghost" block onClick={seedDefaults}>
              {a.seedDev}
            </Button>
          ) : null}
        </>
      )}

      {tab === "challenges" && (
        <>
          <Input label={a.challengeSlug} value={chSlug} onInput={(e) => setChSlug(e.detail.value)} />
          <Input label={a.challengeTitle} value={chTitle} onInput={(e) => setChTitle(e.detail.value)} />
          <Input label={a.challengeHashtag} value={chHashtag} onInput={(e) => setChHashtag(e.detail.value)} />
          <Input label={a.challengeSponsor} value={chSponsor} onInput={(e) => setChSponsor(e.detail.value)} />
          <Input label={a.prizePoolCredits} value={chPrizePool} onInput={(e) => setChPrizePool(e.detail.value)} />
          <Input label={a.challengeDurationDays} value={chDuration} onInput={(e) => setChDuration(e.detail.value)} />
          <Button variant="primary" block onClick={createChallenge}>
            {a.createChallenge}
          </Button>
          <Input label="Challenge ID" value={distributeChallengeId} onInput={(e) => setDistributeChallengeId(e.detail.value)} />
          <Button variant="secondary" block onClick={distributePrizes}>
            {a.distributePrizes}
          </Button>
        </>
      )}

      {tab === "presets" && (
        <>
          <Input label={a.presetId} value={presetId} onInput={(e) => setPresetId(e.detail.value)} />
          <Input label={a.presetLabel} value={presetLabel} onInput={(e) => setPresetLabel(e.detail.value)} />
          <Input label={a.presetCategory} value={presetCategory} onInput={(e) => setPresetCategory(e.detail.value)} />
          <Input label={a.presetExampleIntent} value={presetExampleIntent} onInput={(e) => setPresetExampleIntent(e.detail.value)} />
          <Input label={a.presetDescription} value={presetDescription} onInput={(e) => setPresetDescription(e.detail.value)} />
          <Button variant="primary" block onClick={createPreset}>
            {a.createPreset}
          </Button>
          {stylePresets.map((p) => (
            <View key={p.id} className="admin-row">
              <View>
                <Text className="admin-row__key">{p.label}</Text>
                <Text className="admin-row__desc">{p.id} · {p.category}</Text>
              </View>
              <Button
                size="sm"
                variant="secondary"
                disabled={!p.enabled}
                onClick={async () => {
                  try {
                    await vibeApi.adminDisablePreset(p.id);
                    setStylePresets(await vibeApi.adminListPresets());
                  } catch {
                    Taro.showToast({ title: a.actionFail, icon: "none" });
                  }
                }}
              >
                {p.enabled ? a.toggleOff : "Disabled"}
              </Button>
            </View>
          ))}
          {debugOn ? (
            <Button variant="ghost" block onClick={seedDefaults}>
              {a.seedDev}
            </Button>
          ) : null}
        </>
      )}

      {tab === "activation" && activationFunnel && (
        <View className="admin-stats">
          <Text className="typo-meta">{a.activationFunnel.replace("{days}", String(activationFunnel.period_days))}</Text>
          {(
            [
              ["new_registrations", a.funnelRegistered, null],
              ["preset_selected", "选预设", "new_registrations"],
              ["first_generate_start", a.funnelGenerate, "preset_selected"],
              ["first_generate_complete", "首曲完成", "first_generate_start"],
              ["first_listen", "首次试听", "first_generate_complete"],
              ["first_publish", a.funnelPublish, "first_listen"],
            ] as const
          ).map(([key, label, prevKey]) => {
            const count = activationFunnel[key as keyof typeof activationFunnel] as number;
            const prev = prevKey
              ? (activationFunnel[prevKey as keyof typeof activationFunnel] as number)
              : activationFunnel.new_registrations;
            const pct = prev > 0 ? Math.round((count / prev) * 100) : 0;
            return (
              <View key={key} className="admin-funnel__row">
                <Text className="admin-funnel__label">{label}</Text>
                <Text className="admin-funnel__n">
                  {count}
                  {prevKey ? ` · ${pct}%` : ""}
                </Text>
              </View>
            );
          })}
          <Text className="typo-meta" style={{ marginTop: "24rpx" }}>
            {a.auditLogs}
          </Text>
          {auditLogs.map((log) => (
            <View key={log.id} className="admin-row">
              <Text>{log.action}</Text>
              <Text className="typo-meta">{log.target || ""}</Text>
            </View>
          ))}
        </View>
      )}

      {tab === "tickets" && (
        <>
          {tickets.length === 0 && <Text className="typo-meta">{a.ticketEmpty}</Text>}
          {tickets.map((t) => (
            <View key={t.id} className="admin-row admin-row--ticket">
              <View>
                <Text className="admin-row__key">{t.subject}</Text>
                <Text className="admin-row__desc">
                  {t.user_email || "—"} · {t.category} · {t.status}
                </Text>
                {t.order_id && <Text className="typo-meta">{a.ticketOrder}: {t.order_id}</Text>}
                <Text className="typo-meta">{t.body.slice(0, 160)}{t.body.length > 160 ? "…" : ""}</Text>
              </View>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setResolveTicketId(t.id);
                  setResolveResolution(t.category === "refund" ? "stripe_refunded" : "approved");
                  setResolveRefund(t.category === "refund");
                }}
              >
                {a.ticketResolve}
              </Button>
            </View>
          ))}
          <Input label="Ticket ID" value={resolveTicketId} onInput={(e) => setResolveTicketId(e.detail.value)} />
          <ChipGroup
            options={[
              { value: "approved", label: a.resolutionApproved },
              { value: "rejected", label: a.resolutionRejected },
              { value: "credits_granted", label: a.resolutionCredits },
              { value: "stripe_refunded", label: a.resolutionRefunded },
            ]}
            value={resolveResolution}
            onChange={(v) => setResolveResolution(v as typeof resolveResolution)}
          />
          <Input label={a.ticketCredits} value={resolveCredits} onInput={(e) => setResolveCredits(e.detail.value)} />
          <Input label={a.ticketNote} value={resolveNote} onInput={(e) => setResolveNote(e.detail.value)} />
          <Button variant="ghost" block onClick={() => setResolveRefund((v) => !v)}>
            {resolveRefund ? `✓ ${a.ticketRefund}` : a.ticketRefund}
          </Button>
          <Button variant="primary" block onClick={resolveTicket}>
            {a.ticketResolve}
          </Button>
        </>
      )}

      {tab === "moderation" && (
        <>
          <Input label={a.userSearch} value={userQuery} onInput={(e) => setUserQuery(e.detail.value)} />
          <Button
            variant="secondary"
            block
            onClick={async () => {
              try {
                const rows = await vibeApi.adminListUsers(userQuery.trim() || undefined);
                setUserHits(rows.users || []);
              } catch {
                Taro.showToast({ title: a.actionFail, icon: "none" });
              }
            }}
          >
            {a.userSearch}
          </Button>
          {userHits.map((row) => (
            <View key={row.id} className="admin-row">
              <View>
                <Text className="admin-row__key">{row.email || row.username}</Text>
                <Text className="admin-row__desc">{row.is_active === false ? a.banned : row.kyc_status || ""}</Text>
              </View>
              <Button
                size="sm"
                variant={row.is_active === false ? "secondary" : "danger"}
                onClick={async () => {
                  try {
                    if (row.is_active !== false) {
                      const confirm = await Taro.showModal({ title: a.banUser, content: a.banConfirm });
                      if (!confirm.confirm) return;
                      await vibeApi.adminBanUser(row.id);
                    } else {
                      await vibeApi.adminUnbanUser(row.id);
                    }
                    const rows = await vibeApi.adminListUsers(userQuery.trim() || undefined);
                    setUserHits(rows.users || []);
                    Taro.showToast({ title: row.is_active === false ? a.unbanOk : a.banOk, icon: "success" });
                  } catch {
                    Taro.showToast({ title: a.actionFail, icon: "none" });
                  }
                }}
              >
                {row.is_active === false ? a.unbanUser : a.banUser}
              </Button>
            </View>
          ))}
          <Input label={a.modPattern} value={modPattern} onInput={(e) => setModPattern(e.detail.value)} />
          <ChipGroup
            options={[
              { value: "block", label: a.modLevelBlock },
              { value: "mask", label: a.modLevelMask },
            ]}
            value={modLevel}
            onChange={(v) => setModLevel(v as "block" | "mask")}
          />
          <Button
            variant="primary"
            block
            onClick={async () => {
              if (!modPattern.trim()) return;
              try {
                await vibeApi.adminCreateModerationWord({ pattern: modPattern.trim(), level: modLevel });
                setModPattern("");
                const rows = await vibeApi.adminListModerationWords();
                setModWords(rows);
                Taro.showToast({ title: a.modAdded, icon: "success" });
              } catch {
                Taro.showToast({ title: a.actionFail, icon: "none" });
              }
            }}
          >
            {a.modAdd}
          </Button>
          {modWords.map((w) => (
            <View key={w.id} className="admin-row">
              <Text>
                {w.pattern} · {w.level}
              </Text>
              <Button
                size="sm"
                variant="ghost"
                onClick={async () => {
                  try {
                    await vibeApi.adminDeleteModerationWord(w.id);
                    setModWords((prev) => prev.filter((x) => x.id !== w.id));
                  } catch {
                    Taro.showToast({ title: a.actionFail, icon: "none" });
                  }
                }}
              >
                {a.modDisable}
              </Button>
            </View>
          ))}
        </>
      )}

      {tab === "distribution" && (
        <>
          <View className="admin-tabs">
            <Button
              size="sm"
              variant={queueOnly ? "primary" : "ghost"}
              onClick={() => {
                setQueueOnly(true);
                vibeApi.adminDistributionQueue().then((r) => setDeliveries((r.deliveries || []) as typeof deliveries)).catch(() => {});
              }}
            >
              {a.queueFilter}
            </Button>
            <Button
              size="sm"
              variant={!queueOnly ? "primary" : "ghost"}
              onClick={() => {
                setQueueOnly(false);
                vibeApi.adminDistributionDeliveries().then((r) => setDeliveries((r.deliveries || []) as typeof deliveries)).catch(() => {});
              }}
            >
              {a.allDeliveries}
            </Button>
            <Button size="sm" variant={overdueOnly ? "primary" : "ghost"} onClick={() => setOverdueOnly((on) => !on)}>
              {a.overdueFilter}
            </Button>
          </View>
          {distHealth && (
            <Text className="admin-row__desc">
              {`${a.distributionHealth} · ${a.opsQueue} ${distHealth.ops_queue || 0} · ${a.sessionWait} ${distHealth.session_wait || 0} · ${a.sessionRunning} ${distHealth.session_running || 0} · ${a.slaOverdueCount.replace("{n}", String(distHealth.sla_overdue || 0))} · ${a.submittingCount.replace("{n}", String(distHealth.submitting || 0))} · ${a.staleSubmitting.replace("{n}", String(distHealth.stale_submitting || 0))} · ${a.emptyQueued.replace("{n}", String(distHealth.queued_without_deliveries || 0))} · partners ${distHealth.partner_count || 0}`}
            </Text>
          )}
          <Button
            variant="primary"
            block
            onClick={async () => {
              try {
                await vibeApi.adminReconcileDistribution();
                const [health, queue] = await Promise.all([
                  vibeApi.adminDistributionHealth(),
                  queueOnly ? vibeApi.adminDistributionQueue() : vibeApi.adminDistributionDeliveries(),
                ]);
                setDistHealth(health);
                setDeliveries((queue.deliveries || []) as typeof deliveries);
                Taro.showToast({ title: a.reconciled, icon: "success" });
              } catch {
                Taro.showToast({ title: a.actionFail, icon: "none" });
              }
            }}
          >
            {a.reconcileNow}
          </Button>
          <Text className="admin-row__key">{a.opsDaily}</Text>
          {opsDigest && (
            <View className="admin-tabs">
              {(
                [
                  ["u", opsDigest.actionable?.unmatched_claims, a.unmatchedClaims],
                  ["h", opsDigest.actionable?.harvest_unmatched, a.harvestUnmatched],
                  ["n", opsDigest.actionable?.unattached_snapshots, a.unattachedSnapshots],
                  ["s", opsDigest.actionable?.selector_broke, a.farmHealth],
                  ["l", opsDigest.actionable?.login_wall_seats, a.sessionWait],
                  ["o", opsDigest.actionable?.sla_overdue, a.overdueFilter],
                  ["x", opsDigest.actionable?.session_expired, a.sessionExpired],
                  ["f", opsDigest.actionable?.harvest_failed, a.harvestFailed],
                  ["t", opsDigest.actionable?.patrol_failed, a.patrolFailed],
                  ["p", opsDigest.actionable?.pending_payouts, a.withdrawalsTitle],
                  ["k", opsDigest.actionable?.pending_kyc, a.kycQueue],
                  ["d", opsDigest.actionable?.settlement_drafts, a.fridaySettlementDrafts],
                  ["i", opsDigest.actionable?.pending_invoices, a.syncPending],
                ] as const
              ).map(([id, count, label]) => (
                <Button
                  key={id}
                  size="sm"
                  variant={count ? "secondary" : "ghost"}
                  onClick={() => {
                    if (id === "i") setTab("sync");
                    else if (id === "p" || id === "k" || id === "d") setTab("settlement");
                    else setTab("distribution");
                    if (id === "o") setOverdueOnly(true);
                    if (id === "u" || id === "s" || id === "l" || id === "x" || id === "f") setQueueOnly(true);
                    if (id === "h" || id === "n") setQueueOnly(false);
                    const anchors: Record<string, string> = {
                      u: "ops-anchor-claims",
                      h: "ops-anchor-harvest",
                      n: "ops-anchor-unattached",
                      s: "ops-anchor-farm",
                      l: "ops-anchor-farm",
                      o: "ops-anchor-queue",
                      x: "ops-anchor-farm",
                      f: "ops-anchor-farm",
                      t: "ops-anchor-farm",
                      p: "ops-anchor-payouts",
                      k: "ops-anchor-kyc",
                    };
                    const anchor = anchors[id];
                    setTimeout(() => {
                      if (typeof document !== "undefined" && anchor) {
                        document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
                      }
                    }, 80);
                    Taro.showToast({
                      title: `${label} · ${count || 0}`,
                      icon: "none",
                    });
                  }}
                >
                  {`${label} ${count || 0}`}
                </Button>
              ))}
            </View>
          )}
          {opsDigest?.friday_queue && (
            <View className="admin-row admin-row--stack">
              <Text className="admin-row__key">
                {a.fridayQueueTitle.replace("{n}", String(opsDigest.friday_total || 0))}
              </Text>
              <Text className="admin-row__desc">{a.fridayQueueHint}</Text>
              <Text className="admin-row__desc">{a.fridayQueueWho}</Text>
              <Text className="admin-row__desc">
                {`${a.fridaySettlementDrafts} ${opsDigest.friday_queue.settlement_drafts || 0}`}
                {` · ${a.syncPending} ${opsDigest.friday_queue.pending_invoices || 0}`}
                {` · ${a.kycQueue} ${opsDigest.friday_queue.pending_kyc || 0}`}
                {` · ${a.fridayPayoutReceipts} ${opsDigest.friday_queue.pending_payouts || 0}`}
              </Text>
              <View className="admin-tabs">
                <Button size="sm" variant="secondary" onClick={() => setTab("settlement")}>
                  {a.tabSettlement}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setTab("sync")}>
                  {a.syncPending}
                </Button>
              </View>
            </View>
          )}
          <Text id="ops-anchor-farm" className="admin-row__key">{a.farmHealth}</Text>
          <Text className="admin-row__desc">{`queued ${farmHealth?.queued || 0} · failed ${farmHealth?.failed || 0} · ${a.selectorBroke.replace("{n}", String(farmHealth?.selector_broke || 0))} · ${a.loginWall.replace("{n}", String(farmHealth?.login_wall || 0))} · ${a.patrolFailed} ${farmHealth?.patrol_failed || 0}`}</Text>
          {(farmHealth?.seats || []).slice(0, 12).map((seat) => (
            <View key={`${seat.ownership}-${seat.channel_code}`} className="admin-row admin-row--stack">
              <Text className="admin-row__key">{`${seat.channel_code} · ${seat.ownership}`}</Text>
              <Text className="admin-row__desc">
                {`${seat.status || "—"} · rows ${seat.farm_health?.matched ?? seat.farm_health?.rows ?? 0} · ${seat.farm_health?.elapsed_ms || 0}ms${seat.farm_health?.session_expired ? " · expired" : ""}`}
              </Text>
              {seat.playbook_health ? (
                <View className="admin-row admin-row--stack">
                  <Text className="admin-row__desc">
                    {a.healHint}
                    {seat.playbook_health.ok ? "" : ` · ${(seat.playbook_health.issues || []).join(" / ")}`}
                  </Text>
                  {(seat.playbook_health.statsUrls || []).slice(0, 4).map((url) => (
                    <Button
                      key={url}
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        void Taro.setClipboardData({ data: url });
                        Taro.showToast({ title: a.healCopied, icon: "none" });
                      }}
                    >
                      {url}
                    </Button>
                  ))}
                  {(seat.playbook_health.alternateSelectors || []).slice(0, 4).map((sel) => (
                    <Button
                      key={sel}
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        void Taro.setClipboardData({ data: sel });
                        Taro.showToast({ title: a.healCopied, icon: "none" });
                      }}
                    >
                      {sel}
                    </Button>
                  ))}
                </View>
              ) : null}
            </View>
          ))}
          <Text id="ops-anchor-harvest" className="admin-row__key">{a.harvestUnmatched}</Text>
          {harvestUnmatched.map((row) => (
            <View key={row.id} className="admin-row admin-row--stack">
              <View>
                <Text className="admin-row__key">{row.title || row.channel_code}</Text>
                <Text className="admin-row__desc">{`${row.channel_code} · ${row.period_key} · ${row.streams || 0} · ${((row.revenue_minor || 0) / 100).toFixed(2)}`}</Text>
              </View>
              <Input
                label={a.attachHarvest}
                value={harvestWorkIds[row.id] || ""}
                onInput={(e) => setHarvestWorkIds((prev) => ({ ...prev, [row.id]: e.detail.value }))}
              />
              <Button
                size="sm"
                variant="secondary"
                onClick={async () => {
                  const workId = (harvestWorkIds[row.id] || "").trim();
                  if (!workId) return;
                  try {
                    await vibeApi.adminAttachHarvestUnmatched(row.id, workId);
                    const r = await vibeApi.adminHarvestUnmatched();
                    setHarvestUnmatched((r.rows || []) as typeof harvestUnmatched);
                  } catch {
                    Taro.showToast({ title: a.actionFail, icon: "none" });
                  }
                }}
              >
                {a.attachHarvest}
              </Button>
            </View>
          ))}
          <Button
            variant="secondary"
            block
            onClick={() => {
              if (process.env.TARO_ENV !== "h5") return;
              const input = document.createElement("input");
              input.type = "file";
              input.accept = ".csv,text/csv";
              input.onchange = async () => {
                const file = input.files?.[0];
                if (!file) return;
                try {
                  const imported = (await vibeApi.adminImportReport(file)) as { skipped_no_isrc?: number; draft_batches?: Array<{ lines?: number }> };
                  const [inbox, unmatched, preview] = await Promise.all([
                    vibeApi.adminRoyaltyReports(),
                    vibeApi.adminUnmatchedOfficial(),
                    vibeApi.adminSettlementPreview(),
                  ]);
                  setReportInbox((inbox.imports || []) as typeof reportInbox);
                  setOfficialUnmatched((unmatched.snapshots || []) as typeof officialUnmatched);
                  setSettlementPreview(preview);
                  const drafts = (imported.draft_batches || []).reduce((sum, row) => sum + Number(row.lines || 0), 0);
                  Taro.showToast({
                    title: drafts
                      ? a.draftCreated.replace("{n}", String(drafts))
                      : imported.skipped_no_isrc
                        ? a.isrcUnmatchedTitle
                        : a.importReport,
                    icon: "success",
                  });
                } catch {
                  Taro.showToast({ title: a.actionFail, icon: "none" });
                }
              };
              input.click();
            }}
          >
            {a.importReport}
          </Button>
          <Button
            variant="ghost"
            block
            onClick={async () => {
              try {
                const res = (await vibeApi.adminSyncAnalytics()) as {
                  youtube?: { synced?: number; reason?: string };
                  licensed?: { synced?: number; reason?: string };
                };
                const yt = Number(res.youtube?.synced || 0);
                const cm = Number(res.licensed?.synced || 0);
                setSyncNote(
                  `${a.syncYoutubeCount.replace("{n}", String(yt))} · ${a.syncLicensedCount.replace("{n}", String(cm))}`,
                );
                Taro.showToast({ title: a.syncAnalytics, icon: "success" });
              } catch {
                Taro.showToast({ title: a.actionFail, icon: "none" });
              }
            }}
          >
            {a.syncAnalytics}
          </Button>
          {syncNote && <Text className="admin-row__desc">{syncNote}</Text>}
          {partners && (
            <>
              <Text className="admin-row__key">{a.partnerPayeeTitle}</Text>
              <Text className="admin-row__desc">{partners.note || a.partnerPayeeHint}</Text>
              {(partners.partners || []).map((row) => (
                <View key={row.code} className="admin-row">
                  <View>
                    <Text className="admin-row__key">{`${row.name || row.code} · ${row.region || ""}`}</Text>
                    <Text className="admin-row__desc">
                      {row.configured ? a.partnerReady : a.partnerNotReady}
                      {` · ${row.settlement_path === "partner_api" ? a.partnerReady : a.partnerCsvPath}`}
                    </Text>
                  </View>
                </View>
              ))}
            </>
          )}
          {reportInbox.length > 0 && (
            <>
              <Text className="admin-row__key">{a.reportInbox}</Text>
              {reportInbox.slice(0, 8).map((row) => (
                <View key={row.id} className="admin-row">
                  <View>
                    <Text className="admin-row__key">{row.filename || row.source}</Text>
                    <Text className="admin-row__desc">
                      {`${row.source || ""} · ${row.status || ""} · ${row.row_count || 0}`}
                      {row.skipped_no_isrc ? ` · ${a.isrcUnmatchedTitle} ${row.skipped_no_isrc}` : ""}
                    </Text>
                  </View>
                </View>
              ))}
            </>
          )}
          {officialUnmatched.length > 0 && (
            <>
              <Text id="ops-anchor-unattached" className="admin-row__key">{a.isrcUnmatchedTitle}</Text>
              <Text className="admin-row__desc">{a.isrcUnmatchedHint}</Text>
              {officialUnmatched.slice(0, 12).map((row) => (
                <View key={row.id} className="admin-row admin-row--stack">
                  <Text className="admin-row__key">{row.title || row.isrc || row.id}</Text>
                  <Text className="admin-row__desc">
                    {`${row.channel_code || ""} · ${row.period_key || ""} · ${row.reason === "no_isrc" ? a.isrcReasonNone : a.isrcReasonMismatch}`}
                    {row.work_title ? ` · ${row.work_title}` : ""}
                  </Text>
                  <Input
                    value={attachWorkIds[row.id] || ""}
                    placeholder={a.attachOfficial}
                    onInput={(e) => setAttachWorkIds((prev) => ({ ...prev, [row.id]: e.detail.value }))}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={async () => {
                      const workId = (attachWorkIds[row.id] || row.suggested_work_id || row.work_id || "").trim();
                      if (!workId) return;
                      try {
                        const attached = (await vibeApi.adminAttachOfficialSnapshot(row.id, workId)) as {
                          usable_for_settlement?: boolean;
                          draft_batches?: Array<{ lines?: number }>;
                        };
                        const [unmatched, preview] = await Promise.all([
                          vibeApi.adminUnmatchedOfficial(),
                          vibeApi.adminSettlementPreview(),
                        ]);
                        setOfficialUnmatched((unmatched.snapshots || []) as typeof officialUnmatched);
                        setSettlementPreview(preview);
                        const drafts = (attached.draft_batches || []).reduce((sum, item) => sum + Number(item.lines || 0), 0);
                        Taro.showToast({
                          title: drafts
                            ? a.draftCreated.replace("{n}", String(drafts))
                            : attached.usable_for_settlement
                              ? a.attachOfficial
                              : a.isrcReasonMismatch,
                          icon: drafts || attached.usable_for_settlement ? "success" : "none",
                        });
                      } catch {
                        Taro.showToast({ title: a.actionFail, icon: "none" });
                      }
                    }}
                  >
                    {a.attachOfficial}
                  </Button>
                </View>
              ))}
            </>
          )}
          {workbench && workbenchId && (
            <View className="admin-row admin-row--stack">
              <Text className="admin-row__key">{a.workbenchTitle}</Text>
              {workbench.cover_url ? <Image src={workbench.cover_url} mode="aspectFill" style={{ width: "100%", height: "160px" }} /> : null}
              <Text className="admin-row__desc">
                {String(workbench.metadata?.title || "")}
                {workbench.metadata?.artist_name ? ` · ${String(workbench.metadata.artist_name)}` : ""}
                {workbench.metadata?.isrc ? ` · ISRC ${String(workbench.metadata.isrc)}` : ""}
                {workbench.metadata?.upc ? ` · UPC ${String(workbench.metadata.upc)}` : ""}
              </Text>
              {(workbench.handoff || []).map((line) => (
                <Text key={line.field || line.label} className="admin-row__desc">
                  {line.label}：{line.filled ? line.value : "（空）"}
                </Text>
              ))}
              <Text className="admin-row__desc">
                {workbench.sla_overdue
                  ? a.slaOverdue
                  : workbench.sla_due_at
                    ? a.slaDue.replace("{t}", String(workbench.sla_due_at).slice(0, 16).replace("T", " "))
                    : a.slaEta.replace("{h}", String(workbench.sla_hours || 48))}
              </Text>
              <AssetLanes
                density="compact"
                status={workbench.asset_status}
                onDownloadOriginality={
                  workbench.originality_zip_url
                    ? () => {
                        if (process.env.TARO_ENV === "h5") window.open(workbench.originality_zip_url, "_blank");
                      }
                    : undefined
                }
                onDownloadClips={
                  workbench.clip_pack_url
                    ? () => {
                        if (process.env.TARO_ENV === "h5") window.open(workbench.clip_pack_url, "_blank");
                      }
                    : undefined
                }
              />
              {(workbench.ops_steps || []).map((step) => (
                <Text key={step} className="admin-row__desc">
                  {step}
                </Text>
              ))}
              {(workbench.clip_windows || []).map((clip) => (
                <Text key={`${clip.length}-${clip.start}`} className="admin-row__desc">
                  {`${clip.length}s · ${clip.start}–${clip.end}`}
                </Text>
              ))}
              {workbench.kit_url && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    if (process.env.TARO_ENV === "h5") window.open(workbench.kit_url, "_blank");
                  }}
                >
                  {a.opsKit}
                </Button>
              )}
              {workbench.clip_pack_url && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (process.env.TARO_ENV === "h5") window.open(workbench.clip_pack_url, "_blank");
                  }}
                >
                  {a.downloadClipPack}
                </Button>
              )}
              {workbench.originality_zip_url && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (process.env.TARO_ENV === "h5") window.open(workbench.originality_zip_url, "_blank");
                  }}
                >
                  {a.downloadOriginality}
                </Button>
              )}
              {workbench.cover_url && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    Taro.setClipboardData({ data: workbench.cover_url || "" });
                    Taro.showToast({ title: a.copyCover, icon: "success" });
                  }}
                >
                  {a.copyCover}
                </Button>
              )}
            </View>
          )}
          <View id="ops-anchor-queue" />
          {Array.from(
            deliveries
              .reduce((map, d) => {
                const key = d.release_id || d.id;
                const list = map.get(key) || [];
                list.push(d);
                map.set(key, list);
                return map;
              }, new Map<string, typeof deliveries>())
              .entries(),
          )
            .filter(([, rows]) => !overdueOnly || rows.some((d) => d.sla_overdue || d.sla_escalated))
            .sort((a, b) => {
              const aHot = a[1].some((d) => d.sla_overdue || d.sla_escalated) ? 1 : 0;
              const bHot = b[1].some((d) => d.sla_overdue || d.sla_escalated) ? 1 : 0;
              if (aHot !== bHot) return bHot - aHot;
              return (
                Math.max(...b[1].map((d) => d.priority_score || 0)) - Math.max(...a[1].map((d) => d.priority_score || 0))
              );
            })
            .map(([releaseId, rows]) => (
            <View key={releaseId} className="admin-row admin-row--stack">
              <View>
                <Text className="admin-row__key">{rows[0]?.title || a.releaseGroup}</Text>
                <Text className="admin-row__desc">{`${a.releaseGroup} · ${rows.length}`}</Text>
              </View>
              <Button
                size="sm"
                variant="secondary"
                onClick={async () => {
                  if (workbenchId === releaseId) {
                    setWorkbenchId("");
                    setWorkbench(null);
                    return;
                  }
                  try {
                    const wb = await vibeApi.adminReleaseWorkbench(releaseId);
                    setWorkbenchId(releaseId);
                    setWorkbench(wb);
                  } catch {
                    Taro.showToast({ title: a.actionFail, icon: "none" });
                  }
                }}
              >
                {workbenchId === releaseId ? a.closeWorkbench : a.openWorkbench}
              </Button>
              <Button
                size="sm"
                variant="primary"
                onClick={async () => {
                  try {
                    const marked = await vibeApi.adminMarkReleaseLive(releaseId);
                    const r = await vibeApi.adminDistributionDeliveries();
                    setDeliveries((r.deliveries || []) as typeof deliveries);
                    if (!Number(marked?.updated || 0)) {
                      Taro.showToast({ title: a.liveNeedsReceipt, icon: "none" });
                      return;
                    }
                  } catch {
                    Taro.showToast({ title: a.actionFail, icon: "none" });
                  }
                }}
              >
                {a.markReleaseLive}
              </Button>
              {rows.map((d) => (
                <View key={d.id} className="admin-row admin-row--stack">
                  <View>
                    <Text className="admin-row__key">{d.channel_code}</Text>
                    <Text className="admin-row__desc">
                      {d.owner_email ? `${d.owner_email} · ` : ""}
                      {d.layer ? `${d.layer} · ` : ""}
                      {d.status}
                      {typeof d.retry_count === "number" ? ` · #${d.retry_count}` : ""}
                      {d.claim_active && d.claimed_email ? ` · ${a.claimedBy.replace("{name}", d.claimed_email)}` : ""}
                      {d.reject_reason ? ` · ${d.reject_reason}` : ""}
                      {d.last_error ? ` · ${d.last_error}` : ""}
                      {d.priority_score ? ` · ${a.priorityBadge}` : ""}
                      {d.sla_escalated ? ` · ${a.slaEscalated}` : ""}
                      {d.sla_overdue ? ` · ${a.slaOverdue}` : d.sla_due_at ? ` · ${a.slaDue.replace("{t}", String(d.sla_due_at).slice(5, 16).replace("T", " "))}` : ""}
                      {d.sop ? ` · ${d.sop}` : ""}
                      {(d.submissions || []).length
                        ? ` · ${a.lastSubmit} ${(d.submissions || [])
                            .slice(-2)
                            .map((row) => row.event || row.message || "")
                            .filter(Boolean)
                            .join(" / ")}`
                        : ""}
                    </Text>
                  </View>
                  <Input
                    label={a.fillStoreUrl}
                    value={storeUrls[d.id] ?? d.store_url ?? ""}
                    onInput={(e) => setStoreUrls((prev) => ({ ...prev, [d.id]: e.detail.value }))}
                  />
                  <Text className="admin-row__desc">{copy.creatorUi.storePasteHint}</Text>
                  <Input
                    label={a.fillExternalId}
                    value={externalIds[d.id] ?? d.external_id ?? ""}
                    onInput={(e) => setExternalIds((prev) => ({ ...prev, [d.id]: e.detail.value }))}
                  />
                  <View className="admin-tabs">
                    {d.upload_url && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          if (process.env.TARO_ENV === "h5" && typeof window !== "undefined") {
                            window.open(d.upload_url, "_blank", "noopener,noreferrer");
                          }
                        }}
                      >
                        {a.openPortal}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={async () => {
                        try {
                          const url = (storeUrls[d.id] ?? d.store_url ?? "").trim();
                          const externalId = (externalIds[d.id] ?? d.external_id ?? "").trim();
                          if (!url) {
                            Taro.showToast({ title: a.fillStoreUrl, icon: "none" });
                            return;
                          }
                          if (!looksLikeStorePage(url)) {
                            Taro.showToast({ title: a.notStorePage, icon: "none" });
                            return;
                          }
                          await vibeApi.adminSetDeliveryStatus(d.id, d.status, undefined, {
                            store_url: url,
                            ...(externalId ? { external_id: externalId } : {}),
                          });
                          const r = await vibeApi.adminDistributionDeliveries();
                          setDeliveries((r.deliveries || []) as typeof deliveries);
                        } catch (err) {
                          const msg = String((err as Error)?.message || "");
                          Taro.showToast({ title: msg.includes("not a store page") ? a.notStorePage : a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {a.saveStoreAutoLive}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={async () => {
                        try {
                          const url = (storeUrls[d.id] ?? d.store_url ?? "").trim();
                          const externalId = (externalIds[d.id] ?? d.external_id ?? "").trim();
                          if (!url && !externalId) {
                            Taro.showToast({ title: a.liveNeedsReceipt, icon: "none" });
                            return;
                          }
                          if (url && !looksLikeStorePage(url)) {
                            Taro.showToast({ title: a.notStorePage, icon: "none" });
                            return;
                          }
                          await vibeApi.adminSetDeliveryStatus(d.id, "live", undefined, {
                            ...(url ? { store_url: url } : {}),
                            ...(externalId ? { external_id: externalId } : {}),
                          });
                          const r = await vibeApi.adminDistributionDeliveries();
                          setDeliveries((r.deliveries || []) as typeof deliveries);
                        } catch (err) {
                          const msg = String((err as Error)?.message || "");
                          Taro.showToast({ title: msg.includes("not a store page") ? a.notStorePage : a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {a.markLive}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await vibeApi.adminSetDeliveryStatus(d.id, "in_review");
                          const r = await vibeApi.adminDistributionDeliveries();
                          setDeliveries((r.deliveries || []) as typeof deliveries);
                        } catch {
                          Taro.showToast({ title: a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {a.markReview}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={async () => {
                        try {
                          const pack = await vibeApi.adminDeliveryPack(d.id);
                          if (process.env.TARO_ENV === "h5") {
                            if (pack.kit_url) window.open(pack.kit_url, "_blank");
                            if (pack.clip_pack_url) window.open(pack.clip_pack_url, "_blank");
                            if (pack.originality_zip_url) window.open(pack.originality_zip_url, "_blank");
                          }
                          Taro.showToast({ title: pack.title || a.packReady, icon: "success" });
                        } catch {
                          Taro.showToast({ title: a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {a.downloadOpsPack}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        try {
                          if (d.claim_active) {
                            await vibeApi.adminUnclaimDelivery(d.id);
                          } else {
                            await vibeApi.adminClaimDelivery(d.id);
                          }
                          const r = queueOnly ? await vibeApi.adminDistributionQueue() : await vibeApi.adminDistributionDeliveries();
                          setDeliveries((r.deliveries || []) as typeof deliveries);
                        } catch {
                          Taro.showToast({ title: a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {d.claim_active ? a.unclaimDelivery : a.claimDelivery}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await vibeApi.adminRetryDelivery(d.id);
                          const r = queueOnly ? await vibeApi.adminDistributionQueue() : await vibeApi.adminDistributionDeliveries();
                          setDeliveries((r.deliveries || []) as typeof deliveries);
                        } catch {
                          Taro.showToast({ title: a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {a.retryDelivery}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await vibeApi.adminSetDeliveryStatus(d.id, "rejected", "ops");
                          const r = await vibeApi.adminDistributionDeliveries();
                          setDeliveries((r.deliveries || []) as typeof deliveries);
                        } catch {
                          Taro.showToast({ title: a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {a.markRejected}
                    </Button>
                  </View>
                </View>
              ))}
            </View>
          ))}
          <Text className="admin-row__key">{a.connectorBatches}</Text>
          {connectorBatches.map((b) => (
            <View key={b.id} className="admin-row">
              <View>
                <Text className="admin-row__key">{b.source}</Text>
                <Text className="admin-row__desc">{`${b.status} · ${b.matched_count || 0}/${(b.matched_count || 0) + (b.unmatched_count || 0)}`}</Text>
              </View>
              {b.source === "ops_connector" && b.status !== "confirmed" && (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={async () => {
                    try {
                      await vibeApi.adminConfirmConnectorBatch(b.id);
                      const r = await vibeApi.adminConnectorBatches();
                      setConnectorBatches((r.batches || []) as typeof connectorBatches);
                      Taro.showToast({ title: a.batchConfirmed, icon: "success" });
                    } catch {
                      Taro.showToast({ title: a.actionFail, icon: "none" });
                    }
                  }}
                >
                  {a.confirmBatch}
                </Button>
              )}
            </View>
          ))}
          <Text id="ops-anchor-claims" className="admin-row__key">{a.unmatchedClaims}</Text>
          {connectorClaims.map((claim) => (
            <View key={claim.id} className="admin-row admin-row--stack">
              <View>
                <Text className="admin-row__key">{claim.title || claim.channel_code}</Text>
                <Text className="admin-row__desc">{`${claim.channel_code} · ${claim.period_key} · ${claim.streams || 0}`}</Text>
              </View>
              <Input
                label={a.matchWork}
                value={claimWorkIds[claim.id] || ""}
                onInput={(e) => setClaimWorkIds((prev) => ({ ...prev, [claim.id]: e.detail.value }))}
              />
              <Button
                size="sm"
                variant="secondary"
                onClick={async () => {
                  const workId = (claimWorkIds[claim.id] || "").trim();
                  if (!workId) return;
                  try {
                    await vibeApi.adminMatchConnectorClaim(claim.id, workId);
                    const r = await vibeApi.adminConnectorClaims();
                    setConnectorClaims((r.claims || []) as typeof connectorClaims);
                  } catch {
                    Taro.showToast({ title: a.actionFail, icon: "none" });
                  }
                }}
              >
                {a.matchWork}
              </Button>
            </View>
          ))}
        </>
      )}

      {tab === "settlement" && (
        <>
          <View className="admin-row">
            <View>
              <Text className="admin-row__key">{a.tabSettlement}</Text>
              <Text className="admin-row__desc">{a.dailyOpsHint}</Text>
              <Text className="admin-row__desc">
                {a.pendingWithdrawals.replace("{n}", String(withdrawals.filter((w) => w.status === "pending").length))}
                {` · ${a.kycQueue} ${kycQueue.length}`}
                {` · ${a.harvestUnmatched} ${harvestUnmatched.length}`}
                {` · ${a.selectorBroke.replace("{n}", String(farmHealth?.selector_broke || 0))}`}
                {` · ${a.loginWall.replace("{n}", String(farmHealth?.login_wall || 0))}`}
                {` · ${a.opsQueue} ${distHealth?.ops_queue || 0}`}
              </Text>
            </View>
          </View>
          {kycQueue.length > 0 && <Text id="ops-anchor-kyc" className="admin-row__key">{a.kycQueue}</Text>}
          {kycQueue.map((row) => (
            <View key={row.id || row.email} className="admin-row">
              <View>
                <Text className="admin-row__key">{row.email || row.username || row.id}</Text>
                <Text className="admin-row__desc">{row.kyc_status || "pending"}</Text>
              </View>
              {row.id && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    try {
                      await vibeApi.adminSetKyc(row.id as string, "verified");
                      const r = await vibeApi.adminKycQueue("pending");
                      setKycQueue(r.users || []);
                      Taro.showToast({ title: a.kycVerified, icon: "success" });
                    } catch {
                      Taro.showToast({ title: a.actionFail, icon: "none" });
                    }
                  }}
                >
                  {a.kycVerify}
                </Button>
              )}
            </View>
          ))}
          {settlementPreview && (
            <View className="admin-row">
              <View>
                <Text className="admin-row__key">{a.currentPeriod.replace("{p}", settlementPreview.period_key || "—")}</Text>
                <Text className="admin-row__desc">
                  {a.previewLines.replace("{n}", String(settlementPreview.unsettled_for_period || 0))}
                  {settlementPreview.needs_confirm ? ` · ${a.runNeedConfirm}` : ""}
                  {settlementPreview.gross_minor_for_period
                    ? ` · ${a.previewSplit
                        .replace("{g}", ((settlementPreview.gross_minor_for_period || 0) / 100).toFixed(2))
                        .replace("{c}", ((settlementPreview.commission_minor_for_period || 0) / 100).toFixed(2))
                        .replace("{n}", ((settlementPreview.net_minor_for_period || 0) / 100).toFixed(2))}`
                    : ""}
                  {(settlementPreview.skipped?.self_release || 0) > 0
                    ? ` · ${a.skippedSelfRelease.replace("{n}", String(settlementPreview.skipped?.self_release))}`
                    : ""}
                  {(settlementPreview.skipped?.no_license || 0) > 0
                    ? ` · ${a.skippedNoLicense.replace("{n}", String(settlementPreview.skipped?.no_license))}`
                    : ""}
                  {(settlementPreview.skipped?.below_minimum || 0) > 0
                    ? ` · ${a.skippedBelowMin.replace("{n}", String(settlementPreview.skipped?.below_minimum))}`
                    : ""}
                  {settlementPreview.supplemental ? ` · ${a.runSupplemental}` : ""}
                  {(settlementPreview.by_currency || []).length > 1
                    ? ` · ${a.byCurrency} ${(settlementPreview.by_currency || [])
                        .map((row) => `${row.currency} ${((row.net_minor || 0) / 100).toFixed(2)}`)
                        .join(" / ")}`
                    : ""}
                </Text>
              </View>
            </View>
          )}
          {(settlementPreview?.pending_ops_connector_batches || 0) > 0 && (
            <View className="admin-row">
              <View>
                <Text className="admin-row__key">
                  {a.pendingConnectorBatches.replace("{n}", String(settlementPreview?.pending_ops_connector_batches || 0))}
                </Text>
                <Text className="admin-row__desc">{a.pendingConnectorHint}</Text>
              </View>
              <Button size="sm" variant="secondary" onClick={() => setTab("distribution")}>
                {a.goConfirmConnector}
              </Button>
            </View>
          )}
          <Button
            variant="primary"
            block
            onClick={async () => {
              try {
                const res = await vibeApi.adminRunSettlement();
                const r = await vibeApi.adminSettlementBatches();
                setBatches((r.batches || []) as typeof batches);
                const preview = await vibeApi.adminSettlementPreview().catch(() => null);
                if (preview) setSettlementPreview(preview);
                const lines = Number(res.lines || 0);
                Taro.showToast({
                  title: lines > 0 ? a.runNeedConfirm : a.runSettlementEmpty,
                  icon: lines > 0 ? "success" : "none",
                });
              } catch {
                Taro.showToast({ title: a.actionFail, icon: "none" });
              }
            }}
          >
            {a.runSettlement}
          </Button>
          {(settlementPreview?.unsettled_other_periods || []).length > 0 && (
            <View className="admin-row admin-row--stack">
              <Text className="admin-row__key">{a.unsettledOther}</Text>
              {(settlementPreview?.unsettled_other_periods || []).map((p) => (
                <Button
                  key={p.period_key || "other"}
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    if (!p.period_key) return;
                    try {
                      const res = await vibeApi.adminRunSettlement(p.period_key);
                      const r = await vibeApi.adminSettlementBatches();
                      setBatches((r.batches || []) as typeof batches);
                      const preview = await vibeApi.adminSettlementPreview().catch(() => null);
                      if (preview) setSettlementPreview(preview);
                      Taro.showToast({
                        title: Number(res.lines || 0) > 0 ? a.runNeedConfirm : a.runSettlementEmpty,
                        icon: Number(res.lines || 0) > 0 ? "success" : "none",
                      });
                    } catch {
                      Taro.showToast({ title: a.actionFail, icon: "none" });
                    }
                  }}
                >
                  {`${a.runPeriod.replace("{p}", p.period_key || "")} · ${a.previewLines.replace("{n}", String(p.count || 0))}`}
                </Button>
              ))}
            </View>
          )}
          {batches.map((b) => {
            const id = String(b.batch_id || b.id || "");
            const confirmed = b.status === "confirmed";
            const draft = b.status === "draft";
            return (
              <View key={id} className="admin-row">
                <View>
                  <Text className="admin-row__key">{b.period_key || id}</Text>
                  <Text className="admin-row__desc">
                    {confirmed ? a.alreadyConfirmed : statusLabel(b.status || "", copy.creatorUi.status)}
                    {` · ${a.previewSplit
                      .replace("{g}", ((b.gross_minor || 0) / 100).toFixed(2))
                      .replace("{c}", ((b.commission_minor || 0) / 100).toFixed(2))
                      .replace("{n}", ((b.net_minor || 0) / 100).toFixed(2))}`}
                    {` · ${a.batchLines.replace("{n}", String(b.line_count || 0))}`}
                    {b.user_count ? ` · ${a.batchUsers.replace("{n}", String(b.user_count))}` : ""}
                    {` · ${a.platformTake.replace("{n}", ((b.commission_minor || 0) / 100).toFixed(2))}`}
                    {(b.by_currency || []).length > 1
                      ? ` · ${(b.by_currency || []).map((row) => `${row.currency} ${((row.net_minor || 0) / 100).toFixed(2)}`).join(" / ")}`
                      : ""}
                  </Text>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      if (openBatchId === id) {
                        setOpenBatchId("");
                        return;
                      }
                      try {
                        const detail = await vibeApi.adminSettlementBatch(id);
                        setBatchDetail(detail as typeof batchDetail);
                        setOpenBatchId(id);
                      } catch {
                        Taro.showToast({ title: a.actionFail, icon: "none" });
                      }
                    }}
                  >
                    {openBatchId === id ? a.hideBatch : a.viewBatch}
                  </Button>
                </View>
                {openBatchId === id && batchDetail && (
                  <View className="admin-row admin-row--stack">
                    <Text className="admin-row__key">{a.batchDetail}</Text>
                    {(batchDetail.by_rate || []).map((row) => (
                      <Text key={`rate-${row.rate}`} className="admin-row__desc">
                        {`${row.rate}% · ${row.count} · ${((row.net_minor || 0) / 100).toFixed(2)}`}
                      </Text>
                    ))}
                    {(batchDetail.by_user || []).map((row) => (
                      <Text key={row.user_email || "user"} className="admin-row__desc">
                        {`${row.user_email || "—"} · ${a.batchLines.replace("{n}", String(row.line_count || 0))} · ${a.platformTake.replace("{n}", ((row.commission_minor || 0) / 100).toFixed(2))}`}
                      </Text>
                    ))}
                    {(batchDetail.lines || []).map((line, i) => (
                      <Text key={`${line.channel_code}-${i}`} className="admin-row__desc">
                        {`${line.work_title || "—"} · ${line.channel_code} · ${line.source} · ${line.commission_rate || 0}% · ${line.currency || "CNY"} ${((line.gross_minor || 0) / 100).toFixed(2)} → ${((line.net_minor || 0) / 100).toFixed(2)}`}
                      </Text>
                    ))}
                  </View>
                )}
                {draft && (
                  <View className="admin-tabs">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={async () => {
                        try {
                          await vibeApi.adminConfirmSettlement(id);
                          const r = await vibeApi.adminSettlementBatches();
                          setBatches((r.batches || []) as typeof batches);
                          const preview = await vibeApi.adminSettlementPreview().catch(() => null);
                          if (preview) setSettlementPreview(preview);
                          setOpenBatchId("");
                          Taro.showToast({ title: a.confirmSettlement, icon: "success" });
                        } catch {
                          Taro.showToast({ title: a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {a.confirmSettlement}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await vibeApi.adminVoidSettlement(id);
                          const r = await vibeApi.adminSettlementBatches();
                          setBatches((r.batches || []) as typeof batches);
                          const preview = await vibeApi.adminSettlementPreview().catch(() => null);
                          if (preview) setSettlementPreview(preview);
                          setOpenBatchId("");
                          Taro.showToast({ title: a.voidSettlement, icon: "success" });
                        } catch {
                          Taro.showToast({ title: a.actionFail, icon: "none" });
                        }
                      }}
                    >
                      {a.voidSettlement}
                    </Button>
                  </View>
                )}
              </View>
            );
          })}
          <Input label={a.reviewNote} value={adminNote} onInput={(e) => setAdminNote(e.detail.value)} />
          {withdrawals.some((w) => w.status === "pending") && (
            <View className="admin-row">
              <View>
                <Text id="ops-anchor-payouts" className="admin-row__key">
                  {a.pendingWithdrawals.replace("{n}", String(withdrawals.filter((w) => w.status === "pending").length))}
                </Text>
                <Text className="admin-row__desc">{a.pendingWithdrawHint}</Text>
              </View>
            </View>
          )}
          {withdrawals.map((w) => (
            <View
              key={w.id}
              className="admin-row"
              onClick={() => {
                if (!w.receipt_no) return;
                Taro.setClipboardData({
                  data: w.receipt_no,
                  success: () => Taro.showToast({ title: copy.creatorUi.receiptCopied.replace("{n}", w.receipt_no || ""), icon: "none" }),
                });
              }}
            >
              <View>
                <Text className="admin-row__key">{formatFen(w.amount_minor, w.currency)}</Text>
                <Text className="admin-row__desc">
                  {statusLabel(w.status, copy.creatorUi.status)}
                  {w.receipt_no ? ` · ${copy.creatorUi.receiptNo.replace("{n}", w.receipt_no)}` : ""}
                  {w.user_email ? ` · ${w.user_email}` : ""}
                  {w.risk_flag ? ` · ${a.riskFlag}` : ""}
                  {w.kyc_status === "verified" ? ` · ${a.kycVerified}` : ""}
                </Text>
              </View>
              {w.user_id && w.kyc_status !== "verified" && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    try {
                      await vibeApi.adminSetKyc(w.user_id as string, "verified");
                      const r = await vibeApi.adminWithdrawals();
                      setWithdrawals((r.withdrawals || []) as typeof withdrawals);
                      Taro.showToast({ title: a.kycVerified, icon: "success" });
                    } catch {
                      Taro.showToast({ title: a.actionFail, icon: "none" });
                    }
                  }}
                >
                  {a.kycVerify}
                </Button>
              )}
              {w.status === "pending" && (
                <View className="admin-tabs">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={async () => {
                      try {
                        await vibeApi.adminReviewWithdrawal(w.id, true, adminNote || undefined);
                        const r = await vibeApi.adminWithdrawals();
                        setWithdrawals((r.withdrawals || []) as typeof withdrawals);
                      } catch {
                        Taro.showToast({ title: a.actionFail, icon: "none" });
                      }
                    }}
                  >
                    {a.approveWithdraw}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      try {
                        await vibeApi.adminReviewWithdrawal(w.id, false, adminNote || undefined);
                        const r = await vibeApi.adminWithdrawals();
                        setWithdrawals((r.withdrawals || []) as typeof withdrawals);
                      } catch {
                        Taro.showToast({ title: a.actionFail, icon: "none" });
                      }
                    }}
                  >
                    {a.rejectWithdraw}
                  </Button>
                </View>
              )}
            </View>
          ))}
        </>
      )}

      {tab === "sync" && (
        <>
          <View className="admin-row">
            <View>
              <Text className="admin-row__key">{a.syncPending}</Text>
              <Text className="admin-row__desc">{a.syncEmpty}</Text>
            </View>
          </View>
          {syncInvoices.length === 0 && (
            <View className="admin-row">
              <Text className="admin-row__desc">{a.syncEmpty}</Text>
            </View>
          )}
          {syncInvoices.map((order) => (
            <View key={order.id} className="admin-row">
              <View>
                <Text className="admin-row__key">{order.license_id || order.id}</Text>
                <Text className="admin-row__desc">
                  {order.tier || "—"}
                  {` · ${statusLabel(order.status || "pending_invoice", copy.creatorUi.status)}`}
                  {order.seller_minor != null ? ` · ${((order.seller_minor || 0) / 100).toFixed(2)} ${order.currency || "CNY"}` : ""}
                </Text>
              </View>
              <Button
                size="sm"
                variant="primary"
                onClick={() => {
                  void (async () => {
                    try {
                      await vibeApi.confirmSyncInvoice(order.id);
                      Taro.showToast({ title: a.confirmInvoice, icon: "success" });
                      const res = await vibeApi.listSyncPendingInvoices();
                      setSyncInvoices(res.orders || []);
                    } catch {
                      Taro.showToast({ title: a.actionFail, icon: "none" });
                    }
                  })();
                }}
              >
                {a.confirmInvoice}
              </Button>
            </View>
          ))}
        </>
      )}

      {tab === "keys" && (
        <>
          <Text className="typo-meta">{a.keysHint}</Text>
          <Input label={a.keysVendor} value={newVendor} onInput={(e) => setNewVendor(e.detail.value)} />
          <Input label={a.keysCapability} value={newCapability} onInput={(e) => setNewCapability(e.detail.value)} />
          <Input label="API Key" password value={newApiKey} onInput={(e) => setNewApiKey(e.detail.value)} />
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              if (!newApiKey.trim()) return;
              void vibeApi
                .adminCreateVendorKey({ vendor: newVendor, capability: newCapability, api_key: newApiKey.trim() })
                .then(() => {
                  setNewApiKey("");
                  return vibeApi.adminVendorKeys();
                })
                .then((r) => setVendorKeys(r.keys || []))
                .catch(() => Taro.showToast({ title: a.actionFail, icon: "none" }));
            }}
          >
            {a.keysAdd}
          </Button>
          {vendorKeys.map((row) => (
            <View key={row.id} className="admin-row">
              <View>
                <Text className="admin-row__key">
                  {row.vendor} · {row.capability} · {row.key_prefix}…
                </Text>
                <Text className="admin-row__desc">
                  {row.model || "—"} · {row.inflight ?? 0}/{row.max_inflight ?? 2}
                  {row.daily_quota ? ` · ${row.daily_used ?? 0}/${row.daily_quota}` : ""}
                  {row.last_error ? ` · ${row.last_error}` : ""}
                </Text>
              </View>
              <Button
                size="sm"
                variant="ghost"
                loading={probingKeyId === row.id}
                onClick={() => {
                  setProbingKeyId(row.id);
                  void vibeApi
                    .adminProbeVendorKey(row.id)
                    .then((res) => {
                      Taro.showToast({
                        title: res.probe?.ok ? a.keysProbeOk : a.keysProbeFail,
                        icon: res.probe?.ok ? "success" : "none",
                      });
                      return vibeApi.adminVendorKeys();
                    })
                    .then((r) => setVendorKeys(r.keys || []))
                    .catch(() => Taro.showToast({ title: a.actionFail, icon: "none" }))
                    .finally(() => setProbingKeyId(""));
                }}
              >
                {a.keysProbe}
              </Button>
              <Button
                size="sm"
                variant={row.enabled ? "secondary" : "ghost"}
                onClick={() => {
                  void vibeApi
                    .adminPatchVendorKey(row.id, { enabled: !row.enabled })
                    .then(() => vibeApi.adminVendorKeys())
                    .then((r) => setVendorKeys(r.keys || []))
                    .catch(() => Taro.showToast({ title: a.actionFail, icon: "none" }));
                }}
              >
                {a.keysToggle}
              </Button>
            </View>
          ))}
        </>
      )}
    </PageShell>
  );
}
