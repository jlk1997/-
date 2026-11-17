import { useEffect, useState } from "react";
import { View } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { vibeApi } from "../../services/api";
import { cachedMockAi, cachedMockPayment, cachePlatformHonesty } from "../../platform/platformConfig";
import { StatusLine } from "../ui";
import "./LaunchHonestyBanner.scss";

type Props = {
  surface?: "create" | "pricing" | "feed" | "hub" | "wallet";
};

/** Operational honesty — mock flags plus farm / partner truth on the creator hub. */
export function LaunchHonestyBanner({ surface = "create" }: Props) {
  const { copy } = useLocale();
  const [mockAi, setMockAi] = useState(() => cachedMockAi());
  const [mockPay, setMockPay] = useState(() => cachedMockPayment());
  const [farmNavigate, setFarmNavigate] = useState<boolean | null>(null);
  const [partnersConfigured, setPartnersConfigured] = useState<boolean | null>(null);
  const [kycConfigured, setKycConfigured] = useState<boolean | null>(null);
  const [essentiaReady, setEssentiaReady] = useState<boolean | null>(null);

  useEffect(() => {
    vibeApi
      .getPlatformConfig()
      .then((cfg) => {
        cachePlatformHonesty(cfg);
        setMockAi(Boolean(cfg.mock_ai));
        setMockPay(Boolean(cfg.mock_payment));
        setFarmNavigate(cfg.farm_navigate === true);
        setPartnersConfigured(cfg.partners_configured === true);
        setKycConfigured(cfg.kyc_provider_configured === true);
        setEssentiaReady(cfg.essentia_ready === true);
      })
      .catch(() => {});
  }, []);

  const showPay = mockPay && (surface === "pricing" || surface === "hub");
  const showFarm = surface === "hub" && farmNavigate === false;
  const showPartners = surface === "hub" && partnersConfigured === false;
  const showKyc = (surface === "hub" || surface === "wallet") && kycConfigured === false;
  const showEssentia = surface === "hub" && essentiaReady === false;
  if (!mockAi && !showPay && !showFarm && !showPartners && !showKyc && !showEssentia) return null;

  return (
    <View className="honesty-banner honesty-banner--compact">
      {mockAi ? <StatusLine tone="error">{copy.createUi.mockAiBanner}</StatusLine> : null}
      {showPay ? <StatusLine tone="error">{copy.pricingUi.mockPayBanner}</StatusLine> : null}
      {showFarm ? <StatusLine tone="warning">{copy.creatorUi.automationFarmOff}</StatusLine> : null}
      {showPartners ? <StatusLine tone="warning">{copy.creatorUi.automationNoPartner}</StatusLine> : null}
      {showKyc ? <StatusLine tone="warning">{copy.creatorUi.automationNoKyc}</StatusLine> : null}
      {showEssentia ? <StatusLine tone="warning">{copy.journeyUi.audioAnchorDegraded}</StatusLine> : null}
    </View>
  );
}
