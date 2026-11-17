import { useEffect, useMemo, useState } from "react";
import { View, Text, Input } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { Button, StatusLine } from "../components/ui";
import { vibeApi } from "../services/api";
import { CREATOR_TAB_ROUTE, creatorPage } from "../constants/routes";
import { openStackPage } from "../utils/navigation";
import { AuthDesk } from "./AuthDesk";
import { ChannelTimeline } from "./ChannelTimeline";
import { WeappH5Bridge } from "./WeappH5Bridge";
import { ensureSeatId, type ConnectionCard } from "./ConnectionsRow";
import {
  CHANNEL_PORTALS,
  channelName,
  defaultCheckedShipChannels,
  hasHandedVolumeStore,
  isLiveDelivery,
  leaseOwnerLabel,
  openExternal,
  pickShipBandAction,
  shipChannelGroup,
  type ConnectorLiveState,
  type DeliveryRow,
} from "./lib";
import { pairFromMinted, probeExtensionStatus, sendCommandToExtension, sendPairToExtension, sendPollToExtension } from "./extensionPair";
import { confirmQuickRelease, isQcReady, isReleaseInFlight, resumePendingQuickRelease } from "./quickReleaseAction";
import { cachedFarmNavigate, cachedPartnersConfigured } from "../platform/platformConfig";
import { getItem, setItem } from "../platform/storage";
import "./creator.scss";

type CatalogChannel = {
  code: string;
  name?: string;
  automation_level?: string;
  capability?: string;
};

type Props = {
  workId?: string;
  surface: "reveal" | "workbench" | "desk" | "deliveries";
  compact?: boolean;
  qcReady?: boolean;
  releaseStatus?: string;
  needsBeautify?: boolean;
  onBeautify?: () => void;
  connections?: ConnectionCard[] | null;
  deliveries?: DeliveryRow[] | null;
  connector?: ConnectorLiveState | null;
  weapp?: boolean;
  embedAuth?: boolean;
  farmNavigate?: boolean;
  partnersConfigured?: boolean;
  hasLicense?: boolean;
  onChanged?: () => void;
};

export function ShipCompleteCard({
  workId,
  surface,
  qcReady: qcReadyProp,
  releaseStatus: statusProp,
  compact,
  needsBeautify,
  onBeautify,
  connections: connectionsProp,
  deliveries: deliveriesProp,
  connector: connectorProp,
  weapp,
  embedAuth,
  farmNavigate,
  partnersConfigured,
  hasLicense: hasLicenseProp,
  onChanged,
}: Props) {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const weappEnv = weapp ?? process.env.TARO_ENV === "weapp";
  const showAuth = embedAuth ?? (surface !== "desk" && !compact);
  const [catalog, setCatalog] = useState<CatalogChannel[]>([]);
  const [defaults, setDefaults] = useState<string[]>([]);
  const [connections, setConnections] = useState<ConnectionCard[]>(connectionsProp || []);
  const [deliveries, setDeliveries] = useState<DeliveryRow[]>(deliveriesProp || []);
  const [connector, setConnector] = useState<ConnectorLiveState | null>(connectorProp || null);
  const [qcReady, setQcReady] = useState(Boolean(qcReadyProp));
  const [releaseStatus, setReleaseStatus] = useState(statusProp || "");
  const [checked, setChecked] = useState<string[]>([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pasteId, setPasteId] = useState("");
  const [pasteUrl, setPasteUrl] = useState("");
  const [extensionOn, setExtensionOn] = useState(false);
  const [hasLicense, setHasLicense] = useState(Boolean(hasLicenseProp));
  const [showStores, setShowStores] = useState(!compact);
  const farmOn = farmNavigate ?? cachedFarmNavigate();
  const partnersOn = partnersConfigured ?? cachedPartnersConfigured();

  useEffect(() => {
    if (connectionsProp) setConnections(connectionsProp);
  }, [connectionsProp]);
  useEffect(() => {
    if (deliveriesProp) setDeliveries(deliveriesProp);
  }, [deliveriesProp]);
  useEffect(() => {
    if (connectorProp) setConnector(connectorProp);
  }, [connectorProp]);
  useEffect(() => {
    if (qcReadyProp != null) setQcReady(qcReadyProp);
  }, [qcReadyProp]);
  useEffect(() => {
    if (statusProp != null) setReleaseStatus(statusProp);
  }, [statusProp]);
  useEffect(() => {
    if (hasLicenseProp) {
      setHasLicense(true);
      setConsent(true);
    }
  }, [hasLicenseProp]);

  useEffect(() => {
    if (process.env.TARO_ENV !== "h5") return;
    void probeExtensionStatus().then((status) => setExtensionOn(status.installed));
  }, []);

  async function refresh() {
    const skipHub = Boolean(connectionsProp && connectorProp && hasLicenseProp != null);
    const [ch, del, hub, work] = await Promise.all([
      vibeApi.listReleaseChannels().catch(() => null),
      workId ? vibeApi.listDeliveries(workId).catch(() => null) : Promise.resolve(null),
      skipHub ? Promise.resolve(null) : vibeApi.getCreatorHub().catch(() => null),
      workId && (qcReadyProp == null || !statusProp) ? vibeApi.getWork(workId).catch(() => null) : Promise.resolve(null),
    ]);
    if (ch?.channels) setCatalog(ch.channels.map((row) => ({ code: row.code, name: row.name, automation_level: (row as { automation_level?: string }).automation_level, capability: row.capability })));
    if (ch?.default_channels) setDefaults(ch.default_channels);
    if (del?.deliveries) setDeliveries(del.deliveries as DeliveryRow[]);
    const hubRec = hub as {
      connections?: ConnectionCard[];
      connector?: ConnectorLiveState;
      has_distribution_license?: boolean;
    } | null;
    if (hubRec?.connections && !connectionsProp) setConnections(hubRec.connections);
    if (hubRec?.connector && !connectorProp) setConnector(hubRec.connector);
    if (hubRec?.has_distribution_license) {
      setHasLicense(true);
      setConsent(true);
    }
    if (work) {
      const status = String((work as { release_status?: string }).release_status || "");
      setReleaseStatus(status);
      setQcReady(isQcReady(status));
    }
  }

  useEffect(() => {
    let alive = true;
    void refresh().then(() => {
      if (!alive) return;
    });
    const timer = setInterval(() => {
      void refresh();
    }, 8000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [workId]);

  const connectedCodes = useMemo(
    () => connections.filter((row) => row.status === "settle" || row.status === "metrics").map((row) => row.channel_code),
    [connections],
  );
  const handed = hasHandedVolumeStore(connections);

  useEffect(() => {
    if (checked.length) return;
    const pool = defaults.length ? defaults : catalog.map((row) => row.code);
    setChecked(defaultCheckedShipChannels(pool, connectedCodes));
  }, [defaults, catalog, connectedCodes, checked.length]);

  useEffect(() => {
    if (deliveries.length || isReleaseInFlight(releaseStatus)) setConsent(true);
  }, [deliveries.length, releaseStatus]);

  const groups = useMemo(() => {
    const rows = catalog.length ? catalog : defaults.map((code) => ({ code }));
    const fill: CatalogChannel[] = [];
    const metrics: CatalogChannel[] = [];
    const ops: CatalogChannel[] = [];
    for (const row of rows) {
      const group = shipChannelGroup(row.code, row.automation_level);
      if (group === "metrics") metrics.push(row);
      else if (group === "ops") ops.push(row);
      else fill.push(row);
    }
    return { fill, metrics, ops };
  }, [catalog, defaults]);

  const connectorOnline = extensionOn || Boolean(connector?.online);
  const band = pickShipBandAction({ deliveries, connectorOnline, weapp: weappEnv });
  const shipping = isReleaseInFlight(releaseStatus) || deliveries.some((row) => ["session_wait", "session_running", "ops_queue", "submitting"].includes(row.status || ""));
  const canShip = Boolean(workId) && consent && (qcReady || isReleaseInFlight(releaseStatus)) && checked.length > 0;
  const liveOk = deliveries.some((row) => isLiveDelivery(row));
  const licensed = hasLicense || consent;
  const humanHold = ["challenge", "incomplete", "degraded", "ghost_live", "install", "wait_login"].includes(band.kind);

  function toggle(code: string, group: "fill" | "metrics" | "ops") {
    if (group === "metrics" && !connectedCodes.includes(code)) {
      Taro.showToast({ title: c.shipMetricsNeedSeat, icon: "none" });
      return;
    }
    setChecked((prev) => (prev.includes(code) ? prev.filter((item) => item !== code) : [...prev, code]));
  }

  async function shipNow() {
    if (!workId || !canShip) return;
    setBusy(true);
    try {
      await confirmQuickRelease({
        workId,
        qcReady,
        releaseStatus,
        skipConfirm: consent,
        stayOnCard: true,
        selectedChannels: checked,
        copy: {
          confirmOnce: c.confirmOnce,
          confirmOnceHint: c.confirmOnceHint,
          confirmGo: c.confirmGo,
          labelHint: c.labelHint,
          back: c.back,
          oneTapOk: c.oneTapOk,
        },
        actionFail: copy.adminUi.actionFail,
        onDone: async () => {
          await refresh();
          onChanged?.();
        },
      });
    } finally {
      setBusy(false);
    }
  }

  async function retryFill(id: string) {
    try {
      await vibeApi.retryDelivery(id);
      Taro.showToast({ title: c.shipRetryFill, icon: "none" });
      await refresh();
      onChanged?.();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    }
  }

  async function pasteReceipt() {
    if (!pasteId || !pasteUrl.trim()) return;
    try {
      await vibeApi.setDeliveryStoreUrl(pasteId, pasteUrl.trim());
      setPasteUrl("");
      await refresh();
      onChanged?.();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    }
  }

  async function wakeCopy() {
    const sent = await sendPollToExtension();
    Taro.showToast({ title: sent ? c.harvestWakeSent : c.shipFarmLocal, icon: sent ? "success" : "none" });
  }

  async function openStore(row: DeliveryRow) {
    const portal = row.upload_url || CHANNEL_PORTALS[row.channel_code];
    const conn = connections.find((item) => item.channel_code === row.channel_code);
    try {
      const seatId = conn ? await ensureSeatId(conn) : row.seat_id;
      if (seatId && !weappEnv) {
        await vibeApi.commandSeat(String(seatId), "open_portal", { login_url: portal });
        if (connectorOnline) {
          await sendCommandToExtension({
            kind: "open_portal",
            seatId: String(seatId),
            channel: row.channel_code,
            payload: { login_url: portal },
          });
        }
        void sendPollToExtension();
        Taro.showToast({ title: c.shipOpenStore, icon: "success" });
        onChanged?.();
        return;
      }
    } catch {
      Taro.showToast({ title: c.shipOpenStore, icon: "none" });
    }
    openExternal(portal);
  }

  async function pairNow() {
    if (weappEnv) {
      Taro.showToast({ title: c.connectorBrowserOnly, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      const minted = await vibeApi.mintConnectorToken();
      const sent = await sendPairToExtension(pairFromMinted(minted));
      if (sent) {
        setExtensionOn(true);
        Taro.showToast({ title: c.sentToExtension, icon: "success" });
        void sendPollToExtension();
        await resumePendingQuickRelease(
          {
            confirmOnce: c.confirmOnce,
            confirmOnceHint: c.confirmOnceHint,
            confirmGo: c.confirmGo,
            labelHint: c.labelHint,
            back: c.back,
            oneTapOk: c.oneTapResumeOk || c.oneTapOk,
          },
          copy.adminUi.actionFail,
        );
        onChanged?.();
        return;
      }
      await Taro.setClipboardData({ data: minted.pair_text || minted.token });
      Taro.showToast({ title: c.pairCopiedHint, icon: "none" });
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  function renderGroup(title: string, rows: CatalogChannel[], group: "fill" | "metrics" | "ops") {
    if (!rows.length) return null;
    return (
      <View className="ship-complete__group">
        <Text className="ship-complete__group-title">{title}</Text>
        {group === "ops" && !partnersOn ? <Text className="typo-meta">{c.shipPartnerQueue}</Text> : null}
        {group === "metrics" ? <Text className="typo-meta">{c.routePreviewMetrics}</Text> : null}
        <View className="ship-complete__chips">
          {rows.map((row) => {
            const on = checked.includes(row.code);
            const locked = group === "metrics" && !connectedCodes.includes(row.code);
            return (
              <Text
                key={row.code}
                className={on ? "ship-complete__chip is-on" : locked ? "ship-complete__chip is-locked" : "ship-complete__chip"}
                onClick={() => toggle(row.code, group)}
              >
                {row.name || channelName(row.code, c.channels) || row.code}
              </Text>
            );
          })}
        </View>
      </View>
    );
  }

  const filling = band.kind === "filling" || band.kind === "lease" ? band.row : deliveries.find((row) => ["session_running", "assisting"].includes(row.user_status || row.status || ""));

  useEffect(() => {
    if (weappEnv || !connectorOnline || band.kind !== "wait_login" || !band.row?.id) return;
    const row = band.row;
    const conn = connections.find((item) => item.channel_code === row.channel_code);
    if (!row.seat_id && !conn?.seat_id) return;
    const key = `bittune.autoOpenStore:${row.id}`;
    if (getItem(key)) return;
    setItem(key, "1");
    void openStore(row);
  }, [weappEnv, connectorOnline, band.kind, band.row?.id, connections]);

  useEffect(() => {
    if (weappEnv || !connectorOnline || band.kind !== "incomplete" || !band.row?.id) return;
    const key = `bittune.autoPollFill:${band.row.id}`;
    if (getItem(key)) return;
    setItem(key, "1");
    void sendPollToExtension();
  }, [weappEnv, connectorOnline, band.kind, band.row?.id]);

  useEffect(() => {
    if (weappEnv || !extensionOn || farmOn) return;
    if (band.kind !== "lease" && band.kind !== "filling") return;
    if (!band.row?.id) return;
    const key = `bittune.autoPollRun:${band.row.id}`;
    if (getItem(key)) return;
    setItem(key, "1");
    void sendPollToExtension();
  }, [weappEnv, extensionOn, farmOn, band.kind, band.row?.id]);

  useEffect(() => {
    if (weappEnv || !extensionOn || farmOn || !hasLicense) return;
    const pending = deliveries.filter((item) => isLiveDelivery(item) && item.id && !getItem(`bittune.autoHarvest:${item.id}`));
    if (!pending.length) return;
    for (const row of pending) setItem(`bittune.autoHarvest:${row.id}`, "1");
    void sendPollToExtension();
  }, [weappEnv, extensionOn, farmOn, hasLicense, deliveries]);

  return (
    <View id="ship-complete-band" className={`ship-complete${surface === "desk" ? " ship-complete--desk" : ""}${compact ? " ship-complete--compact" : ""}`}>
      <Text className="ship-complete__title">{c.shipBandTitle}</Text>
      {deliveries.length ? (
        <ChannelTimeline
          deliveries={deliveries}
          labels={{
            handoff: c.status.waiting_login,
            assisting: c.status.assisting,
            ops: c.status.ops_handling,
            live: c.status.live,
            timelineOpen: c.timelineOpen,
            timelineFill: c.timelineFill,
            timelineAttach: c.timelineAttach,
            timelineSubmit: c.timelineSubmit,
            timelineReceipt: c.timelineReceipt,
            timelineNow: c.timelineNow,
            ...c,
          }}
        />
      ) : null}
      {filling ? (
        <StatusLine tone="info" density="quiet">
          {c.connectorLastDelivery
            .replace("{name}", channelName(filling.channel_code, c.channels) || filling.channel_code)
            .replace("{event}", c.timelineFill)
            .replace("{msg}", "")}
        </StatusLine>
      ) : null}
      <Text className="typo-meta">{c.shipBandHint}</Text>
      {compact ? null : <Text className="typo-meta">{c.shipNoGlobal}</Text>}
      {!farmOn ? <Text className="typo-meta">{c.shipFarmLocal}</Text> : null}

      {needsBeautify && onBeautify ? (
        <View className="ship-complete__fork">
          <Button size="sm" variant="secondary" onClick={onBeautify}>
            {c.shipBeautifyFirst}
          </Button>
          <Text className="typo-meta">{c.shipDirectNow}</Text>
        </View>
      ) : null}

      {!qcReady && !isReleaseInFlight(releaseStatus) ? <StatusLine tone="info" density="quiet">{c.shipQcGate}</StatusLine> : null}

      <Button variant="secondary" block onClick={() => openStackPage(creatorPage("release", { workId }))}>
        {c.shipOpenForm}
      </Button>
      <Text className="typo-meta">{c.shipDiscoverSplit}</Text>

      {band.row && (band.kind === "lease" || band.kind === "filling") ? (
        <View className="ship-complete__alert">
          <StatusLine tone="info" density="quiet">
            {leaseOwnerLabel(band.row, c, farmOn)}
          </StatusLine>
          {extensionOn && !weappEnv && !farmOn ? <Text className="typo-meta">{c.shipFillWoke}</Text> : null}
        </View>
      ) : null}

      {band.kind === "challenge" && band.row ? (
        <View className="ship-complete__alert">
          <StatusLine tone="error" density="quiet">{c.shipChallenge}</StatusLine>
          <Button size="sm" variant="primary" onClick={() => void openStore(band.row!)}>
            {c.shipChallengeGo}
          </Button>
        </View>
      ) : null}

      {band.kind === "degraded" && band.row ? (
        <View className="ship-complete__drop">
          <StatusLine tone="info" density="quiet">{c.shipDragMaster}</StatusLine>
          <Button size="sm" variant="primary" onClick={() => void openStore(band.row!)}>
            {c.shipDragMaster}
          </Button>
        </View>
      ) : null}

      {band.kind === "incomplete" && band.row ? (
        <View className="ship-complete__alert">
          <StatusLine tone="info" density="quiet">{c.shipFillIncomplete}</StatusLine>
          {connectorOnline && !weappEnv ? <Text className="typo-meta">{c.shipFillWoke}</Text> : null}
          {(() => {
            const health =
              connections.find((item) => item.channel_code === band.row?.channel_code)?.farm_health ||
              connections.find((item) => item.channel_code === band.row?.channel_code)?.seat?.farm_health;
            if (!health) return null;
            if (health.license_blocked) return <Text className="typo-meta">{c.shipLicenseSettleNeed}</Text>;
            if (health.handed_to_extension) return <Text className="typo-meta">{c.shipFarmLocal}</Text>;
            return c.seatFarmHealth ? (
              <Text className="typo-meta">
                {c.seatFarmHealth
                  .replace("{n}", String(health.matched ?? health.rows ?? 0))
                  .replace("{src}", health.official_csv ? "CSV" : "DOM")}
              </Text>
            ) : null;
          })()}
          <Button size="sm" variant="secondary" onClick={() => void retryFill(band.row!.id)}>
            {c.shipRetryFill}
          </Button>
        </View>
      ) : null}

      {band.kind === "ghost_live" && band.row ? (
        <View className="ship-complete__paste">
          <StatusLine tone="info" density="quiet">{c.shipPublishingPaste}</StatusLine>
          <Text className="typo-meta">{c.shipPasteReceipt}</Text>
          <Input
            className="ship-complete__input"
            value={pasteId === band.row.id ? pasteUrl : ""}
            placeholder={c.storePasteHint}
            onInput={(e) => {
              setPasteId(band.row!.id);
              setPasteUrl(e.detail.value);
            }}
          />
          <Button size="sm" variant="ghost" onClick={() => void pasteReceipt()}>
            {c.pasteStoreFallback}
          </Button>
        </View>
      ) : null}

      {band.kind === "install" ? (
        <View className="ship-complete__alert">
          <StatusLine tone="info" density="quiet">{c.sessionWaitHint}</StatusLine>
          <Button size="sm" variant="primary" loading={busy} onClick={() => void pairNow()}>
            {c.shipPairNow}
          </Button>
          <Text className="typo-meta">{c.pairInstallHint}</Text>
        </View>
      ) : null}

      {band.kind === "wait_login" && band.row ? (
        <View className="ship-complete__alert">
          <StatusLine tone="info" density="quiet">{c.sessionWaitHint}</StatusLine>
          <Button size="sm" variant="primary" onClick={() => void openStore(band.row!)}>
            {c.shipOpenStore}
          </Button>
        </View>
      ) : null}

      {weappEnv ? <WeappH5Bridge path={CREATOR_TAB_ROUTE} workId={workId} nextAction={connector?.last_delivery?.status} /> : null}

      {showAuth ? (
        <AuthDesk
          connections={connections}
          weapp={weappEnv}
          onChanged={() => {
            void refresh();
            onChanged?.();
          }}
        />
      ) : !handed && !weappEnv && band.kind === "ready" ? (
        <Text className="typo-meta">{c.oneTapWaitConnector}</Text>
      ) : null}

      {shipping ? <Text className="typo-meta">{c.shipWake}</Text> : null}

      {liveOk ? (
        <View className="ship-complete__alert">
          <StatusLine tone="success" density="quiet">{licensed ? c.shipSettleHint : c.shipLicenseSettleNeed}</StatusLine>
          {licensed ? (
            <Button size="sm" variant="secondary" onClick={() => openStackPage(creatorPage("settlements"))}>
              {c.shipSettleNext}
            </Button>
          ) : null}
          {!weappEnv && !farmOn ? (
            <Button size="sm" variant="ghost" onClick={() => void wakeCopy()}>
              {c.harvestWake}
            </Button>
          ) : null}
          {!weappEnv && !farmOn && hasLicense && extensionOn ? <Text className="typo-meta">{c.harvestWakeSent}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}
