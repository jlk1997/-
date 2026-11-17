import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { Badge, Button, ChipGroup, StatusLine } from "../../../components/ui";
import { creatorPage, CREATOR_PAGE_ROUTES } from "../../../constants/routes";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import { NextActionCard } from "../../NextActionCard";
import { requireAuth } from "../../../utils/auth";
import { pickCsvFile, uploadRoyaltyReportUniversal } from "../../../platform/upload";
import { vibeApi } from "../../../services/api";
import { formatFen, syncProviderLabel, syncReasonLabel, type SyncResultRow } from "../../lib";
import { useEffect, useState } from "react";
import { listenExtensionEvents, markBittunePage, pairFromMinted, sendPairToExtension } from "../../extensionPair";
import "../../creator.scss";
import "./index.scss";

type Source = {
  id: string;
  usable_for_settlement?: boolean;
  configured?: boolean;
  bound?: boolean;
  reason?: string;
  has_isrc?: boolean;
  provider?: string;
  path?: string;
};

export default function DataImportPage() {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const weapp = process.env.TARO_ENV === "weapp";
  const [msg, setMsg] = useState("");
  const [fail, setFail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showOps, setShowOps] = useState(false);
  const [sources, setSources] = useState<Source[]>([]);
  const [syncedAt, setSyncedAt] = useState("");
  const [results, setResults] = useState<SyncResultRow[]>([]);
  const [needIsrc, setNeedIsrc] = useState(false);
  const [claims, setClaims] = useState<Array<{ id: string; title?: string; channel_code?: string; streams?: number; status?: string }>>([]);
  const [works, setWorks] = useState<Array<{ id: string; title?: string }>>([]);
  const [matchIds, setMatchIds] = useState<Record<string, string>>({});
  const [mintMeta, setMintMeta] = useState<{ role?: string; expires_at?: string } | null>(null);
  const [inbox, setInbox] = useState<
    Array<{ id: string; filename?: string; source?: string; status?: string; row_count?: number; created_at?: string; usable_for_settlement?: boolean }>
  >([]);
  const [harvestRows, setHarvestRows] = useState<
    Array<{
      id: string;
      title?: string;
      channel_code?: string;
      period_key?: string;
      streams?: number;
      revenue_minor?: number;
    }>
  >([]);
  const [unattached, setUnattached] = useState<
    Array<{
      id: string;
      title?: string;
      channel_code?: string;
      period_key?: string;
      streams?: number;
      revenue_minor?: number;
      suggested_work_id?: string;
      suggested_title?: string;
      usable_for_settlement?: boolean;
    }>
  >([]);
  const [isrcBlocked, setIsrcBlocked] = useState<
    Array<{
      id: string;
      title?: string;
      isrc?: string;
      channel_code?: string;
      period_key?: string;
      work_id?: string;
      work_title?: string;
      reason?: string;
    }>
  >([]);

  async function loadSources() {
    if (!requireAuth(creatorPage("dataImport"))) return;
    try {
      const res = await vibeApi.listAnalyticsSources();
      setSources(((res.sources || []) as Source[]).filter((s) => !String(s.id).endsWith("_api") || s.configured));
      const [claimRes, workRes, inboxRes, unattachedRes, blockedRes, harvestRes] = await Promise.all([
        vibeApi.listConnectorClaims().catch(() => ({ claims: [] })),
        vibeApi.listWorks("newest").catch(() => []),
        vibeApi.listRoyaltyReports().catch(() => ({ imports: [] })),
        vibeApi.listUnattachedSnapshots().catch(() => ({ snapshots: [] })),
        vibeApi.listIsrcBlocked().catch(() => ({ snapshots: [] })),
        vibeApi.listHarvestUnmatched().catch(() => ({ rows: [] })),
      ]);
      setInbox((inboxRes.imports || []) as typeof inbox);
      setClaims((claimRes.claims || []) as typeof claims);
      setWorks((Array.isArray(workRes) ? workRes : []) as Array<{ id: string; title?: string }>);
      setHarvestRows((harvestRes.rows || []) as typeof harvestRows);
      const snaps = (unattachedRes.snapshots || []) as typeof unattached;
      setUnattached(snaps);
      setIsrcBlocked((blockedRes.snapshots || []) as typeof isrcBlocked);
      setMatchIds((prev) => {
        const next = { ...prev };
        for (const snap of snaps) {
          if (snap.suggested_work_id && !next[snap.id]) next[snap.id] = snap.suggested_work_id;
        }
        return next;
      });
    } catch {
      setSources([]);
    }
  }

  useDidShow(() => {
    if (!weapp) markBittunePage();
    void loadSources();
  });
  useEffect(() => {
    if (weapp) return undefined;
    markBittunePage();
    return listenExtensionEvents(() => {
      void loadSources();
    });
  }, [weapp]);
  usePullDownRefresh(async () => {
    await loadSources();
    Taro.stopPullDownRefresh();
  });

  async function pick() {
    if (busy) return;
    if (weapp) {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.dataImport);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    if (!requireAuth(creatorPage("dataImport"))) return;
    setBusy(true);
    try {
      const file = await pickCsvFile();
      const res = await uploadRoyaltyReportUniversal(file, "user_export");
      const parts = [
        res.deduped ? c.importDeduped : c.importOk.replace("{n}", String(res.row_count ?? 0)),
        c.importMatched.replace("{n}", String(res.matched_works ?? 0)),
      ];
      if ((res.rematched || 0) > 0) {
        parts.push(c.rematchOk.replace("{n}", String(res.rematched)));
      }
      if ((res.unmatched_rows || 0) > 0) {
        parts.push(c.importUnmatched.replace("{n}", String(res.unmatched_rows)));
      }
      if ((res.periods || []).length) {
        parts.push(c.importPeriods.replace("{p}", (res.periods || []).join(" / ")));
      }
      const ok = parts.join(" · ");
      setFail(false);
      setNeedIsrc((res.unmatched_rows || 0) > 0);
      setMsg(ok);
      Taro.showToast({ title: c.importOk.replace("{n}", String(res.row_count ?? 0)), icon: "success" });
      void loadSources();
    } catch {
      setFail(true);
      setMsg(c.importFail);
      Taro.showToast({ title: c.importFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  async function rematchNow() {
    if (busy) return;
    if (weapp) {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.dataImport);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    if (!requireAuth(creatorPage("dataImport"))) return;
    setBusy(true);
    try {
      const res = await vibeApi.rematchRoyaltyReports();
      const n = Number(res.matched || 0);
      setFail(false);
      setMsg(c.rematchOk.replace("{n}", String(n)));
      Taro.showToast({ title: c.rematchOk.replace("{n}", String(n)), icon: n > 0 ? "success" : "none" });
      void loadSources();
    } catch {
      setFail(true);
      setMsg(copy.adminUi.actionFail);
    } finally {
      setBusy(false);
    }
  }

  async function syncNow() {
    if (busy) return;
    if (weapp) {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.dataImport);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    if (!requireAuth(creatorPage("dataImport"))) return;
    setBusy(true);
    try {
      const res = await vibeApi.syncCreatorAnalytics();
      const n = Number(res.synced || 0);
      const rows = (Array.isArray(res.results) ? res.results : []) as SyncResultRow[];
      setResults(rows);
      setSyncedAt(String(res.synced_at || ""));
      setFail(false);
      const firstReason = rows.find((row) => row.reason && row.reason !== "ok")?.reason;
      setMsg(n > 0 ? c.syncOk.replace("{n}", String(n)) : firstReason ? syncReasonLabel(firstReason, c) : c.syncNone);
      Taro.showToast({ title: n > 0 ? c.syncOk.replace("{n}", String(n)) : c.syncNone, icon: n > 0 ? "success" : "none" });
      void loadSources();
    } catch {
      setFail(true);
      setMsg(copy.adminUi.actionFail);
    } finally {
      setBusy(false);
    }
  }

  async function connectYoutube() {
    if (weapp) {
      void copyWeappCreatorLink(CREATOR_PAGE_ROUTES.dataImport);
      Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    if (!requireAuth(creatorPage("dataImport"))) return;
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
  }

  function sourceTitle(s: Source) {
    if (s.id === "official_csv") return c.sourceCsv;
    if (s.id === "youtube") return c.sourceYoutube;
    if (s.id === "chartmetric") return c.sourceChartmetric;
    if (s.id === "ops_connector") return c.connectorOpsTitle;
    if (s.id === "user_connector") return c.connectorUserTitle;
    return `${c.sourcePartner} · ${s.provider || s.id}`;
  }

  function sourceHint(s: Source) {
    if (s.id === "chartmetric" && s.configured && s.has_isrc === false) return c.needIsrc;
    if (s.reason === "configured_no_endpoint") return c.noPartnerEndpoint;
    if (s.reason === "configured_no_public_earnings_api" || (s.reason === "not_configured" && String(s.id).endsWith("_api"))) {
      return c.noPublicApi;
    }
    if (s.id === "youtube" && !s.configured) return c.youtubeNeedConfig;
    if (s.id === "youtube" && s.bound) return c.youtubeConnected;
    return s.usable_for_settlement ? c.dataHint : c.displayOnlyHint;
  }

  return (
    <PageShell title={c.harvestUnmatchedTitle} subtitle={c.navImportHint} ambient>
      <View className="creator">
        <WeappH5Bridge path={CREATOR_PAGE_ROUTES.dataImport} />
        <View className="creator-hero">
          <Text className="creator-hero__kicker">{c.settlementBadge}</Text>
          <Text className="creator-hero__title">{c.harvestUnmatchedTitle}</Text>
          <Text className="creator-hero__sub">{c.harvestAttachHint}</Text>
          <Text className="typo-meta" onClick={() => Taro.navigateTo({ url: creatorPage("help") })}>
            {c.seeHelp}
          </Text>
        </View>

        <Text className="creator-pick__title">{c.harvestSeatTitle}</Text>
        {harvestRows.length === 0 ? (
          <View className="creator-card">
            <NextActionCard
              kicker={c.nextAction}
              title={c.goDeliveries}
              hint={c.harvestEmptyHint}
              go={c.nextGo}
              onClick={() => Taro.navigateTo({ url: creatorPage("deliveries") })}
            />
          </View>
        ) : (
          <View className="creator-card">
            <Text className="creator-pick__title">{c.harvestUnmatchedTitle}</Text>
            <StatusLine tone="info" density="quiet">{c.unmatchedHint.replace("{n}", String(harvestRows.length))}</StatusLine>
            {harvestRows.map((row) => (
              <View key={row.id} className="creator-card">
                <View className="creator-channel">
                  <View>
                    <Text className="creator-channel__name">{row.title || row.channel_code || row.id.slice(0, 8)}</Text>
                    <Text className="creator-channel__meta">
                      {`${row.channel_code || ""} · ${row.period_key || ""} · ${row.streams || 0}`}
                      {row.revenue_minor ? ` · ${formatFen(row.revenue_minor)}` : ""}
                    </Text>
                  </View>
                  <Badge tone="warning">{c.unmatchedBadge}</Badge>
                </View>
                {works.length > 0 && (
                  <>
                    <ChipGroup
                      options={works.slice(0, 8).map((work) => ({ value: work.id, label: work.title || work.id.slice(0, 6) }))}
                      value={matchIds[row.id] || ""}
                      onChange={(value) => setMatchIds((prev) => ({ ...prev, [row.id]: value }))}
                    />
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        if (weapp) {
                          void copyWeappCreatorLink(CREATOR_PAGE_ROUTES.dataImport);
                          Taro.showToast({ title: c.weappDeskHint, icon: "none" });
                          return;
                        }
                        const workId = matchIds[row.id];
                        if (!workId) return;
                        void (async () => {
                          try {
                            await vibeApi.attachHarvestUnmatched(row.id, workId);
                            Taro.showToast({ title: c.attachSnapshot, icon: "success" });
                            void loadSources();
                          } catch {
                            Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                          }
                        })();
                      }}
                    >
                      {c.attachSnapshot}
                    </Button>
                  </>
                )}
              </View>
            ))}
          </View>
        )}

        {claims.length > 0 && (
          <View className="creator-card">
            <Text className="creator-pick__title">{c.claimsTitle}</Text>
            {claims.map((claim) => (
              <View key={claim.id} className="creator-card">
                <View className="creator-channel">
                  <View>
                    <Text className="creator-channel__name">{claim.title || claim.channel_code}</Text>
                    <Text className="creator-channel__meta">{`${claim.channel_code || ""} · ${claim.streams || 0}`}</Text>
                  </View>
                  <Badge tone={claim.status === "matched" ? "success" : "warning"}>
                    {claim.status === "matched" ? c.claimMatched : c.settlementBadge}
                  </Badge>
                </View>
                {works.length > 0 && claim.status !== "matched" && (
                  <>
                    <ChipGroup
                      options={works.slice(0, 8).map((work) => ({ value: work.id, label: work.title || work.id.slice(0, 6) }))}
                      value={matchIds[claim.id] || ""}
                      onChange={(value) => setMatchIds((prev) => ({ ...prev, [claim.id]: value }))}
                    />
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        if (weapp) {
                          void copyWeappCreatorLink(CREATOR_PAGE_ROUTES.dataImport);
                          Taro.showToast({ title: c.weappDeskHint, icon: "none" });
                          return;
                        }
                        const workId = matchIds[claim.id];
                        if (!workId) return;
                        void (async () => {
                          try {
                            await vibeApi.matchConnectorClaim(claim.id, workId);
                            Taro.showToast({ title: c.claimMatched, icon: "success" });
                            void loadSources();
                          } catch {
                            Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                          }
                        })();
                      }}
                    >
                      {c.matchClaim}
                    </Button>
                  </>
                )}
              </View>
            ))}
          </View>
        )}

        <View className="creator-card">
          <Text className="creator-pick__title">{c.opsSidePath}</Text>
          <StatusLine tone="info">{c.opsSidePathHint}</StatusLine>
          <Button variant="ghost" block onClick={() => setShowOps((prev) => !prev)}>
            {showOps ? c.hideOpsPath : c.showOpsPath}
          </Button>
        </View>

        {showOps ? (
          <>
        {weapp ? (
          <StatusLine tone="info">{c.weappDeskHint}</StatusLine>
        ) : (
        <View className={busy ? "creator-drop creator-drop--busy" : "creator-drop"} onClick={() => !busy && void pick()}>
          <Text className="creator-drop__title">{busy ? copy.provenanceUi.loading : c.importTap}</Text>
          <Text className="creator-drop__hint">{c.importNotMainPath}</Text>
        </View>
        )}

        <Text className="creator-pick__title">{c.harvestCsvTitle}</Text>
        <Text className="typo-meta">{c.harvestCsvHint}</Text>
        {inbox.length > 0 && (
          <View className="creator-card">
            <Text className="creator-pick__title">{c.inboxTitle}</Text>
            {inbox.map((row) => (
              <View key={row.id} className="creator-channel">
                <View>
                  <Text className="creator-channel__name">{row.filename || row.source}</Text>
                  <Text className="creator-channel__meta">
                    {`${row.source || ""} · ${row.status || ""} · ${row.row_count || 0}`}
                    {row.created_at ? ` · ${row.created_at.slice(0, 10)}` : ""}
                  </Text>
                </View>
                <Badge tone={row.usable_for_settlement ? "success" : "warning"}>
                  {row.usable_for_settlement ? c.settlementBadge : c.displayOnlyBadge}
                </Badge>
              </View>
            ))}
          </View>
        )}
        {inbox.length === 0 && <StatusLine tone="info">{c.inboxEmpty}</StatusLine>}

        {isrcBlocked.length > 0 && (
          <View className="creator-card">
            <Text className="creator-pick__title">{c.alertIsrcBlocked.replace("{n}", String(isrcBlocked.length))}</Text>
            <StatusLine tone="info">{c.isrcBlockedHint.replace("{n}", String(isrcBlocked.length))}</StatusLine>
            {isrcBlocked.slice(0, 8).map((row) => (
              <View
                key={row.id}
                className="creator-channel creator-channel--tap"
                onClick={() =>
                  Taro.navigateTo({
                    url: creatorPage("release", { workId: row.work_id || undefined }),
                  })
                }
              >
                <View>
                  <Text className="creator-channel__name">{row.work_title || row.title || row.isrc || row.id}</Text>
                  <Text className="creator-channel__meta">
                    {`${row.channel_code || ""} · ${row.period_key || ""} · ${row.reason === "no_isrc" ? c.needIsrc : c.needIsrcLabel}`}
                  </Text>
                </View>
                <Button size="sm" variant="secondary">
                  {c.metaIsrc}
                </Button>
              </View>
            ))}
          </View>
        )}
        {unattached.length > 0 && (
          <View className="creator-card">
            <Text className="creator-pick__title">{c.unmatchedTitle}</Text>
            <StatusLine tone="info">{c.unmatchedHint.replace("{n}", String(unattached.length))}</StatusLine>
            {unattached.map((row) => (
              <View key={row.id} className="creator-card">
                <View className="creator-channel">
                  <View>
                    <Text className="creator-channel__name">{row.title || row.channel_code || row.id.slice(0, 8)}</Text>
                    <Text className="creator-channel__meta">
                      {`${row.channel_code || ""} · ${row.period_key || ""} · ${row.streams || 0}`}
                      {row.suggested_title ? ` · ${row.suggested_title}` : ""}
                    </Text>
                  </View>
                  <Badge tone={row.usable_for_settlement ? "success" : "warning"}>
                    {row.usable_for_settlement ? c.settlementBadge : c.displayOnlyBadge}
                  </Badge>
                </View>
                {works.length > 0 && (
                  <>
                    <ChipGroup
                      options={works.slice(0, 8).map((work) => ({ value: work.id, label: work.title || work.id.slice(0, 6) }))}
                      value={matchIds[row.id] || row.suggested_work_id || ""}
                      onChange={(value) => setMatchIds((prev) => ({ ...prev, [row.id]: value }))}
                    />
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        if (weapp) {
                          void copyWeappCreatorLink(CREATOR_PAGE_ROUTES.dataImport);
                          Taro.showToast({ title: c.weappDeskHint, icon: "none" });
                          return;
                        }
                        const workId = matchIds[row.id] || row.suggested_work_id;
                        if (!workId) return;
                        void (async () => {
                          try {
                            await vibeApi.attachUnattachedSnapshot(row.id, workId);
                            Taro.showToast({ title: c.attachSnapshot, icon: "success" });
                            void loadSources();
                          } catch {
                            Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                          }
                        })();
                      }}
                    >
                      {c.attachSnapshot}
                    </Button>
                  </>
                )}
              </View>
            ))}
          </View>
        )}

        {sources.map((s) => (
          <View key={s.id} className="creator-card">
            <View className="creator-release-head">
              <View className="creator-channel__head">
                <View className={s.usable_for_settlement ? "creator-channel__pip creator-channel__pip--live" : "creator-channel__pip creator-channel__pip--display"} />
                <Text className="creator-pick__title">{sourceTitle(s)}</Text>
              </View>
              <Badge tone={s.usable_for_settlement ? "success" : "warning"}>
                {s.usable_for_settlement ? c.settlementBadge : c.displayOnlyBadge}
              </Badge>
            </View>
            <Text className="typo-meta">{sourceHint(s)}</Text>
            {s.id === "youtube" && (
              <Button size="sm" variant={s.bound ? "ghost" : "secondary"} onClick={() => void connectYoutube()}>
                {s.bound ? c.youtubeConnected : c.youtubeConnect}
              </Button>
            )}
          </View>
        ))}

        <View className="creator-card">
          <Text className="creator-pick__title">{c.connectorTitle}</Text>
          <StatusLine tone="info">
            {process.env.TARO_ENV === "weapp" ? c.connectorBrowserOnly : c.connectorBrowserOnlyH5}
          </StatusLine>
          <StatusLine tone="info">{c.connectorHint}</StatusLine>
          <Text className="typo-meta">{c.installConnector}</Text>
          {mintMeta && (
            <Text className="typo-meta">
              {c.connectorRole
                .replace("{role}", mintMeta.role || "user")
                .replace("{exp}", (mintMeta.expires_at || "").slice(0, 10))}
            </Text>
          )}
          {!weapp ? (
            <Button
              variant="primary"
              block
              loading={busy}
              onClick={() => {
                void (async () => {
                  setBusy(true);
                  try {
                    const minted = await vibeApi.mintConnectorToken();
                    setMintMeta({ role: minted.role, expires_at: minted.expires_at || undefined });
                    const sent = await sendPairToExtension(pairFromMinted(minted));
                    if (sent) {
                      Taro.showToast({ title: c.sentToExtension, icon: "success" });
                      return;
                    }
                    await Taro.setClipboardData({ data: minted.pair_text || minted.token });
                    Taro.showToast({ title: c.extensionNotInstalled, icon: "none" });
                  } catch {
                    Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            >
              {c.sendToExtension}
            </Button>
          ) : null}
          {!weapp ? (
          <Button
            variant="secondary"
            block
            loading={busy}
            onClick={() => {
              void (async () => {
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
              })();
            }}
          >
            {c.mintConnectorToken}
          </Button>
          ) : null}
        </View>
        <Button variant="primary" block loading={busy} onClick={() => void syncNow()}>
          {c.syncNow}
        </Button>
        <Button variant="secondary" block loading={busy} onClick={() => void rematchNow()}>
          {c.rematchNow}
        </Button>
        {unattached.some((row) => row.suggested_work_id) && (
          <Button
            variant="ghost"
            block
            loading={busy}
            onClick={() => {
              void (async () => {
                setBusy(true);
                try {
                  const res = await vibeApi.attachSuggestedSnapshots();
                  Taro.showToast({
                    title: `${c.attachSuggested} · ${res.attached || 0}`,
                    icon: "success",
                  });
                  void loadSources();
                } catch {
                  Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                } finally {
                  setBusy(false);
                }
              })();
            }}
          >
            {c.attachSuggested}
          </Button>
        )}
        {syncedAt && <Text className="typo-meta">{c.lastSync.replace("{t}", syncedAt.slice(0, 16).replace("T", " "))}</Text>}
        {results.length > 0 && (
          <View className="creator-card">
            <Text className="creator-pick__title">{c.syncBreakdown}</Text>
            {results.map((row, i) => (
              <View key={`${row.provider || row.source || "src"}-${i}`} className="creator-channel">
                <View>
                  <Text className="creator-channel__name">{syncProviderLabel(row, c)}</Text>
                  <Text className="creator-channel__meta">{syncReasonLabel(row.reason, c)}</Text>
                </View>
                <Text className="creator-channel__name">{String(row.synced || 0)}</Text>
              </View>
            ))}
          </View>
        )}
          </>
        ) : null}
        {msg && <StatusLine tone={fail ? "error" : "success"}>{msg}</StatusLine>}
        {!fail && msg && (
          <View className="creator-actions">
            <Button variant="primary" onClick={() => Taro.navigateTo({ url: creatorPage("settlements") })}>
              {c.goSettlements}
            </Button>
            <Button variant="secondary" onClick={() => Taro.navigateTo({ url: creatorPage("wallet") })}>
              {c.goWallet}
            </Button>
            {needIsrc && (
              <Button variant="ghost" onClick={() => Taro.navigateTo({ url: creatorPage("release") })}>
                {c.goFillIsrc}
              </Button>
            )}
          </View>
        )}
      </View>
    </PageShell>
  );
}
