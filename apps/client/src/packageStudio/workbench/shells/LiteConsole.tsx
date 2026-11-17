import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { Button, ChipGroup, StatusLine } from "../../../components/ui";
import { WorkQualityCard } from "../../../components/studio/WorkQualityCard";
import { BounceDock, FlowSteps, ListenCompare, NeedRail, PackRail, Stage, intensityChip } from "../shared";
import { LivePreview } from "../engine/LivePreview";
import { isWeapp } from "../types";
import type { WorkbenchModel } from "../hooks/useWorkbenchSession";

export function LiteConsole({ model }: { model: WorkbenchModel }) {
  const w = model.w;
  const session = model.session;
  if (!session) return null;
  return (
    <View className="wb wb--lite">
      <FlowSteps model={model} />
      <Text className="wb__note">{isWeapp ? w.weappHint : w.liteShoreHint}</Text>
      {session.lane_pack_degraded ? <StatusLine tone="info" density="quiet">{w.lanePackHint}</StatusLine> : null}
      {session.desktop_edits ? <Text className="wb__note">{w.desktopEditsHint}</Text> : null}
      {session.continued_from_result ? <Text className="wb__note">{w.continuedFromMaster}</Text> : null}

      <ListenCompare model={model} />
      {isWeapp ? <Text className="typo-meta">小程序里听的是服务器片段，不是实时效果。</Text> : <LivePreview model={model} variant="lite" />}

      <Stage kicker="02" title={w.stageLook} hint={w.flowLookHint} className="wb-stage--look">
        <NeedRail model={model} embed />
        <PackRail model={model} embed />
        <Text className="wb__section">{w.intensity}</Text>
        <ChipGroup
          value={intensityChip(session.intensity)}
          onChange={(value) => void model.onIntensity(Number(value))}
          options={[
            { value: "0.4", label: w.intensitySoft },
            { value: "0.7", label: w.intensityMid },
            { value: "1", label: w.intensityFull },
            { value: "1.2", label: w.intensityHot },
            { value: "1.5", label: w.intensityMax },
          ]}
        />
      </Stage>

      {session.last_result_work_id ? (
        <View className="wb-stage">
          <WorkQualityCard workId={session.last_result_work_id} title={session.last_result_title} doorOnly onRemelt={() => void model.onRegen("remelt")} />
        </View>
      ) : null}

      <BounceDock model={model} />
      <Text
        className="wb__footnote"
        onClick={() => {
          const url = `https://superformersmusic.com/studio/mixer?work=${session.source_work_id}`;
          if (!isWeapp && typeof window !== "undefined") {
            window.open(url, "_blank");
            return;
          }
          void Taro.setClipboardData({ data: url });
        }}
      >
        {w.openDesktopMixer}
      </Text>
      <Text className="wb__footnote">{w.honesty}</Text>
    </View>
  );
}
