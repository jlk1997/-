import type { ReactNode } from "react";
import { useState } from "react";
import { View, Text, ScrollView } from "@tarojs/components";
import { Button, ChipGroup, SegmentedControl, showError, showSuccess } from "../../components/ui";
import { creatorPage } from "../../constants/routes";
import { openRadioPage, openStackPage } from "../../utils/navigation";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { vibeApi } from "../../services/api";
import { NEED_OPTIONS, NODE_LABEL, isWeapp, type BenchCopy, type Clip, type Node, type Pack } from "./types";
import type { WorkbenchModel } from "./hooks/useWorkbenchSession";
import { nextCoreDoor } from "../../utils/nextCoreDoor";
import { fidelityLabel } from "./engine/contract";
import { ShipCompleteCard } from "../../packageCreator/ShipCompleteCard";
import { isQcReady } from "../../packageCreator/quickReleaseAction";

export function intensityChip(value: number) {
  const opts = [0.4, 0.7, 1, 1.2, 1.5] as const;
  return String(opts.reduce((best, cur) => (Math.abs(cur - value) < Math.abs(best - value) ? cur : best)));
}

export function Stage({
  kicker,
  title,
  hint,
  children,
  className,
}: {
  kicker?: string;
  title?: string;
  hint?: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <View className={className ? `wb-stage ${className}` : "wb-stage"}>
      {kicker ? <Text className="wb-stage__kicker">{kicker}</Text> : null}
      {title ? <Text className="wb-stage__title">{title}</Text> : null}
      {hint ? <Text className="typo-meta">{hint}</Text> : null}
      {children}
    </View>
  );
}

export function FlowSteps({ model }: { model: WorkbenchModel }) {
  const w = model.w;
  const steps = [
    { id: "listen", label: w.flowListen, done: model.heard },
    { id: "look", label: w.flowLook, done: Boolean(model.appliedName || model.nodes.length) },
    { id: "bounce", label: w.flowBounce, done: Boolean(model.session?.last_result_work_id) },
  ];
  const current = steps.findIndex((step) => !step.done);
  return (
    <View className="wb-flow">
      {steps.map((step, index) => (
        <View key={step.id} className={`wb-flow__step${step.done ? " is-done" : ""}${index === current ? " is-now" : ""}`}>
          <Text className="wb-flow__index">{step.done ? "✓" : String(index + 1)}</Text>
          <Text className="wb-flow__label">{step.label}</Text>
        </View>
      ))}
    </View>
  );
}

export function ListenCompare({ model, showC }: { model: WorkbenchModel; showC?: boolean }) {
  const w = model.w;
  const session = model.session;
  if (!session) return null;
  return (
    <View className="wb-listen">
      <Text className="wb-stage__kicker">{w.stageListen}</Text>
      <Text className="wb-listen__now">
        {w.nowPlaying} · {model.ab === "b" ? w.compareB : model.ab === "c" ? w.compareC : w.compareA}
      </Text>
      <View className="wb-listen__row">
        <Button size="sm" variant={model.ab === "a" ? "primary" : "ghost"} onClick={() => model.playSource("a")}>
          {w.listenOriginal}
        </Button>
        <Button size="sm" variant={model.ab === "b" ? "primary" : "ghost"} disabled={!session.last_result_audio_url} onClick={() => model.playSource("b")}>
          {session.last_result_audio_url ? w.listenAfter : w.compareB}
        </Button>
        {showC ? (
          <Button size="sm" variant={model.ab === "c" ? "primary" : "ghost"} disabled={!session.previous_result_audio_url} onClick={() => model.playSource("c")}>
            {w.compareC}
          </Button>
        ) : null}
      </View>
      <Text className="typo-meta">{session.last_result_audio_url ? w.compareReady : w.flowListenHint}</Text>
    </View>
  );
}

export function BounceDock({ model, embedShip = true }: { model: WorkbenchModel; embedShip?: boolean }) {
  const w = model.w;
  const session = model.session;
  const creditsCtx = useCreditsOptional();
  const [doorBusy, setDoorBusy] = useState("");
  if (!session) return null;
  const hasMaster = Boolean(session.last_result_work_id);
  const door =
    session.next_action?.door ||
    nextCoreDoor({
      hasResult: hasMaster,
      releaseStatus: session.last_result_release_status,
      degraded: Boolean(session.next_action?.degraded),
    });
  const shipId = session.last_result_work_id || "";
  const dspOn = creditsCtx?.dspDistribution !== false;
  const credits =
    (session.credit_estimate?.bounce || 0) > 0 ? w.creditBounce.replace("{n}", String(session.credit_estimate?.bounce || 0)) : w.creditFree;
  const doorLabel =
    door === "deliveries" ? w.doorDeliveries : door === "release" && dspOn ? w.doorRelease : door === "fix" ? w.doorFix : w.doorRadio;
  const doorHint =
    door === "deliveries"
      ? w.doorLiveHint
      : door === "release" && dspOn
        ? w.doorReleaseHint
        : door === "fix"
          ? w.doorFixHint
          : w.doorRadioHint;
  const readyLine = hasMaster
    ? doorHint
    : model.appliedName
      ? w.appliedReady.replace("{name}", model.appliedName)
      : w.flowBounceHint;

  async function onCoreNext() {
    if (!hasMaster || !shipId) return;
    setDoorBusy(door);
    try {
      if (door === "deliveries") {
        openStackPage(creatorPage("deliveries", { workId: shipId }));
        return;
      }
      if (door === "fix") {
        await vibeApi.reprocessWork(shipId).catch(() => vibeApi.triggerPostProcess(shipId));
        showSuccess(model.copy.worksUi.reprocessQueued);
        return;
      }
      if (door === "release" && dspOn) {
        openStackPage(creatorPage("work", { workId: shipId, pane: "ship" }));
        return;
      }
      openRadioPage({ workId: shipId });
      const trial = (await vibeApi.startRadioTrial(shipId)) as { work_id?: string };
      showSuccess(model.copy.creatorUi.radioTrialLive);
      if (trial.work_id && trial.work_id !== shipId) openRadioPage({ workId: trial.work_id });
    } catch {
      showError(model.copy.adminUi.actionFail);
    } finally {
      setDoorBusy("");
    }
  }

  return (
    <View className={hasMaster ? "wb__dock wb__dock--ship" : "wb__dock"}>
      <Text className="wb-dock__ready">{readyLine}</Text>
      {model.busy === "bounce" ? (
        <Text className="typo-meta">
          {`正在服务器上出成品，预计约 ${Math.max(8, Math.round((model.duration || 30) * 0.35))} 秒`}
        </Text>
      ) : null}
      {embedShip && hasMaster && shipId && dspOn ? (
        <ShipCompleteCard
          workId={shipId}
          surface="workbench"
          compact
          qcReady={isQcReady(session.last_result_release_status)}
          releaseStatus={session.last_result_release_status || ""}
        />
      ) : null}
      {hasMaster ? (
        <Button variant="secondary" block loading={Boolean(doorBusy)} onClick={() => void onCoreNext()}>
          {doorLabel}
        </Button>
      ) : (
        <Button variant="primary" block loading={model.busy === "bounce"} onClick={() => void model.onBounce()}>
          {w.bounce}
        </Button>
      )}
      <View className="wb-dock__row">
        {hasMaster ? (
          <>
            <Button size="sm" variant="secondary" loading={model.busy === "bounce"} onClick={() => void model.onBounce()}>
              {w.bounceAgain}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => model.playSource("b")}>
              {w.listenAfter}
            </Button>
          </>
        ) : null}
        <Button size="sm" variant="ghost" onClick={() => void model.onUndo()}>
          {session.can_undo ? w.undoStep : w.undoToA}
        </Button>
        {hasMaster ? (
          <Button size="sm" variant="ghost" onClick={() => openStackPage(creatorPage("work", { workId: shipId, pane: "ship" }))}>
            {w.openResult}
          </Button>
        ) : null}
      </View>
      <Text className="typo-meta">{credits}</Text>
    </View>
  );
}

export function Stepper({
  label,
  value,
  min,
  max,
  step,
  digits = 1,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  digits?: number;
  onChange: (v: number) => void;
}) {
  return (
    <View className="wb-step">
      <Text className="wb-step__label">{label}</Text>
      <View className="wb-step__row">
        <Button size="sm" variant="ghost" onClick={() => onChange(Math.max(min, Number((value - step).toFixed(digits))))}>
          −
        </Button>
        <Text className="wb-step__value">{value.toFixed(digits)}</Text>
        <Button size="sm" variant="ghost" onClick={() => onChange(Math.min(max, Number((value + step).toFixed(digits))))}>
          +
        </Button>
      </View>
    </View>
  );
}

export function NodeKnobs({
  node,
  labels,
  onChange,
  onRemove,
}: {
  node: Node;
  labels: BenchCopy;
  onChange: (params: Record<string, number>) => void;
  onRemove?: () => void;
}) {
  const params = node.params || {};
  const title = labels[NODE_LABEL[node.type] || "eq"];
  const regen = node.type.startsWith("regen_");
  const aiNode = node.type.startsWith("ai_");
  const failed = Boolean(params.failed);
  return (
    <View className={failed ? "wb-node is-failed" : "wb-node"}>
      <Text className="wb-node__title">{title}</Text>
      <Text className="typo-meta">{fidelityLabel(node.type)}</Text>
      {failed ? <Text className="typo-meta">{labels.nodeFailed}</Text> : null}
      {aiNode && !failed ? <Text className="typo-meta">{labels.aiHonesty}</Text> : null}
      {regen && !failed ? <Text className="typo-meta">{labels.regenHint}</Text> : null}
      {node.type === "eq" && (
        <>
          <Stepper label={labels.low} value={Number(params.low || 0)} min={-6} max={6} step={0.5} onChange={(low) => onChange({ low })} />
          <Stepper label={labels.mid} value={Number(params.mid || 0)} min={-6} max={6} step={0.5} onChange={(mid) => onChange({ mid })} />
          <Stepper label={labels.high} value={Number(params.high || 0)} min={-6} max={6} step={0.5} onChange={(high) => onChange({ high })} />
        </>
      )}
      {node.type === "compress" && (
        <>
          <Stepper label={labels.threshold} value={Number(params.threshold || -18)} min={-30} max={-6} step={1} digits={0} onChange={(threshold) => onChange({ threshold })} />
          <Stepper label={labels.compress} value={Number(params.ratio || 2)} min={1} max={6} step={0.2} onChange={(ratio) => onChange({ ratio })} />
        </>
      )}
      {node.type === "reverb" && (
        <Stepper label={labels.mix} value={Number(params.mix || 0.2)} min={0} max={0.7} step={0.05} digits={2} onChange={(mix) => onChange({ mix })} />
      )}
      {node.type === "delay" && (
        <>
          <Stepper label={labels.delayMs} value={Number(params.ms || 180)} min={40} max={600} step={10} digits={0} onChange={(ms) => onChange({ ms })} />
          <Stepper label={labels.mix} value={Number(params.mix || 0.12)} min={0} max={0.6} step={0.05} digits={2} onChange={(mix) => onChange({ mix })} />
        </>
      )}
      {node.type === "loudness" && (
        <Stepper label={labels.loudness} value={Number(params.i || -14)} min={-18} max={-9} step={0.5} onChange={(i) => onChange({ i })} />
      )}
      {node.type === "highpass" && (
        <Stepper label={labels.hz} value={Number(params.hz || 80)} min={20} max={400} step={10} digits={0} onChange={(hz) => onChange({ hz })} />
      )}
      {node.type === "lowpass" && (
        <Stepper label={labels.hz} value={Number(params.hz || 12000)} min={2000} max={18000} step={250} digits={0} onChange={(hz) => onChange({ hz })} />
      )}
      {node.type === "widen" && (
        <Stepper label={labels.widenAmount} value={Number(params.amount || 1)} min={0} max={2} step={0.1} onChange={(amount) => onChange({ amount })} />
      )}
      {node.type === "limiter" && (
        <Stepper label={labels.limit} value={Number(params.limit || 0.92)} min={0.4} max={1} step={0.02} digits={2} onChange={(limit) => onChange({ limit })} />
      )}
      {node.type === "pitch" && (
        <Stepper label={labels.pitch} value={Number(params.semitones || 0)} min={-12} max={12} step={1} digits={0} onChange={(semitones) => onChange({ semitones })} />
      )}
      {node.type === "tempo" && (
        <Stepper label={labels.tempo} value={Number(params.ratio || 1)} min={0.5} max={2} step={0.05} digits={2} onChange={(ratio) => onChange({ ratio })} />
      )}
      {onRemove ? (
        <Button size="sm" variant="ghost" onClick={onRemove}>
          {labels.removeNode}
        </Button>
      ) : null}
    </View>
  );
}

export function NeedRail({ model, embed }: { model: WorkbenchModel; embed?: boolean }) {
  return (
    <View className="wb__needs">
      {embed ? null : <Text className="wb__section">{model.w.needRail}</Text>}
      <ChipGroup
        value={model.need || "all"}
        onChange={(value) => model.setNeed(value === "all" ? "" : value)}
        options={[
          { value: "all", label: model.w.packsOfficial },
          ...NEED_OPTIONS.map((item) => ({ value: item.id, label: String(model.w[item.label]) })),
        ]}
      />
    </View>
  );
}

export function PackRail({ model, embed }: { model: WorkbenchModel; embed?: boolean }) {
  const w = model.w;
  return (
    <View className="wb__packs">
      {embed && model.appliedName ? <Text className="wb-pack__applied">{w.appliedPack.replace("{name}", model.appliedName)}</Text> : null}
      {!isWeapp && (
        <SegmentedControl
          value={model.scope}
          onChange={model.setScope}
          options={[
            { value: "official", label: w.packsOfficial },
            { value: "community", label: w.packsCommunity },
            { value: "mine", label: w.packsMine },
          ]}
        />
      )}
      {!embed && model.appliedName ? <Text className="wb-pack__applied">{w.appliedPack.replace("{name}", model.appliedName)}</Text> : null}
      <ScrollView scrollX className="wb__pack-row">
        <View className="wb__pack-row-inner">
          {model.visiblePacks.map((pack: Pack) => (
            <View key={pack.id} className={pack.id === model.session?.applied_pack_id ? "wb-pack is-applied" : "wb-pack"}>
              <Text className="wb-pack__kind">{pack.kind === "lane" ? w.publishKindLane : w.publishKindScene}</Text>
              <Text className="wb-pack__title">{model.packTitle(pack)}</Text>
              <Text className="wb-pack__hint">{model.packHint(pack)}</Text>
              {pack.kind === "lane" ? <Text className="typo-meta">{w.lanePackHint}</Text> : null}
              <Text className="wb-pack__price">
                {(pack.price_credits || 0) > 0 && !pack.owned
                  ? model.copy.marketplaceUi.priceCredits.replace("{n}", String(pack.price_credits))
                  : model.copy.marketplaceUi.free}
              </Text>
              <View className="wb-pack__actions">
                <Button size="sm" variant="ghost" loading={model.busy === `preview-${pack.id}`} onClick={() => void model.onPreview(pack)}>
                  {w.previewPack}
                </Button>
                <Button size="sm" variant="secondary" loading={model.busy === `pack-${pack.id}`} onClick={() => void model.onApply(pack)}>
                  {w.applyPack}
                </Button>
              </View>
            </View>
          ))}
          {model.visiblePacks.length === 0 && <Text className="typo-meta">{w.emptyPacks}</Text>}
        </View>
      </ScrollView>
    </View>
  );
}

export function MasterTrim({ model }: { model: WorkbenchModel }) {
  const start = model.masterTrim?.start ?? 0;
  const end = model.masterTrim?.end ?? model.duration;
  return (
    <View className="wb__trim">
      <Text className="wb__section">{model.w.trimTitle}</Text>
      <Stepper label={model.w.trimStart} value={start} min={0} max={Math.max(0, end - 0.2)} step={0.5} onChange={(value) => void model.onTrim(value, end)} />
      <Stepper label={model.w.trimEnd} value={end} min={start + 0.2} max={Math.max(model.duration, end)} step={0.5} onChange={(value) => void model.onTrim(start, value)} />
    </View>
  );
}

export function ClipInspector({ model }: { model: WorkbenchModel }) {
  const clip = (model.clips as Clip[]).find((row) => row.id === model.selectedClipId);
  if (!clip) return null;
  return (
    <View className="wb__clip">
      <Text className="wb__section">{model.w.selectedClip}</Text>
      <Stepper label={model.w.trimStart} value={clip.start} min={0} max={clip.end - 0.1} step={0.1} onChange={(start) => void model.patchClip(clip.id, { start })} />
      <Stepper
        label={model.w.clipMove}
        value={clip.start}
        min={0}
        max={Math.max(0, 600 - (clip.end - clip.start))}
        step={0.1}
        onChange={(start) => void model.patchClip(clip.id, { start, end: start + (clip.end - clip.start), offset: clip.offset })}
      />
      <Stepper label={model.w.trimEnd} value={clip.end} min={clip.start + 0.1} max={600} step={0.1} onChange={(end) => void model.patchClip(clip.id, { end })} />
      <Stepper label={model.w.fadeIn} value={clip.fade_in} min={0} max={4} step={0.05} digits={2} onChange={(fade_in) => void model.patchClip(clip.id, { fade_in })} />
      <Stepper label={model.w.fadeOut} value={clip.fade_out} min={0} max={4} step={0.05} digits={2} onChange={(fade_out) => void model.patchClip(clip.id, { fade_out })} />
      <Stepper label={model.w.clipGain} value={clip.gain} min={0} max={2} step={0.1} onChange={(gain) => void model.patchClip(clip.id, { gain })} />
      <Button size="sm" variant="ghost" onClick={() => void model.patchClip(clip.id, { mute: !clip.mute })}>
        {clip.mute ? model.w.unmute : model.w.mute}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => void model.onSplitSelected((clip.start + clip.end) / 2)}>
        {model.w.splitClip}
      </Button>
    </View>
  );
}
