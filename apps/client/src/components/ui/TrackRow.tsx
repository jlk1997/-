import { View, Text, Image } from "@tarojs/components";
import { Icon } from "./Icon";
import { Badge } from "./Badge";
import { clsx } from "../../utils/clsx";
import "./TrackRow.scss";

type Props = {
  title: string;
  subtitle?: string;
  coverUrl?: string;
  index?: number;
  active?: boolean;
  badge?: string;
  badgeTone?: "accent" | "success" | "warning" | "danger";
  onClick?: () => void;
  onPlay?: () => void;
  onAction?: () => void;
  actionLabel?: string;
  onMenu?: () => void;
  className?: string;
};

export function TrackRow({
  title,
  subtitle,
  coverUrl,
  index,
  active,
  badge,
  badgeTone = "warning",
  onClick,
  onPlay,
  onAction,
  actionLabel,
  onMenu,
  className,
}: Props) {
  return (
    <View
      className={clsx("ui-track-row", active && "ui-track-row--active", badge && "ui-track-row--flagged", className)}
      onClick={onClick}
    >
      {index != null && <Text className="ui-track-row__index">{index}</Text>}
      {coverUrl ? (
        <Image className="ui-track-row__cover" src={coverUrl} mode="aspectFill" lazyLoad />
      ) : (
        <View className="ui-track-row__cover ui-track-row__cover--fallback">
          <Icon name="music" accent />
        </View>
      )}
      <View className="ui-track-row__info">
        <Text className="ui-track-row__title">{title}</Text>
        <View className="ui-track-row__meta">
          {subtitle ? <Text className="ui-track-row__subtitle">{subtitle}</Text> : null}
          {badge ? <Badge tone={badgeTone}>{badge}</Badge> : null}
        </View>
      </View>
      {onPlay && (
        <View
          className="ui-track-row__play"
          onClick={(e) => {
            e.stopPropagation();
            onPlay();
          }}
        >
          <Icon name="play" accent />
        </View>
      )}
      {onAction && actionLabel ? (
        <Text
          className="ui-track-row__action"
          onClick={(e) => {
            e.stopPropagation();
            onAction();
          }}
        >
          {actionLabel}
        </Text>
      ) : null}
      {onMenu && (
        <View
          className="ui-track-row__menu"
          onClick={(e) => {
            e.stopPropagation();
            onMenu();
          }}
        >
          <Icon name="more" />
        </View>
      )}
    </View>
  );
}
