import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { clsx } from "../../utils/clsx";
import { Button } from "../ui/Button";
import { Icon, type IconName } from "../ui/Icon";
import "./AssetLanes.scss";

export type AssetLaneStatus = {
  listing?: { ready?: boolean; label?: string; wav?: boolean };
  evidence?: { needed?: boolean; ready?: boolean; label?: string; quality?: string };
  clips?: { needed?: boolean; ready?: boolean; key?: string };
  instrumental?: { needed?: boolean; ready?: boolean; work_id?: string; can_spawn?: boolean; self?: boolean };
  needs_ai_musician?: boolean;
};

type Density = "full" | "compact" | "legend";

type Props = {
  status?: AssetLaneStatus | null;
  density?: Density;
  skuKind?: string | null;
  forceEvidence?: boolean;
  forceClips?: boolean;
  forceInstrumental?: boolean;
  onDownloadOriginality?: () => void;
  onDownloadClips?: () => void;
  onSpawnInstrumental?: () => void;
  spawningInstrumental?: boolean;
};

type Lamp = "on" | "wait" | "off" | "info";

type Lane = {
  id: "listing" | "evidence" | "clips" | "instrumental";
  icon: IconName;
  title: string;
  use: string;
  lamp: Lamp;
  state: string;
  action?: { label: string; onClick: () => void };
  note?: string;
};

export function AssetLanes({
  status,
  density = "full",
  skuKind,
  forceEvidence,
  forceClips,
  forceInstrumental,
  onDownloadOriginality,
  onDownloadClips,
  onSpawnInstrumental,
  spawningInstrumental,
}: Props) {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const listingReady = Boolean(status?.listing?.ready);
  const evidenceNeeded = Boolean(status?.evidence?.needed || forceEvidence);
  const evidenceReady = Boolean(status?.evidence?.ready);
  const clipsNeeded = Boolean(status?.clips?.needed || forceClips);
  const clipsReady = status?.clips?.ready === true;
  const instrumentalNeeded = Boolean(status?.instrumental?.needed || forceInstrumental || skuKind === "instrumental");
  const instrumentalReady = Boolean(status?.instrumental?.ready || skuKind === "instrumental");
  const canSpawn = Boolean(status?.instrumental?.can_spawn && onSpawnInstrumental);
  const legend = density === "legend";

  const lanes: Lane[] = [
    {
      id: "listing",
      icon: "music",
      title: c.laneListing,
      use: c.laneListingUse,
      lamp: legend ? "info" : listingReady ? "on" : "wait",
      state: legend ? c.laneAlways : listingReady ? c.laneReady : c.laneWaitMaster,
    },
    {
      id: "evidence",
      icon: "flask",
      title: c.laneEvidence,
      use: c.laneEvidenceUse,
      lamp: legend ? "info" : !evidenceNeeded ? "off" : evidenceReady ? "on" : "wait",
      state: legend ? c.laneWhenAsked : !evidenceNeeded ? c.laneSkip : evidenceReady ? c.laneReady : c.laneWait,
      action:
        evidenceReady && onDownloadOriginality
          ? { label: c.downloadOriginality, onClick: onDownloadOriginality }
          : undefined,
      note: status?.needs_ai_musician ? c.neteaseAiMusician : evidenceNeeded ? c.tmeEmailHint : undefined,
    },
    {
      id: "clips",
      icon: "feed",
      title: c.laneClips,
      use: c.laneClipsUse,
      lamp: legend ? "info" : !clipsNeeded ? "off" : clipsReady ? "on" : "wait",
      state: legend ? c.laneShortVideo : !clipsNeeded ? c.laneSkip : clipsReady ? c.laneReady : c.laneWaitClips,
      action: clipsNeeded && clipsReady && onDownloadClips ? { label: c.downloadClipPack, onClick: onDownloadClips } : undefined,
    },
    {
      id: "instrumental",
      icon: "remix",
      title: c.laneInstrumental,
      use: c.laneInstrumentalUse,
      lamp: legend ? "info" : instrumentalReady ? "on" : instrumentalNeeded ? "wait" : "off",
      state: legend
        ? c.laneSeparateSku
        : instrumentalReady
          ? c.laneReady
          : instrumentalNeeded
            ? c.laneWaitInstrumental
            : c.laneSkip,
      action:
        canSpawn && !spawningInstrumental
          ? { label: c.laneSpawnInstrumental, onClick: onSpawnInstrumental! }
          : undefined,
    },
  ];

  return (
    <View className={clsx("asset-lanes", `asset-lanes--${density}`)}>
      <Text className="asset-lanes__kicker">{c.laneTitle}</Text>
      {density !== "compact" ? <Text className="asset-lanes__legend">{c.laneLegend}</Text> : null}
      <View className="asset-lanes__grid">
        {lanes.map((lane) => (
          <View key={lane.id} className={clsx("asset-lane", `asset-lane--${lane.lamp}`)}>
            <View className={clsx("asset-lane__lamp", `asset-lane__lamp--${lane.lamp}`)} />
            <View className="asset-lane__icon">
              <Icon name={lane.icon} size="sm" accent={lane.lamp === "on" || lane.lamp === "info"} muted={lane.lamp === "off"} />
            </View>
            <View className="asset-lane__copy">
              <Text className="asset-lane__title">{lane.title}</Text>
              <Text className="asset-lane__use">{lane.use}</Text>
              {density === "compact" ? null : <Text className="asset-lane__state">{lane.state}</Text>}
              {density === "full" && lane.note ? <Text className="asset-lane__note">{lane.note}</Text> : null}
              {lane.action ? (
                <Button className="asset-lane__action" size="sm" variant="ghost" onClick={lane.action.onClick}>
                  {lane.action.label}
                </Button>
              ) : null}
            </View>
          </View>
        ))}
      </View>
    </View>
  );
}

export function AssetChips({
  evidence,
  clips,
  instrumental,
}: {
  evidence?: boolean;
  clips?: boolean;
  instrumental?: boolean;
}) {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  return (
    <View className="asset-chips">
      <Text className="asset-chip asset-chip--on">{c.chipMaster}</Text>
      {evidence ? <Text className="asset-chip">{c.chipEvidence}</Text> : null}
      {clips ? <Text className="asset-chip">{c.chipClips}</Text> : null}
      {instrumental ? <Text className="asset-chip">{c.chipInstrumental}</Text> : null}
    </View>
  );
}
