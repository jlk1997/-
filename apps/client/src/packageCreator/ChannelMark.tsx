import { View, Text } from "@tarojs/components";
import "./ChannelMark.scss";

const MARK: Record<string, { letter: string; bg: string }> = {
  netease: { letter: "云", bg: "#c20c0c" },
  qq_music: { letter: "Q", bg: "#31c27c" },
  kugou: { letter: "酷", bg: "#0c8cf5" },
  kuwo: { letter: "我", bg: "#ff6a00" },
  qishui: { letter: "汽", bg: "#2b6cff" },
  spotify: { letter: "S", bg: "#1db954" },
  apple_music: { letter: "", bg: "#fc3c44" },
  youtube_music: { letter: "Y", bg: "#ff0033" },
  tiktok_music: { letter: "T", bg: "#111111" },
  amazon_music: { letter: "A", bg: "#25d1da" },
  deezer: { letter: "D", bg: "#a238ff" },
  soundcloud: { letter: "SC", bg: "#ff5500" },
  bandcamp: { letter: "B", bg: "#1da0c3" },
  bilibili: { letter: "B", bg: "#00a1d6" },
  wechat_channels: { letter: "微", bg: "#07c160" },
  douyin_musician: { letter: "抖", bg: "#111111" },
  kuaishou_musician: { letter: "快", bg: "#ff4906" },
};

type Props = {
  code: string;
  size?: "sm" | "md";
};

export function ChannelMark({ code, size = "sm" }: Props) {
  const mark = MARK[code] || { letter: (code || "?").slice(0, 1).toUpperCase(), bg: "#3a3a4a" };
  return (
    <View className={`channel-mark channel-mark--${size}`} style={{ background: mark.bg }}>
      <Text className="channel-mark__letter">{mark.letter}</Text>
    </View>
  );
}
