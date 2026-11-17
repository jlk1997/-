import { useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh, useRouter, useShareAppMessage } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { AsyncPanel, Badge, Button, Collapsible, SectionLabel, ShareButton, StatusLine } from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { commercePage, creatorPage, socialPage, studioPage } from "../../../constants/routes";
import { workSharePayload, shareWork } from "../../../platform/share";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import { channelName, isLiveDelivery, isStoreAssist, isUploadWait, openExternal, sessionWaitCta, statusLabel, statusTone, storeRowMeta } from "../../lib";
import { saveClipPack, saveOriginalityPack } from "../../kitAction";
import { NextActionCard } from "../../NextActionCard";
import { AssetLanes } from "../../../components/studio/AssetLanes";
import "../../creator.scss";

type Store = {
  channel_code: string;
  name?: string;
  status?: string;
  user_status?: string;
  store_url?: string;
  external_id?: string;
  has_receipt?: boolean;
  upload_url?: string;
  sop?: string;
};

type Passport = {
  work_id?: string;
  release_id?: string;
  title?: string;
  artist_name?: string;
  isrc?: string;
  upc?: string;
  cover_url?: string;
  ai_disclosed?: boolean;
  c2pa_verified?: boolean;
  c2pa_state?: string;
  commission_rate?: number | null;
  live_stores?: number;
  store_count?: number;
  stores?: Store[];
  next_store_action?: { code?: string; next?: string | null };
  share_line?: string;
  mode?: string;
  clip_windows?: Array<{ length?: number; start?: number; end?: number }>;
  human_edits?: Array<{ kind?: string; section?: string; note?: string; at?: string }>;
  portal_channels?: Array<{ code: string; name?: string; upload_url?: string; sop?: string }>;
  commercial?: boolean;
  radio_trial?: { live?: boolean; station?: string; listen_completes?: number };
  needs_ai_musician?: boolean;
  asset_status?: {
    listing?: { ready?: boolean; label?: string; wav?: boolean };
    evidence?: { needed?: boolean; ready?: boolean; label?: string; quality?: string };
    clips?: { needed?: boolean; ready?: boolean };
  };
  rights_certificate?: {
    exclusive?: boolean;
    non_exclusive?: boolean;
    ai_disclosed?: boolean;
    human_edits?: number;
    commission_rate?: number | null;
    sync_tiers?: string[];
    c2pa_verified?: boolean;
  };
};

export default function PassportPage() {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const router = useRouter();
  const workId = String(router.params.workId || router.params.work_id || "");
  const releaseId = String(router.params.releaseId || router.params.release_id || "");
  const [sharing, setSharing] = useState(false);
  const [clipBusy, setClipBusy] = useState(false);
  const { data, loading, error, reload } = useAsyncQuery<Passport | null>(async () => {
    const passport = releaseId
      ? ((await vibeApi.getReleasePassport(releaseId)) as Passport)
      : workId
        ? ((await vibeApi.getWorkPassport(workId)) as Passport)
        : null;
    if (!passport) return null;
    const id = passport.work_id || workId;
    if (!id) return passport;
    const trial = await vibeApi.getRadioTrial(id).catch(() => null);
    return { ...passport, radio_trial: trial as Passport["radio_trial"] };
  }, [workId, releaseId]);

  const passportWorkId = data?.work_id || workId;
  useShareAppMessage(() => {
    const line = String(data?.share_line || data?.title || copy.brand.name);
    if (passportWorkId) return workSharePayload(passportWorkId, line);
    return { title: line };
  });

  useDidShow(() => {
    void reload();
  });
  usePullDownRefresh(async () => {
    await reload(true);
    Taro.stopPullDownRefresh();
  });

  async function share() {
    const line = String(data?.share_line || "");
    if (!line) return;
    await Taro.setClipboardData({ data: line });
    Taro.showToast({ title: c.passportCopied, icon: "success" });
  }

  async function shareFeed() {
    if (process.env.TARO_ENV === "weapp") {
      await copyWeappCreatorLink(creatorPage("passport", { workId: workId || undefined, releaseId: releaseId || undefined }));
      Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    const id = data?.work_id || workId;
    if (!id) return;
    setSharing(true);
    try {
      const result = await vibeApi.sharePassportToFeed(id);
      Taro.showToast({ title: result.updated ? c.passportUpdated : c.passportShared, icon: "success" });
    } catch (err) {
      Taro.showToast({ title: String((err as Error)?.message || copy.adminUi.actionFail), icon: "none" });
    } finally {
      setSharing(false);
    }
  }

  const stores = data?.stores || [];
  const live = Number(data?.live_stores || 0);
  const storeCodes = new Set(stores.map((store) => store.channel_code));
  const extraPortals = (data?.portal_channels || []).filter((portal) => !storeCodes.has(portal.code));
  const waiting = new Set(["session_wait", "session_running", "waiting_login", "assisting", "ops_queue", "awaiting_manual", "needs_upload"]);

  return (
    <PageShell title={c.passportTitle} subtitle={data?.title || c.hubSubtitle} ambient>
      <View className="creator">
        <WeappH5Bridge path={creatorPage("passport", { workId: workId || undefined, releaseId: releaseId || undefined })} />
        {process.env.TARO_ENV === "weapp" ? <StatusLine tone="info" density="quiet">{c.weappDeskHint}</StatusLine> : null}
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void reload()}
          empty={!loading && !data}
          emptyTitle={c.passportTitle}
          emptyDescription={c.hubSubtitle}
        >
          <View className="creator-hero">
            {data?.cover_url ? <Image className="creator-hero__cover" src={data.cover_url} mode="aspectFill" lazyLoad /> : null}
            <Text className="creator-hero__kicker">{c.passportTitle}</Text>
            <Text className="creator-hero__title">
              {live > 0 ? c.passportCelebrate.replace("{n}", String(live)) : data?.title || c.passportPending}
            </Text>
            <Text className="creator-hero__sub">
              {data?.title && live > 0 ? data.title : data?.artist_name || "—"}
              {data?.artist_name && live > 0 ? ` · ${data.artist_name}` : ""}
              {data?.isrc ? ` · ${c.metaIsrc} ${data.isrc}` : ""}
            </Text>
            {data?.next_store_action?.next ? (
              <StatusLine tone="info" density="quiet">{data.next_store_action.next}</StatusLine>
            ) : null}
            <View className="creator-actions">
              {data?.ai_disclosed ? <Badge tone="accent">AI</Badge> : null}
              {data?.c2pa_state === "embedded" ? (
                <Badge tone="success">{copy.worksUi.c2paEmbedded}</Badge>
              ) : data?.c2pa_state === "sidecar" ? (
                <Badge>{copy.worksUi.c2paSidecar}</Badge>
              ) : null}
              {live > 0 ? <Badge tone="success">{c.liveStores.replace("{n}", String(live))}</Badge> : <Badge tone="warning">{c.status.publishing}</Badge>}
            </View>
            {data?.radio_trial?.live ? (
              <NextActionCard
                kicker={c.radioTrialTitle}
                title={c.radioTrialLive}
                hint={data.radio_trial.station ? `${c.radioTrialHint} · ${data.radio_trial.station}` : c.radioTrialHint}
                go={c.goRadio}
                onClick={() =>
                  Taro.navigateTo({
                    url: socialPage("radio", {
                      workId: data.work_id,
                      station: data.radio_trial?.station,
                    }),
                  })
                }
              />
            ) : null}
          </View>

          {passportWorkId ? (
            <ShareButton
              className="ui-btn ui-btn--primary ui-btn--block"
              dataset={{ workid: passportWorkId, title: String(data?.share_line || data?.title || "") }}
              onShare={() => shareWork(passportWorkId, String(data?.share_line || data?.title || copy.brand.name))}
            >
              {c.passportShare}
            </ShareButton>
          ) : (
            <Button variant="primary" block onClick={() => void share()}>
              {c.passportShare}
            </Button>
          )}
          <Collapsible label={c.passportMoreShare} storageKey="passport-share-more">
            <Button variant="ghost" block onClick={() => void share()}>
              {c.passportCopy}
            </Button>
            {data?.work_id || workId ? (
              <Button variant="secondary" block loading={sharing} onClick={() => void shareFeed()}>
                {c.passportShareFeed}
              </Button>
            ) : null}
            {data?.share_line ? <Text className="typo-meta">{data.share_line}</Text> : null}
          </Collapsible>

          <Collapsible label={c.musicianTools} storageKey="passport-musician">
            <AssetLanes
              status={{
                ...data?.asset_status,
                needs_ai_musician: data?.needs_ai_musician,
              }}
              forceClips={Boolean(data?.clip_windows?.length)}
              onDownloadOriginality={
                data?.asset_status?.evidence?.ready && (data?.work_id || workId)
                  ? () => void saveOriginalityPack(String(data?.work_id || workId), c)
                  : undefined
              }
              onDownloadClips={
                data?.asset_status?.clips?.ready && (data?.work_id || workId)
                  ? () => void saveClipPack(String(data?.work_id || workId), c)
                  : undefined
              }
            />
            <StatusLine tone={data?.commercial ? "success" : "info"} density="quiet">
              {data?.commercial ? c.commercialOpen : c.commercialStamp}
            </StatusLine>
            <Text className="typo-meta">{c.rightsNonExclusive}</Text>
            <Text className="typo-meta">
              {c.rightsCertificateHint
                .replace("{edits}", String(data?.rights_certificate?.human_edits || data?.human_edits?.length || 0))
                .replace("{ai}", data?.ai_disclosed ? "AI" : "—")}
            </Text>
            {passportWorkId ? (
              <Button
                variant="ghost"
                size="sm"
                block
                onClick={() => Taro.navigateTo({ url: studioPage("provenance", { workId: passportWorkId }) })}
              >
                {c.viewLineageProof}
              </Button>
            ) : null}
            {data?.mode === "label" && live > 0 && !data?.isrc ? (
              <Text className="typo-meta">{c.trackCodeAuto}</Text>
            ) : null}
          </Collapsible>

          <SectionLabel>{c.dspStoresTitle}</SectionLabel>
          {stores.map((store) => {
            const waitingPortal = waiting.has(store.user_status || store.status || "") ? store.upload_url : "";
            const link = store.store_url || waitingPortal;
            const meta = storeRowMeta(store, c);
            return (
              <View key={store.channel_code} className={`creator-channel ${isLiveDelivery(store) ? "creator-channel--live" : waiting.has(store.user_status || store.status || "") ? "creator-channel--wait" : ""}`.trim()}>
                <View className="creator-channel creator-channel--tap" onClick={() => openExternal(link)}>
                <View>
                  <Text className="creator-channel__name">{store.name || channelName(store.channel_code, c.channels)}</Text>
                  <Text className="creator-channel__meta">
                    {store.sop ? `${meta.line} · ${store.sop}` : meta.line}
                  </Text>
                </View>
                <Badge tone={statusTone(store.user_status || store.status)}>
                  {statusLabel(store.user_status || store.status || "publishing", c.status)}
                </Badge>
                </View>
                <View className="creator-actions">
                  {store.upload_url ? (
                    <Button size="sm" variant="ghost" onClick={() => openExternal(store.upload_url)}>
                      {c.openMusicianPortal}
                    </Button>
                  ) : null}
                  {store.store_url ? (
                    <Button size="sm" variant="ghost" onClick={() => openExternal(store.store_url)}>
                      {c.openStorePage}
                    </Button>
                  ) : null}
                </View>
              </View>
            );
          })}
          {stores.some((store) => isStoreAssist(store.status, store.user_status)) ? (
            <NextActionCard
              kicker={c.waitingNow}
              title={
                stores.some((store) => isUploadWait(store.status, store.user_status)) &&
                !stores.some((store) => isStoreAssist(store.status, store.user_status) && !isUploadWait(store.status, store.user_status))
                  ? c.bucketUpload
                  : sessionWaitCta(c, {
                      weapp: process.env.TARO_ENV === "weapp",
                      connectorOnline: process.env.TARO_ENV !== "weapp",
                      waiting: stores.filter((store) => isStoreAssist(store.status, store.user_status)).length,
                    }).title
              }
              hint={c.portalNotStore}
              go={c.nextGo}
              urgent
              onClick={() =>
                Taro.navigateTo({
                  url: creatorPage(
                    stores.some((store) => isUploadWait(store.status, store.user_status)) &&
                      !stores.some((store) => isStoreAssist(store.status, store.user_status) && !isUploadWait(store.status, store.user_status))
                      ? "deliveries"
                      : "accounts",
                    { workId: workId || undefined, releaseId: releaseId || undefined },
                  ),
                })
              }
            />
          ) : null}

          {(data?.human_edits || []).length > 0 && (
            <Collapsible label={c.humanEdits} storageKey="passport-edits">
              <Text className="typo-meta">{c.humanEditsHint}</Text>
              {(data?.human_edits || []).slice(-8).map((edit, index) => (
                <View key={`${edit.at || index}-${edit.section || edit.kind}`} className="creator-check">
                  <Text className="creator-check__label">
                    {`${edit.kind === "workbench" ? copy.provenanceUi.workbenchStep : edit.kind || "edit"}${edit.section ? ` · ${edit.section}` : ""}${edit.note ? ` · ${edit.note}` : ""}`}
                  </Text>
                </View>
              ))}
            </Collapsible>
          )}

          {(data?.clip_windows || []).length > 0 && (
            <Collapsible label={c.clipPack} storageKey="passport-clips">
              <Text className="typo-meta">{c.portalClipHint}</Text>
              {data?.work_id || workId ? (
                <Button
                  size="sm"
                  variant="secondary"
                  loading={clipBusy}
                  onClick={() => {
                    const id = data?.work_id || workId;
                    if (!id) return;
                    void (async () => {
                      setClipBusy(true);
                      try {
                        await saveClipPack(id, c);
                      } catch {
                        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                      } finally {
                        setClipBusy(false);
                      }
                    })();
                  }}
                >
                  {c.downloadClipPack}
                </Button>
              ) : null}
              {(data?.clip_windows || []).map((clip) => (
                <View key={`${clip.length}-${clip.start}`} className="creator-check">
                  <Text className="creator-check__label">{`${clip.length}s · ${clip.start}–${clip.end}`}</Text>
                </View>
              ))}
            </Collapsible>
          )}

          {extraPortals.length > 0 && (
            <>
              <SectionLabel>{c.clipLaneTitle}</SectionLabel>
              {extraPortals.map((portal) => (
                <View key={portal.code} className="creator-channel" onClick={() => openExternal(portal.upload_url)}>
                  <View>
                    <Text className="creator-channel__name">{portal.name || channelName(portal.code, c.channels)}</Text>
                    <Text className="creator-channel__meta">{portal.sop || portal.upload_url}</Text>
                  </View>
                  <Badge tone="info">{c.openPortal}</Badge>
                </View>
              ))}
            </>
          )}

          {data?.work_id ? (
            <View className="creator-actions creator-actions--stack">
              {data.radio_trial?.live ? (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() =>
                    Taro.navigateTo({
                      url: socialPage("radio", {
                        workId: data.work_id,
                        station: data.radio_trial?.station,
                      }),
                    })
                  }
                >
                  {c.goRadio}
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() =>
                    Taro.navigateTo({
                      url: creatorPage("deliveries", { workId: data.work_id, releaseId: data.release_id }),
                    })
                  }
                >
                  {c.viewProgress}
                </Button>
              )}
              <Collapsible label={c.passportMoreDoors} defaultOpen={false}>
                <Button size="sm" variant="ghost" block onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId: data.work_id }) })}>
                  {c.workLedgerTitle}
                </Button>
                <Button size="sm" variant="ghost" block onClick={() => Taro.navigateTo({ url: creatorPage("wallet") })}>
                  {c.goWallet}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  block
                  onClick={() => Taro.navigateTo({ url: commercePage("syncDesk", { workId: data.work_id }) })}
                >
                  {c.goSync}
                </Button>
                {!data.radio_trial?.live ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    block
                    onClick={() =>
                      Taro.navigateTo({
                        url: socialPage("radio", {
                          workId: data.work_id,
                          station: data.radio_trial?.station,
                        }),
                      })
                    }
                  >
                    {c.goRadio}
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    block
                    onClick={() =>
                      Taro.navigateTo({
                        url: creatorPage("deliveries", { workId: data.work_id, releaseId: data.release_id }),
                      })
                    }
                  >
                    {c.viewProgress}
                  </Button>
                )}
              </Collapsible>
            </View>
          ) : null}
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
