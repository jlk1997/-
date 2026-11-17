import { useEffect } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell, SectionLabel } from "../../../components/PageShell";
import { AsyncPanel, Button, MetricCard, StatusLine } from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { STACK_PAGE_ROUTES, CREATOR_PAGE_ROUTES, commercePage, creatorPage } from "../../../constants/routes";
import { formatFen, formatPayoutCountdown, formatWarmup } from "../../../packageCreator/lib";
import "./index.scss";

type EarningsPayload = {
  wallet: {
    balance_credits: number;
    lifetime_earned: number;
    estimated_weekly_royalty?: number;
    remix_credits_7d?: number;
    recent_tips?: Array<{ amount: number; from_username?: string; created_at?: string }>;
  };
  weekly: {
    listens: number;
    tips: number;
    published: number;
    remixes: number;
    duel_mentions?: number;
    radio_completes?: number;
    radio_self_completes?: number;
    wallet_split?: { credits_tips?: number; radio_minor?: number; sync_minor?: number; embed_minor?: number; dsp_minor?: number };
    payout_calendar?: { next_payout_date?: string; weekday_label?: string; days_until_payout?: number; is_payout_day?: boolean };
  } | null;
};

export default function CreatorEarningsPage() {
  const { copy, locale } = useLocale();
  const e = copy.ecosystemUi;
  const p = copy.profileUi;
  const d = copy.discoverUi;
  const fen = (n?: number) => formatFen(n, "CNY", locale);

  const { data, loading, error, reload } = useAsyncQuery<(EarningsPayload & { packs?: Awaited<ReturnType<typeof vibeApi.effectPackEarnings>> }) | null>(
    async () => {
      if (!requireAuth(commercePage("creatorEarnings"))) return null;
      const [wallet, weekly, packs] = await Promise.all([
        vibeApi.getCreatorWallet(),
        vibeApi.getCreatorWeeklySummary(),
        vibeApi.effectPackEarnings().catch(() => null),
      ]);
      return { wallet, weekly, packs: packs || undefined };
    },
    []
  );

  useDidShow(() => {
    void reload();
  });

  useEffect(() => {
    Taro.setNavigationBarTitle({ title: e.earningsTitle });
  }, [e.earningsTitle]);

  const wallet = data?.wallet;
  const weekly = data?.weekly;
  const remixCredits = wallet?.remix_credits_7d ?? wallet?.estimated_weekly_royalty ?? 0;
  const fiatSplit = weekly?.wallet_split;
  const showFiat =
    Boolean(fiatSplit) &&
    ((fiatSplit?.sync_minor || 0) > 0 || (fiatSplit?.embed_minor || 0) > 0 || (fiatSplit?.dsp_minor || 0) > 0);

  return (
    <PageShell title={e.earningsTitle} ambient>
      <View className="creator-earnings">
        <AsyncPanel
          loading={loading}
          error={error}
          skeletonCount={4}
          errorIcon="profile"
          errorTitle={e.earningsLoadFail}
          errorActionLabel={d.retry}
          onRetry={() => void reload()}
        >
          {wallet && (
            <>
              <SectionLabel>{e.creditsTipsSection}</SectionLabel>
              <MetricCard icon="profile" label={e.walletBalance} value={String(wallet.balance_credits)} />
              <MetricCard icon="heart" label={e.walletLifetime} value={String(wallet.lifetime_earned)} variant="info" />
              {remixCredits > 0 ? (
                <>
                  <MetricCard icon="music" label={e.estimatedRoyalty} value={String(remixCredits)} variant="warning" />
                  <StatusLine tone="info" density="quiet">{e.remixCreditsHint}</StatusLine>
                </>
              ) : null}
              {weekly ? (
                <Text className="creator-earnings__weekly">
                  {p.weeklyDigestEngagement
                    .replace("{listens}", String(weekly.listens))
                    .replace("{tips}", String(weekly.tips))
                    .replace("{published}", String(weekly.published))
                    .replace("{remix}", String(weekly.remixes))}
                  {weekly.duel_mentions != null ? ` · ${e.duelMentions.replace("{n}", String(weekly.duel_mentions))}` : ""}
                  {weekly.radio_completes != null ? ` · ${e.weeklyRadio.replace("{n}", String(weekly.radio_completes))}` : ""}
                </Text>
              ) : null}
              {showFiat && fiatSplit ? (
                <>
                  <SectionLabel>{e.fiatRoyaltySection}</SectionLabel>
                  <Text className="creator-earnings__weekly">
                    {p.weeklyFiatSplit
                      .replace("{radio}", formatWarmup(fiatSplit.radio_minor, copy.creatorUi.warmupNotCash))
                      .replace("{sync}", fen(fiatSplit.sync_minor))
                      .replace("{embed}", fen(fiatSplit.embed_minor))
                      .replace("{dsp}", fen(fiatSplit.dsp_minor))
                      .replace("{tips}", String(fiatSplit.credits_tips ?? weekly?.tips))}
                  </Text>
                </>
              ) : null}
              {data?.packs ? (
                <View>
                  <MetricCard icon="music" label={copy.workbenchUi.packIncome} value={String(data.packs.purchase_count || 0)} />
                  <Text className="creator-earnings__weekly">{e.packIncomeHint}</Text>
                  <Text className="creator-earnings__weekly">
                    {copy.workbenchUi.packApplies.replace("{n}", String(data.packs.apply_count || 0))}
                    {" · "}
                    {copy.workbenchUi.packBounces.replace("{n}", String(data.packs.bounce_count || 0))}
                    {" · "}
                    {copy.workbenchUi.packReleased.replace("{n}", String(data.packs.released_count || 0))}
                  </Text>
                </View>
              ) : null}
              {weekly?.payout_calendar?.next_payout_date ? (
                <StatusLine tone="info">{formatPayoutCountdown(weekly.payout_calendar, copy.creatorUi)}</StatusLine>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => Taro.navigateTo({ url: creatorPage("help") })}>
                {copy.creatorUi.seeHelp}
              </Button>
              {(wallet.recent_tips || []).length > 0 && (
                <View className="creator-earnings__tips">
                  <Text className="creator-earnings__tips-title">{e.recentTipsTitle}</Text>
                  {(wallet.recent_tips || []).map((t, i) => (
                    <Text key={i} className="creator-earnings__tips-line">
                      @{t.from_username || "?"} +{t.amount}
                    </Text>
                  ))}
                </View>
              )}
              <Button variant="primary" block onClick={() => Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.wallet })}>
                {e.goFiatWallet}
              </Button>
              <Button variant="ghost" block onClick={() => Taro.navigateTo({ url: `${STACK_PAGE_ROUTES.settings}?section=credits` })}>
                {e.goCreditsDetail}
              </Button>
              <Button variant="ghost" block onClick={() => Taro.navigateTo({ url: STACK_PAGE_ROUTES.pricing })}>
                {e.earningsPricingCta}
              </Button>
            </>
          )}
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
