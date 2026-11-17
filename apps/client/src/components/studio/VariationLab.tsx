import { useState } from "react";
import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { usePlayerTransport } from "../../contexts/PlayerProvider";
import { Button, Icon } from "../ui";
import { hapticLight } from "../../utils/haptic";
import "./VariationLab.scss";

export type VariationWork = {
  id: string;
  title: string;
  audio_url?: string;
  hls_url?: string;
  cover_url?: string;
};

type Props = {
  works: VariationWork[];
  selectedId?: string | null;
  onSelect?: (workId: string) => void;
  onHeard?: (workId: string) => void;
  heardIds?: Set<string>;
};

export function VariationLab({ works, selectedId, onSelect, onHeard, heardIds }: Props) {
  const { copy } = useLocale();
  const v = copy.variationLabUi;
  const lab = copy.variationLab;
  const { playTrack, currentTrackId, isPlaying } = usePlayerTransport();
  const [localHeard, setLocalHeard] = useState<Set<string>>(new Set());
  const heard = heardIds || localHeard;
  if (!works.length) return null;

  function playWork(w: VariationWork) {
    if (!w.audio_url) return;
    hapticLight();
    const next = new Set(heard).add(w.id);
    if (!heardIds) setLocalHeard(next);
    onHeard?.(w.id);
    const queue = works
      .filter((row) => row.audio_url)
      .map((row) =>
        workToPlayerTrack(
          { id: row.id, title: row.title, audio_url: row.audio_url as string, cover_url: row.cover_url },
          { source: "generation", isOwner: true },
        ),
      );
    const idx = queue.findIndex((t) => t.id === w.id);
    playTrack(queue[idx] || queue[0], { queue, startIndex: Math.max(0, idx), navigate: false });
  }

  return (
    <View className="variation-lab">
      <Text className="variation-lab__title">{v.title}</Text>
      <View className="variation-lab__grid">
        {works.map((w) => {
          const playing = currentTrackId === w.id && isPlaying;
          const wasHeard = heard.has(w.id);
          return (
            <View
              key={w.id}
              className={`variation-lab__cell ${selectedId === w.id ? "variation-lab__cell--active" : ""}`}
              onClick={() => onSelect?.(w.id)}
            >
              <Text className="variation-lab__label">{w.title}</Text>
              {w.audio_url ? (
                <Button
                  size="sm"
                  block
                  variant={playing ? "primary" : wasHeard ? "secondary" : "ghost"}
                  onClick={(e) => {
                    e.stopPropagation();
                    playWork(w);
                  }}
                >
                  <Icon name={playing ? "pause" : "play"} size="sm" /> {playing ? lab.playing : lab.listen}
                </Button>
              ) : null}
            </View>
          );
        })}
      </View>
    </View>
  );
}
