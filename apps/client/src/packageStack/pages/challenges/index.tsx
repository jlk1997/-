import { useMemo, useState } from "react";
import { View } from "@tarojs/components";
import Taro, { useDidShow, useRouter, useShareAppMessage } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell, SectionLabel } from "../../../components/PageShell";
import { ChallengeCard } from "../../../components/community/ChallengeCard";
import { Button, EmptyState, LoadingSkeleton, StatPill } from "../../../components/ui";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth } from "../../../utils/auth";
import { stackPage } from "../../../constants/routes";
import { captureReferralFromQuery, myReferralCode } from "../../../platform/referral";
import { sharePage } from "../../../platform/share";
import "./index.scss";

type Challenge = Awaited<ReturnType<typeof vibeApi.getChallenges>>[number];

export default function ChallengesPage() {
  const { copy } = useLocale();
  const ch = copy.challengesUi;
  const router = useRouter();
  const [items, setItems] = useState<Challenge[]>([]);
  const [loading, setLoading] = useState(false);
  const isWeapp = process.env.TARO_ENV === "weapp";

  useShareAppMessage(() => ({
    title: ch.title,
    path: stackPage("challenges", { ref: myReferralCode() || undefined }),
  }));

  useDidShow(async () => {
    captureReferralFromQuery(router.params as Record<string, unknown>);
    bootstrapAuth();
    setLoading(true);
    try {
      setItems(await vibeApi.getChallenges());
    } catch {
      Taro.showToast({ title: ch.loadFail, icon: "none" });
    } finally {
      setLoading(false);
    }
  });

  const sorted = useMemo(
    () => [...items].sort((a, b) => b.participant_count - a.participant_count),
    [items]
  );

  const featured = sorted[0];
  const rest = sorted.slice(1);

  return (
    <PageShell label={copy.navGroups.community} title={ch.title} subtitle={ch.subtitle} wide ambient>
      {!isWeapp ? (
        <Button
          variant="ghost"
          size="sm"
          block
          onClick={() => sharePage(ch.title, stackPage("challenges", { ref: myReferralCode() || undefined }))}
        >
          {copy.player.share}
        </Button>
      ) : null}
      {!loading && items.length > 0 && (
        <View className="challenges-stats">
          <StatPill label={ch.activeCount.replace("{n}", String(items.length))} variant="accent" />
        </View>
      )}
      {loading && <LoadingSkeleton count={3} />}
      {!loading && items.length === 0 && (
        <EmptyState
          iconName="flag"
          title={ch.empty}
          description={ch.emptyDesc}
          actionLabel={copy.tabBar.feed}
          onAction={() => Taro.switchTab({ url: "/pages/feed/index" })}
        />
      )}
      {featured && (
        <>
          <SectionLabel>{ch.featuredLabel}</SectionLabel>
          <ChallengeCard
            title={featured.title}
            hashtag={featured.hashtag}
            coverUrl={featured.cover_url}
            participantCount={featured.participant_count}
            participantsLabel={ch.participants}
            endsAt={featured.ends_at}
            deadlinePrefix={ch.deadlinePrefix}
            prizePoolCredits={featured.prize_pool_credits}
            prizePoolLabel={ch.prizePool}
            featured
            onClick={() => Taro.navigateTo({ url: stackPage("challenge", { slug: featured.slug }) })}
          />
        </>
      )}
      {rest.length > 0 && (
        <>
          <SectionLabel>{ch.allLabel}</SectionLabel>
          <View className="challenges-grid">
            {rest.map((item) => (
              <View key={item.id} className="challenges-grid__cell">
                <ChallengeCard
                  title={item.title}
                  hashtag={item.hashtag}
                  coverUrl={item.cover_url}
                  participantCount={item.participant_count}
                  participantsLabel={ch.participants}
                  endsAt={item.ends_at}
                  deadlinePrefix={ch.deadlinePrefix}
                  prizePoolCredits={item.prize_pool_credits}
                  prizePoolLabel={ch.prizePool}
                  onClick={() => Taro.navigateTo({ url: stackPage("challenge", { slug: item.slug }) })}
                />
              </View>
            ))}
          </View>
        </>
      )}
    </PageShell>
  );
}
