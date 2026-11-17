import { useMemo, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useRouter, useDidShow, useShareAppMessage } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { PageShell, SectionLabel } from "../../../components/PageShell";
import { LeaderboardEntry } from "../../../components/community/LeaderboardEntry";
import { BottomSheet, Button, EmptyState, ImmersiveCover, LoadingSkeleton, ShareButton, StatPill } from "../../../components/ui";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../../utils/auth";
import { useCreditsOptional } from "../../../contexts/CreditsProvider";
import { setItem } from "../../../platform/storage";
import { openWorkForOwner } from "../../../utils/workNav";
import { stackPage } from "../../../constants/routes";
import { goShipBand } from "../../../packageCreator/nextActionNav";
import { captureReferralFromQuery, myReferralCode } from "../../../platform/referral";
import { sharePage } from "../../../platform/share";
import { startSameStyle } from "../../../utils/sameStyleNav";
import "./index.scss";

type ChallengeData = Awaited<ReturnType<typeof vibeApi.getChallenge>>;
type Entry = ChallengeData["entries"][number];

export default function ChallengeDetailPage() {
  const router = useRouter();
  const { copy } = useLocale();
  const cd = copy.challengeDetail;
  const slug = router.params.slug || "";
  const [challenge, setChallenge] = useState<ChallengeData | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [works, setWorks] = useState<Array<{ id: string; title: string }>>([]);
  const [submitting, setSubmitting] = useState(false);
  const [mineIds, setMineIds] = useState<Set<string>>(new Set());
  const creditsCtx = useCreditsOptional();

  useShareAppMessage(() => ({
    title: challenge?.title || cd.pageTitleFallback,
    path: stackPage("challenge", { slug, ref: myReferralCode() || undefined }),
  }));

  async function reload() {
    if (!slug) return;
    const [data, board] = await Promise.all([
      vibeApi.getChallenge(slug),
      vibeApi.getChallengeLeaderboard(slug).catch(() => null),
    ]);
    setChallenge(data);
    if (board?.entries?.length) {
      setEntries(
        board.entries.map((e) => ({
          work_id: e.work_id,
          title: e.title,
          author: e.author,
          like_count: e.like_count,
          cover_url: e.cover_url,
          moods: [],
          audio_url: data.entries?.find((x) => x.work_id === e.work_id)?.audio_url,
          hls_url: data.entries?.find((x) => x.work_id === e.work_id)?.hls_url,
        }))
      );
    } else {
      setEntries(data.entries || []);
    }
  }

  useDidShow(async () => {
    captureReferralFromQuery(router.params as Record<string, unknown>);
    if (!slug) return;
    bootstrapAuth();
    setLoading(true);
    try {
      await reload();
      if (!isLoggedIn()) {
        setMineIds(new Set());
      } else {
        const list = await vibeApi.listWorks().catch(() => []);
        setMineIds(new Set(list.map((w) => w.id)));
      }
    } catch {
      Taro.showToast({ title: cd.loadFail, icon: "none" });
    } finally {
      setLoading(false);
    }
  });

  const playQueue = useMemo(
    () =>
      entries
        .filter((e) => e.audio_url)
        .map((e) =>
          workToPlayerTrack(
            { id: e.work_id, title: e.title, audio_url: e.audio_url!, hls_url: e.hls_url, moods: e.moods },
            { artist: e.author, source: "challenge", isOwner: mineIds.has(e.work_id) }
          )
        ),
    [entries, mineIds]
  );

  async function openWorkPicker() {
    if (!requireAuth(stackPage("challenge", { slug }))) return;
    try {
      const list = await vibeApi.listWorks();
      if (!list.length) {
        Taro.showModal({
          title: cd.noWorksTitle,
          content: cd.noWorksContent,
          success: (r) => {
            if (r.confirm) goCreateOfficial();
          },
        });
        return;
      }
      setWorks(list.map((w) => ({ id: w.id, title: w.title })));
      setPickerOpen(true);
    } catch {
      Taro.showToast({ title: cd.loadWorksFail, icon: "none" });
    }
  }

  async function submitWork(workId: string) {
    if (!challenge) return;
    setSubmitting(true);
    try {
      const res = await vibeApi.enterChallenge(slug, workId, `#${challenge.hashtag || challenge.title}`);
      Taro.showToast({ title: cd.submitSuccess, icon: "success" });
      const reward = res.task_reward;
      if (reward?.credits_granted && !reward.duplicate) {
        if (reward.balance != null) creditsCtx?.setBalance(reward.balance);
        else void creditsCtx?.refresh();
        setTimeout(() => {
          Taro.showToast({
            title: cd.taskReward.replace("{n}", String(reward.credits_granted)),
            icon: "success",
          });
        }, 600);
      }
      setPickerOpen(false);
      await reload();
    } catch {
      Taro.showToast({ title: cd.submitFail, icon: "none" });
    } finally {
      setSubmitting(false);
    }
  }

  function goCreateOfficial() {
    if (!challenge) return;
    setItem("create:challengeSlug", slug);
    setItem("create:seedIntent", challenge.description || `#${challenge.hashtag} ${challenge.title}`);
    Taro.switchTab({ url: "/pages/create/index" });
  }

  const title = challenge?.title || cd.pageTitleFallback;
  const hashtag = challenge?.hashtag || "";

  return (
    <PageShell
      label={copy.navGroups.community}
      title={title}
      subtitle={hashtag}
      wide
      immersive
      noPadTop
      ambient
      actions={
        <ShareButton
          className="ui-btn ui-btn--ghost ui-btn--sm"
          onShare={() =>
            sharePage(title, stackPage("challenge", { slug, ref: myReferralCode() || undefined }))
          }
        >
          {copy.player.share}
        </ShareButton>
      }
    >
      <ImmersiveCover coverUrl={challenge?.cover_url} height="320rpx">
        {challenge?.description && <Text className="challenge-hero__desc">{challenge.description}</Text>}
        <View className="challenge-hero__stats">
          {challenge?.participant_count != null && (
            <StatPill label={copy.challengesUi.participants.replace("{n}", String(challenge.participant_count))} />
          )}
          {challenge?.ends_at && (
            <StatPill label={`${cd.deadlinePrefix}${challenge.ends_at.slice(0, 10)}`} variant="muted" />
          )}
          {challenge?.prize_pool_credits ? (
            <StatPill label={cd.prizePool.replace("{n}", String(challenge.prize_pool_credits))} variant="accent" />
          ) : null}
          {challenge?.sponsor_label ? (
            <StatPill label={cd.sponsor.replace("{name}", challenge.sponsor_label)} variant="muted" />
          ) : null}
          {challenge?.awards_distributed ? <StatPill label={cd.awardsDone} variant="muted" /> : null}
        </View>
      </ImmersiveCover>

      <SectionLabel>{cd.leaderboard}</SectionLabel>
      {loading && <LoadingSkeleton count={4} variant="line" />}
      {!loading && entries.length === 0 && (
        <EmptyState
          iconName="flag"
          title={cd.emptyEntriesShort}
          actionLabel={copy.challengesUi.rowCta}
          onAction={() => Taro.navigateTo({ url: stackPage("challenges") })}
        />
      )}
      {entries.map((e, i) => (
        <LeaderboardEntry
          key={e.work_id}
          rank={i + 1}
          title={e.title}
          author={e.author}
          coverUrl={e.cover_url}
          likeCount={e.like_count}
          likesLabel={cd.likes}
          track={
            e.audio_url
              ? workToPlayerTrack(
                  { id: e.work_id, title: e.title, audio_url: e.audio_url, hls_url: e.hls_url, moods: e.moods },
                  { artist: e.author, source: "challenge", isOwner: mineIds.has(e.work_id) }
                )
              : undefined
          }
          queue={playQueue}
          onClick={() => openWorkForOwner(e.work_id, mineIds.has(e.work_id))}
          actionLabel={copy.derivative.startSameStyle}
          onAction={() => startSameStyle(e.work_id, e.title)}
        />
      ))}
      {challenge?.awards_distributed &&
        entries.slice(0, 3).some((row) => mineIds.has(row.work_id)) && (
          <View className="challenge-actions">
            {entries.slice(0, 3).map((row, idx) =>
              mineIds.has(row.work_id) ? (
                <Button
                  key={row.work_id}
                  variant="primary"
                  block
                  onClick={() =>
                    goShipBand(row.work_id)
                  }
                >
                  {`${cd.winnerCta} · #${idx + 1}`}
                </Button>
              ) : null,
            )}
          </View>
        )}

      <View className="challenge-actions">
        <Button variant="primary" block loading={submitting} onClick={openWorkPicker}>
          {cd.selectWorkSubmit}
        </Button>
        <Button variant="secondary" block onClick={goCreateOfficial}>
          {cd.createForChallenge}
        </Button>
      </View>

      <BottomSheet open={pickerOpen} title={cd.submitTitle} onClose={() => setPickerOpen(false)}>
        {works.length === 0 && <Text className="typo-meta">{cd.noWorks}</Text>}
        {works.map((w) => (
          <Button key={w.id} variant="ghost" block loading={submitting} onClick={() => submitWork(w.id)}>
            {w.title}
          </Button>
        ))}
      </BottomSheet>
    </PageShell>
  );
}
