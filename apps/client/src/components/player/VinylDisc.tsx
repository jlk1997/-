import { View, Image } from "@tarojs/components";
import { clsx } from "../../utils/clsx";
import { CoverPlate } from "../ui/CoverPlate";
import "./VinylDisc.scss";

type Props = {
  coverUrl?: string;
  title?: string;
  spinning?: boolean;
  playing?: boolean;
  className?: string;
};

export function VinylDisc({ coverUrl, title, spinning, playing, className }: Props) {
  return (
    <View className={clsx("vinyl-disc", playing && "vinyl-disc--playing", className)}>
      <View className={clsx("vinyl-disc__pulse", playing && "vinyl-disc__pulse--on")} />
      <View className={clsx("vinyl-disc__pulse vinyl-disc__pulse--2", playing && "vinyl-disc__pulse--on")} />
      <View className="vinyl-disc__grooves" />
      <View className={clsx("vinyl-disc__disc", spinning && "vinyl-disc__disc--spin")}>
        {coverUrl ? (
          <Image className="vinyl-disc__cover" src={coverUrl} mode="aspectFill" />
        ) : (
          <CoverPlate className="vinyl-disc__cover" title={title || "音"} seed={title} size="lg" />
        )}
        <View className="vinyl-disc__ring" />
        <View className="vinyl-disc__hole" />
      </View>
    </View>
  );
}
