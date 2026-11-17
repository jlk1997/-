import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh, useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { AsyncPanel, Button, ChipGroup, Collapsible, Input, ListRow, SectionLabel, StatusLine } from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { CREATOR_PAGE_ROUTES, creatorPage } from "../../../constants/routes";
import { NextActionCard } from "../../NextActionCard";
import { SeatLamps, type SeatLamp } from "../../SeatLamps";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import { ConnectionsRow, type ConnectionCard } from "../../ConnectionsRow";
import { channelName, confirmCreatorAction, connectorLiveLine, hasHandedVolumeStore, payoutChannelLabel, pickNextAuthStore, sessionWaitCta } from "../../lib";
import { resumePendingQuickRelease } from "../../quickReleaseAction";
import { listenExtensionEvents, markBittunePage, pairFromMinted, probeExtensionStatus, sendPairToExtension, sendPollToExtension, sendUnpairToExtension } from "../../extensionPair";
import "../../creator.scss";
import "./index.scss";

type Binding = { id?: string; provider: string; external_release_id?: string };
type Payout = { id: string; channel: string; account_name?: string; account_no?: string; account_no_masked?: string; is_default?: boolean };
type Aggregator = { code: string; name: string; region?: string; configured?: boolean };

export default function AccountsPage() {
  const { copy, locale } = useLocale();
  const c = copy.creatorUi;
  const router = useRouter();
  const [provider, setProvider] = useState("distrokid");
  const [token, setToken] = useState("");
  const [releaseId, setReleaseId] = useState("");
  const [artistId, setArtistId] = useState("");
  const [accountNo, setAccountNo] = useState("");
  const [accountName, setAccountName] = useState("");
  const [payoutChannel, setPayoutChannel] = useState(locale === "en" ? "paypal" : "alipay");
  const [busy, setBusy] = useState(false);
  const [mintMeta, setMintMeta] = useState<{ role?: string; expires_at?: string } | null>(null);
  const [showAllStores, setShowAllStores] = useState(false);
  const [extensionOn, setExtensionOn] = useState(false);
  const [extensionMeta, setExtensionMeta] = useState<{ version?: string; period?: string } | null>(null);

  const { data, loading, error, reload } = useAsyncQuery<{
    bindings: Binding[];
    accounts: Payout[];
    aggregators: Aggregator[];
    connector_online?: boolean;
    connector?: {
      online?: boolean;
      version?: string;
      period_key?: string;
      last_harvest?: { channel?: string; count?: number; matched?: number; unclaimed?: number } | null;
      last_delivery?: { channel_code?: string; event?: string; message?: string } | null;
      queue_count?: number;
    };
    session_wait_count?: number;
    seats: SeatLamp[];
    playbooks: Array<{ code: string; name?: string }>;
    connections?: ConnectionCard[];
  } | null>(async () => {
    if (!requireAuth(creatorPage("accounts"))) return null;
    const [bindings, payouts, catalog, hub, seats] = await Promise.all([
      vibeApi.listDistributorBindings().catch(() => ({ bindings: [] })),
      vibeApi.listPayoutAccounts().catch(() => ({ accounts: [] })),
      vibeApi.listReleaseChannels().catch(() => ({ aggregators: [] })),
      vibeApi.getCreatorHub().catch(() => ({})),
      vibeApi.listSeats().catch(() => ({ seats: [], playbooks: [] })),
    ]);
    return {
      bindings: (bindings.bindings || []) as Binding[],
      accounts: (payouts.accounts || []) as Payout[],
      aggregators: (catalog.aggregators || []) as Aggregator[],
      connector_online: Boolean((hub as { connector_online?: boolean }).connector_online),
      connector: (hub as { connector?: {
        online?: boolean;
        version?: string;
        period_key?: string;
        last_harvest?: { channel?: string; count?: number; matched?: number; unclaimed?: number } | null;
        last_delivery?: { channel_code?: string; event?: string; message?: string } | null;
        queue_count?: number;
      } }).connector,
      session_wait_count: Number((hub as { session_wait_count?: number }).session_wait_count || 0),
      seats: (seats.seats || []) as SeatLamp[],
      playbooks: seats.playbooks || [],
      connections: ((hub as { connections?: ConnectionCard[] }).connections || []) as ConnectionCard[],
    };
  }, []);

  useDidShow(() => {
    if (process.env.TARO_ENV === "h5") void sendPollToExtension();
    void reload().then((hub) => {
      if (hasHandedVolumeStore(hub?.connections) && process.env.TARO_ENV !== "weapp") {
        void resumePendingQuickRelease(
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
      }
    });
    if (process.env.TARO_ENV === "h5") {
      void probeExtensionStatus().then((status) => {
        setExtensionOn(status.installed);
        setExtensionMeta(status.installed ? { version: status.version, period: status.period } : null);
      });
    }
    if (router.params.youtube === "connected") {
      Taro.showToast({ title: c.youtubeConnected, icon: "success" });
    }
  });
  useEffect(() => {
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      void reload(true);
      if (process.env.TARO_ENV === "h5") {
        void probeExtensionStatus().then((status) => {
          setExtensionOn(status.installed);
          setExtensionMeta(status.installed ? { version: status.version, period: status.period } : null);
        });
      }
    };
    const id = setInterval(tick, 20000);
    const onVis = () => {
      if (typeof document === "undefined" || document.hidden) return;
      tick();
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVis);
    const stop = listenExtensionEvents((event) => {
      if (event.type === "BITTUNE_UNPAIRED") {
        setExtensionOn(false);
        setExtensionMeta(null);
      }
      void reload(true);
    });
    return () => {
      stop();
      clearInterval(id);
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVis);
    };
  }, [reload]);
  usePullDownRefresh(async () => {
    await reload();
    Taro.stopPullDownRefresh();
  });

  async function bind() {
    if (busy) return;
    if (process.env.TARO_ENV === "weapp") {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.accounts);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    const ok = await confirmCreatorAction({
      title: c.bindDistributor,
      content: c.bindDistributorHint,
      confirmText: c.confirmGo,
      cancelText: c.back,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await vibeApi.bindDistributor(provider, token || undefined, releaseId || undefined);
      Taro.showToast({ title: c.bindDistributor, icon: "success" });
      setToken("");
      void reload();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  async function unbind(provider: string) {
    if (busy) return;
    if (process.env.TARO_ENV === "weapp") {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.accounts);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      await vibeApi.unbindDistributor(provider);
      Taro.showToast({ title: c.unbindOk, icon: "success" });
      void reload();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  async function removePayout(accountId: string) {
    if (busy) return;
    if (process.env.TARO_ENV === "weapp") {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.accounts);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      await vibeApi.deletePayoutAccount(accountId);
      Taro.showToast({ title: c.deletePayoutOk, icon: "success" });
      void reload();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  async function addPayout() {
    if (busy) return;
    if (process.env.TARO_ENV === "weapp") {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.accounts);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    if (!accountNo.trim()) {
      Taro.showToast({ title: c.payoutAccount, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      await vibeApi.addPayoutAccount({
        channel: payoutChannel,
        account_name: accountName,
        account_no: accountNo,
        is_default: true,
      });
      Taro.showToast({ title: c.addPayout, icon: "success" });
      setAccountNo("");
      void reload();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  const waiting = Number(data?.session_wait_count || 0);
  const online = Boolean(data?.connector_online);
  const weapp = process.env.TARO_ENV === "weapp";
  if (!weapp) markBittunePage();
  const waitCta = waiting > 0 ? sessionWaitCta(c, { weapp, connectorOnline: online, waiting }) : null;
  const firstUserSeat = (data?.seats || []).find((seat) => seat.ownership === "user" && seat.id);

  function goWaitCta() {
    if (!waitCta) return;
    if (waitCta.to === "remote" || weapp) {
      if (firstUserSeat?.id) {
        Taro.navigateTo({ url: creatorPage("remoteLogin", { seatId: String(firstUserSeat.id) }) });
        return;
      }
      Taro.showToast({ title: c.connectMyAccount, icon: "none" });
      return;
    }
    if (waitCta.to === "portal") {
      Taro.navigateTo({ url: creatorPage("deliveries") });
      return;
    }
    if (!online) {
      void sendToExtension();
      return;
    }
    const next = pickNextAuthStore(data?.connections);
    if (next?.seat_id) {
      Taro.navigateTo({ url: creatorPage("remoteLogin", { seatId: String(next.seat_id) }) });
      return;
    }
    setShowAllStores(true);
  }

  async function unpairExtension() {
    if (busy) return;
    const ok = await confirmCreatorAction({
      title: c.unpairExtension,
      content: c.unpairConfirmHint,
      confirmText: c.confirmGo,
      cancelText: c.back,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await vibeApi.revokeConnectorToken();
      await sendUnpairToExtension();
      setExtensionOn(false);
      setExtensionMeta(null);
      Taro.showToast({ title: c.unpairExtensionOk, icon: "success" });
      void reload();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  async function mintToken() {
    if (busy) return;
    if (weapp) {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.accounts);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    const ok = await confirmCreatorAction({
      title: c.mintConnectorToken,
      content: c.mintTokenHint,
      confirmText: c.confirmGo,
      cancelText: c.back,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const minted = await vibeApi.mintConnectorToken();
      setMintMeta({ role: minted.role, expires_at: minted.expires_at || undefined });
      await Taro.setClipboardData({ data: minted.pair_text || minted.token });
      Taro.showToast({ title: c.tokenCopied, icon: "success" });
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  async function sendToExtension() {
    if (busy) return;
    if (weapp) {
      Taro.showToast({ title: c.connectorBrowserOnly, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      const minted = await vibeApi.mintConnectorToken();
      setMintMeta({ role: minted.role, expires_at: minted.expires_at || undefined });
      const pair = pairFromMinted(minted);
      const sent = await sendPairToExtension(pair);
      if (sent) {
        setExtensionOn(true);
        Taro.showToast({ title: c.sentToExtension, icon: "success" });
        void reload();
        return;
      }
      await Taro.setClipboardData({ data: minted.pair_text || minted.token });
      Taro.showToast({ title: c.extensionNotInstalled, icon: "none" });
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell title={c.goAccounts} subtitle={c.storeLaneHint} ambient>
      <View className="creator">
        <WeappH5Bridge path={CREATOR_PAGE_ROUTES.accounts} />
        {weapp ? <StatusLine tone="info" density="quiet">{c.weappDeskHint}</StatusLine> : null}
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void reload()}
        >
          <View className="creator-hero">
            <Text className="creator-hero__kicker">{c.storeLaneTitle}</Text>
            <Text className="creator-hero__title">{waiting ? c.needLoginStores.replace("{n}", String(waiting)) : online ? c.connectorOnline : c.seatConnectMine}</Text>
            <Text className="creator-hero__sub">{c.storeLaneHint}</Text>
            {waitCta ? (
              <NextActionCard
                kicker={c.waitingNow}
                title={waitCta.title}
                hint={waitCta.hint}
                go={waitCta.go}
                urgent
                onClick={goWaitCta}
              />
            ) : (
              <NextActionCard
                kicker={c.nextAction}
                title={c.seatConnectMine}
                hint={c.feeSelfLine}
                go={c.nextGo}
                onClick={() => setShowAllStores(true)}
              />
            )}
          </View>
          <View className="creator-card">
            <Text className="creator-mode__title">{c.seatConnectMine}</Text>
            <ConnectionsRow
              connections={data?.connections}
              copy={c}
              weapp={weapp}
              extensionOn={extensionOn}
              compact={false}
              expandAll={showAllStores}
              onChanged={() => void reload(true)}
            />
          </View>
          <View className="creator-card">
            <Text className="creator-mode__title">{c.seatPlatformPack}</Text>
            <SeatLamps seats={data?.seats} copy={c} ownership="platform" />
          </View>

          <Collapsible
            label={c.addPayout}
            storageKey="accounts-payout"
            defaultOpen={(data?.accounts || []).length === 0}
          >
            {weapp ? <StatusLine tone="info">{c.weappDeskHint}</StatusLine> : null}
            {weapp ? (
              (data?.accounts || []).length === 0 ? (
                <Text className="typo-meta">{c.payoutsEmpty}</Text>
              ) : (
                (data?.accounts || []).map((a) => (
                  <ListRow
                    key={a.id}
                    icon="profile"
                    label={a.account_name || payoutChannelLabel(a.channel, c)}
                    hint={`${payoutChannelLabel(a.channel, c)} · ${a.account_no_masked || a.account_no || ""}`}
                  />
                ))
              )
            ) : (data?.accounts || []).length === 0 ? (
              <>
                <ChipGroup
                  options={
                    locale === "en"
                      ? [
                          { value: "paypal", label: c.channelPaypal },
                          { value: "bank", label: c.channelBank },
                        ]
                      : [
                          { value: "alipay", label: c.channelAlipay },
                          { value: "wechat", label: c.channelWechat },
                          { value: "paypal", label: c.channelPaypal },
                          { value: "bank", label: c.channelBank },
                        ]
                  }
                  value={payoutChannel}
                  onChange={setPayoutChannel}
                />
                <Input label={c.payoutName} value={accountName} onInput={(e) => setAccountName(e.detail.value)} />
                <Input label={c.payoutAccount} value={accountNo} onInput={(e) => setAccountNo(e.detail.value)} />
                <Button variant="primary" block loading={busy} onClick={() => void addPayout()}>
                  {c.addPayout}
                </Button>
                <Text className="typo-meta">{c.payoutsEmpty}</Text>
              </>
            ) : (
              (data?.accounts || []).map((a) => (
                <ListRow
                  key={a.id}
                  icon="profile"
                  label={a.account_name || payoutChannelLabel(a.channel, c)}
                  hint={`${payoutChannelLabel(a.channel, c)} · ${a.account_no_masked || a.account_no || ""}`}
                  value={c.deletePayout}
                  onClick={() => {
                    void confirmCreatorAction({
                      title: c.deletePayout,
                      content: `${c.deletePayoutHint}\n${a.account_name || payoutChannelLabel(a.channel, c)}`,
                      confirmText: c.confirmGo,
                      cancelText: c.back,
                    }).then((ok) => {
                      if (ok) void removePayout(a.id);
                    });
                  }}
                />
              ))
            )}
            <Button variant="ghost" block onClick={() => Taro.navigateTo({ url: creatorPage("wallet") })}>
              {c.goWallet}
            </Button>
          </Collapsible>

          <Collapsible label={c.connectorTitle} storageKey="accounts-connector" defaultOpen>
            <Text className="typo-meta">{c.connectorHint}</Text>
            <StatusLine tone="info" density="quiet">
              {weapp ? c.connectorBrowserOnly : c.connectorBrowserOnlyH5}
            </StatusLine>
            <View className="creator-guide">
              <View className="creator-guide__row">
                <Text className="creator-guide__n">1</Text>
                <Text className="creator-guide__t">{c.connectorStep1}</Text>
              </View>
              <View className="creator-guide__row">
                <Text className="creator-guide__n">2</Text>
                <Text className="creator-guide__t">{c.connectorStep2}</Text>
              </View>
              <View className="creator-guide__row">
                <Text className="creator-guide__n">3</Text>
                <Text className="creator-guide__t">{c.connectorStep3}</Text>
              </View>
            </View>
            {mintMeta && (
              <Text className="typo-meta">
                {c.connectorRole.replace("{role}", mintMeta.role || "user").replace("{exp}", (mintMeta.expires_at || "").slice(0, 10))}
              </Text>
            )}
            {!weapp && extensionOn ? (
              <StatusLine tone="success" density="quiet">
                {extensionMeta?.period
                  ? c.extensionInSync.replace("{period}", extensionMeta.period)
                  : c.extensionDetected}
              </StatusLine>
            ) : null}
            {connectorLiveLine(c, data?.connector) ? (
              <StatusLine tone={(data?.connector?.queue_count || 0) > 0 ? "info" : "success"} density="quiet">
                {connectorLiveLine(c, data?.connector)}
              </StatusLine>
            ) : null}
            {data?.connector?.last_harvest ? (
              <StatusLine tone={(data.connector.last_harvest.unclaimed || 0) > 0 ? "error" : "info"} density="quiet">
                {`${c.connectorLastHarvest
                  .replace("{name}", channelName(String(data.connector.last_harvest.channel || ""), c.channels))
                  .replace("{n}", String(data.connector.last_harvest.count || 0))
                  .replace("{m}", String(data.connector.last_harvest.matched ?? 0))}${
                  (data.connector.last_harvest.unclaimed || 0) > 0
                    ? c.connectorHarvestUnclaimed.replace("{u}", String(data.connector.last_harvest.unclaimed))
                    : ""
                }`}
              </StatusLine>
            ) : null}
            {(data?.connector?.last_harvest?.unclaimed || 0) > 0 ? (
              <Button variant="secondary" block onClick={() => Taro.navigateTo({ url: creatorPage("dataImport") })}>
                {c.nextImport}
              </Button>
            ) : null}
            {!weapp ? (
              <Button variant="primary" block loading={busy} onClick={() => void sendToExtension()}>
                {c.sendToExtension}
              </Button>
            ) : null}
            {!weapp ? (
              <Button variant="ghost" block loading={busy} onClick={() => void mintToken()}>
                {c.mintConnectorToken}
              </Button>
            ) : null}
            {!weapp && (data?.connector_online || extensionOn) ? (
              <Button variant="ghost" block loading={busy} onClick={() => void unpairExtension()}>
                {c.unpairExtension}
              </Button>
            ) : null}
            <Text className="typo-meta">{c.connectorLoadHint}</Text>
            {waiting > 0 && (
              <Button variant="secondary" block onClick={() => Taro.navigateTo({ url: creatorPage("deliveries") })}>
                {c.goSeeDeliveries}
              </Button>
            )}
          </Collapsible>

          <Collapsible label={c.opsSidePath} storageKey="accounts-ops" defaultOpen={false}>
            {weapp ? <StatusLine tone="info">{c.weappDeskHint}</StatusLine> : null}
            <StatusLine tone="info">{c.importNotMainPath}</StatusLine>
            {!weapp ? <StatusLine tone="info">{c.tokenHint}</StatusLine> : null}
            {!weapp ? (
              <>
                <ChipGroup
                  options={[
                    { value: "distrokid", label: "DistroKid" },
                    { value: "tunecore", label: "TuneCore" },
                    { value: "routenote", label: "RouteNote" },
                  ]}
                  value={provider}
                  onChange={setProvider}
                />
                <Input label={c.officialToken} password value={token} onInput={(e) => setToken(e.detail.value)} />
                <Input label={c.releaseIdLabel} value={releaseId} onInput={(e) => setReleaseId(e.detail.value)} />
                <Button
                  variant="ghost"
                  block
                  onClick={() => {
                    void (async () => {
                      try {
                        const res = await vibeApi.youtubeOauthUrl();
                        if (!res.configured || !res.url) {
                          Taro.showToast({ title: c.youtubeNeedConfig, icon: "none" });
                          return;
                        }
                        if (process.env.TARO_ENV === "h5" && typeof window !== "undefined") {
                          window.location.href = res.url;
                          return;
                        }
                        await Taro.setClipboardData({ data: res.url });
                        Taro.showToast({ title: c.youtubeCopied, icon: "success" });
                      } catch {
                        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                      }
                    })();
                  }}
                >
                  {c.youtubeConnect}
                </Button>
                <Input label={c.chartmetricArtist} value={artistId} onInput={(e) => setArtistId(e.detail.value)} />
                <Button
                  variant="ghost"
                  block
                  loading={busy}
                  onClick={() => {
                    void (async () => {
                      if (busy || !artistId.trim()) return;
                      setBusy(true);
                      try {
                        await vibeApi.bindDistributor("chartmetric", undefined, artistId.trim());
                        Taro.showToast({ title: c.bindChartmetric, icon: "success" });
                        setArtistId("");
                        void reload();
                      } catch {
                        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                      } finally {
                        setBusy(false);
                      }
                    })();
                  }}
                >
                  {c.bindChartmetric}
                </Button>
                <Button variant="secondary" block loading={busy} onClick={() => void bind()}>
                  {c.bindDistributor}
                </Button>
              </>
            ) : null}
            <SectionLabel>{c.providerLabel}</SectionLabel>
            {(data?.bindings || []).length === 0 && <Text className="typo-meta">{c.bindingsEmpty}</Text>}
            {(data?.bindings || []).map((b, i) => (
              <ListRow
                key={b.id || `${b.provider}-${i}`}
                icon="grimoire"
                label={b.provider}
                hint={b.external_release_id}
                value={weapp ? undefined : c.unbindAccount}
                onClick={
                  weapp
                    ? undefined
                    : () => {
                        void confirmCreatorAction({
                          title: c.unbindAccount,
                          content: `${c.unbindHint}\n${b.provider}`,
                          confirmText: c.confirmGo,
                          cancelText: c.back,
                        }).then((ok) => {
                          if (ok) void unbind(b.provider);
                        });
                      }
                }
              />
            ))}
            {(data?.bindings || []).some((b) => b.provider === "youtube") && (
              <>
                <StatusLine tone="success">{c.youtubeConnected}</StatusLine>
                {!weapp ? (
                  <Button
                    variant="ghost"
                    block
                    loading={busy}
                    onClick={() => {
                      void confirmCreatorAction({
                        title: c.youtubeDisconnect,
                        content: c.youtubeDisconnectHint,
                        confirmText: c.confirmGo,
                        cancelText: c.back,
                      }).then((ok) => {
                        if (ok) void unbind("youtube");
                      });
                    }}
                  >
                    {c.youtubeDisconnect}
                  </Button>
                ) : null}
              </>
            )}

            {(data?.aggregators || []).length > 0 && (
              <>
                <Text className="creator-mode__title">{c.partnerLayerTitle}</Text>
                {(data?.aggregators || []).map((row) => (
                  <ListRow
                    key={row.code}
                    icon="sigil"
                    label={row.name}
                    hint={row.configured ? c.partnerReady : c.partnerWaiting}
                  />
                ))}
              </>
            )}
          </Collapsible>
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
