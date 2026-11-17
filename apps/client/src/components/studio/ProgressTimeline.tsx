import { View, Text } from "@tarojs/components";
import { clsx } from "../../utils/clsx";
import "./ProgressTimeline.scss";

export type ProgressStep = {
  id: string;
  label: string;
};

type Props = {
  steps: ProgressStep[];
  current: number;
  className?: string;
};

export function ProgressTimeline({ steps, current, className }: Props) {
  return (
    <View className={clsx("progress-timeline", className)}>
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <View key={step.id} className="progress-timeline__item">
            <View className="progress-timeline__rail">
              {i > 0 && <View className={clsx("progress-timeline__line", (done || active) && "progress-timeline__line--on")} />}
              <View
                className={clsx(
                  "progress-timeline__node",
                  done && "progress-timeline__node--done",
                  active && "progress-timeline__node--active"
                )}
              >
                {done ? <Text className="progress-timeline__check">✓</Text> : <Text className="progress-timeline__num">{i + 1}</Text>}
              </View>
            </View>
            <Text className={clsx("progress-timeline__label", active && "progress-timeline__label--active", done && "progress-timeline__label--done")}>
              {step.label}
            </Text>
          </View>
        );
      })}
    </View>
  );
}
