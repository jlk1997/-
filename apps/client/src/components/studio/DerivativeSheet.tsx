import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { Button, ChipGroup, TextArea } from "../ui";
import { vibeApi } from "../../services/api";
import { setItem, removeItem } from "../../platform/storage";
import { canRemixWork } from "../../utils/remixLicense";
import { startRegenerate, startSameStyle } from "../../utils/sameStyleNav";
import { showCoverUnavailable } from "../../utils/coverUnavailable";
import "./DerivativeSheet.scss";

export type DerivativeMode = "remix" | "cover" | "variation" | "regenerate" | "sameStyle";

type Props = {
  workId: string;
  workTitle: string;
  initialMode?: DerivativeMode;
  onClose: () => void;
};

const MODE_ORDER: DerivativeMode[] = ["sameStyle", "regenerate", "remix", "cover", "variation"];

export function DerivativeSheet({ workId, workTitle, initialMode = "sameStyle", onClose }: Props) {
  const { copy } = useLocale();
  const d = copy.derivative;
  const c = copy.createUi;
  const [mode, setMode] = useState<DerivativeMode>(initialMode);
  const [intent, setIntent] = useState(initialMode === "remix" ? d.remix.example : "");
  const [preview, setPreview] = useState<{ prompt?: string; bpm?: number; key?: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [remixAllowed, setRemixAllowed] = useState(true);
  const [showModes, setShowModes] = useState(false);

  useEffect(() => {
    let cancelled = false;
    vibeApi
      .getWork(workId)
      .then((w) => {
        if (!cancelled) setRemixAllowed(canRemixWork(w));
      })
      .catch(() => {
        if (!cancelled) setRemixAllowed(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workId]);

  async function runPreview() {
    if (mode !== "remix" || !intent.trim()) return;
    setLoading(true);
    try {
      setPreview(await vibeApi.previewRemix(workId, intent.trim()));
      Taro.showToast({ title: copy.settingsUi.previewDone, icon: "success" });
    } catch {
      Taro.showToast({ title: d.previewFail, icon: "none" });
    } finally {
      setLoading(false);
    }
  }

  function start() {
    if (mode === "cover") {
      showCoverUnavailable();
      return;
    }
    if (mode === "remix" && !remixAllowed) {
      Taro.showToast({ title: d.remixNotAllowed, icon: "none" });
      return;
    }
    onClose();
    if (mode === "sameStyle") {
      startSameStyle(workId, workTitle, intent.trim() || undefined);
      return;
    }
    if (mode === "regenerate") {
      startRegenerate(workId, workTitle, intent.trim() || undefined);
      return;
    }
    setItem("create:seedWorkId", workId);
    setItem("create:mode", mode);
    setItem("create:seedTitle", workTitle);
    if (intent.trim()) setItem("create:seedIntent", intent.trim());
    else if (mode === "remix") setItem("create:seedIntent", d.remix.example);
    else removeItem("create:seedIntent");
    Taro.switchTab({ url: "/pages/create/index" });
  }

  const modeLabel =
    mode === "remix"
      ? d.remix.short
      : mode === "cover"
        ? d.cover.short
        : mode === "regenerate"
          ? d.regenerate.short
          : mode === "sameStyle"
            ? d.sameStyle.short
            : copy.createUi.modeVariation;

  const modeDesc =
    mode === "remix"
      ? d.remix.description
      : mode === "cover"
        ? d.cover.description
        : mode === "regenerate"
          ? d.regenerate.description
          : mode === "sameStyle"
            ? d.sameStyle.description
            : copy.createUi.modeVariationDesc;

  const startLabel =
    mode === "remix"
      ? d.startRemix
      : mode === "cover"
        ? d.startCover
        : mode === "regenerate"
          ? d.startRegenerate
          : mode === "sameStyle"
            ? d.startSameStyle
            : copy.createUi.modeVariation;

  return (
    <View className="derivative-sheet" onClick={onClose}>
      <View className="derivative-sheet__panel" onClick={(e) => e.stopPropagation()}>
        <View className="derivative-sheet__handle" />
        <Text className="derivative-sheet__title">{d.selectAction}</Text>
        <Text className="derivative-sheet__work">{workTitle}</Text>
        {!showModes ? (
          <View className="derivative-sheet__recommend">
            <Text className="derivative-sheet__mode-pill">{modeLabel}</Text>
            <Text className="derivative-sheet__desc">{modeDesc}</Text>
            <Button variant="ghost" size="sm" onClick={() => setShowModes(true)}>
              {d.tryAnother}
            </Button>
          </View>
        ) : (
          <ChipGroup
            options={MODE_ORDER.map((value) => ({
              value,
              label:
                value === "sameStyle"
                  ? d.sameStyle.short
                  : value === "regenerate"
                    ? d.regenerate.short
                    : value === "remix"
                      ? d.remix.short
                      : value === "cover"
                        ? d.cover.short
                        : copy.createUi.modeVariation,
            }))}
            value={mode}
            onChange={(v) => {
              const next = v as DerivativeMode;
              if (next === "cover") {
                showCoverUnavailable();
                return;
              }
              setMode(next);
              setPreview(null);
              if (next === "remix" && !intent.trim()) setIntent(d.remix.example);
            }}
          />
        )}
        {showModes ? <Text className="derivative-sheet__desc">{modeDesc}</Text> : null}
        {mode === "variation" && (
          <Text className="typo-meta">{copy.pricingUi.ruleSingle} ×3 {copy.pricingUi.creditUnit}</Text>
        )}
        {mode === "remix" && !remixAllowed && (
          <Text className="derivative-sheet__blocked typo-meta">{d.remixNotAllowed}</Text>
        )}
        <TextArea
          label={d.intentLabel}
          placeholder={d.intentPlaceholder}
          value={intent}
          onInput={(e) => setIntent(e.detail.value)}
          maxlength={300}
        />
        {preview && (
          <View className="derivative-sheet__preview">
            <Text className="typo-meta">{preview.prompt}</Text>
            {preview.bpm != null && <Text className="typo-meta">BPM {preview.bpm} · {preview.key}</Text>}
          </View>
        )}
        <View className="derivative-sheet__actions">
          {mode === "remix" && remixAllowed && (
            <Button variant="secondary" block loading={loading} onClick={runPreview}>
              {c.remixPreview}
            </Button>
          )}
          <Button variant="primary" block onClick={start} disabled={mode === "remix" && !remixAllowed}>
            {startLabel}
          </Button>
          <Button variant="ghost" block onClick={onClose}>
            {copy.actions.cancel}
          </Button>
        </View>
      </View>
    </View>
  );
}
