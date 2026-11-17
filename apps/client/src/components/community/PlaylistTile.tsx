import { View, Text } from "@tarojs/components";
import { Icon } from "../ui";
import "./PlaylistTile.scss";

const GRADIENTS = [
  "linear-gradient(135deg, #3a3a44, rgba(255, 255, 255, 0.2))",
  "linear-gradient(135deg, rgba(10, 132, 255, 0.55), rgba(14, 14, 22, 0.9))",
  "linear-gradient(135deg, rgba(20, 184, 166, 0.55), rgba(5, 5, 8, 0.85))",
  "linear-gradient(135deg, rgba(90, 98, 120, 0.7), rgba(10, 132, 255, 0.45))",
];

type Props = {
  title: string;
  trackCount: number;
  trackLabel: string;
  index?: number;
  onClick?: () => void;
};

export function PlaylistTile({ title, trackCount, trackLabel, index = 0, onClick }: Props) {
  const gradient = GRADIENTS[index % GRADIENTS.length];

  return (
    <View className="playlist-tile" onClick={onClick}>
      <View className="playlist-tile__cover" style={{ background: gradient }}>
        <Icon name="journey" size="lg" accent />
        <View className="playlist-tile__count-ring">
          <Text className="playlist-tile__count">{trackCount}</Text>
        </View>
      </View>
      <Text className="playlist-tile__title">{title}</Text>
      <Text className="playlist-tile__meta">{trackLabel}</Text>
    </View>
  );
}
