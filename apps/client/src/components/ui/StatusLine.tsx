import { View, Text } from "@tarojs/components";
import { clsx } from "../../utils/clsx";
import "./ui.scss";

type Tone = "info" | "success" | "error" | "loading" | "warning";

export function StatusLine({
  tone = "info",
  density,
  children,
  onClick,
}: {
  tone?: Tone;
  density?: "default" | "quiet";
  children: string;
  onClick?: () => void;
}) {
  return (
    <View
      className={clsx(
        "ui-status",
        `ui-status--${tone}`,
        density === "quiet" && "ui-status--quiet",
        onClick && "ui-status--tap",
      )}
      onClick={onClick}
    >
      <Text>{children}</Text>
    </View>
  );
}
