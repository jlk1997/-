import { View, Text } from "@tarojs/components";
import { Icon, type IconName } from "../ui/Icon";
import { clsx } from "../../utils/clsx";
import "./NotificationCard.scss";

const TYPE_ICONS: Record<string, IconName> = {
  remix_done: "remix",
  new_follower: "profile",
  job_completed: "music",
  job_failed: "stop",
  post_liked: "heartFilled",
  post_commented: "comment",
  duel_invite: "remix",
  duel_accepted: "remix",
  duel_result: "flag",
  mention: "comment",
  challenge_award: "flag",
  challenge_ending: "flag",
  tip_received: "heartFilled",
  creator_weekly: "feed",
  radio_trial_ended: "music",
  radio_trial_ending: "music",
  radio_listen_settled: "music",
  distribution_status: "share",
  settlement_ready: "sigil",
  settlement_draft: "sigil",
  withdrawal_update: "grimoire",
  withdrawal_paid: "grimoire",
  release_hint: "share",
  release_auto_submitted: "share",
  sync_order: "sigil",
  low_credits: "sparkle",
  subscription_expiring: "info",
  ops_sla: "flag",
  payout_day: "grimoire",
  seat_challenge: "profile",
};

function iconFor(type: string): IconName {
  if (TYPE_ICONS[type]) return TYPE_ICONS[type];
  if (type.startsWith("recall_")) return "sparkle";
  return "bell";
}

function toneFor(type: string): "accent" | "info" | "warm" | "danger" {
  if (TYPE_TONES[type]) return TYPE_TONES[type];
  if (type.startsWith("recall_")) return "warm";
  if (type === "ops_sla" || type === "seat_challenge") return "warm";
  if (type === "payout_day") return "accent";
  return "accent";
}

const TYPE_TONES: Record<string, "accent" | "info" | "warm" | "danger"> = {
  remix_done: "info",
  new_follower: "accent",
  job_completed: "accent",
  job_failed: "danger",
  post_liked: "warm",
  post_commented: "info",
  duel_invite: "accent",
  duel_accepted: "info",
  duel_result: "warm",
  mention: "info",
  challenge_award: "accent",
  challenge_ending: "warm",
  tip_received: "warm",
  creator_weekly: "info",
  radio_trial_ended: "accent",
  radio_trial_ending: "warm",
  radio_listen_settled: "accent",
  distribution_status: "info",
  settlement_ready: "accent",
  settlement_draft: "info",
  withdrawal_update: "warm",
  withdrawal_paid: "accent",
  release_hint: "accent",
  release_auto_submitted: "info",
  sync_order: "warm",
  low_credits: "warm",
  subscription_expiring: "warm",
  ops_sla: "warm",
  payout_day: "accent",
  seat_challenge: "warm",
};

type Props = {
  type: string;
  message: string;
  time?: string;
  unread?: boolean;
  onClick?: () => void;
};

export function NotificationCard({ type, message, time, unread, onClick }: Props) {
  const icon = iconFor(type);
  const tone = toneFor(type);

  return (
    <View className={clsx("notification-card", unread && "notification-card--unread", onClick && "notification-card--clickable")} onClick={onClick}>
      <View className={clsx("notification-card__icon", `notification-card__icon--${tone}`)}>
        <Icon name={icon} accent size="md" />
      </View>
      <View className="notification-card__body">
        <Text className="notification-card__message">{message}</Text>
        {time && <Text className="notification-card__time">{time}</Text>}
      </View>
      {unread && <View className="notification-card__dot" />}
      {onClick && <Text className="notification-card__arrow">›</Text>}
    </View>
  );
}
