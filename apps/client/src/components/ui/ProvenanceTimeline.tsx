import { View, Text } from "@tarojs/components";
import { Icon, type IconName } from "./Icon";
import { clsx } from "../../utils/clsx";
import "./ProvenanceTimeline.scss";

type Step = {
  kind?: string;
  type?: string;
  model?: unknown;
  created_at?: unknown;
  music_request?: {
    pack_id?: string;
    graph_hash?: string;
    exit?: string;
    not_store_multitrack?: boolean;
    intensity?: number;
  } | null;
};

type Props = {
  steps: Step[];
  stepLabel: string;
  modelLabel: string;
  workbenchLabel?: string;
  workbenchHint?: string;
};

function stepIcon(kind: string): IconName {
  const k = kind.toLowerCase();
  if (k.includes("workbench") || k.includes("beautify")) return "flask";
  if (k.includes("remix")) return "remix";
  if (k.includes("cover")) return "music";
  if (k.includes("generat")) return "create";
  if (k.includes("embed") || k.includes("ingest")) return "feed";
  return "music";
}

export function ProvenanceTimeline({ steps, stepLabel, modelLabel, workbenchLabel, workbenchHint }: Props) {
  return (
    <View className="prov-timeline">
      {steps.map((step, i) => {
        const raw = String(step.kind || step.type || `${stepLabel} ${i + 1}`);
        const isWorkbench = raw.toLowerCase() === "workbench";
        const kind = isWorkbench && workbenchLabel ? workbenchLabel : raw;
        const req = step.music_request;
        const isLast = i === steps.length - 1;
        return (
          <View key={i} className="prov-timeline__item">
            <View className="prov-timeline__rail">
              <View className={clsx("prov-timeline__node", i === 0 && "prov-timeline__node--start", isLast && "prov-timeline__node--end")}>
                <Icon name={stepIcon(raw)} size="sm" accent />
              </View>
              {!isLast && <View className="prov-timeline__line" />}
            </View>
            <View className="prov-timeline__card">
              <Text className="prov-timeline__kind">{kind}</Text>
              {isWorkbench && workbenchHint ? <Text className="prov-timeline__meta">{workbenchHint}</Text> : null}
              {req?.exit ? <Text className="prov-timeline__meta">{req.exit}</Text> : null}
              {req?.graph_hash ? <Text className="prov-timeline__meta">{String(req.graph_hash).slice(0, 12)}</Text> : null}
              {req?.pack_id ? <Text className="prov-timeline__meta">{String(req.pack_id).slice(0, 8)}</Text> : null}
              {req?.not_store_multitrack ? <Text className="prov-timeline__meta">一首立体声</Text> : null}
              {step.model != null && (
                <Text className="prov-timeline__meta">
                  {modelLabel}
                  {String(step.model)}
                </Text>
              )}
              {step.created_at != null && (
                <Text className="prov-timeline__meta">{String(step.created_at).slice(0, 16).replace("T", " ")}</Text>
              )}
            </View>
          </View>
        );
      })}
    </View>
  );
}
