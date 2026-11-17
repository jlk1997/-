import { Text, View } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { Button } from "../components/ui";

export function ConnectorInstall({ weapp }: { weapp?: boolean }) {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  if (weapp) {
    return <Text className="connector-install__note">{c.connectorBrowserOnly}</Text>;
  }
  return (
    <View className="connector-install">
      <Text className="connector-install__title">{c.connectorInstallTitle}</Text>
      <Text className="connector-install__line">1. {c.connectorStepDownload}</Text>
      <Button
        size="sm"
        variant="primary"
        onClick={() => {
          if (typeof window !== "undefined") window.location.assign("/connector/bityin-connector.zip");
        }}
      >
        {c.connectorDownload}
      </Button>
      <Text className="connector-install__line">2. {c.connectorStepUnzip}</Text>
      <Text className="connector-install__line">3. {c.connectorStepChrome}</Text>
      <Text className="connector-install__line">4. {c.connectorStepDev}</Text>
      <Text className="connector-install__line">5. {c.connectorStepLoad}</Text>
      <Text className="connector-install__note">{c.connectorPhoneNote}</Text>
    </View>
  );
}
