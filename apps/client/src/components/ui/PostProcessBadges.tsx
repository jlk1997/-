import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { Badge } from "./Badge";
import "./PostProcessBadges.scss";

type Props = {
  status?: Record<string, unknown>;
  c2paVerified?: boolean;
  c2paState?: string;
  onRetry?: () => void;
  retrying?: boolean;
};

export function PostProcessBadges({ status, c2paVerified, c2paState, onRetry, retrying }: Props) {
  const { copy } = useLocale();
  const w = copy.worksUi;
  const state = String(status?.state || "");
  const hls = Boolean(status?.hls_done || status?.hls_url);
  const cover = Boolean(status?.cover_done || status?.cover_url);
  const master = Boolean((status?.master as { key?: string; url?: string } | undefined)?.key || (status?.master as { url?: string } | undefined)?.url);
  const stems = (status?.stems as { quality?: string } | undefined) || {};
  const sku = String(status?.sku_kind || "");
  const failed = Boolean(status?.failed || status?.last_error);
  const degraded = state === "degraded" || failed;
  const pending = state === "pending" || state === "running";
  const c2pa =
    c2paState ||
    (status?.c2pa_done || status?.c2pa ? (status?.c2pa_embedded ? "embedded" : "sidecar") : c2paVerified ? "embedded" : "none");

  if (!status && c2pa === "none") return null;

  return (
    <View className="ui-pp-badges">
      {hls ? <Badge tone="success">{w.hlsReady}</Badge> : pending ? <Badge>{w.hlsPending}</Badge> : null}
      {cover ? <Badge tone="accent">{w.coverReady}</Badge> : pending ? <Badge>{w.coverPending}</Badge> : null}
      {master ? <Badge tone="success">{w.masterReady}</Badge> : null}
      {stems.quality === "demucs" ? <Badge tone="success">{w.stemsReview}</Badge> : stems.quality === "preview" ? <Badge>{w.stemsPreview}</Badge> : null}
      {sku === "instrumental" ? <Badge tone="accent">{w.instrumentalSku}</Badge> : null}
      {c2pa === "embedded" ? <Badge tone="success">{w.c2paEmbedded}</Badge> : c2pa === "sidecar" ? <Badge>{w.c2paSidecar}</Badge> : null}
      {degraded ? <Badge tone="warning">{w.artifactsDegraded}</Badge> : null}
      {degraded && onRetry ? (
        <Text
          className={retrying ? "ui-pp-badges__retry ui-pp-badges__retry--busy" : "ui-pp-badges__retry"}
          onClick={() => {
            if (!retrying) onRetry();
          }}
        >
          {retrying ? w.reprocessWorking : w.retryArtifacts}
        </Text>
      ) : null}
    </View>
  );
}
