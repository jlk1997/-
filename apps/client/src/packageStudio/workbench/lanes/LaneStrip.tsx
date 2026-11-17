import { View, Text } from "@tarojs/components";
import { Button } from "../../../components/ui";
import { Stepper } from "../shared";
import { LANE_LABEL, isWeapp, type Lane } from "../types";
import type { WorkbenchModel } from "../hooks/useWorkbenchSession";
import { useLanePeaks } from "../engine/lanePeaks";

export function LaneStrip({ model, lite }: { model: WorkbenchModel; lite?: boolean }) {
  const w = model.w;
  const peaks = useLanePeaks();
  const lanes = model.lanes.filter((lane) => {
    if (lite) return lane.kind !== "master";
    if (!model.laneReady) return false;
    return true;
  });
  return (
    <View className={lite ? "wb__lanes wb__lanes--lite" : "wb__lanes"}>
      <Text className="wb__section">{w.lanesTitle}</Text>
      <Text className="typo-meta">
        {model.session?.edit_lanes?.label ? `${model.session.edit_lanes.label}。` : ""}
        {lite ? w.lanesLiteHint : w.lanesHonesty}
      </Text>
      {!model.laneReady && model.variant === "pro" && !isWeapp && (
        <Button size="sm" variant="ghost" loading={model.busy === "lanes"} onClick={() => void model.prepareLanes()}>
          {w.lanesPrepare}
        </Button>
      )}
      <View className={lite ? "wb__lanes-row" : "wb__lanes-grid"}>
        {lanes.map((lane: Lane) => (
          <View
            key={lane.id}
            className={`${lite ? "wb-lane wb-lane--lite" : "wb-lane"}${lane.id === model.selectedLaneId ? " is-selected" : ""}${lane.mute ? " is-mute" : ""}`}
          >
            <Text className="wb-lane__name" onClick={() => model.setSelectedLaneId(lane.id)}>
              {w[LANE_LABEL[lane.kind] || "laneOther"]}
            </Text>
            <View className="wb-lane__meter" aria-hidden>
              <View className="wb-lane__meter-fill" style={{ width: `${Math.round((peaks[lane.kind] || 0) * 100)}%` }} />
            </View>
            <View className="wb-lane__toggles">
              <Button size="sm" variant={lane.mute ? "secondary" : "ghost"} onClick={() => void model.patchLanes(model.lanes.map((row) => (row.id === lane.id ? { ...row, mute: !row.mute } : row)))}>
                {lane.mute ? w.unmute : w.mute}
              </Button>
              {!lite && (
                <Button
                  size="sm"
                  variant={lane.solo ? "secondary" : "ghost"}
                  onClick={() =>
                    void model.patchLanes(model.lanes.map((row) => (row.id === lane.id ? { ...row, solo: !row.solo, mute: false } : { ...row, solo: false })))
                  }
                >
                  {w.solo}
                </Button>
              )}
            </View>
            <Stepper label={w.gain} value={lane.gain} min={0} max={2} step={0.1} onChange={(gain) => void model.patchLanes(model.lanes.map((row) => (row.id === lane.id ? { ...row, gain } : row)))} />
            {!lite && (
              <Stepper label={w.pan} value={lane.pan} min={-1} max={1} step={0.1} onChange={(pan) => void model.patchLanes(model.lanes.map((row) => (row.id === lane.id ? { ...row, pan } : row)))} />
            )}
            {!lite && lane.kind === "vocal" && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  void model.patchLanes(
                    model.lanes.map((row) =>
                      row.id === lane.id ? { ...row, automation: [{ t: 0, v: 0 }, { t: 6, v: Number(row.gain || 1) }] } : row,
                    ),
                  )
                }
              >
                渐入
              </Button>
            )}
          </View>
        ))}
      </View>
    </View>
  );
}
