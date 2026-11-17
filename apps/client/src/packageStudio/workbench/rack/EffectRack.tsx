import { View, Text } from "@tarojs/components";
import { Button } from "../../../components/ui";
import { NodeKnobs } from "../shared";
import { LANE_LABEL, isWeapp, type Node } from "../types";
import type { WorkbenchModel } from "../hooks/useWorkbenchSession";

export function EffectRack({ model }: { model: WorkbenchModel }) {
  const w = model.w;
  return (
    <View className="wb__rack">
      {model.variant === "pro" && !model.rackOpen && model.nodes.length > 0 && (
        <Button size="sm" variant="secondary" onClick={() => model.setRackOpen(true)}>
          {w.openRack}
        </Button>
      )}
      {(model.rackOpen || model.variant === "lite") && model.nodes.length > 0 && (
        <>
          <Text className="wb__section">{w.knobsTitle}</Text>
          <Text className="typo-meta">{w.knobsHint}</Text>
          {model.nodes.map((node: Node) => (
            <NodeKnobs key={node.id} node={node} labels={w} onChange={(params) => void model.patchNode(node.id, params)} onRemove={() => void model.removeNode(node.id)} />
          ))}
        </>
      )}
      {model.variant === "pro" && !isWeapp && (
        <View className="wb__ai">
          <Text className="typo-meta">{w.selectedLane.replace("{name}", w[LANE_LABEL[model.lanes.find((row) => row.id === model.selectedLaneId)?.kind || "master"] || "laneMaster"])}</Text>
          <View className="wb__ai-row">
            <Button size="sm" variant="ghost" onClick={() => void model.addNode("eq")}>
              {w.eq}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void model.addNode("compress")}>
              {w.compress}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void model.addNode("reverb")}>
              {w.reverb}
            </Button>
          </View>
          <Text className="typo-meta">{w.aiHonesty}</Text>
          <View className="wb__ai-row">
            <Button size="sm" variant="ghost" onClick={() => void model.addAi("ai_denoise")}>
              {w.addAiDenoise}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void model.addAi("ai_vocal")}>
              {w.addAiVocal}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void model.addAi("ai_remaster")}>
              {w.addAiRemaster}
            </Button>
          </View>
        </View>
      )}
    </View>
  );
}
