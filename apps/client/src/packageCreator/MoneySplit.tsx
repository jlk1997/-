import { View, Text } from "@tarojs/components";
import { formatFen } from "./lib";
import "./creator.scss";

type Props = {
  gross: number;
  take: number;
  net: number;
  currency?: string;
  labels: { gross: string; take: string; net: string };
};

export function MoneySplit({ gross, take, net, currency = "CNY", labels }: Props) {
  const g = Math.max(0, gross || 0);
  const t = Math.max(0, take || 0);
  const n = Math.max(0, net || 0);
  const total = g || 1;
  return (
    <View className="creator-split">
      <View className="creator-split__bar">
        <View className="creator-split__net" style={{ width: `${Math.min(100, (n / total) * 100)}%` }} />
        <View className="creator-split__take" style={{ width: `${Math.min(100, (t / total) * 100)}%` }} />
      </View>
      <View className="creator-split__legend">
        <Text className="creator-split__item">
          {labels.gross} {formatFen(g, currency)}
        </Text>
        <Text className="creator-split__item creator-split__item--take">
          {labels.take} {formatFen(t, currency)}
        </Text>
        <Text className="creator-split__item creator-split__item--net">
          {labels.net} {formatFen(n, currency)}
        </Text>
      </View>
    </View>
  );
}
