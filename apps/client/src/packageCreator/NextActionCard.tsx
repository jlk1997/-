import { View, Text, Image } from "@tarojs/components";
import "./creator.scss";
import { hapticLight } from "../utils/haptic";

type Props = {
  kicker: string;
  title: string;
  hint: string;
  go: string;
  who?: string;
  park?: string;
  urgent?: boolean;
  waiting?: boolean;
  chips?: string[];
  coverUrl?: string;
  onClick: () => void;
};

export function NextActionCard({ kicker, title, hint, go, who, park, urgent, waiting, chips, coverUrl, onClick }: Props) {
  const tone = urgent ? "urgent" : waiting ? "wait" : "default";
  return (
    <View
      className={tone === "default" ? "creator-next" : `creator-next creator-next--${tone}`}
      onClick={() => {
        hapticLight();
        onClick();
      }}
    >
      {coverUrl ? <Image className="creator-next__cover" src={coverUrl} mode="aspectFill" /> : null}
      <View className="creator-next__copy">
        <Text className="creator-next__kicker">{kicker}</Text>
        <Text className="creator-next__title">{title}</Text>
        {hint ? <Text className="creator-next__hint">{hint}</Text> : null}
        {who || park ? (
          <Text className="creator-next__park">{[who, park].filter(Boolean).join(" · ")}</Text>
        ) : null}
        {chips && chips.length > 0 ? (
          <View className="creator-next__chips">
            {chips.map((chip) => (
              <Text key={chip} className="creator-next__chip">
                {chip}
              </Text>
            ))}
          </View>
        ) : null}
      </View>
      <Text className="creator-next__go">{waiting ? "…" : go}</Text>
    </View>
  );
}
