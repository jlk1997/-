import { useState, useEffect } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { BottomSheet } from "./BottomSheet";
import { Button } from "./Button";
import { ShareButton } from "./ShareButton";
import { shareWork } from "../../platform/share";
import "./CelebrationSheet.scss";

type Props = {
  open: boolean;
  variant: "publish" | "playlist" | "firstTrack";
  onClose: () => void;
  shareTitle?: string;
  workId?: string;
  upsellLabel?: string;
  onUpsell?: () => void;
  releaseLabel?: string;
  releaseDisabled?: boolean;
  releaseHint?: string;
  onRelease?: () => void;
  passportLabel?: string;
  onPassport?: () => void;
  beautifyLabel?: string;
  onBeautify?: () => void;
  radioLabel?: string;
  onRadio?: () => void;
  clipsLabel?: string;
  onClips?: () => void;
  connectorLabel?: string;
  onConnector?: () => void;
  labLabel?: string;
  onLab?: () => void;
  communityLabel?: string;
  onCommunity?: () => void;
};

export function CelebrationSheet({
  open,
  variant,
  onClose,
  shareTitle,
  workId,
  upsellLabel,
  onUpsell,
  releaseLabel,
  releaseDisabled,
  releaseHint,
  onRelease,
  passportLabel,
  onPassport,
  beautifyLabel,
  onBeautify,
  radioLabel,
  onRadio,
  clipsLabel,
  onClips,
  connectorLabel,
  onConnector,
  labLabel,
  onLab,
  communityLabel,
  onCommunity,
}: Props) {
  const { copy } = useLocale();
  const c = copy.celebrationUi;
  const [showMore, setShowMore] = useState(false);
  const title =
    variant === "publish" ? c.publishTitle : variant === "playlist" ? c.playlistTitle : c.firstTrackTitle;
  const body =
    variant === "publish" ? c.publishBody : variant === "playlist" ? c.playlistBody : c.firstTrackBody;
  const hasRelease = Boolean(releaseLabel && onRelease);
  const publishPrimary = variant === "publish" && Boolean(releaseLabel && onRelease && !releaseDisabled);
  const firstTrackPrimary = variant === "firstTrack" && Boolean(beautifyLabel && onBeautify);
  const extras = [
    workId
      ? {
          key: "share",
          label: c.share,
          onClick: () => {
            shareWork(workId, shareTitle || copy.brand.name);
            onClose();
          },
          share: true as const,
        }
      : null,
    radioLabel && onRadio
      ? {
          key: "radio",
          label: radioLabel,
          onClick: onRadio,
        }
      : null,
    {
      key: "continue",
      label: c.continueCreate,
      onClick: () => Taro.switchTab({ url: "/pages/create/index" }),
    },
    !publishPrimary && !firstTrackPrimary && communityLabel && onCommunity
      ? { key: "community", label: communityLabel, onClick: onCommunity }
      : null,
    clipsLabel && onClips ? { key: "clips", label: clipsLabel, onClick: onClips } : null,
    labLabel && onLab ? { key: "lab", label: labLabel, onClick: onLab } : null,
    passportLabel && onPassport ? { key: "passport", label: passportLabel, onClick: onPassport } : null,
    connectorLabel && onConnector ? { key: "connector", label: connectorLabel, onClick: onConnector } : null,
    upsellLabel && onUpsell ? { key: "upsell", label: upsellLabel, onClick: onUpsell } : null,
    hasRelease && !publishPrimary
      ? {
          key: "release",
          label: releaseDisabled && releaseHint ? releaseHint : (releaseLabel as string),
          onClick: () => {
            if (!releaseDisabled) onRelease?.();
          },
        }
      : null,
  ].filter(
    (row): row is { key: string; label: string; onClick: () => void; share?: true } => Boolean(row),
  );

  useEffect(() => {
    if (!open) setShowMore(false);
  }, [open]);

  if (!open) return null;

  return (
    <BottomSheet
      open={open}
      onClose={() => {
        setShowMore(false);
        onClose();
      }}
      title={title}
      footer={
        <View className="celebration-sheet__footer">
          {publishPrimary ? (
            <Button variant="primary" block onClick={onRelease}>
              {releaseLabel}
            </Button>
          ) : firstTrackPrimary ? (
            <Button variant="primary" block onClick={onBeautify}>
              {beautifyLabel}
            </Button>
          ) : (
            <Button variant="primary" block onClick={() => Taro.switchTab({ url: "/pages/create/index" })}>
              {c.continueCreate}
            </Button>
          )}
          {firstTrackPrimary && communityLabel && onCommunity ? (
            <Button variant="secondary" block onClick={onCommunity}>
              {communityLabel}
            </Button>
          ) : null}
          {showMore
            ? extras.map((row) =>
                row.share && workId ? (
                  <ShareButton
                    key={row.key}
                    className="ui-btn ui-btn--ghost ui-btn--sm ui-btn--block"
                    dataset={{ workid: workId, title: shareTitle || copy.brand.name }}
                    onShare={row.onClick}
                  >
                    {row.label}
                  </ShareButton>
                ) : (
                  <Button key={row.key} variant="ghost" block onClick={row.onClick}>
                    {row.label}
                  </Button>
                ),
              )
            : extras.length > 0 && (
                <Button variant="ghost" block onClick={() => setShowMore(true)}>
                  {c.moreActions}
                </Button>
              )}
        </View>
      }
    >
      <View className="celebration-sheet">
        <View className="celebration-sheet__confetti" aria-hidden />
        <Text className="celebration-sheet__body">{body}</Text>
        {variant === "publish" ? <Text className="celebration-sheet__body">{c.publishNotStore}</Text> : null}
      </View>
    </BottomSheet>
  );
}
