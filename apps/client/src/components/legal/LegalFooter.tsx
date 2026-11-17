import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { LEGAL_ROUTES } from "../../utils/legal";
import { useLegalMeta } from "../../hooks/useLegalMeta";
import "./LegalFooter.scss";

export function LegalFooter() {
  const { copy } = useLocale();
  const l = copy.legalUi;
  const meta = useLegalMeta();

  const links = [
    { label: l.privacyPolicy, route: LEGAL_ROUTES.privacy },
    { label: l.termsOfService, route: LEGAL_ROUTES.terms },
    { label: l.aiServiceNotice, route: LEGAL_ROUTES.aiNotice },
    { label: l.paymentTerms, route: LEGAL_ROUTES.paymentTerms },
    { label: l.minorProtection, route: LEGAL_ROUTES.minorProtection },
    { label: l.distributionLicense, route: LEGAL_ROUTES.distributionLicense },
    { label: l.royaltyPayout, route: LEGAL_ROUTES.royaltyPayout },
  ];

  const icp = meta?.icp_number?.trim();

  return (
    <View className="legal-footer">
      <View className="legal-footer__links">
        {links.map((link, i) => (
          <Text key={link.route}>
            {i > 0 ? <Text className="legal-footer__sep"> · </Text> : null}
            <Text className="legal-footer__link" onClick={() => Taro.navigateTo({ url: link.route })}>
              {link.label}
            </Text>
          </Text>
        ))}
      </View>
      {icp ? (
        <Text className="legal-footer__icp">{l.icpLabel.replace("{icp}", icp)}</Text>
      ) : (
        <Text className="legal-footer__icp">{l.icpPending}</Text>
      )}
      {meta?.company_name ? (
        <Text className="legal-footer__company">{l.operatedBy.replace("{name}", meta.company_name)}</Text>
      ) : null}
      <Text className="legal-footer__company">{l.analysisOptional}</Text>
      {meta?.contact_email || meta?.contact_phone ? (
        <Text className="legal-footer__company">
          {[meta.contact_email, meta.contact_phone].filter(Boolean).join(" · ")}
        </Text>
      ) : null}
    </View>
  );
}
