import { useCallback, useEffect, useState } from "react";
import { View, Text, Image, ScrollView } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { vibeApi } from "../../services/api";
import { stackPage } from "../../constants/routes";
import { Icon, LoadingSkeleton } from "../ui";
import "./ChallengesRow.scss";

type ChallengeItem = {
  id: string;
  slug: string;
  title: string;
  hashtag?: string;
  cover_url?: string;
  participant_count?: number;
  prize_pool_credits?: number;
};

export function ChallengesRow() {
  const { copy } = useLocale();
  const ch = copy.challengesUi;
  const d = copy.discoverUi;
  const [items, setItems] = useState<ChallengeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    vibeApi
      .getChallenges()
      .then((res) => setItems((res || []).slice(0, 8)))
      .catch(() => {
        setItems([]);
        setError(true);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openHub() {
    Taro.navigateTo({ url: stackPage("challenges") });
  }

  return (
    <View className="challenges-row">
      <View className="challenges-row__head">
        <Icon name="flag" size="sm" accent />
        <Text className="challenges-row__title">{ch.rowTitle}</Text>
        <Text className="challenges-row__more" onClick={openHub}>
          {copy.socialUi.seeAll}
        </Text>
      </View>

      {loading && <LoadingSkeleton count={2} variant="line" />}

      {!loading && error && (
        <View className="challenges-row__banner challenges-row__banner--error">
          <Text className="challenges-row__banner-text">{ch.loadFail}</Text>
          <Text className="challenges-row__banner-link" onClick={() => void load()}>
            {d.retry}
          </Text>
        </View>
      )}

      {!loading && !error && items.length === 0 && (
        <View className="challenges-row__banner" onClick={openHub}>
          <Text className="challenges-row__banner-text">{ch.rowEmpty}</Text>
          <Text className="challenges-row__banner-hint">{ch.rowHint}</Text>
          <Text className="challenges-row__banner-link">{ch.rowCta} →</Text>
        </View>
      )}

      {!loading && !error && items.length > 0 && (
        <ScrollView scrollX enableFlex className="challenges-row__scroll">
          <View className="challenges-row__track">
            {items.map((item) => (
              <View
                key={item.id}
                className="challenges-row__card"
                onClick={() => Taro.navigateTo({ url: stackPage("challenge", { slug: item.slug }) })}
              >
                {item.cover_url ? (
                  <Image className="challenges-row__cover" src={item.cover_url} mode="aspectFill" lazyLoad />
                ) : (
                  <View className="challenges-row__cover challenges-row__cover--empty">
                    <Icon name="flag" size="sm" accent />
                  </View>
                )}
                <Text className="challenges-row__name" numberOfLines={1}>
                  {item.title}
                </Text>
                <Text className="challenges-row__meta" numberOfLines={1}>
                  {item.hashtag ? `#${item.hashtag}` : ch.participants.replace("{n}", String(item.participant_count || 0))}
                </Text>
              </View>
            ))}
          </View>
        </ScrollView>
      )}
    </View>
  );
}
