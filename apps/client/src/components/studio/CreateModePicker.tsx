import { useState } from "react";
import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import type { CreateMode } from "./CreateModePicker.types";
import { clsx } from "../../utils/clsx";
import { Icon, type IconName } from "../ui/Icon";
import { Button } from "../ui/Button";
import { hapticLight } from "../../utils/haptic";
import { showCoverUnavailable } from "../../utils/coverUnavailable";
import Taro from "@tarojs/taro";
import "./CreateModePicker.scss";

export type { CreateMode } from "./CreateModePicker.types";

const MODE_IDS: CreateMode[] = ["quickTrack", "playlist", "lyrics", "remix", "cover", "variation"];

const MODE_ICON: Record<CreateMode, IconName> = {
  quickTrack: "music",
  playlist: "queue",
  lyrics: "lyrics",
  remix: "remix",
  cover: "create",
  variation: "sparkle",
};

const NEED_WORK: CreateMode[] = ["remix", "cover", "variation"];

type Props = {
  value: CreateMode;
  onChange: (mode: CreateMode) => void;
  onJourney?: () => void;
  hasWorks?: boolean;
};

export function CreateModePicker({ value, onChange, onJourney, hasWorks = true }: Props) {
  const { copy } = useLocale();
  const modes = copy.studioSummary.modes;
  const desc = copy.createUi.modeDesc;
  const c = copy.createUi;
  const d = copy.derivative;
  const [expanded, setExpanded] = useState(false);

  function modeLabel(id: CreateMode) {
    const map: Record<CreateMode, string> = {
      quickTrack: modes.quickTrack,
      playlist: modes.playlist || c.modeQuickPlaylist,
      lyrics: modes.lyrics,
      remix: modes.remix,
      cover: modes.cover,
      variation: modes.variation,
    };
    return map[id];
  }

  function pick(id: CreateMode) {
    if (id === "cover") {
      showCoverUnavailable();
      return;
    }
    if (!hasWorks && NEED_WORK.includes(id)) {
      Taro.showToast({ title: c.needWorkFirst, icon: "none" });
      return;
    }
    hapticLight();
    onChange(id);
  }

  if (!expanded) {
    return (
      <View className="mode-picker mode-picker--recommend">
        <View className={clsx("mode-picker__item", "mode-picker__item--active", `mode-picker__item--${value}`)}>
          <View className="mode-picker__emoji">
            <Icon name={MODE_ICON[value]} size="sm" accent />
          </View>
          <View className="mode-picker__body">
            <Text className="mode-picker__label">{modeLabel(value)}</Text>
            <Text className="mode-picker__desc">{desc[value]}</Text>
          </View>
          <View className="mode-picker__check" />
        </View>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            hapticLight();
            setExpanded(true);
          }}
        >
          {d.tryAnother}
        </Button>
        {onJourney ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              hapticLight();
              onJourney();
            }}
          >
            {c.modeJourney}
          </Button>
        ) : null}
      </View>
    );
  }

  return (
    <View className="mode-picker">
      {MODE_IDS.map((id) => (
        <View
          key={id}
          className={clsx(
            "mode-picker__item",
            value === id && "mode-picker__item--active",
            `mode-picker__item--${id}`,
            !hasWorks && NEED_WORK.includes(id) && "mode-picker__item--locked",
          )}
          onClick={() => pick(id)}
        >
          <View className="mode-picker__emoji">
            <Icon name={MODE_ICON[id]} size="sm" accent={value === id} />
          </View>
          <View className="mode-picker__body">
            <Text className="mode-picker__label">{modeLabel(id)}</Text>
            <Text className="mode-picker__desc">{desc[id]}</Text>
          </View>
          {value === id && <View className="mode-picker__check" />}
        </View>
      ))}
      {onJourney ? (
        <View
          className="mode-picker__item mode-picker__item--journey"
          onClick={() => {
            hapticLight();
            onJourney();
          }}
        >
          <View className="mode-picker__emoji">
            <Icon name="journey" size="sm" accent />
          </View>
          <View className="mode-picker__body">
            <Text className="mode-picker__label">{c.modeJourney}</Text>
            <Text className="mode-picker__desc">{c.modeJourneyDesc}</Text>
          </View>
        </View>
      ) : null}
    </View>
  );
}
