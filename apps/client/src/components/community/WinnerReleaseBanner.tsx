import { useEffect, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { vibeApi } from "../../services/api";
import { isLoggedIn } from "../../utils/auth";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { goShipBand } from "../../packageCreator/nextActionNav";
import { openWorkbench } from "../../utils/workbenchNav";
import { Button } from "../ui";
import "./WinnerReleaseBanner.scss";

type Unpublished = {
  work_id: string;
  title?: string;
  cover_url?: string;
  qc_ready?: boolean;
  from_workbench?: boolean;
  priority?: { reason?: string } | null;
};

export function WinnerReleaseBanner() {
  const { copy } = useLocale();
  const d = copy.discoverUi;
  const credits = useCreditsOptional();
  const [work, setWork] = useState<Unpublished | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [tick, setTick] = useState(0);

  const dspOff = credits?.dspDistribution === false;

  useEffect(() => {
    if (!isLoggedIn()) return;
    setLoadError(false);
    vibeApi
      .getCreatorHub()
      .then((hub) => {
        const raw = hub.unpublished_works;
        const rows = (Array.isArray(raw) ? raw : []).filter(
          (row: Unpublished) => row.priority?.reason === "duel_winner" || row.priority?.reason === "challenge_winner",
        );
        setWork(rows[0] || null);
        setLoadError(false);
      })
      .catch(() => {
        setWork(null);
        setLoadError(true);
      });
  }, [credits?.dspDistribution, tick]);

  if (loadError) {
    return (
      <View className="winner-banner">
        <View className="winner-banner__cover winner-banner__cover--empty" />
        <View className="winner-banner__body">
          <Text className="winner-banner__kicker">{d.winnerBannerTitle}</Text>
          <Text className="winner-banner__title">{d.loadError}</Text>
        </View>
        <Button size="sm" variant="ghost" onClick={() => setTick((n) => n + 1)}>
          {d.retry}
        </Button>
      </View>
    );
  }

  if (!work) return null;

  return (
    <View className={`winner-banner${work.from_workbench === false ? " winner-banner--bench" : ""}`}>
      {work.cover_url ? (
        <Image className="winner-banner__cover" src={work.cover_url} mode="aspectFill" lazyLoad />
      ) : (
        <View className="winner-banner__cover winner-banner__cover--empty" />
      )}
      <View className="winner-banner__body">
        <Text className="winner-banner__kicker">{d.winnerBannerTitle}</Text>
        <Text className="winner-banner__title">
          {dspOff
            ? copy.creatorUi.featureOff
            : work.from_workbench === false
              ? copy.creatorUi.nextBeautifyHint
              : d.winnerBannerHint.replace("{title}", work.title || copy.creatorUi.releaseUntitled)}
        </Text>
      </View>
      {dspOff ? (
        <Button size="sm" variant="ghost" onClick={() => Taro.navigateTo({ url: "/packageCreator/pages/help/index" })}>
          {copy.creatorUi.helpTitle}
        </Button>
      ) : work.from_workbench === false ? (
        <Button size="sm" variant="primary" onClick={() => openWorkbench(work.work_id)}>
          {copy.generation.reveal.beautify}
        </Button>
      ) : (
      <Button
        size="sm"
        variant="primary"
        onClick={() => goShipBand(work.work_id)}
      >
        {d.winnerBannerGo}
      </Button>
      )}
    </View>
  );
}
