import { useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro, { useDidShow, useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { PageShell } from "../../../components/PageShell";
import { Badge, Button, EmptyState, LoadingSkeleton, StatusLine } from "../../../components/ui";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../../utils/auth";
import { useCreditsOptional } from "../../../contexts/CreditsProvider";
import { usePlayerTransport } from "../../../contexts/PlayerProvider";
import { commercePage, creatorPage, openCreatorDesk, socialPage } from "../../../constants/routes";
import { formatFen, statusLabel, statusTone } from "../../../packageCreator/lib";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../../packageCreator/WeappH5Bridge";
import "./index.scss";

type Listing = {
  work_id: string;
  title?: string;
  enabled?: boolean;
  commercial?: boolean;
  owner_id?: string;
  audio_url?: string;
  cover_url?: string;
  from_workbench?: boolean;
  redirected_from_work_id?: string;
  tier_cards?: Array<{ id: string; credits: number; fiat_minor: number; label: string }>;
  rights_certificate?: {
    exclusive?: boolean;
    non_exclusive?: boolean;
    ai_disclosed?: boolean;
    c2pa_verified?: boolean;
    human_edits?: number;
  };
};

type Order = { id: string; tier?: string; status?: string; license_id?: string; pay_method?: string };

export default function SyncDeskPage() {
  const { copy } = useLocale();
  const s = copy.syncDeskUi;
  const router = useRouter();
  const focusWorkId = String(router.params.workId || "");
  const creditsCtx = useCreditsOptional();
  const { playTrack } = usePlayerTransport();
  const [listings, setListings] = useState<Listing[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [meId, setMeId] = useState("");
  const [focusMine, setFocusMine] = useState<Listing | null>(null);
  const syncNext = commercePage("syncDesk", focusWorkId ? { workId: focusWorkId } : undefined);

  function load() {
    bootstrapAuth();
    setLoading(true);
    Promise.all([
      vibeApi.listSyncCatalog().catch(() => ({ listings: [] })),
      isLoggedIn() ? vibeApi.listSyncOrders().catch(() => ({ orders: [] })) : Promise.resolve({ orders: [] }),
      isLoggedIn() ? vibeApi.me().catch(() => null) : Promise.resolve(null),
      focusWorkId ? vibeApi.getSyncListing(focusWorkId).catch(() => null) : Promise.resolve(null),
    ])
      .then(([cat, mine, me, focus]) => {
        setListings((cat.listings || []) as Listing[]);
        setOrders((mine.orders || []) as Order[]);
        if (me?.id) setMeId(String(me.id));
        setFocusMine(focus && me?.id && String((focus as Listing).owner_id || "") === String(me.id) ? (focus as Listing) : null);
      })
      .finally(() => setLoading(false));
  }

  useDidShow(() => {
    load();
  });

  async function buy(workId: string, tier: string, pay: "credits" | "invoice") {
    if (process.env.TARO_ENV === "weapp") {
      await copyWeappCreatorLink(commercePage("syncDesk", { workId }));
      return;
    }
    if (!requireAuth(syncNext)) return;
    const confirm = await Taro.showModal({
      title: s.title,
      content: s.consent,
      confirmText: pay === "credits" ? s.buyCredits : s.buyInvoice,
      cancelText: copy.creatorUi.back,
    });
    if (!confirm.confirm) return;
    setBusy(`${workId}-${tier}-${pay}`);
    try {
      await vibeApi.placeSyncOrder({ work_id: workId, tier, pay_method: pay, consent: true });
      await creditsCtx?.refresh();
      Taro.showToast({ title: s.ordered, icon: "success" });
      load();
    } catch {
      Taro.showToast({ title: copy.marketplaceUi.purchaseFail, icon: "none" });
    } finally {
      setBusy("");
    }
  }

  async function copyPro() {
    if (!requireAuth(syncNext)) return;
    try {
      const res = await vibeApi.getProExport();
      await Taro.setClipboardData({ data: res.csv || "" });
      Taro.showToast({ title: s.proCopied, icon: "success" });
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    }
  }

  async function listFocus() {
    if (process.env.TARO_ENV === "weapp") {
      await copyWeappCreatorLink(commercePage("syncDesk", { workId: focusWorkId }));
      return;
    }
    if (!focusWorkId || !requireAuth(syncNext)) return;
    setBusy("list-focus");
    try {
      await vibeApi.saveSyncListing(focusWorkId, true);
      Taro.showToast({ title: s.listed, icon: "success" });
      load();
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy("");
    }
  }

  function playListing(row: Listing) {
    if (!row.audio_url) return;
    playTrack(
      workToPlayerTrack({ id: row.work_id, title: row.title || row.work_id, audio_url: row.audio_url, cover_url: row.cover_url }, { source: "feed" }),
      { navigate: false },
    );
  }

  const hopFocusId = String(focusMine?.work_id || focusWorkId);
  const focusListed = listings.some((row) => row.work_id === hopFocusId || row.work_id === focusWorkId);
  const showFocusUnlisted = Boolean(focusWorkId && focusMine && !focusMine.enabled && !focusListed);

  return (
    <PageShell title={s.title} subtitle={s.subtitle} ambient>
      <View className="sync-desk">
        <WeappH5Bridge path={commercePage("syncDesk", focusWorkId ? { workId: focusWorkId } : undefined)} />
        <StatusLine tone="info" density="quiet">{s.notDsp}</StatusLine>
        <Button variant="secondary" block onClick={() => void copyPro()}>
          {s.proExport}
        </Button>
        <Button variant="ghost" block onClick={() => openCreatorDesk()}>
          {s.listMine}
        </Button>
        {loading && <LoadingSkeleton count={3} />}
        {!loading && listings.length === 0 && !showFocusUnlisted && (
          <EmptyState
            iconName="music"
            title={s.empty}
            description={s.emptyDesc}
            actionLabel={s.listMine}
            onAction={() => openCreatorDesk()}
          />
        )}
        {showFocusUnlisted ? (
          <View className="sync-desk__card sync-desk__card--focus">
            {focusMine?.cover_url ? <Image className="sync-desk__cover" src={focusMine.cover_url} mode="aspectFill" /> : <View className="sync-desk__cover" />}
            <Badge tone="warning">{s.focused}</Badge>
            {focusMine?.from_workbench ? <Badge>{copy.worksUi.beautifyMaster}</Badge> : null}
            <Text className="sync-desk__title">{focusMine?.title || focusWorkId}</Text>
            {focusMine?.redirected_from_work_id ? (
              <StatusLine tone="info">{copy.creatorUi.releasePreferMaster}</StatusLine>
            ) : null}
            <StatusLine tone="info">{s.focusUnlisted}</StatusLine>
            <Button size="sm" variant="primary" loading={busy === "list-focus"} onClick={() => void listFocus()}>
              {s.focusUnlistedGo}
            </Button>
          </View>
        ) : null}
        {[...listings]
          .sort((a, b) => Number(b.work_id === hopFocusId || b.work_id === focusWorkId) - Number(a.work_id === hopFocusId || a.work_id === focusWorkId))
          .map((row) => {
            const mine = Boolean(meId && row.owner_id && row.owner_id === meId);
            const focused = row.work_id === hopFocusId || row.work_id === focusWorkId;
            return (
              <View key={row.work_id} className={focused ? "sync-desk__card sync-desk__card--focus" : "sync-desk__card"}>
                {row.cover_url ? <Image className="sync-desk__cover" src={row.cover_url} mode="aspectFill" /> : <View className="sync-desk__cover" />}
                {focused ? <Badge tone="accent">{s.focused}</Badge> : null}
                {row.from_workbench ? <Badge>{copy.worksUi.beautifyMaster}</Badge> : null}
                <Text className="sync-desk__title">{row.title || row.work_id}</Text>
                <Badge tone={row.commercial ? "success" : "info"}>
                  {row.commercial ? copy.creatorUi.syncListingOn : copy.creatorUi.syncListingOff}
                </Badge>
                {row.rights_certificate ? (
                  <Text className="typo-meta">
                    {[
                      s.rightsTrust.replace(
                        "{ai}",
                        row.rights_certificate.ai_disclosed ? s.rightsAiDisclosed : s.rightsAiHuman,
                      ),
                      row.rights_certificate.c2pa_verified ? s.rightsC2pa : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </Text>
                ) : null}
                {!mine && row.audio_url ? <Text className="typo-meta">{s.hearFirst}</Text> : null}
                {row.audio_url ? (
                  <Button size="sm" variant="ghost" onClick={() => playListing(row)}>
                    {s.listenPreview}
                  </Button>
                ) : null}
                {mine ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId: row.work_id }) })}
                  >
                    {s.manageMine}
                  </Button>
                ) : (
                  (row.tier_cards || []).map((tier) => (
                    <View key={tier.id} className="sync-desk__row">
                      <View>
                        <Text>{tier.label}</Text>
                        <Text className="sync-desk__price">{`${tier.credits} · ${formatFen(tier.fiat_minor)}`}</Text>
                      </View>
                      <View>
                        <Button
                          size="sm"
                          loading={busy === `${row.work_id}-${tier.id}-credits`}
                          onClick={() => void buy(row.work_id, tier.id, "credits")}
                        >
                          {s.buyCredits}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={busy === `${row.work_id}-${tier.id}-invoice`}
                          onClick={() => void buy(row.work_id, tier.id, "invoice")}
                        >
                          {s.buyInvoice}
                        </Button>
                      </View>
                    </View>
                  ))
                )}
              </View>
            );
          })}
        {orders.length > 0 && (
          <>
            <Text className="sync-desk__title">{s.myOrders}</Text>
            {orders.map((order) => (
              <View key={order.id} className="sync-desk__card">
                <Text>{order.tier || order.license_id || order.id}</Text>
                <Badge tone={statusTone(order.status)}>{statusLabel(order.status || "", copy.creatorUi.status)}</Badge>
                <Text className="typo-meta">{order.license_id || order.pay_method}</Text>
                {order.status === "pending_invoice" ? (
                  <StatusLine tone="info" density="quiet">{s.invoiceWaitOps}</StatusLine>
                ) : null}
              </View>
            ))}
          </>
        )}
      </View>
    </PageShell>
  );
}
