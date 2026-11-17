import { View, Text, Image } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { Button, Icon, Tag } from "../ui";
import { usePlayerTransport } from "../../contexts/PlayerProvider";
import { startSameStyle } from "../../utils/sameStyleNav";
import { openWorkDetail } from "../../utils/workNav";
import { hapticLight } from "../../utils/haptic";
import "./SameStyleWall.scss";

export type SameStyleWallItem = {
  id: string;
  title: string;
  cover_url?: string;
  audio_url?: string;
  moods?: string[];
  genres?: string[];
  owner_username?: string;
};

type Props = {
  works: SameStyleWallItem[];
  loading?: boolean;
  empty?: boolean;
  error?: boolean;
  onRetry?: () => void;
};

export function SameStyleWall({ works, loading, empty, error, onRetry }: Props) {
  const { copy } = useLocale();
  const { playTrack, currentTrackId, isPlaying } = usePlayerTransport();
  const d = copy.discoverUi;

  function playWork(item: SameStyleWallItem) {
    hapticLight();
    if (!item.audio_url) {
      openWorkDetail(item.id);
      return;
    }
    const queue = works
      .filter((row) => row.audio_url)
      .map((row) =>
        workToPlayerTrack(
          { id: row.id, title: row.title, audio_url: row.audio_url as string, cover_url: row.cover_url },
          { source: "feed" },
        ),
      );
    playTrack(
      workToPlayerTrack({ id: item.id, title: item.title, audio_url: item.audio_url, cover_url: item.cover_url }, { source: "feed" }),
      { queue, navigate: false },
    );
  }

  if (loading) {
    return (
      <View className="same-style-wall">
        <View className="same-style-wall__head">
          <Text className="same-style-wall__title">{d.sameStyleWallTitle}</Text>
        </View>
        <View className="same-style-wall__row">
          {[0, 1, 2].map((i) => (
            <View key={i} className="same-style-wall__card same-style-wall__card--skeleton" />
          ))}
        </View>
      </View>
    );
  }

  if (error && !works.length) {
    return (
      <View className="same-style-wall same-style-wall--empty">
        <Text className="same-style-wall__title">{d.sameStyleWallTitle}</Text>
        <Text className="same-style-wall__hint">{d.loadError}</Text>
        {onRetry ? (
          <Button size="sm" variant="ghost" onClick={onRetry}>
            {d.retry}
          </Button>
        ) : null}
      </View>
    );
  }

  if (!works.length) {
    if (!empty) return null;
    return (
      <View className="same-style-wall same-style-wall--empty">
        <Text className="same-style-wall__title">{d.sameStyleWallTitle}</Text>
        <Text className="same-style-wall__hint">{d.sameStyleWallEmpty}</Text>
        <Text className="same-style-wall__empty-desc">{d.sameStyleWallEmptyDesc}</Text>
      </View>
    );
  }

  return (
    <View className="same-style-wall">
      <View className="same-style-wall__head">
        <Text className="same-style-wall__title">{d.sameStyleWallTitle}</Text>
      </View>
      <View className="same-style-wall__row">
        {works.slice(0, 6).map((w) => {
          const playing = currentTrackId === w.id && isPlaying;
          const chips = [...(w.moods || []), ...(w.genres || [])].slice(0, 2);
          return (
            <View key={w.id} className={playing ? "same-style-wall__card same-style-wall__card--playing" : "same-style-wall__card"}>
              <View className="same-style-wall__cover-wrap" onClick={() => playWork(w)}>
                {w.cover_url ? (
                  <Image className="same-style-wall__cover" src={w.cover_url} mode="aspectFill" lazyLoad />
                ) : (
                  <View className="same-style-wall__cover same-style-wall__cover--empty" />
                )}
                <View className="same-style-wall__play">
                  <Icon name="play" size="sm" tone="dark" />
                  <Text className="same-style-wall__play-label">{playing ? d.sameStylePlaying : d.sameStyleListen}</Text>
                </View>
                <View
                  className="same-style-wall__same"
                  onClick={(ev) => {
                    ev.stopPropagation();
                    hapticLight();
                    startSameStyle(w.id, w.title);
                  }}
                >
                  <Text className="same-style-wall__same-text">{copy.derivative.startSameStyle}</Text>
                </View>
              </View>
              <Text className="same-style-wall__name" onClick={() => openWorkDetail(w.id)}>
                {w.title}
              </Text>
              {w.owner_username ? <Text className="same-style-wall__author">@{w.owner_username}</Text> : null}
              {chips.length > 0 && (
                <View className="same-style-wall__chips">
                  {chips.map((chip) => (
                    <Tag key={chip}>{chip}</Tag>
                  ))}
                </View>
              )}
            </View>
          );
        })}
      </View>
    </View>
  );
}
