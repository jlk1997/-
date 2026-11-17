import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { creatorOsH5Ready, creatorOsH5Url, refreshPlatformHonesty } from "../platform/platformConfig";
import { getLocaleCopy } from "../utils/localeCopy";
import { Button } from "../components/ui";
import { CREATOR_TAB_ROUTE } from "../constants/routes";
import { vibeApi } from "../services/api";

type Props = {
  path?: string;
  workId?: string;
  nextAction?: string;
};

export async function copyWeappCreatorLink(path: string) {
  await refreshPlatformHonesty();
  const url = creatorOsH5Url(path);
  const c = getLocaleCopy().creatorUi;
  if (!creatorOsH5Ready(path)) {
    Taro.showToast({ title: c.weappH5NeedOrigin, icon: "none" });
    return false;
  }
  await Taro.setClipboardData({ data: url });
  Taro.showToast({ title: c.weappH5Copied, icon: "success" });
  return true;
}

export function WeappH5Bridge({ path = CREATOR_TAB_ROUTE, workId, nextAction }: Props) {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const [progress, setProgress] = useState("");

  useEffect(() => {
    if (process.env.TARO_ENV !== "weapp") return;
    let alive = true;
    async function poll() {
      try {
        const hub = (await vibeApi.getCreatorHub()) as {
          connector?: { queue_count?: number; last_delivery?: { status?: string; event?: string } };
          next_action?: string;
          session_wait_count?: number;
        };
        const queue = Number(hub.connector?.queue_count || 0);
        const status = String(
          nextAction || hub.next_action || hub.connector?.last_delivery?.status || hub.connector?.last_delivery?.event || "",
        );
        const working =
          queue > 0 ||
          Number(hub.session_wait_count || 0) > 0 ||
          ["assisting", "session_running", "session_wait", "wait_connector", "needs_challenge", "fill_incomplete", "needs_upload"].includes(
            status,
          );
        if (alive) setProgress(working ? c.shipWeappPc : "");
      } catch {
        if (alive && (nextAction || workId)) setProgress((prev) => prev || c.shipWeappPc);
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 8000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [workId, nextAction, c.shipWeappPc]);

  if (process.env.TARO_ENV !== "weapp") return null;
  const ready = creatorOsH5Ready(path);

  return (
    <View className="creator-h5-bridge">
      {ready ? null : <Text className="typo-meta">{c.weappH5NeedOrigin}</Text>}
      {progress ? <Text className="creator-h5-bridge__hint">{progress}</Text> : null}
      <Button variant="primary" block disabled={!ready} onClick={() => void copyWeappCreatorLink(path)}>
        {ready ? c.weappH5Hint : c.weappH5NeedOrigin}
      </Button>
    </View>
  );
}
