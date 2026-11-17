import { useEffect, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { vibeApi } from "../../services/api";
import { usePlayerTransport } from "../../contexts/PlayerProvider";
import { socialPage } from "../../constants/routes";
import { Icon, LoadingSkeleton, Button } from "../ui";
import { openRadioPage } from "../../utils/navigation";
import { hapticLight } from "../../utils/haptic";
import "./MoodRadioRow.scss";

type Track = {
  work_id: string;
  post_id?: string;
  title: string;
  author: string;
  cover_url?: string;
  audio_url?: string;
  station?: string;
  featured?: boolean;
  is_mine?: boolean;
};

function displayTitle(title: string | undefined, fallback: string): string {
  const t = title?.trim();
  if (!t || t.length <= 1) return fallback;
  return t;
}

export function MoodRadioRow({ compact = false, guestFirstListen = false }: { compact?: boolean; guestFirstListen?: boolean }) {
  const { copy } = useLocale();
  const e = copy.engagementUi;
  const { playTrack, currentTrackId, isPlaying } = usePlayerTransport();
  const [tracks, setTracks] = useState<Track[]>([]);
  const [displayOnly, setDisplayOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [station, setStation] = useState("daily");

  useEffect(() => {
    setLoading(true);
    vibeApi
      .getMoodRadio(3)
      .then((res) => {
        setTracks(res.tracks || []);
        setDisplayOnly(res.usable_for_settlement !== true);
        setStation(res.station_of_day || "daily");
      })
      .catch(() => setTracks([]))
      .finally(() => setLoading(false));
    vibeApi.trackEvent("radio_daily_open").catch(() => {});
  }, []);

  if (loading) {
    return (
      <View className={compact ? "mood-radio mood-radio--compact" : "mood-radio"}>
        <LoadingSkeleton count={compact ? 1 : 2} variant="line" />
      </View>
    );
  }

  if (compact) {
    const first = tracks[0];
    const playing = Boolean(first && currentTrackId === first.work_id && isPlaying);
    return (
      <View className={guestFirstListen ? "mood-radio mood-radio--compact mood-radio--guest" : "mood-radio mood-radio--compact"}>
        <View className="mood-radio__head">
          <Icon name="music" size="sm" accent />
          <Text className="mood-radio__title">{guestFirstListen ? e.guestRadioKicker : e.radioTitle}</Text>
          <Text className="mood-radio__of-day">{e.radioOfDay}</Text>
        </View>
        {guestFirstListen ? <Text className="mood-radio__rules">{e.guestRadioHint}</Text> : null}
        <View
          className="mood-radio__item"
          onClick={() => {
            if (first) play(first, 0);
            else openRadioPage();
          }}
        >
          {first?.cover_url ? (
            <Image className="mood-radio__cover" src={first.cover_url} mode="aspectFill" lazyLoad />
          ) : (
            <View className="mood-radio__cover mood-radio__cover--fallback">
              <Icon name="music" size="sm" accent />
            </View>
          )}
          <View className="mood-radio__meta">
            <Text className="mood-radio__name" numberOfLines={1}>
              {first ? displayTitle(first.title, e.radioUntitled.replace("{n}", "1")) : e.radioEmpty}
            </Text>
            <Text className="mood-radio__author" numberOfLines={1}>
              {playing ? e.radioNowPlaying : e.tapToListen}
            </Text>
          </View>
          <View className="mood-radio__play">
            <Icon name={playing ? "pause" : "play"} size="sm" accent />
          </View>
        </View>
        <Text className="mood-radio__author" onClick={() => Taro.navigateTo({ url: socialPage("radio", { workId: first?.work_id, station }) })}>
          {e.radioOpen}
        </Text>
      </View>
    );
  }

  if (!tracks.length) {
    return (
      <View className="mood-radio mood-radio--empty">
        <View className="mood-radio__head">
          <Icon name="music" size="sm" accent />
          <Text className="mood-radio__title">{e.radioTitle}</Text>
        </View>
        <Text className="mood-radio__empty">{e.radioEmpty}</Text>
        <Text className="mood-radio__rules">{e.radioEmptyDesc}</Text>
        <Text className="mood-radio__rules">{e.creditsVsFiat}</Text>
        <View className="mood-radio__actions">
          <Button variant="primary" size="sm" block onClick={() => openRadioPage()}>
            {e.radioOpen}
          </Button>
        </View>
      </View>
    );
  }

  function play(t: Track, index: number) {
    if (!t.audio_url) {
      Taro.showToast({ title: e.radioNoAudio, icon: "none" });
      return;
    }
    hapticLight();
    const track = workToPlayerTrack(
      {
        id: t.work_id,
        title: displayTitle(t.title, e.radioUntitled.replace("{n}", String(index + 1))),
        audio_url: t.audio_url,
        cover_url: t.cover_url,
        moods: [],
      },
      {
        artist: t.author,
        source: "radio",
        station: t.station || station,
        isOwner: t.is_mine,
      },
    );
    playTrack(track, { navigate: false });
    Taro.showToast({ title: e.radioPlaying, icon: "none" });
  }

  return (
    <View className={guestFirstListen ? "mood-radio mood-radio--guest" : "mood-radio"}>
      <View className="mood-radio__head">
        <Icon name="music" size="sm" accent />
        <Text className="mood-radio__title">{guestFirstListen ? e.guestRadioKicker : e.radioTitle}</Text>
        <Text className="mood-radio__of-day">{e.radioOfDay}</Text>
        <Text className="mood-radio__author" onClick={() => Taro.navigateTo({ url: socialPage("radio") })}>
          {e.radioOpen}
        </Text>
      </View>
      {guestFirstListen ? <Text className="mood-radio__rules">{e.guestRadioHint}</Text> : <Text className="mood-radio__rules">{e.creditsVsFiat}</Text>}
      {displayOnly ? <Text className="mood-radio__rules">{e.radioDisplayOnly}</Text> : null}
      <View className="mood-radio__list">
        {tracks.map((t, i) => {
          const title = displayTitle(t.title, e.radioUntitled.replace("{n}", String(i + 1)));
          return (
            <View
              key={t.work_id}
              className={currentTrackId === t.work_id && isPlaying ? "mood-radio__item mood-radio__item--playing" : "mood-radio__item"}
              onClick={() => play(t, i)}
            >
              {t.cover_url ? (
                <Image className="mood-radio__cover" src={t.cover_url} mode="aspectFill" lazyLoad />
              ) : (
                <View className="mood-radio__cover mood-radio__cover--fallback">
                  <Icon name="music" size="sm" accent />
                </View>
              )}
              <View className="mood-radio__meta">
                <Text className="mood-radio__name" numberOfLines={1}>
                  {title}
                </Text>
                <Text className="mood-radio__author" numberOfLines={1}>
                  @{t.author || "?"}
                </Text>
              </View>
              <View className="mood-radio__play">
                <Icon name="play" size="sm" accent />
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}
