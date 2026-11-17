import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { Button, StatusLine } from "../components/ui";
import { vibeApi } from "../services/api";
import { CREATOR_TAB_ROUTE } from "../constants/routes";
import { ConnectionsRow, ensureSeatId, SeatScopeToggles, type ConnectionCard } from "./ConnectionsRow";
import { ConnectorInstall } from "./ConnectorInstall";
import { channelName, confirmCreatorAction, hasHandedVolumeStore, pickNextAuthStore } from "./lib";
import { pairFromMinted, probeExtensionStatus, sendCommandToExtension, sendPairToExtension, sendPollToExtension } from "./extensionPair";
import { resumePendingQuickRelease } from "./quickReleaseAction";
import { WeappH5Bridge } from "./WeappH5Bridge";
import { getLocaleCopy } from "../utils/localeCopy";

export function AuthDesk({
  connections,
  weapp,
  onChanged,
}: {
  connections?: ConnectionCard[] | null;
  weapp?: boolean;
  onChanged?: () => void;
}) {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const [extensionOn, setExtensionOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pairCopied, setPairCopied] = useState(false);
  const nextStore = pickNextAuthStore(connections);
  const handed = hasHandedVolumeStore(connections);
  const reloginDue = (connections || []).find((row) => row.relogin_due && row.status !== "needs_login" && row.status !== "disconnected");

  useEffect(() => {
    if (process.env.TARO_ENV !== "h5") return;
    void probeExtensionStatus().then((status) => setExtensionOn(status.installed));
  }, []);

  useEffect(() => {
    if (weapp || !nextStore || nextStore.seat_id) return;
    let alive = true;
    void ensureSeatId(nextStore).then((id) => {
      if (alive && id) onChanged?.();
    });
    return () => {
      alive = false;
    };
  }, [weapp, nextStore?.channel_code, nextStore?.seat_id]);

  useEffect(() => {
    if (!handed || weapp) return;
    const locale = getLocaleCopy();
    void resumePendingQuickRelease(
      {
        confirmOnce: locale.creatorUi.confirmOnce,
        confirmOnceHint: locale.creatorUi.confirmOnceHint,
        confirmGo: locale.creatorUi.confirmGo,
        labelHint: locale.creatorUi.labelHint,
        back: locale.creatorUi.back,
        oneTapOk: locale.creatorUi.oneTapResumeOk || locale.creatorUi.oneTapOk,
      },
      locale.adminUi.actionFail,
    );
  }, [handed, weapp]);

  async function pairOnce() {
    const minted = await vibeApi.mintConnectorToken();
    const sent = await sendPairToExtension(pairFromMinted(minted));
    if (sent) {
      setExtensionOn(true);
      setPairCopied(false);
      return true;
    }
    await Taro.setClipboardData({ data: minted.pair_text || minted.token });
    setPairCopied(true);
    return false;
  }

  async function pair() {
    if (weapp) {
      Taro.showToast({ title: c.connectorBrowserOnly, icon: "none" });
      return false;
    }
    const ready = await confirmCreatorAction({
      title: c.pairInstallTitle,
      content: c.pairInstallHint,
      confirmText: c.confirmGo,
      cancelText: c.back,
    });
    if (!ready) return false;
    setBusy(true);
    try {
      const sent = await pairOnce();
      Taro.showToast({ title: sent ? c.sentToExtension : c.pairCopiedHint, icon: sent ? "success" : "none" });
      if (sent) onChanged?.();
      return sent;
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function handNext() {
    if (!nextStore) return;
    if (weapp) {
      Taro.showToast({ title: c.connectorBrowserOnly, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      if (!extensionOn) {
        try {
          const sent = await pairOnce();
          if (!sent) Taro.showToast({ title: c.pairCopiedHint, icon: "none" });
        } catch {
          /* open the official page anyway */
        }
      }
      const seatId = await ensureSeatId(nextStore);
      if (!seatId) {
        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
        return;
      }
      const firstPage = nextStore.first_page || nextStore.portal;
      await vibeApi.commandSeat(seatId, "open_portal", { login_url: firstPage });
      if (extensionOn) {
        await sendCommandToExtension({
          kind: "open_portal",
          seatId,
          channel: nextStore.channel_code,
          payload: { login_url: firstPage },
        });
      }
      Taro.showToast({ title: c.authDeskNextGo, icon: "success" });
      void sendPollToExtension();
      onChanged?.();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <View className="creator-card">
      <View className="creator-desk__head-row">
        <Text className="creator-mode__title">{c.authDeskTitle}</Text>
        {!weapp ? (
          <Text className={extensionOn ? "creator-lamp creator-lamp--on" : "creator-lamp"}>{extensionOn ? c.connectorOn : c.connectorOff}</Text>
        ) : null}
      </View>
      <Text className="typo-meta">{weapp ? c.authDeskHintWeapp : c.authDeskHint}</Text>
      {reloginDue ? (
        <StatusLine tone="info" density="quiet">
          {c.connReloginDue.replace("{name}", channelName(reloginDue.channel_code, c.channels) || reloginDue.name || reloginDue.channel_code)}
        </StatusLine>
      ) : null}
      {weapp ? <WeappH5Bridge path={CREATOR_TAB_ROUTE} /> : null}
      {!weapp && !extensionOn ? (
        <>
          <Button size="sm" variant="primary" loading={busy} onClick={() => void pair()}>
            {c.authDeskPair}
          </Button>
          <ConnectorInstall weapp={weapp} />
          <Text className="connector-install__note">{c.connectorLoadHint}</Text>
        </>
      ) : null}
      {pairCopied ? <StatusLine tone="info" density="quiet">{c.pairCopiedHint}</StatusLine> : null}
      {nextStore ? (
        <View className="creator-next-store">
          <Text className="creator-mode__title">
            {c.authDeskNextStore.replace("{name}", channelName(nextStore.channel_code, c.channels) || nextStore.name || nextStore.channel_code)}
          </Text>
          {nextStore.automation_level === "metrics_only" ? (
            <StatusLine tone="info" density="quiet">{c.routePreviewMetrics}</StatusLine>
          ) : nextStore.degraded || nextStore.automation_level === "connector_assist" ? (
            <StatusLine tone="info" density="quiet">{nextStore.degraded ? c.routePreviewDegraded : c.routePreviewAssist}</StatusLine>
          ) : null}
          <Text className="typo-meta">{c.authDeskPermissions}</Text>
          {!weapp && nextStore.seat_id ? (
            <SeatScopeToggles
              seatId={String(nextStore.seat_id)}
              scopes={nextStore.scopes}
              hasLicense={Boolean(nextStore.has_license)}
              automationLevel={nextStore.automation_level}
              copy={c}
              onDone={onChanged}
            />
          ) : null}
          {!weapp ? (
            <Button size="sm" variant="primary" loading={busy} onClick={() => void handNext()}>
              {c.authDeskNextGo}
            </Button>
          ) : null}
        </View>
      ) : handed ? (
        <StatusLine tone="success" density="quiet">{c.authDeskReady}</StatusLine>
      ) : (
        <Text className="typo-meta">{c.authDeskEmpty}</Text>
      )}
      <ConnectionsRow
        connections={connections}
        copy={c}
        weapp={weapp}
        extensionOn={extensionOn}
        compact
        onChanged={onChanged}
      />
    </View>
  );
}
