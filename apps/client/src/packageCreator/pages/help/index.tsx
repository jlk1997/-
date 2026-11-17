import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { LEGAL_ROUTES } from "../../../utils/legal";
import { AssetLanes } from "../../../components/studio/AssetLanes";
import { Collapsible } from "../../../components/ui";
import "../../creator.scss";

type HelpQA = {
  q: "helpQ1" | "helpQ2" | "helpQ3" | "helpQ4" | "helpQ5" | "helpQ6" | "helpQ7" | "helpQ8" | "helpQ9" | "helpQ10" | "helpQ11";
  a: "helpA1" | "helpA2" | "helpA3" | "helpA4" | "helpA5" | "helpA6" | "helpA7" | "helpA8" | "helpA9" | "helpA10" | "helpA11";
};

const GROUPS: Array<{
  label: "helpGroupRelease" | "helpGroupStores" | "helpGroupMoney";
  storageKey: string;
  defaultOpen?: boolean;
  items: HelpQA[];
}> = [
  {
    label: "helpGroupRelease",
    storageKey: "creator-help-release",
    defaultOpen: true,
    items: [
      { q: "helpQ1", a: "helpA1" },
      { q: "helpQ2", a: "helpA2" },
      { q: "helpQ11", a: "helpA11" },
    ],
  },
  {
    label: "helpGroupStores",
    storageKey: "creator-help-stores",
    items: [
      { q: "helpQ6", a: "helpA6" },
      { q: "helpQ7", a: "helpA7" },
      { q: "helpQ9", a: "helpA9" },
      { q: "helpQ10", a: "helpA10" },
    ],
  },
  {
    label: "helpGroupMoney",
    storageKey: "creator-help-money",
    items: [
      { q: "helpQ3", a: "helpA3" },
      { q: "helpQ4", a: "helpA4" },
      { q: "helpQ5", a: "helpA5" },
      { q: "helpQ8", a: "helpA8" },
    ],
  },
];

export default function CreatorHelpPage() {
  const { copy } = useLocale();
  const c = copy.creatorUi;

  return (
    <PageShell title={c.helpTitle} subtitle={c.helpSubtitle} ambient>
      <View className="creator creator-help">
        {process.env.TARO_ENV === "weapp" ? (
          <Text className="typo-meta">{c.weappDeskHint}</Text>
        ) : null}
        <View className="creator-help__legend">
          <Text className="creator-help__legend-text">{c.helpLegendLead}</Text>
          <AssetLanes density="legend" />
        </View>
        {GROUPS.map((group) => (
          <Collapsible
            key={group.label}
            label={c[group.label]}
            storageKey={group.storageKey}
            defaultOpen={group.defaultOpen}
          >
            {group.items.map((row, i) => (
              <View key={row.q} className="creator-help__item">
                <Text className="creator-help__n">{String(i + 1).padStart(2, "0")}</Text>
                <View className="creator-help__body">
                  <Text className="creator-help__q">{c[row.q]}</Text>
                  <Text className="creator-help__a">{c[row.a]}</Text>
                </View>
              </View>
            ))}
          </Collapsible>
        ))}
        <View className="creator-help__legal creator-card--tap" onClick={() => Taro.navigateTo({ url: LEGAL_ROUTES.distributionLicense })}>
          <Text className="creator-help__legal-title">{c.helpLegalLicense}</Text>
        </View>
        <View className="creator-help__legal creator-card--tap" onClick={() => Taro.navigateTo({ url: LEGAL_ROUTES.royaltyPayout })}>
          <Text className="creator-help__legal-title">{c.helpLegalPayout}</Text>
        </View>
      </View>
    </PageShell>
  );
}
