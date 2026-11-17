import { View, Text } from "@tarojs/components";
import { Icon } from "../ui";
import { clsx } from "../../utils/clsx";
import { hapticLight } from "../../utils/haptic";
import "./BeautifyDoorCard.scss";

type Props = {
  title: string;
  hint: string;
  goLabel: string;
  songLabel?: string;
  empty?: boolean;
  className?: string;
  onClick: () => void;
};

/** Standing 美化台 door — same look on create, library, profile, and work detail. */
export function BeautifyDoorCard({ title, hint, goLabel, songLabel, empty, className, onClick }: Props) {
  return (
    <View
      className={clsx("beautify-door", empty && "beautify-door--empty", className)}
      hoverClass="beautify-door--pressed"
      onClick={() => {
        hapticLight();
        onClick();
      }}
    >
      <View className="beautify-door__icon">
        <Icon name="sparkle" size="lg" accent={!empty} muted={empty} />
      </View>
      <View className="beautify-door__body">
        <Text className="beautify-door__title">{title}</Text>
        <Text className="beautify-door__hint">{hint}</Text>
        {songLabel ? <Text className="beautify-door__song">{songLabel}</Text> : null}
      </View>
      <Text className="beautify-door__go">{goLabel} ›</Text>
    </View>
  );
}
