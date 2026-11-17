import { useEffect, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { vibeApi } from "../../services/api";
import { isLoggedIn } from "../../utils/auth";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { openWorkbench } from "../../utils/workbenchNav";
import { openRadioPage, openStackPage } from "../../utils/navigation";
import { commercePage, creatorPage } from "../../constants/routes";
import { goShipBand } from "../../packageCreator/nextActionNav";
import { Button } from "../ui";
import "./WinnerReleaseBanner.scss";

type WeekDrop = {
  station?: string;
  station_name?: string;
  why?: string;
  next_action?: string;
  work?: { work_id: string; title?: string; cover_url?: string; qc_ready?: boolean; from_workbench?: boolean } | null;
};

export function WeekDropBanner() {
  const { copy } = useLocale();
  const d = copy.discoverUi;
  const c = copy.creatorUi;
  const credits = useCreditsOptional();
  const [drop, setDrop] = useState<WeekDrop | null>(null);
  const [trialBusy, setTrialBusy] = useState(false);

  const dspOff = credits?.dspDistribution === false;

  useEffect(() => {
    if (!isLoggedIn()) return;
    vibeApi
      .getReleaseCalendar()
      .then((cal) => {
        if (cal.week_drop?.work?.work_id) setDrop(cal.week_drop);
        else setDrop(null);
      })
      .catch(() => setDrop(null));
  }, [credits?.dspDistribution]);

  const work = drop?.work;
  if (!drop || !work?.work_id) return null;
  const isTrial = drop.next_action === "radio_trial";
  const isWatch = drop.next_action === "watch_trial";
  const isSync = drop.next_action === "sync";
  const isWallet = drop.next_action === "wallet";
  const isStores = drop.next_action === "stores";
  const needsBeautify = drop.next_action === "beautify" || work.from_workbench === false;

  function startTrial() {
    setTrialBusy(true);
    openRadioPage({ workId: work.work_id, station: drop.station, trial: "1" });
    void vibeApi
      .startRadioTrial(work.work_id, drop.station)
      .then((trial) => {
        Taro.showToast({ title: c.radioTrialLive, icon: "success" });
        const station = typeof (trial as { station?: string }).station === "string" ? (trial as { station?: string }).station : drop.station;
        const workId = (trial as { work_id?: string }).work_id || work.work_id;
        setDrop(null);
        if (workId !== work.work_id) openRadioPage({ workId, station });
      })
      .catch(() => {
        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
      })
      .finally(() => setTrialBusy(false));
  }

  return (
    <View className={`winner-banner${needsBeautify ? " winner-banner--bench" : ""}`}>
      {work.cover_url ? (
        <Image className="winner-banner__cover" src={work.cover_url} mode="aspectFill" lazyLoad />
      ) : (
        <View className="winner-banner__cover winner-banner__cover--empty" />
      )}
      <View
        className="winner-banner__body"
        onClick={() => openRadioPage({ workId: work.work_id, station: drop.station })}
      >
        <Text className="winner-banner__kicker">{d.weekDropTitle}</Text>
        <Text className="winner-banner__title">
          {needsBeautify
            ? c.nextBeautifyHint
            : `${d.weekDropHint.replace("{title}", work.title || c.releaseUntitled)}${drop.station_name ? ` · ${drop.station_name}` : ""}`}
        </Text>
      </View>
      <View className="winner-banner__actions">
        {isTrial ? (
          <Button size="sm" variant="primary" loading={trialBusy} onClick={() => void startTrial()}>
            {c.radioTrialStart}
          </Button>
        ) : null}
        {isWatch ? (
          <Button
            size="sm"
            variant="primary"
            onClick={() => openRadioPage({ workId: work.work_id, station: drop.station })}
          >
            {c.goRadio}
          </Button>
        ) : null}
        {needsBeautify && !isTrial && !isWatch ? (
          <Button size="sm" variant="primary" onClick={() => openWorkbench(work.work_id)}>
            {copy.generation.reveal.beautify}
          </Button>
        ) : isStores ? (
          <Button
            size="sm"
            variant="primary"
            onClick={() => openStackPage(creatorPage("deliveries", { workId: work.work_id }))}
          >
            {c.nextStores}
          </Button>
        ) : isSync ? (
          <Button
            size="sm"
            variant="primary"
            onClick={() => openStackPage(commercePage("syncDesk", { workId: work.work_id }))}
          >
            {c.nextSync}
          </Button>
        ) : isWallet ? (
          <Button size="sm" variant="primary" onClick={() => openStackPage(creatorPage("wallet"))}>
            {c.nextWallet}
          </Button>
        ) : dspOff ? (
          <Text className="typo-meta">{c.featureOff}</Text>
        ) : isTrial || isWatch ? null : (
          <Button
            size="sm"
            variant="primary"
            onClick={() => goShipBand(work.work_id)}
          >
            {d.weekDropGo}
          </Button>
        )}
      </View>
    </View>
  );
}
