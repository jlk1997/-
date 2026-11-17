import { useEffect } from "react";
import { View, Text, Textarea } from "@tarojs/components";
import { Icon } from "../ui";
import "./CreateFormulaPanel.scss";

const FORMULA_INPUT_SELECTOR = ".create-formula__input-wrap textarea, .create-formula__input-wrap .taro-textarea";
const isH5 = process.env.TARO_ENV === "h5";

function syncFormulaTextareaHeight() {
  if (!isH5 || typeof document === "undefined") return;
  const el = document.querySelector(FORMULA_INPUT_SELECTOR) as HTMLTextAreaElement | null;
  if (!el) return;
  el.style.height = "auto";
  const minPx = 120;
  const maxPx = 320;
  const next = Math.min(Math.max(el.scrollHeight, minPx), maxPx);
  el.style.height = `${next}px`;
}

type Props = {
  intentLabel: string;
  intentHint: string;
  intentPlaceholder: string;
  textIntent: string;
  onTextIntentChange: (value: string) => void;
  polishLabel: string;
  polishingLabel: string;
  polishing?: boolean;
  onPolish?: () => void;
  intentTip?: string;
  maxlength?: number;
  onIntentBlur?: () => void;
  draftLabel?: string;
  onDraft?: () => void;
  adjustLabel?: string;
  onAdjust?: () => void;
  choicesLabel?: string;
  choices?: Array<{ id: string; label: string }>;
  onChoice?: () => void;
};

export function CreateFormulaPanel({
  intentLabel,
  intentHint,
  intentPlaceholder,
  textIntent,
  onTextIntentChange,
  polishLabel,
  polishingLabel,
  polishing = false,
  onPolish,
  intentTip,
  maxlength = 300,
  onIntentBlur,
  draftLabel,
  onDraft,
  adjustLabel,
  onAdjust,
  choicesLabel,
  choices,
  onChoice,
}: Props) {
  useEffect(() => {
    syncFormulaTextareaHeight();
    const timer = setTimeout(syncFormulaTextareaHeight, 0);
    return () => clearTimeout(timer);
  }, [textIntent]);

  return (
    <View className="create-formula">
      <View className="create-formula__glow" aria-hidden />

      <View className="create-formula__head">
        <View className="create-formula__head-left">
          <Text className="create-formula__title">{intentLabel}</Text>
        </View>
        <View className="create-formula__head-actions">
          {onDraft && draftLabel ? (
            <Text className="create-formula__draft" onClick={onDraft}>
              {draftLabel}
            </Text>
          ) : null}
          {onPolish && (
          <View
            className={`create-formula__polish ${polishing ? "create-formula__polish--loading" : ""}`}
            onClick={polishing ? undefined : onPolish}
          >
            <Icon name="sparkle" size="sm" accent />
            <Text className="create-formula__polish-text">{polishing ? polishingLabel : polishLabel}</Text>
          </View>
        )}
        </View>
      </View>

      <View className="create-formula__prompt">
        <View className="create-formula__input-wrap">
          <Textarea
            className="create-formula__input"
            value={textIntent}
            placeholder={intentPlaceholder}
            maxlength={maxlength}
            autoHeight={!isH5}
            disableDefaultPadding
            onInput={(e) => {
              onTextIntentChange(e.detail.value);
              if (isH5) {
                requestAnimationFrame(syncFormulaTextareaHeight);
              }
            }}
            onBlur={() => onIntentBlur?.()}
          />
        </View>
        <View className="create-formula__prompt-foot">
          {intentHint ? <Text className="create-formula__hint">{intentHint}</Text> : <View className="create-formula__foot-spacer" />}
          {onAdjust && adjustLabel ? (
            <View className="create-formula__adjust" onClick={onAdjust}>
              <Text className="create-formula__adjust-text">{adjustLabel}</Text>
              <Icon name="chevronDown" size="sm" />
            </View>
          ) : null}
          <Text className="create-formula__count">
            {textIntent.length}/{maxlength}
          </Text>
        </View>
      </View>

      {choices && choices.length > 0 ? (
        <View className="create-formula__choices">
          {choicesLabel ? <Text className="create-formula__choices-label">{choicesLabel}</Text> : null}
          <View className="create-formula__choice-row">
            {choices.map((chip) => (
              <Text key={chip.id} className="create-formula__choice" onClick={onChoice}>
                {chip.label}
              </Text>
            ))}
          </View>
        </View>
      ) : null}

      {intentTip && (
        <View className="create-formula__tip">
          <Icon name="info" size="sm" accent />
          <Text className="create-formula__tip-text">{intentTip}</Text>
        </View>
      )}
    </View>
  );
}
