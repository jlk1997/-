import { View, Text } from "@tarojs/components";
import { clsx } from "../../utils/clsx";
import { Button } from "../ui/Button";
import { StatusLine } from "../ui/StatusLine";
import "./WorkReleaseTimeline.scss";

export type JourneyStage = {
  stage: string;
  label: string;
  status: string;
  can_rerun?: boolean;
  has_receipt?: boolean;
};

export type JourneyNext = {
  action?: string;
  label?: string;
  hint?: string;
};

type Props = {
  stages: JourneyStage[];
  nextAction?: JourneyNext | null;
  copy: {
    title: string;
    go: string;
    waitHint: string;
    doneHint: string;
    statusDone: string;
    statusWait: string;
    statusNeed: string;
    statusLive: string;
    statusFail: string;
  };
  busy?: boolean;
  onAction?: (action: string) => void;
};

function toneFor(status: string, hasReceipt?: boolean): "done" | "active" | "wait" | "error" {
  const s = (status || "").toLowerCase();
  if (s === "live" && hasReceipt === false) return "active";
  if (["completed", "passed", "live", "earning", "ready", "done"].includes(s)) return "done";
  if (["degraded", "failed", "rejected"].includes(s)) return "error";
  if (["in_progress", "pending", "submitting", "publishing"].includes(s)) return "active";
  return "wait";
}

function statusLabel(status: string, copy: Props["copy"], hasReceipt?: boolean) {
  const tone = toneFor(status, hasReceipt);
  if (tone === "done") {
    if (status === "live" && hasReceipt !== false) return copy.statusLive;
    return copy.statusDone;
  }
  if (tone === "error") return copy.statusFail;
  if (tone === "active") return copy.statusNeed;
  return copy.statusWait;
}

export function WorkReleaseTimeline({ stages, nextAction, copy, busy, onAction }: Props) {
  const action = nextAction?.action || "";
  const waiting = action === "wait" || action === "wait_revenue" || action === "wait_review";
  const finished = action === "done";
  const actionable = Boolean(action && onAction && !waiting && !finished && action !== "generate");

  return (
    <View className="work-journey">
      <Text className="work-journey__title">{copy.title}</Text>
      <View className="work-journey__rail">
        {stages.map((stage, i) => {
          const tone = toneFor(stage.status, stage.has_receipt);
          const last = i === stages.length - 1;
          return (
            <View key={stage.stage} className="work-journey__row">
              <View className="work-journey__mark">
                <View className={clsx("work-journey__dot", `work-journey__dot--${tone}`)} />
                {!last ? <View className={clsx("work-journey__line", tone === "done" && "work-journey__line--on")} /> : null}
              </View>
              <View className="work-journey__body">
                <Text className="work-journey__label">{stage.label}</Text>
                <Text className={clsx("work-journey__status", `work-journey__status--${tone}`)}>
                  {statusLabel(stage.status, copy, stage.has_receipt)}
                </Text>
              </View>
            </View>
          );
        })}
      </View>
      {finished ? (
        <StatusLine tone="success" density="quiet">
          {nextAction?.label || copy.doneHint}
        </StatusLine>
      ) : waiting ? (
        <StatusLine tone="info" density="quiet">
          {nextAction?.label || copy.waitHint}
        </StatusLine>
      ) : nextAction?.label ? (
        <StatusLine tone={action === "reprocess" ? "warning" : "info"}>{nextAction.label}</StatusLine>
      ) : null}
      {actionable ? (
        <Button variant="primary" size="sm" block loading={busy} onClick={() => onAction?.(action)}>
          {copy.go}
        </Button>
      ) : null}
      {nextAction?.hint ? (
        <StatusLine tone="info" density="quiet">
          {nextAction.hint}
        </StatusLine>
      ) : null}
    </View>
  );
}
