import { LOCALE_STORAGE_KEY } from "@vibe-sorcery/i18n";
import { getItem } from "../platform/storage";

export const LEGAL_STORAGE_KEYS = {
  privacyAccepted: "legal:privacy_accepted",
  privacyVersion: "legal:privacy_version",
} as const;

export const LEGAL_ROUTES = {
  privacy: "/packageLegal/pages/privacy/index",
  terms: "/packageLegal/pages/terms/index",
  aiNotice: "/packageLegal/pages/ai-notice/index",
  communityRules: "/packageLegal/pages/community-rules/index",
  paymentTerms: "/packageLegal/pages/payment-terms/index",
  minorProtection: "/packageLegal/pages/minor-protection/index",
  distributionLicense: "/packageLegal/pages/distribution-license/index",
  royaltyPayout: "/packageLegal/pages/royalty-payout/index",
} as const;

export const LEGAL_SLUGS = {
  privacy: "privacy-policy",
  terms: "terms-of-service",
  aiNotice: "ai-service-notice",
  communityRules: "community-guidelines",
  paymentTerms: "payment-terms",
  minorProtection: "minor-protection",
  distributionLicense: "distribution-license",
  royaltyPayout: "royalty-payout",
} as const;

export function legalDocLabel(name: string, locale: string) {
  return locale === "en" ? name : `《${name}》`;
}

export function openLegalPage(route: string) {
  const Taro = require("@tarojs/taro").default;
  const title = getItem(LOCALE_STORAGE_KEY) === "en" ? "Couldn’t open this page" : "无法打开页面";
  Taro.navigateTo({ url: route }).catch(() => {
    Taro.showToast({ title, icon: "none" });
  });
}
