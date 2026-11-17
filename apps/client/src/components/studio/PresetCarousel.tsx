import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { PresetSigil } from "./PresetSigil";
import "./PresetCarousel.scss";

export type StylePreset = {
  id: string;
  label: string;
  category?: string;
  description?: string;
  example_intent?: string;
  member_only?: boolean;
};

type Props = {
  presets: StylePreset[];
  selectedId: string | null;
  onSelect: (preset: StylePreset) => void;
  isMember?: boolean;
  onMemberGate?: () => void;
  className?: string;
  shopLabel?: string;
  onShop?: () => void;
  compact?: boolean;
};

export function PresetCarousel({ presets, selectedId, onSelect, isMember, onMemberGate, className, shopLabel, onShop, compact }: Props) {
  const { copy } = useLocale();
  const c = copy.createUi;
  if (!presets.length && !onShop) return null;

  function handleSelect(p: StylePreset) {
    if (p.member_only && !isMember) {
      onMemberGate?.();
      return;
    }
    onSelect(p);
  }

  return (
    <View className={`${className ? `presets ${className}` : "presets"}${compact ? " presets--compact" : ""}`}>
      <View className="presets__scroll">
        {presets.map((p, index) => {
          const locked = Boolean(p.member_only && !isMember);
          return (
          <View
            key={p.id}
            className={`presets__card ${selectedId === p.id ? "presets__card--active" : ""}${locked ? " presets__card--locked" : ""}`}
            onClick={() => handleSelect(p)}
          >
            <View className={`presets__cover presets__cover--${index % 6}`}>
              <PresetSigil presetId={p.id} size="md" active={selectedId === p.id} />
            </View>
            <Text className="presets__label">{p.label}</Text>
            {!compact && p.member_only && <Text className="presets__member">{c.memberOnlyPreset}</Text>}
            {!compact && p.description && <Text className="presets__desc">{p.description}</Text>}
          </View>
        );
        })}
        {onShop && shopLabel ? (
          <View className="presets__card presets__card--shop" onClick={onShop}>
            <Text className="presets__label">{shopLabel}</Text>
            <Text className="presets__desc">{c.homePromptHint}</Text>
          </View>
        ) : null}
      </View>
    </View>
  );
}
