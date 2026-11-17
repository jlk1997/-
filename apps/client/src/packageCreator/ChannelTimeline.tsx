import { View, Text } from "@tarojs/components";
import { clsx } from "../utils/clsx";
import { connectorEventLabel, isLiveDelivery, type DeliveryRow } from "./lib";
import "./JourneyProgress.scss";

const CONNECTOR_STEPS = [
  { id: "open", events: ["opening", "portal_queued"] },
  { id: "fill", events: ["fields_filled"] },
  { id: "attach", events: ["master_attached", "planted", "master_planted"] },
  { id: "submit", events: ["submitted"] },
  { id: "receipt", events: ["receipt"] },
] as const;

const STEP_LABEL_KEYS = ["timelineOpen", "timelineFill", "timelineAttach", "timelineSubmit", "timelineReceipt"] as const;

export function deliveryStageIndex(deliveries: DeliveryRow[]) {
  if (!deliveries.length) return 0;
  const keys = deliveries.map((d) => d.user_status || d.status);
  const anyLive = deliveries.some((d) => isLiveDelivery(d));
  if (deliveries.every((d) => isLiveDelivery(d) || d.status === "taken_down") && anyLive) {
    return 3;
  }
  if (keys.some((key) => ["ops_queue", "ops_handling", "in_review", "awaiting_manual", "needs_upload"].includes(key || ""))) {
    return 2;
  }
  if (keys.some((key) => ["session_running", "assisting", "needs_retry"].includes(key || ""))) {
    return 1;
  }
  if (deliveries.some((d) => d.status === "live")) {
    return 2;
  }
  return 0;
}

export function connectorStepIndex(deliveries: DeliveryRow[]) {
  const events = deliveries.flatMap((row) => (row.submissions || []).map((item) => String(item.event || "")));
  if (deliveries.some((row) => isLiveDelivery(row)) || events.includes("receipt")) return 5;
  for (let i = CONNECTOR_STEPS.length - 1; i >= 0; i -= 1) {
    if (CONNECTOR_STEPS[i].events.some((event) => events.includes(event))) return i + 1;
  }
  if (deliveries.some((row) => ["session_running", "assisting", "needs_retry"].includes(row.user_status || row.status || ""))) {
    return 1;
  }
  return 0;
}

export function connectorStepNowLabel(deliveries: DeliveryRow[], labels: Record<string, string>) {
  const actionable = deliveries.filter((row) => row.automation_level !== "metrics_only" && row.status !== "metrics_only");
  const step = connectorStepIndex(actionable.length ? actionable : deliveries);
  if (step <= 0) return "";
  const key = STEP_LABEL_KEYS[Math.min(step, STEP_LABEL_KEYS.length) - 1];
  return labels[key] || "";
}

export function ChannelTimeline({
  deliveries,
  labels,
}: {
  deliveries: DeliveryRow[];
  labels: { handoff: string; assisting: string; ops: string; live: string } & Record<string, string>;
}) {
  const current = deliveryStageIndex(deliveries);
  const step = connectorStepIndex(deliveries);
  const stages = [
    { id: "handoff", label: labels.handoff },
    { id: "assisting", label: labels.assisting },
    { id: "ops", label: labels.ops },
    { id: "live", label: labels.live },
  ];
  const steps = CONNECTOR_STEPS.map((item) => ({
    id: item.id,
    label:
      item.id === "open"
        ? labels.timelineOpen || connectorEventLabel("opening", labels)
        : item.id === "fill"
          ? labels.timelineFill || connectorEventLabel("fields_filled", labels)
          : item.id === "attach"
            ? labels.timelineAttach || connectorEventLabel("master_attached", labels)
            : item.id === "submit"
              ? labels.timelineSubmit || connectorEventLabel("submitted", labels)
              : labels.timelineReceipt || connectorEventLabel("receipt", labels),
  }));
  const showSteps = deliveries.some(
    (row) =>
      row.automation_level !== "metrics_only" &&
      row.status !== "metrics_only" &&
      ((row.submissions || []).length > 0 ||
        ["session_wait", "session_running", "assisting", "needs_retry", "in_review"].includes(row.user_status || row.status || "")),
  );
  return (
    <View>
      {showSteps ? null : (
      <View className="creator-journey">
        {stages.map((stage, i) => {
          const last = i === stages.length - 1;
          const done = current > i;
          const on = current === i;
          return (
            <View key={stage.id} className="creator-journey__item">
              <View className="creator-journey__rail">
                <View className={clsx("creator-journey__node", done && "creator-journey__node--done", on && "creator-journey__node--current")}>
                  <Text className="creator-journey__num">{done ? "✓" : String(i + 1)}</Text>
                </View>
                {!last && <View className={clsx("creator-journey__line", done && "creator-journey__line--on")} />}
              </View>
              <Text className={clsx("creator-journey__label", (done || on) && "creator-journey__label--on")}>{stage.label}</Text>
            </View>
          );
        })}
      </View>
      )}
      {showSteps && connectorStepNowLabel(deliveries, labels) ? (
        <Text className="creator-journey__now">
          {(labels.timelineNow || "{step}").replace("{step}", connectorStepNowLabel(deliveries, labels))}
        </Text>
      ) : null}
      {showSteps ? (
        <View className="creator-journey creator-journey--steps">
          {steps.map((item, i) => {
            const last = i === steps.length - 1;
            const done = step > i;
            const on = step === i + 1 || (step === 0 && i === 0);
            return (
              <View key={item.id} className="creator-journey__item">
                <View className="creator-journey__rail">
                  <View className={clsx("creator-journey__node", done && "creator-journey__node--done", on && "creator-journey__node--current")}>
                    <Text className="creator-journey__num">{done ? "✓" : String(i + 1)}</Text>
                  </View>
                  {!last && <View className={clsx("creator-journey__line", done && "creator-journey__line--on")} />}
                </View>
                <Text className={clsx("creator-journey__label", (done || on) && "creator-journey__label--on")}>{item.label}</Text>
              </View>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}
