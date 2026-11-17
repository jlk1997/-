import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { requireAuth } from "../../utils/auth";
import { hapticLight } from "../../utils/haptic";
import { Button } from "./Button";
import "./ui.scss";

type Props = {
  message?: string;
  loginLabel?: string;
  next?: string;
};

export function AuthBanner({ message, loginLabel, next }: Props) {
  const { copy } = useLocale();
  const text = message ?? copy.settingsUi.authBanner;
  const label = loginLabel ?? copy.loginUi.login;

  return (
    <View className="ui-auth-banner">
      <Text className="ui-auth-banner__text">{text}</Text>
      <Button
        size="sm"
        variant="primary"
        onClick={() => {
          hapticLight();
          requireAuth(next);
        }}
      >
        {label}
      </Button>
    </View>
  );
}
