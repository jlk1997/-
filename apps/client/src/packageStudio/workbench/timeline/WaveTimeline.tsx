import { useState } from "react";
import { View, Text } from "@tarojs/components";
import { Button } from "../../../components/ui";
import { Stepper } from "../shared";
import { LANE_LABEL, NODE_LABEL } from "../types";
import type { WorkbenchModel } from "../hooks/useWorkbenchSession";
import { ClipBlock, pct, pickTrackTime } from "./ClipLayer";
import { LaneWaveform } from "./LaneWaveform";

function rulerMarks(duration: number) {
  const span = duration > 90 ? 15 : duration > 40 ? 10 : duration > 16 ? 5 : 2;
  const marks = [0];
  for (let time = span; time < duration - 0.25; time += span) marks.push(time);
  if (duration > 0) marks.push(Number(duration.toFixed(1)));
  return marks;
}

export function WaveTimeline({ model }: { model: WorkbenchModel }) {
  const w = model.w;
  const duration = model.duration;
  const [zoom, setZoom] = useState(1);
  const waveform = model.session?.source_waveform_url || "";
  const prepared = model.laneReady ? model.lanes : model.lanes.filter((lane) => lane.kind === "master");
  const rows = prepared.length ? prepared : model.lanes.slice(0, 1);
  const regionWidth = Math.max(0.2, model.regionEnd - model.regionStart);
  function snap(time: number) {
    return Math.round(time * 10) / 10;
  }

  return (
    <View className="wb__timeline">
      <View className="wb-timeline__head" onClick={() => model.setTimelineOpen((open) => !open)}>
        <View>
          <Text className="wb-stage__kicker">{w.timelineTitle}</Text>
          <Text className="wb-timeline__toggle">{model.timelineOpen ? w.timelineCollapsed : w.timelineExpand}</Text>
        </View>
        <Text className="wb-timeline__chevron">{model.timelineOpen ? "–" : "+"}</Text>
      </View>
      {model.timelineOpen ? (
        <View className="wb-timeline" style={{ width: `${zoom * 100}%` }}>
          <Text className="typo-meta">{w.timelineWaveHint}</Text>
          <View className="wb-timeline__zoom">
            <Button size="sm" variant={zoom === 1 ? "secondary" : "ghost"} onClick={() => setZoom(1)}>1×</Button>
            <Button size="sm" variant={zoom === 2 ? "secondary" : "ghost"} onClick={() => setZoom(2)}>2×</Button>
            <Button size="sm" variant={zoom === 4 ? "secondary" : "ghost"} onClick={() => setZoom(4)}>4×</Button>
          </View>
          {!model.laneReady ? <Text className="typo-meta">{w.lanesWait}</Text> : null}
          <View className="wb-timeline__ruler">
            {rulerMarks(duration).map((time, index) => (
              <Text key={`${time}-${index}`} className="wb-timeline__tick" style={{ left: pct(time, duration) }}>
                {`${time % 1 ? time.toFixed(1) : time}s`}
              </Text>
            ))}
            {(model.session?.edit_lanes?.marks || []).map((mark) => (
              <Text key={`${mark.tag}-${mark.start}`} className="wb-timeline__tick" style={{ left: pct(mark.start || 0, duration) }}>
                {mark.tag}
              </Text>
            ))}
          </View>
          {rows.map((lane) => {
            const laneClips = model.clips.filter((clip) => clip.lane === lane.id || clip.lane === lane.kind);
            const laneNodes = model.nodes.filter(
              (node) => (node.target || "master") === lane.id || (lane.kind === "master" && (node.target || "master") === "master"),
            );
            const trackId = `wb-track-${lane.id}`;
            const selector = `#${trackId}`;
            return (
              <View key={lane.id} className="wb-timeline__row">
                <Text className="wb-timeline__name">{w[LANE_LABEL[lane.kind] || "laneOther"]}</Text>
                <View
                  id={trackId}
                  className={`wb-timeline__track${lane.mute ? " is-mute" : ""}`}
                  onClick={(ev) => pickTrackTime(selector, duration, ev, (time) => model.onPickRegion(snap(time)))}
                >
                  <LaneWaveform laneId={lane.id} laneKind={lane.kind} duration={duration} waveformUrl={waveform} />
                  <View className="wb-timeline__region" style={{ left: pct(model.regionStart, duration), width: pct(regionWidth, duration) }} />
                  {laneClips.length ? (
                    laneClips.map((clip) => (
                      <ClipBlock
                        key={clip.id}
                        clip={clip}
                        duration={duration}
                        selected={clip.id === model.selectedClipId}
                        label={clip.id === "master-trim" ? w.trimTitle : clip.mute ? w.takeMuted : clip.id}
                        trackSelector={selector}
                        onSelect={() => model.setSelectedClipId(clip.id)}
                        onCommit={(clipId, next) => void model.patchClip(clipId, next)}
                      />
                    ))
                  ) : (
                    <View className="wb-clip is-ghost" style={{ left: "0%", width: "100%" }}>
                      <Text className="wb-clip__label">{w.ghostLane}</Text>
                    </View>
                  )}
                  <View className="wb-timeline__chips">
                    {laneNodes.map((node) => (
                      <Text key={node.id} className={`wb-timeline__chip${node.params?.failed ? " is-failed" : ""}`}>
                        {w[NODE_LABEL[node.type] || "eq"]}
                      </Text>
                    ))}
                  </View>
                </View>
              </View>
            );
          })}
        </View>
      ) : (
        <Text className="typo-meta">{model.nodes.length || model.clips.length ? w.timelineNodes : w.timelineHint}</Text>
      )}
      <View className="wb__regen-region">
        <Text className="wb__section">{w.regenTitle}</Text>
        <Text className="typo-meta">{w.regenRegionHint}</Text>
        <Text className="typo-meta">{`${model.regionStart.toFixed(1)}s – ${model.regionEnd.toFixed(1)}s`}</Text>
        <Stepper label={w.trimStart} value={model.regionStart} min={0} max={model.regionEnd - 0.5} step={0.5} onChange={model.setRegionStart} />
        <Stepper label={w.trimEnd} value={model.regionEnd} min={model.regionStart + 0.5} max={Math.max(model.duration, 8)} step={0.5} onChange={model.setRegionEnd} />
        <View className="wb__regen-row">
          <Button size="sm" variant="ghost" loading={model.busy === "regen-extend-15"} onClick={() => void model.onRegen("extend", 15, true)}>
            {w.regenExtend15}
          </Button>
          <Button size="sm" variant="ghost" loading={model.busy === "regen-extend-30"} onClick={() => void model.onRegen("extend", 30, true)}>
            {w.regenExtend30}
          </Button>
          <Button size="sm" variant="ghost" loading={model.busy === "regen-remelt-15"} onClick={() => void model.onRegen("remelt", 15, true)}>
            {w.regenRemelt}
          </Button>
          <Button size="sm" variant="ghost" loading={model.busy === "regen-same_style-15"} onClick={() => void model.onRegen("same_style", 15, true)}>
            {w.regenSame}
          </Button>
        </View>
      </View>
    </View>
  );
}
