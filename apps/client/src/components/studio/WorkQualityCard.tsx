import { useEffect, useMemo, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { Button, RingGauge, StatusLine, ProgressRail } from "../ui";
import { AssetLanes } from "./AssetLanes";
import { vibeApi } from "../../services/api";
import { pickAndUploadCover } from "../../platform/upload";
import { openWorkbench } from "../../utils/workbenchNav";
import "./WorkQualityCard.scss";

type Scores = Awaited<ReturnType<typeof vibeApi.getWorkQuality>>;

type Props = {
  workId: string;
  title?: string;
  moods?: string[];
  /** When true, stay collapsed behind a door unless QC fails. */
  doorOnly?: boolean;
  onOptimize?: (suggestion: string) => void;
  onLab?: () => void;
  onCover?: () => void;
  onScores?: (scores: Scores) => void;
  onRemelt?: () => void;
};

export function WorkQualityCard({ workId, title, moods, doorOnly = false, onOptimize, onLab, onCover, onScores, onRemelt }: Props) {
  const { copy } = useLocale();
  const q = copy.qualityUi;
  const [scores, setScores] = useState<Scores | null>(null);
  const [uploading, setUploading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    vibeApi
      .getWorkQuality(workId)
      .then((res) => {
        setScores(res);
        onScores?.(res);
      })
      .catch(() => setScores(null));
  }, [workId]);

  const suggestion = useMemo(() => {
    const key = scores?.suggestion_key;
    if (key === "loudness") return q.suggestLoudness;
    if (key === "duration") return q.suggestDuration;
    if (key === "originality") return q.suggestOriginality;
    if (key === "cover") return q.suggestCover;
    if (key === "mood") return q.suggestMood;
    if (key === "structure") return q.suggestStructure;
    return q.suggestPublish;
  }, [scores, q]);

  const resonance = scores?.resonance ?? 80;
  const completion = scores?.completion ?? 80;
  const preflightFail = scores?.suggestion_key === "loudness" || scores?.suggestion_key === "duration";
  const coverFail = scores?.suggestion_key === "cover";
  const originalityRisk = Number(scores?.preflight?.originality_risk || 0);
  const originalityFail = scores?.suggestion_key === "originality" || originalityRisk >= 80;

  async function uploadCover() {
    setUploading(true);
    try {
      Taro.showLoading({ title: copy.worksUi.coverUploading, mask: true });
      await pickAndUploadCover(workId);
      Taro.hideLoading();
      const res = await vibeApi.getWorkQuality(workId);
      setScores(res);
      onScores?.(res);
      onCover?.();
      Taro.showToast({ title: copy.worksUi.coverUploaded, icon: "success" });
    } catch {
      Taro.hideLoading();
      Taro.showToast({ title: copy.worksUi.coverUploadFail, icon: "none" });
    } finally {
      setUploading(false);
    }
  }

  if (!open && !preflightFail && !originalityFail) {
    return (
      <View className="work-quality work-quality--quiet" onClick={() => setOpen(true)}>
        <Text className="work-quality__title">{doorOnly ? q.doorQuiet : q.title}</Text>
        <Text className="typo-meta">{`${q.resonance} ${resonance} · ${q.completion} ${completion}`}</Text>
      </View>
    );
  }

  return (
    <View className="work-quality">
      <Text className="work-quality__title" onClick={() => setOpen(false)}>
        {doorOnly ? q.doorOpen : q.title}
      </Text>
      {preflightFail ? <StatusLine tone="error">{suggestion}</StatusLine> : null}
      {coverFail ? <StatusLine tone="info">{suggestion}</StatusLine> : null}
      {originalityFail && !preflightFail ? <StatusLine tone="error">{q.suggestOriginality}</StatusLine> : null}
      {scores && !doorOnly ? (
      <AssetLanes
        density="compact"
        skuKind={scores.release_assets?.sku_kind}
        status={{
          listing: { ready: Boolean(scores.release_assets?.master_ready), wav: Boolean(scores.release_assets?.master_wav) },
          evidence: {
            needed: Boolean(scores.release_assets?.stems_quality && scores.release_assets.stems_quality !== "none"),
            ready: Boolean(scores.release_assets?.evidence_ready),
            quality: scores.release_assets?.stems_quality,
          },
          clips: {
            needed: Boolean(scores.release_assets?.clips_needed),
            ready: Boolean(scores.release_assets?.clips_ready),
          },
        }}
      />
      ) : null}
      {scores && doorOnly ? (
        <Text className="typo-meta">
          {scores.release_assets?.master_ready ? q.listingReady : q.evidencePending}
        </Text>
      ) : null}
      {!doorOnly ? (
      <View className="work-quality__gauges">
        <View className="work-quality__gauge">
          <RingGauge value={resonance} max={100} label={q.resonance} />
        </View>
        <View className="work-quality__gauge">
          <RingGauge value={completion} max={100} label={q.completion} />
        </View>
      </View>
      ) : null}
      {!doorOnly ? (
      <View className={originalityFail ? "work-quality__risk work-quality__risk--hot" : "work-quality__risk"}>
        <Text className="work-quality__risk-label">{q.originality}</Text>
        <ProgressRail pct={Math.min(100, originalityRisk)} />
        <Text className="work-quality__risk-value">{originalityRisk}</Text>
      </View>
      ) : null}
      {(moods?.length || title) && (
        <Text className="typo-meta">{q.moods.replace("{tags}", (moods || []).join(" · ") || title || "—")}</Text>
      )}
      {!preflightFail && !coverFail && !originalityFail && <Text className="work-quality__hint">{suggestion}</Text>}
      {(preflightFail || originalityFail || resonance < 70) && (
        <Button variant="primary" size="sm" block onClick={() => (onRemelt ? onRemelt() : openWorkbench(workId))}>
          {q.remelt}
        </Button>
      )}
      {scores?.remelt_too_close ? (
        <>
          <Text className="typo-meta">{q.remeltAgain}</Text>
          {preflightFail || originalityFail || resonance < 70 ? null : (
            <Button variant="primary" size="sm" block onClick={() => (onRemelt ? onRemelt() : openWorkbench(workId))}>
              {q.remelt}
            </Button>
          )}
        </>
      ) : scores?.remelt_explain === "av_distance" || scores?.reference_ready ? (
        <Text className="typo-meta">{q.remeltHint}</Text>
      ) : null}
      {(preflightFail || originalityFail) && onLab && (
        <Button variant="secondary" size="sm" block onClick={onLab}>
          {q.goLab}
        </Button>
      )}
      {coverFail && (
        <Button variant="primary" size="sm" block loading={uploading} onClick={() => void uploadCover()}>
          {q.uploadCover}
        </Button>
      )}
      {onOptimize && (
        <Button variant="secondary" size="sm" block onClick={() => onOptimize(suggestion)}>
          {preflightFail ? copy.generation.tryVariations : q.optimize}
        </Button>
      )}
    </View>
  );
}
