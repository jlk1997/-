import { useRef, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, useShareAppMessage } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { PageShell, SectionLabel } from "../../components/PageShell";
import {
  AsyncPanel,
  Button,
  EmptyState,
  ImmersiveCover,
  LibraryShelf,
  ListRow,
  LoadingSkeleton,
  StatPill,
  CreatorLevelBadge,
  type IconName,
} from "../../components/ui";
import { usePlayer } from "../../contexts/PlayerProvider";
import { vibeApi, isUnauthorized } from "../../services/api";
import { bootstrapAuth, clearToken, isLoggedIn, requireAuth } from "../../utils/auth";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { setItem } from "../../platform/storage";
import { resolveRestorableJobId } from "../../utils/restoreGeneration";
import { STACK_PAGE_ROUTES, stackPage, openLibrary, openCreatorDesk } from "../../constants/routes";
import { openRadioPage } from "../../utils/navigation";
import { openStackPage } from "../../utils/navigation";
import { fetchUnreadCount } from "../../utils/unreadBadge";
import { openBeautifyDoor, pickBeautifySourceId } from "../../utils/workbenchNav";
import { BeautifyDoorCard } from "../../components/studio/BeautifyDoorCard";
import { referralSharePath, myReferralCode } from "../../platform/referral";
import { workSharePayload } from "../../platform/share";
import { CoachMarks } from "../../components/onboarding/CoachMarks";
import { formatFen, formatPayoutCountdown, formatWarmup } from "../../packageCreator/lib";
import "./index.scss";

type WorkPreview = {
  id: string;
  title: string;
  cover_url?: string;
  audio_url: string;
  moods: string[];
  from_workbench?: boolean;
  post_process_status?: Record<string, unknown> | null;
};

export default function Profile() {
  const { copy } = useLocale();
  const p = copy.profileUi;
  const w = copy.worksUi;
  const creditsCtx = useCreditsOptional();

  useShareAppMessage((res) => {
    const ds = (res?.target as { dataset?: Record<string, string> } | undefined)?.dataset;
    if (ds?.workid) return workSharePayload(ds.workid, ds.title || copy.brand.name);
    return {
      title: copy.progressUi.referralTitle,
      path: referralSharePath(myReferralCode()),
    };
  });
  const { playTrack } = usePlayer();
  const [loggedIn, setLoggedIn] = useState(false);
  const [me, setMe] = useState<{
    username: string;
    display_name?: string;
    avatar_url?: string;
    email_bound?: boolean;
  } | null>(null);
  const subscription = creditsCtx?.subscription;
  const [unread, setUnread] = useState(0);
  const [recentWorks, setRecentWorks] = useState<WorkPreview[]>([]);
  const [activeJob, setActiveJob] = useState<{ jobId: string; returnUrl: string } | null>(null);
  const [creatorLevel, setCreatorLevel] = useState<string | null>(null);
  const [weeklySummary, setWeeklySummary] = useState<{
    listens: number;
    tips: number;
    published: number;
    remixes: number;
    duel_mentions?: number;
    wallet_split?: { credits_tips?: number; radio_minor?: number; sync_minor?: number; embed_minor?: number; dsp_minor?: number };
    payout_calendar?: { next_payout_date?: string; weekday_label?: string; days_until_payout?: number; is_payout_day?: boolean };
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const hasMeRef = useRef(false);
  const lastRefreshAt = useRef(0);
  const NAV_ITEMS: Array<{
    label: string;
    url?: string;
    icon: IconName;
    badgeKey?: "unread";
    hint?: string;
  }> = [
    { label: copy.creatorUi.deskMoney, url: "earnings", icon: "sigil" },
    { label: p.notifications, url: STACK_PAGE_ROUTES.notifications, icon: "bell", badgeKey: "unread" },
    {
      label: p.settings,
      url: me?.email_bound === false ? stackPage("settings", { section: "account" }) : STACK_PAGE_ROUTES.settings,
      icon: "profile",
      hint: me?.email_bound === false ? p.bindEmailHint : undefined,
    },
  ];

  async function refreshUser() {
    bootstrapAuth();
    if (!isLoggedIn()) {
      setLoggedIn(false);
      setRecentWorks([]);
      setActiveJob(null);
      setLoading(false);
      setLoadError(false);
      return;
    }
    setLoggedIn(true);
    if (hasMeRef.current && Date.now() - lastRefreshAt.current < 30_000) {
      setLoading(false);
      return;
    }
    if (!hasMeRef.current) setLoading(true);
    setLoadError(false);
    try {
      const [u, notif, works] = await Promise.all([
        vibeApi.me(),
        fetchUnreadCount().then((unread_count) => ({ unread_count })).catch(() => ({ unread_count: 0 })),
        vibeApi.listWorks("newest", undefined, 8).catch(() => []),
      ]);
      setMe({
        username: u.username,
        display_name: u.display_name,
        avatar_url: u.avatar_url,
        email_bound: u.email_bound !== false && !String(u.email || "").endsWith("@wechat.local"),
      });
      hasMeRef.current = true;
      lastRefreshAt.current = Date.now();
      setUnread(notif.unread_count);
      setRecentWorks(works.slice(0, 4));
      void resolveRestorableJobId()
        .then((restored) => setActiveJob(restored ? { jobId: restored.jobId, returnUrl: restored.returnUrl } : null))
        .catch(() => setActiveJob(null));
      void vibeApi
        .getProgress()
        .then((progress) => setCreatorLevel(progress?.level ?? null))
        .catch(() => {});
      void vibeApi
        .getCreatorWeeklySummary()
        .then(setWeeklySummary)
        .catch(() => {});
    } catch (err) {
      if (isUnauthorized(err)) {
        clearToken();
        setLoggedIn(false);
        setMe(null);
      } else {
        setLoadError(true);
      }
    } finally {
      setLoading(false);
    }
  }

  useDidShow(() => {
    void creditsCtx?.refresh();
    refreshUser();
  });

  function logout() {
    clearToken();
    setLoggedIn(false);
    setMe(null);
    creditsCtx?.refresh();
  }

  function playRecentWork(workId: string) {
    const work = recentWorks.find((item) => item.id === workId);
    if (!work?.audio_url) return;
    const tracks = recentWorks
      .filter((item) => item.audio_url)
      .map((item) => workToPlayerTrack(item, { source: "library", isOwner: true }));
    const track = tracks.find((t) => t.id === workId);
    if (track) playTrack(track, { queue: tracks, navigate: true });
  }

  function resumeActiveJob() {
    if (!activeJob) return;
    const url =
      activeJob.returnUrl.includes("playlist") || activeJob.returnUrl.includes("create")
        ? `${activeJob.returnUrl}${activeJob.returnUrl.includes("?") ? "&" : "?"}jobId=${activeJob.jobId}`
        : activeJob.returnUrl;
    if (url.startsWith("/pages/create") || url.startsWith("/pages/library") || url.startsWith("/pages/feed") || url.startsWith("/pages/profile") || url.startsWith("/pages/creator")) {
      Taro.switchTab({ url: url.split("?")[0] }).catch(() => openStackPage(url));
      return;
    }
    openStackPage(url);
  }

  if (!loggedIn) {
    return (
      <PageShell title={p.title} ambient tabVariant noPadTop hideHeader>
        <ImmersiveCover height="200rpx">
          <Text className="profile-guest__hero-title">{copy.brand.name}</Text>
          <Text className="profile-guest__hero-tag">{copy.brand.tagline}</Text>
        </ImmersiveCover>
        <Button
          variant="primary"
          block
          className="profile-guest__cta"
          onClick={() => requireAuth("/pages/create/index")}
        >
          {p.loginButton}
        </Button>
        <Button variant="ghost" block onClick={() => Taro.switchTab({ url: "/pages/create/index" })}>
          {p.guestTryCreate}
        </Button>
        <Button variant="ghost" block onClick={() => openStackPage(STACK_PAGE_ROUTES.pricing)}>
          {p.viewPricing}
        </Button>
      </PageShell>
    );
  }

  const credits = creditsCtx?.balance ?? 0;
  const shelfItems = recentWorks.map((item) => ({
    id: item.id,
    title: item.title,
    coverUrl: item.cover_url,
  }));

  return (
    <PageShell title={p.title} showCredits={false} ambient tabVariant noPadTop hideHeader>
      {loading && !me && <LoadingSkeleton count={3} />}
      {loadError && (
        <EmptyState
          iconName="profile"
          title={copy.worksUi.loadFail}
          actionLabel={copy.discoverUi.retry}
          onAction={() => void refreshUser()}
        />
      )}
      {!loadError && (
      <>
      <ImmersiveCover coverUrl={me?.avatar_url} height="300rpx">
        <View className="profile-hero">
          <View
            className="profile-hero__avatar-ring"
            onClick={() => {
              if (!loggedIn) return;
              void (async () => {
                try {
                  const { uploadUserAvatar } = await import("../../utils/avatarUpload");
                  const url = await uploadUserAvatar();
                  if (!url) return;
                  setMe((prev) => (prev ? { ...prev, avatar_url: url } : prev));
                  Taro.showToast({ title: copy.settingsUi.profileSaved, icon: "success" });
                } catch {
                  Taro.showToast({ title: copy.settingsUi.saveProfileFail, icon: "none" });
                }
              })();
            }}
          >
            <View className="profile-hero__avatar-inner">
              {me?.avatar_url ? (
                <View className="profile-hero__avatar-img" style={{ backgroundImage: `url(${me.avatar_url})` }} />
              ) : (
                <Text className="profile-hero__avatar-fallback">{(me?.display_name || me?.username || "?").slice(0, 1).toUpperCase()}</Text>
              )}
            </View>
          </View>
          {me && <Text className="profile-hero__name">{me.display_name || me.username}</Text>}
          {me && (
            <Text className="profile-hero__link" onClick={() => openStackPage(stackPage("user", { username: me.username }))}>
              @{me.username}
            </Text>
          )}
          {loggedIn ? <Text className="profile-hero__link">{copy.settingsUi.uploadAvatar}</Text> : null}
          <CreatorLevelBadge level={creatorLevel} />
        </View>
      </ImmersiveCover>

      <View className="profile-quick coach-anchor-credits">
        {subscription?.status === "active" && (
          <StatPill
            className="ui-stat-pill--member"
            label={p.member.replace("{n}", String(subscription.monthly_credits ?? 0))}
            variant="accent"
            onClick={() => openStackPage(STACK_PAGE_ROUTES.pricing)}
          />
        )}
        <StatPill label={`${p.billingHub} · ${credits}`} onClick={() => openStackPage(STACK_PAGE_ROUTES.pricing)} />
        {unread > 0 && <StatPill label={`${p.notifications} ${unread}`} variant="danger" onClick={() => openStackPage(STACK_PAGE_ROUTES.notifications)} />}
      </View>

      {activeJob && (
        <View className="profile-active-job" onClick={resumeActiveJob}>
          <View className="profile-active-job__pulse" />
          <View className="profile-active-job__body">
            <Text className="profile-active-job__label">{p.activeJobTeaser}</Text>
            <Text className="profile-active-job__action">{p.activeJobAction}</Text>
          </View>
        </View>
      )}

      <View className="profile-vault coach-anchor-shelf">
        <Text className="profile-vault__view-all" onClick={() => openLibrary()}>
          {copy.tabBar.library} →
        </Text>
      </View>

      <View className="profile-menu coach-anchor-menu">
        {NAV_ITEMS.map((item) => (
          <ListRow
            key={item.url}
            icon={item.icon}
            label={item.label}
            hint={item.hint}
            badge={item.badgeKey === "unread" ? unread : undefined}
            onClick={() => {
              if (item.url === "earnings") {
                openCreatorDesk("money");
                return;
              }
              if (item.url) openStackPage(item.url);
            }}
          />
        ))}
      </View>

      <Button variant="ghost" block onClick={logout} className="profile-logout">
        {p.logout}
      </Button>
      </>
      )}
      <CoachMarks page="profile" />
    </PageShell>
  );
}
