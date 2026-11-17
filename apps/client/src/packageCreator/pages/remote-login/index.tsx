import { useEffect, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh, useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { AsyncPanel, Button, StatusLine } from "../../../components/ui";
import { vibeApi } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { CREATOR_PAGE_ROUTES, creatorPage } from "../../../constants/routes";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import "../../creator.scss";
import "./index.scss";

type RemoteState = {
  status?: string;
  login_url?: string;
  screenshot?: string;
  has_session?: boolean;
  note?: string;
  seat?: { id?: string; channel_code?: string; status?: string; playbook?: { name?: string } };
};

export default function RemoteLoginPage() {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const router = useRouter();
  const seatId = String(router.params.seatId || router.params.seat_id || "");
  const [data, setData] = useState<RemoteState | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [openedPortal, setOpenedPortal] = useState(false);
  const weapp = process.env.TARO_ENV === "weapp";

  async function load(start = false) {
    if (!requireAuth(creatorPage("remoteLogin", { seatId }))) return;
    if (!seatId) {
      setError(new Error("missing seat"));
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const row = start && !weapp ? await vibeApi.startSeatRemoteLogin(seatId) : await vibeApi.seatRemoteStatus(seatId);
      setData(row as RemoteState);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error("remote failed"));
    } finally {
      setLoading(false);
    }
  }

  useDidShow(() => {
    void (async () => {
      if (!seatId || !requireAuth(creatorPage("remoteLogin", { seatId }))) return;
      try {
        const row = (await vibeApi.seatRemoteStatus(seatId)) as RemoteState;
        if (!weapp && (!row?.status || row.status === "idle")) {
          await load(true);
          return;
        }
        setData(row);
        setError(null);
        setLoading(false);
      } catch {
        void load(!weapp);
      }
    })();
  });
  usePullDownRefresh(async () => {
    await load(false);
    Taro.stopPullDownRefresh();
  });
  useEffect(() => {
    const timer = setInterval(() => {
      if (!seatId) return;
      void vibeApi.seatRemoteStatus(seatId).then((row) => setData(row as RemoteState)).catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [seatId]);

  const ready = Boolean(data?.has_session);
  const name = data?.seat?.playbook?.name || data?.seat?.channel_code || "";
  const seatFail = data?.seat?.status === "needs_challenge" || data?.seat?.status === "expired";
  const h5 = process.env.TARO_ENV === "h5";
  const canOpenPortal = Boolean(data?.login_url) && h5;
  const primary: "open" | "ack" | "deliveries" = ready
    ? "deliveries"
    : canOpenPortal && !openedPortal
      ? "open"
      : "ack";

  async function ackLoggedIn() {
    if (busy) return;
    if (weapp) {
      await copyWeappCreatorLink(creatorPage("remoteLogin", { seatId }));
      Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      const row = (await vibeApi.ackSeatRemoteLogin(seatId)) as RemoteState;
      setData(row);
      Taro.showToast({ title: c.remoteLoggedIn, icon: "success" });
      if (row.has_session) {
        try {
          await vibeApi.kickSeatRuntime(seatId);
        } catch {
          Taro.showToast({ title: c.harvestFailHint || copy.adminUi.actionFail, icon: "none" });
        }
        Taro.navigateTo({ url: creatorPage("deliveries") });
      }
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell title={c.remoteLoginTitle} subtitle={c.remoteLoginHint} ambient>
      <View className="creator">
        <WeappH5Bridge path={creatorPage("remoteLogin", { seatId })} />
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void load(true)}
        >
          <View className="creator-hero">
            <Text className="creator-hero__kicker">{name}</Text>
            <Text className="creator-hero__title">{ready ? c.remoteReady : c.remoteLoginTitle}</Text>
            <StatusLine tone={ready ? "success" : seatFail ? "error" : "loading"}>
              {ready
                ? c.remoteReady
                : data?.seat?.status === "needs_challenge"
                  ? c.seatChallengeHint
                  : data?.seat?.status === "expired"
                    ? c.seatExpiredHint
                    : data?.status === "user_finished"
                      ? (process.env.TARO_ENV === "weapp" ? c.seatWeappHint : c.remoteNeedConnector)
                      : c.remoteWaiting}
            </StatusLine>
          </View>
          <View className="creator-card">
            <View className="creator-guide">
              <View className="creator-guide__row">
                <Text className="creator-guide__n">1</Text>
                <Text className="creator-guide__t">{c.remoteStep1}</Text>
              </View>
              <View className="creator-guide__row">
                <Text className="creator-guide__n">2</Text>
                <Text className="creator-guide__t">{c.remoteStep2}</Text>
              </View>
              <View className="creator-guide__row">
                <Text className="creator-guide__n">3</Text>
                <Text className="creator-guide__t">{c.remoteStep3}</Text>
              </View>
            </View>
          </View>
          {data?.screenshot ? <Image className="remote-shot" src={data.screenshot} mode="widthFix" /> : null}
          <View className="creator-card">
            <StatusLine tone="info">{process.env.TARO_ENV === "weapp" ? c.seatWeappHint : c.remoteLoginHint}</StatusLine>
            {primary === "open" && data?.login_url ? (
              <Button
                variant="primary"
                block
                onClick={() => {
                  setOpenedPortal(true);
                  if (typeof window !== "undefined") window.open(data.login_url, "_blank");
                }}
              >
                {c.openThisPortal}
              </Button>
            ) : null}
            {primary === "ack" && !weapp ? (
              <Button variant="primary" block loading={busy} onClick={() => void ackLoggedIn()}>
                {c.remoteLoggedIn}
              </Button>
            ) : null}
            {primary === "deliveries" ? (
              <Button variant="primary" block onClick={() => Taro.navigateTo({ url: creatorPage("deliveries") })}>
                {c.goDeliveriesAfterRemote}
              </Button>
            ) : null}
            {data?.login_url ? (
              <Button
                variant="secondary"
                block
                onClick={() => {
                  void Taro.setClipboardData({ data: String(data.login_url) }).then(() => {
                    Taro.showToast({ title: c.loginUrlCopied, icon: "success" });
                  });
                }}
              >
                {c.copyLoginUrl}
              </Button>
            ) : null}
            {(ready || seatFail || error) && (
              <Button variant="ghost" block onClick={() => Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.accounts })}>
                {c.goAccounts}
              </Button>
            )}
          </View>
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
