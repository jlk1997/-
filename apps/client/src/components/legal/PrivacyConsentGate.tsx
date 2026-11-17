import { useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { Button } from "../ui";
import { ConsentCheckbox } from "./ConsentCheckbox";
import { LEGAL_ROUTES, LEGAL_STORAGE_KEYS, legalDocLabel } from "../../utils/legal";
import { getItem, setItem } from "../../platform/storage";
import "./PrivacyConsentGate.scss";

type Props = {
  onAccepted: () => void;
  readingLegal?: boolean;
};

export function PrivacyConsentGate({ onAccepted, readingLegal = false }: Props) {
  const { copy, locale } = useLocale();
  const l = copy.legalUi;
  const [checked, setChecked] = useState(false);
  const privacyLabel = legalDocLabel(l.privacyPolicy, locale);
  const termsLabel = legalDocLabel(l.termsOfService, locale);

  function accept() {
    if (!checked) {
      Taro.showToast({ title: l.mustAgree, icon: "none" });
      return;
    }
    setItem(LEGAL_STORAGE_KEYS.privacyAccepted, "1");
    setItem(LEGAL_STORAGE_KEYS.privacyVersion, "2026-07-20");
    onAccepted();
  }

  if (readingLegal) return null;

  return (
    <View className="privacy-gate">
      <View className="privacy-gate__card">
        <Text className="privacy-gate__title">{l.privacyGateTitle}</Text>
        <Text className="privacy-gate__body">{l.privacyGateBody}</Text>
        <ConsentCheckbox
          checked={checked}
          onChange={setChecked}
          links={[
            { label: termsLabel, route: LEGAL_ROUTES.terms },
            { label: privacyLabel, route: LEGAL_ROUTES.privacy },
          ]}
        >
          {l.agreePrefix}
        </ConsentCheckbox>
        <View className="privacy-gate__actions">
          <Button variant="primary" block onClick={accept}>
            {l.privacyGateAgree}
          </Button>
          <Button
            variant="ghost"
            block
            onClick={() => Taro.showToast({ title: l.privacyGateDeclineHint, icon: "none" })}
          >
            {l.privacyGateDecline}
          </Button>
        </View>
      </View>
    </View>
  );
}

export function hasLocalPrivacyConsent(): boolean {
  return getItem(LEGAL_STORAGE_KEYS.privacyAccepted) === "1";
}
