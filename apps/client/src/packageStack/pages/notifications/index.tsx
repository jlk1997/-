import { useRef, useState } from "react";
import { View } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { NotificationCard } from "../../../components/community/NotificationCard";
import { Button, ChipGroup, EmptyState, LoadingSkeleton, RingGauge } from "../../../components/ui";
import { CREATOR_PAGE_ROUTES, creatorPage, openCreatorDesk, socialPage, STACK_PAGE_ROUTES, stackPage } from "../../../constants/routes";
import { goShipBand } from "../../../packageCreator/nextActionNav";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../../utils/auth";
import { formatWarmup } from "../../../packageCreator/lib";
import { openWorkbench } from "../../../utils/workbenchNav";
import "./index.scss";

function isWorkbenchJobPayload(payload: Record<string, unknown>): boolean {
  return (
    payload.job_type === "workbench_render" ||
    Boolean(payload.workbench_session_id) ||
    payload.remix_intent === "workbench"
  );
}

type NotificationItem = {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  read: boolean;
  created_at: string | null;
};

type Filter = "all" | "unread";

export default function NotificationsPage() {
  const { copy, locale } = useLocale();
  const n = copy.notificationsUi;
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const lastLoadAt = useRef(0);

  function formatAmount(minor: unknown, currency: unknown): string {
    const value = (Number(minor || 0) / 100).toFixed(2);
    const cur = String(currency || "CNY").toUpperCase();
    if (cur === "USD") return `$${value}`;
    return locale === "en" ? `CNY ${value}` : `¥${value}`;
  }

  function formatMessage(item: NotificationItem): string {
    const user = String(
      item.payload.remixer_username ||
        item.payload.follower_username ||
        item.payload.liker_username ||
        item.payload.commenter_username ||
        n.fallbackUser
    );
    if (item.type === "remix_done") return n.remixDone.replace("{user}", user);
    if (item.type === "new_follower") return n.newFollower.replace("{user}", user);
    if (item.type === "job_completed") return String(item.payload.message || n.jobCompleted);
    if (item.type === "job_failed") return String(item.payload.message || n.jobFailed);
    if (item.type === "post_liked") return n.postLiked.replace("{user}", user);
    if (item.type === "post_commented") return n.postCommented.replace("{user}", user);
    if (item.type === "subscription_expiring") {
      const days = String(item.payload.days ?? item.payload.days_left ?? "3");
      return n.subscriptionExpiring.replace("{days}", days);
    }
    if (item.type === "low_credits") {
      const bal = String(item.payload.balance ?? "0");
      return n.lowCredits.replace("{n}", bal);
    }
    if (item.type === "duel_invite") {
      const user = String(item.payload.challenger_username || n.fallbackUser);
      return n.duelInvite.replace("{user}", user);
    }
    if (item.type === "duel_accepted") {
      const user = String(item.payload.opponent_username || n.fallbackUser);
      return n.duelAccepted.replace("{user}", user);
    }
    if (item.type === "duel_result") {
      return String(item.payload.message || n.duelResult);
    }
    if (item.type === "challenge_award") {
      const title = String(item.payload.challenge_title || "");
      const rank = String(item.payload.rank || "");
      const credits = String(item.payload.credits || "");
      return n.challengeAward.replace("{title}", title).replace("{rank}", rank).replace("{credits}", credits);
    }
    if (item.type === "release_hint" || item.type === "release_auto_submitted") {
      return String(item.payload.message || (item.type === "release_hint" ? n.releaseHint : n.releaseAutoSubmitted));
    }
    if (item.type === "sync_order") {
      return String(item.payload.message || n.syncOrder);
    }
    if (item.type === "challenge_ending") {
      const title = String(item.payload.challenge_title || "");
      const hours = String(item.payload.hours_left || "24");
      return n.challengeEnding.replace("{title}", title).replace("{hours}", hours);
    }
    if (item.type === "creator_weekly") {
      const split = item.payload.wallet_split;
      if (split && typeof split === "object") {
        const s = split as Record<string, unknown>;
        const cal = item.payload.payout_calendar as { days_until_payout?: number; is_payout_day?: boolean } | undefined;
        const payout =
          cal?.is_payout_day || cal?.days_until_payout === 0
            ? n.creatorWeeklyPayoutToday
            : n.creatorWeeklyPayoutInDays.replace("{n}", String(cal?.days_until_payout ?? ""));
        const fen = (v: unknown) => formatAmount(v, "CNY");
        const warmup = formatWarmup(Number(s.radio_minor || 0), copy.creatorUi.warmupNotCash);
        return n.creatorWeeklySplit
          .replace("{radio}", warmup)
          .replace("{sync}", fen(s.sync_minor))
          .replace("{embed}", fen(s.embed_minor))
          .replace("{dsp}", fen(s.dsp_minor))
          .replace("{tips}", String(item.payload.tips ?? s.credits_tips ?? 0))
          .replace("{payout}", payout);
      }
      return String(item.payload.message || n.creatorWeekly);
    }
    if (item.type === "radio_trial_ended") {
      return String(item.payload.message || n.radioTrialEnded);
    }
    if (item.type === "radio_trial_ending") {
      return String(item.payload.message || n.radioTrialEnding);
    }
    if (item.type === "radio_listen_settled") {
      return n.radioListenSettled
        .replace("{title}", String(item.payload.work_title || item.payload.title || ""))
        .replace("{n}", String(item.payload.payout_minor || 0));
    }
    if (item.type === "tip_received") {
      const credits = String(item.payload.credits || "0");
      const user = String(item.payload.from_username || n.fallbackUser);
      return n.tipReceived.replace("{user}", user).replace("{credits}", credits);
    }
    if (item.type === "mention") {
      const user = String(item.payload.commenter_username || n.fallbackUser);
      return n.mention.replace("{user}", user);
    }
    if (item.type === "distribution_status") {
      return n.distributionStatus
        .replace("{channel}", String(item.payload.channel_code || ""))
        .replace("{status}", String(item.payload.status || item.payload.message || ""));
    }
    if (item.type === "ops_sla") {
      return n.opsSla.replace("{channel}", String(item.payload.channel_code || item.payload.message || ""));
    }
    if (item.type === "payout_day") {
      return n.payoutDay.replace("{amt}", formatAmount(item.payload.available_minor, item.payload.currency));
    }
    if (item.type === "settlement_draft") {
      const period = String(item.payload.period_key || "");
      const hasAmount = item.payload.amount_minor != null && item.payload.amount_minor !== "";
      const amount = hasAmount ? formatAmount(item.payload.amount_minor, item.payload.currency) : "";
      if (period && amount) return n.settlementDraftAmount.replace("{p}", period).replace("{amt}", amount);
      return period ? n.settlementDraftPeriod.replace("{p}", period) : n.settlementDraft;
    }
    if (item.type === "settlement_ready") {
      const period = String(item.payload.period_key || "");
      const receipt = String(item.payload.receipt_no || "");
      const hasAmount = item.payload.amount_minor != null && item.payload.amount_minor !== "";
      const amount = hasAmount ? formatAmount(item.payload.amount_minor, item.payload.currency) : "";
      if (period && amount && receipt) {
        return n.settlementReadyReceipt.replace("{p}", period).replace("{amt}", amount).replace("{n}", receipt);
      }
      if (period && amount) return n.settlementReadyAmount.replace("{p}", period).replace("{amt}", amount);
      return period ? n.settlementReadyPeriod.replace("{p}", period) : n.settlementReady;
    }
    if (item.type === "withdrawal_update" || item.type === "withdrawal_paid") {
      const receipt = String(item.payload.receipt_no || "");
      const status = String(item.payload.status || "");
      const amount = formatAmount(item.payload.amount_minor, item.payload.currency);
      if (item.type === "withdrawal_paid" || status === "paid_manual") {
        return receipt ? n.withdrawalPaid.replace("{n}", receipt).replace("{amt}", amount) : n.withdrawalUpdate.replace("{status}", status || item.type);
      }
      if (status === "rejected") {
        return receipt ? n.withdrawalRejected.replace("{n}", receipt) : n.withdrawalUpdate.replace("{status}", status);
      }
      return n.withdrawalUpdate.replace("{status}", status || String(item.payload.message || item.type));
    }
    if (typeof item.payload.message === "string" && item.payload.message.trim()) return item.payload.message;
    if (item.type.startsWith("recall_")) {
      return String(item.payload.body || item.payload.title || n.recall);
    }
    if (item.type === "seat_challenge") {
      return String(item.payload.body || item.payload.title || n.seatChallenge);
    }
    const title = typeof item.payload.title === "string" ? item.payload.title.trim() : "";
    const body = typeof item.payload.body === "string" ? item.payload.body.trim() : "";
    if (title && body && title !== body) return `${title} · ${body}`;
    if (title) return title;
    if (body) return body;
    return item.type;
  }

  function formatTime(iso: string | null): string {
    if (!iso) return "";
    return iso.slice(0, 16).replace("T", " ");
  }

  async function openWinnerRelease(workId: string) {
    goShipBand(workId);
  }

  function openNotification(item: NotificationItem) {
    if (item.type.startsWith("recall_")) {
      Taro.switchTab({ url: "/pages/create/index" });
      return;
    }
    if (item.type === "subscription_expiring" || item.type === "low_credits") {
      Taro.navigateTo({ url: STACK_PAGE_ROUTES.pricing });
      return;
    }
    if (item.type === "duel_invite" || item.type === "duel_accepted" || item.type === "duel_result") {
      const workId = String(item.payload.work_id || "");
      if (item.type === "duel_result" && item.payload.won && workId) {
        void openWinnerRelease(workId);
        return;
      }
      const duelId = String(item.payload.duel_id || "");
      if (duelId) Taro.navigateTo({ url: socialPage("duel", { id: duelId }) });
      return;
    }
    if (item.type === "challenge_award") {
      const workId = String(item.payload.work_id || "");
      if (workId) void openWinnerRelease(workId);
      else Taro.navigateTo({ url: STACK_PAGE_ROUTES.challenges });
      return;
    }
    if (item.type === "release_hint") {
      const workId = String(item.payload.work_id || "");
      goShipBand(workId || undefined);
      return;
    }
    if (item.type === "release_auto_submitted") {
      const workId = String(item.payload.work_id || "");
      const releaseId = String(item.payload.release_id || "");
      Taro.navigateTo({ url: creatorPage("deliveries", { workId, releaseId }) });
      return;
    }
    if (item.type === "sync_order") {
      const workId = String(item.payload.work_id || "");
      if (workId) Taro.navigateTo({ url: creatorPage("work", { workId }) });
      else openCreatorDesk();
      return;
    }
    if (item.type === "challenge_ending") {
      const slug = String(item.payload.challenge_slug || "");
      if (slug) Taro.navigateTo({ url: stackPage("challenge", { slug }) });
      else Taro.navigateTo({ url: STACK_PAGE_ROUTES.challenges });
      return;
    }
    if (item.type === "creator_weekly") {
      openCreatorDesk("money");
      return;
    }
    if (item.type === "radio_trial_ending") {
      const workId = String(item.payload.work_id || "");
      Taro.navigateTo({
        url: workId
          ? socialPage("radio", { workId, station: String(item.payload.station || "") || undefined })
          : socialPage("radio"),
      });
      return;
    }
    if (item.type === "radio_trial_ended") {
      const workId = String(item.payload.work_id || "");
      const channels = (item.payload.channel_suggestion as { channels?: string[] } | undefined)?.channels;
      if (workId) {
        goShipBand(workId);
      } else openCreatorDesk();
      return;
    }
    if (item.type === "radio_listen_settled") {
      const workId = String(item.payload.work_id || "");
      Taro.navigateTo({ url: workId ? creatorPage("work", { workId }) : creatorPage("settlements") });
      return;
    }
    if (item.type === "seat_challenge") {
      const seatId = String(item.payload.seat_id || "");
      Taro.navigateTo({ url: seatId ? creatorPage("remoteLogin", { seatId }) : creatorPage("accounts") });
      return;
    }
    if (item.type === "distribution_status") {
      const releaseId = String(item.payload.release_id || "");
      Taro.navigateTo({ url: creatorPage("deliveries", { releaseId }) });
      return;
    }
    if (item.type === "ops_sla") {
      const releaseId = String(item.payload.release_id || "");
      Taro.navigateTo({ url: creatorPage("deliveries", { releaseId: releaseId || undefined }) });
      return;
    }
    if (item.type === "settlement_draft") {
      Taro.navigateTo({ url: creatorPage("settlements") });
      return;
    }
    if (item.type === "settlement_ready" || item.type === "payout_day") {
      openCreatorDesk("money");
      return;
    }
    if (item.type === "withdrawal_update" || item.type === "withdrawal_paid") {
      Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.wallet });
      return;
    }
    if (item.type === "job_completed" && item.payload.playlist_id) {
      Taro.navigateTo({ url: `/pages/playlist/index?id=${item.payload.playlist_id}` });
      return;
    }
    if ((item.type === "job_completed" || item.type === "job_failed") && isWorkbenchJobPayload(item.payload)) {
      const benchId = String(
        item.payload.source_work_id || item.payload.parent_work_id || item.payload.work_id || "",
      );
      if (benchId) {
        openWorkbench(benchId);
        return;
      }
    }
    if (item.payload.work_id) {
      Taro.navigateTo({ url: `${STACK_PAGE_ROUTES.work}?workId=${item.payload.work_id}` });
    }
  }

  async function load(force = false) {
    bootstrapAuth();
    if (!isLoggedIn()) return;
    if (!force && lastLoadAt.current && Date.now() - lastLoadAt.current < 15_000) return;
    setLoading(true);
    try {
      const res = await vibeApi.getNotifications();
      setItems(res.items);
      setUnread(res.unread_count);
      lastLoadAt.current = Date.now();
    } catch {
      Taro.showToast({ title: n.loadFail, icon: "none" });
    } finally {
      setLoading(false);
    }
  }

  useDidShow(() => {
    void load();
  });

  async function markAllRead() {
    try {
      await vibeApi.markNotificationsRead({ all: true });
      await load(true);
    } catch {
      Taro.showToast({ title: n.actionFail, icon: "none" });
    }
  }

  async function tapItem(item: NotificationItem) {
    if (!item.read) {
      await vibeApi.markNotificationsRead({ notification_id: item.id }).catch(() => {});
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, read: true } : i)));
      setUnread((u) => Math.max(0, u - 1));
    }
    openNotification(item);
  }

  const visible = filter === "unread" ? items.filter((i) => !i.read) : items;

  if (!isLoggedIn()) {
    return (
      <PageShell label={copy.navGroups.account} title={n.title} subtitle={n.loginSubtitle} showCredits={false} ambient>
        <EmptyState
          iconName="bell"
          title={n.loginSubtitle}
          actionLabel={copy.loginUi.login}
          onAction={() => requireAuth(STACK_PAGE_ROUTES.notifications)}
        />
      </PageShell>
    );
  }

  return (
    <PageShell
      label={copy.navGroups.account}
      title={n.title}
      subtitle={unread > 0 ? n.unreadSubtitle.replace("{n}", String(unread)) : n.allRead}
      badge={unread > 0 ? String(unread) : undefined}
      ambient
    >
      {unread > 0 && (
        <View className="notifications-header">
          <RingGauge value={unread} max={Math.max(unread, 10)} label={n.unreadLabel} sublabel={n.unreadSubtitle.replace("{n}", String(unread))} />
          <Button variant="secondary" size="sm" onClick={markAllRead}>
            {n.markAllRead}
          </Button>
        </View>
      )}

      <ChipGroup
        options={[
          { value: "all", label: n.filterAll },
          { value: "unread", label: n.filterUnread },
        ]}
        value={filter}
        onChange={(v) => setFilter(v as Filter)}
      />

      {loading && <LoadingSkeleton count={4} variant="line" />}
      {!loading && visible.length === 0 && (
        <EmptyState
          iconName="bell"
          title={filter === "unread" ? n.emptyUnread : n.empty}
          actionLabel={copy.tabBar.feed}
          onAction={() => Taro.switchTab({ url: "/pages/feed/index" })}
        />
      )}
      <View className="notifications-list">
        {visible.map((item) => (
          <NotificationCard
            key={item.id}
            type={item.type}
            message={formatMessage(item)}
            time={formatTime(item.created_at)}
            unread={!item.read}
            onClick={() => tapItem(item)}
          />
        ))}
      </View>
    </PageShell>
  );
}
