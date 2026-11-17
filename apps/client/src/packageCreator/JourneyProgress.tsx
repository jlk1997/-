import { View, Text } from "@tarojs/components";
import { clsx } from "../utils/clsx";
import "./JourneyProgress.scss";

export type JourneyStep = {
  id: string;
  label: string;
  done?: boolean;
  current?: boolean;
};

export function JourneyProgress({
  steps,
  onStepClick,
}: {
  steps: JourneyStep[];
  onStepClick?: (id: string) => void;
}) {
  return (
    <View className="creator-journey">
      {steps.map((step, i) => {
        const last = i === steps.length - 1;
        return (
          <View
            key={step.id}
            className="creator-journey__item"
            onClick={() => onStepClick?.(step.id)}
          >
            <View className="creator-journey__rail">
              <View
                className={clsx(
                  "creator-journey__node",
                  step.done && "creator-journey__node--done",
                  step.current && "creator-journey__node--current",
                )}
              >
                <Text className="creator-journey__num">{step.done ? "✓" : String(i + 1)}</Text>
              </View>
              {!last && <View className={clsx("creator-journey__line", step.done && "creator-journey__line--on")} />}
            </View>
            <Text className={clsx("creator-journey__label", (step.done || step.current) && "creator-journey__label--on")}>
              {step.label}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

export function buildCreatorJourney(
  labels: { generate: string; release: string; stores: string; wait: string; settle: string; payout: string },
  state: {
    works: number;
    releases: number;
    delivering: boolean;
    hasReal: boolean;
    hasPayout: boolean;
    unpublishedCount?: number;
    hasLive?: boolean;
    hasLabelRelease?: boolean;
    waitingForStatement?: boolean;
  },
): JourneyStep[] {
  const unpublished = state.unpublishedCount || 0;
  const storesDone = Boolean(state.hasLive);
  const selfRelease = state.hasLabelRelease === false;
  const waitDone = Boolean(state.hasReal);
  const flags = selfRelease
    ? [state.works > 0, state.releases > 0 && unpublished === 0, storesDone, state.hasPayout]
    : [
        state.works > 0,
        state.releases > 0 && unpublished === 0,
        storesDone,
        waitDone,
        waitDone,
        state.hasPayout,
      ];
  const firstOpen = flags.findIndex((v) => !v);
  const keys = selfRelease
    ? [
        { id: "generate", label: labels.generate },
        { id: "release", label: labels.release },
        { id: "stores", label: labels.stores },
        { id: "payout", label: labels.payout },
      ]
    : [
        { id: "generate", label: labels.generate },
        { id: "release", label: labels.release },
        { id: "stores", label: labels.stores },
        { id: "wait", label: labels.wait },
        { id: "settle", label: labels.settle },
        { id: "payout", label: labels.payout },
      ];
  return keys.map((k, i) => ({
    ...k,
    done: flags[i],
    current: firstOpen === i || (firstOpen < 0 && i === keys.length - 1),
  }));
}
