import { useEffect, useMemo, useState } from "react";
import { View, Text, Image, Textarea } from "@tarojs/components";
import Taro, { useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { Badge, Button, ChipGroup, Collapsible, EmptyState, Input, ModeTileGrid, SectionLabel, StatusLine, StepRail } from "../../../components/ui";
import { ConsentCheckbox } from "../../../components/legal/ConsentCheckbox";
import { vibeApi, type Work } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { CREATOR_PAGE_ROUTES, creatorPage, socialPage } from "../../../constants/routes";
import { LEGAL_ROUTES, legalDocLabel } from "../../../utils/legal";
import { useCreditsOptional } from "../../../contexts/CreditsProvider";
import { channelName, confirmCreatorAction, deliveryBuckets, humanizeDeliveryError, isLiveDelivery, isStoreAssist, isWaitingLogin, routePreviewLabel, sessionWaitCta, shipChannelGroup, statusLabel, statusTone, type WorkPick } from "../../lib";
import { isWorkbenchMaster, releaseTargetId } from "../../../utils/workbenchWorks";
import { saveClipPack, saveOriginalityPack, saveReleaseKit } from "../../kitAction";
import { ChannelTimeline } from "../../ChannelTimeline";
import { NextActionCard } from "../../NextActionCard";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import { AuthDesk } from "../../AuthDesk";
import { ShipCompleteCard } from "../../ShipCompleteCard";
import { sendPollToExtension } from "../../extensionPair";
import { type ConnectionCard } from "../../ConnectionsRow";
import { ChannelMark } from "../../ChannelMark";
import { AssetChips, AssetLanes } from "../../../components/studio/AssetLanes";
import { uploadFile } from "../../../platform/upload";
import "../../creator.scss";
import "./index.scss";

type Qc = {
  passed?: boolean;
  checks?: Record<string, boolean>;
  originality?: { risk_score?: number };
};

type ReleasePayload = {
  id: string;
  work_id?: string;
  redirected_from_work_id?: string;
  from_workbench?: boolean;
  mode?: "label" | "self_release";
  status?: string;
  already_active?: boolean;
  selected_channels?: string[];
  qc_result?: Qc;
  kit_url?: string;
  commission_rate?: number;
  allowed_commission_rates?: number[];
  asset_status?: {
    listing?: { ready?: boolean; label?: string; wav?: boolean };
    evidence?: { needed?: boolean; ready?: boolean; label?: string; quality?: string };
    clips?: { needed?: boolean; ready?: boolean };
    needs_ai_musician?: boolean;
  };
  metadata?: {
    title?: string;
    artist_name?: string;
    isrc?: string;
    ai_disclosed?: boolean;
    lyrics?: string | null;
    language?: string | null;
    genres?: string[];
    upc?: string | null;
    listing?: Record<string, unknown>;
  };
  deliveries?: Array<{ channel_code?: string; status?: string; user_status?: string }>;
  route_preview?: Array<{ channel_code?: string; route?: string; automation_level?: string }>;
  automation?: {
    ready_to_confirm?: boolean;
    qc_hydrated?: boolean;
    qc_passed?: boolean;
    channel_suggestion?: { reason?: string; channels?: string[]; region?: string };
  };
};

export default function ReleaseWizardPage() {
  const { copy, locale } = useLocale();
  const c = copy.creatorUi;
  const credits = useCreditsOptional();
  const router = useRouter();
  const routeWorkId = router.params.workId || "";
  const weapp = process.env.TARO_ENV === "weapp";
  const [workId, setWorkId] = useState(routeWorkId);
  const [connections, setConnections] = useState<ConnectionCard[] | null>(null);
  const [works, setWorks] = useState<WorkPick[]>([]);
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<"label" | "self_release">("label");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [defaultArtist, setDefaultArtist] = useState("");
  const [isrc, setIsrc] = useState("");
  const [rate, setRate] = useState("20");
  const [allowedRates, setAllowedRates] = useState<number[]>([20, 30]);
  const [channels, setChannels] = useState<string[]>([]);
  const [catalog, setCatalog] = useState<Array<{
    code: string;
    name: string;
    region: string;
    delivery_mode?: string;
    capability?: "auto" | "wait_connector" | "needs_link";
    auto_default?: boolean;
    sop?: string;
    automation_level?: string;
    required_fields?: string[];
    asset_profile?: { needs_stems_evidence?: boolean; needs_clips?: boolean; needs_instrumental?: boolean };
  }>>([]);
  const [portals, setPortals] = useState<Array<{ code: string; name: string }>>([]);
  const [autoReady, setAutoReady] = useState(false);
  const [releaseId, setReleaseId] = useState("");
  const [qc, setQc] = useState<Qc | null>(null);
  const [busy, setBusy] = useState(false);
  const [kitUrl, setKitUrl] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [aiDisclosed, setAiDisclosed] = useState(true);
  const [listing, setListing] = useState<Record<string, string>>({ language: "zh" });
  const [submitted, setSubmitted] = useState(false);
  const [receipt, setReceipt] = useState<Array<{ channel_code?: string; status?: string; user_status?: string; last_error?: string }>>([]);
  const [routePreview, setRoutePreview] = useState<Array<{ channel_code?: string; route?: string; automation_level?: string; degraded?: boolean }>>([]);
  const [radioTrial, setRadioTrial] = useState<{
    live?: boolean;
    status?: string;
    station?: string;
    listen_completes?: number;
    next_action?: string;
    channel_suggestion?: { reason?: string; channels?: string[] };
  } | null>(null);
  const [channelSuggest, setChannelSuggest] = useState<{
    reason?: string;
    channels?: string[];
    shippable?: string[];
    blocked?: Array<{ code?: string; reason?: string }>;
    region?: string;
  } | null>(null);
  const [spawningInstrumental, setSpawningInstrumental] = useState(false);
  const [assetStatus, setAssetStatus] = useState<ReleasePayload["asset_status"]>();
  const [skuKind, setSkuKind] = useState("");
  const [preferMaster, setPreferMaster] = useState(false);
  const [catalogError, setCatalogError] = useState(false);

  const steps = [
    { id: "song", label: c.beatSong, icon: "music" as const },
    { id: "stores", label: c.beatStores, icon: "feed" as const },
    { id: "ship", label: c.beatShip, icon: "share" as const },
  ];

  useEffect(() => {
    if (routeWorkId) setWorkId(routeWorkId);
    if (!requireAuth(creatorPage("release", { workId: routeWorkId || undefined }))) return;
    vibeApi
      .listWorks("newest")
      .then((rows) => {
        setWorks(rows as Work[]);
        const found = rows.find((w) => w.id === routeWorkId);
        if (found) setTitle((prev) => prev || found.title);
      })
      .catch(() => setWorks([]));
    vibeApi
      .me()
      .then((me) => {
        const name = me.display_name || me.username || "";
        if (!name) return;
        setDefaultArtist(name);
        setArtist((prev) => prev || name);
      })
      .catch(() => {});
  }, [routeWorkId]);

  async function hydrateRelease(idHint?: string) {
    if (weapp) return null;
    if (!requireAuth(creatorPage("release", { workId: workId || undefined })) || !workId) return null;
    const created = (await vibeApi.createRelease(workId)) as ReleasePayload;
    if (created.work_id && created.work_id !== workId) {
      setWorkId(created.work_id);
      setPreferMaster(true);
    } else if (created.redirected_from_work_id) {
      setPreferMaster(true);
    }
    setReleaseId(created.id);
    if (created.already_active) {
      if (process.env.TARO_ENV === "h5") void sendPollToExtension();
      Taro.redirectTo({ url: creatorPage("deliveries", { releaseId: created.id, workId: created.work_id || workId }) });
      return created.id;
    }
    if (created.mode === "label" || created.mode === "self_release") setMode(created.mode);
    setTitle((prev) => prev || created.metadata?.title || works.find((w) => w.id === workId)?.title || "");
    setArtist((prev) => prev || created.metadata?.artist_name || "");
    setIsrc((prev) => prev || created.metadata?.isrc || "");
    if (typeof created.metadata?.ai_disclosed === "boolean") setAiDisclosed(created.metadata.ai_disclosed);
    const meta = created.metadata;
    if (meta) {
      const extra = meta.listing || {};
      setListing((prev) => ({
        language: prev.language || meta.language || "zh",
        lyrics: prev.lyrics || meta.lyrics || "",
        genres: prev.genres || (meta.genres || []).join("，"),
        upc: prev.upc || meta.upc || "",
        lyricist: prev.lyricist || String(extra.lyricist || ""),
        composer: prev.composer || String(extra.composer || ""),
        arranger: prev.arranger || String(extra.arranger || ""),
        producer: prev.producer || String(extra.producer || ""),
        featured_artists: prev.featured_artists || String(extra.featured_artists || ""),
        explicit: prev.explicit || String(extra.explicit || ""),
        copyright_line: prev.copyright_line || String(extra.copyright_line || ""),
        sound_recording_line: prev.sound_recording_line || String(extra.sound_recording_line || ""),
        label_name: prev.label_name || String(extra.label_name || ""),
        release_date: prev.release_date || String(extra.release_date || ""),
        territories: prev.territories || String(extra.territories || ""),
        price_minor: prev.price_minor || (extra.price_minor != null ? String(extra.price_minor) : ""),
        instrumental: prev.instrumental || (extra.instrumental ? "1" : ""),
      }));
    }
    if (created.selected_channels?.length) setChannels(created.selected_channels);
    if (created.qc_result?.checks || created.qc_result?.passed) setQc(created.qc_result);
    if (created.allowed_commission_rates?.length) {
      setAllowedRates(created.allowed_commission_rates);
      if (!created.allowed_commission_rates.includes(Number(created.commission_rate || rate))) {
        setRate(String(created.allowed_commission_rates[0]));
      }
    }
    if (created.commission_rate) setRate(String(created.commission_rate));
    if (created.kit_url) setKitUrl(created.kit_url);
    if (created.asset_status) setAssetStatus(created.asset_status);
    vibeApi
      .getWork(workId)
      .then((w) => {
        const sku = String((w.post_process_status as { sku_kind?: string } | undefined)?.sku_kind || "");
        setSkuKind(sku);
      })
      .catch(() => {});
    if (created.automation?.channel_suggestion) setChannelSuggest(created.automation.channel_suggestion);
    if (created.route_preview?.length) setRoutePreview(created.route_preview);
    const ready = Boolean(created.automation?.ready_to_confirm || created.automation?.qc_passed || created.qc_result?.passed);
    setAutoReady(ready);
    if (ready) {
      const loaded = await loadCatalog(created);
      const nextStep =
        loaded.ok &&
        (loaded.routeStores.length || loaded.suggested.length || loaded.selected.length || loaded.defaults.length)
          ? 2
          : 1;
      setStep(nextStep);
    }
    if (created.status && created.status !== "draft" && !idHint) {
      Taro.showToast({ title: c.resumeDraft, icon: "none" });
    }
    return created.id;
  }

  async function ensureRelease() {
    if (releaseId) return releaseId;
    return hydrateRelease(releaseId);
  }

  useEffect(() => {
    if (weapp) return;
    if (!workId || !requireAuth(creatorPage("release", { workId }))) return;
    void hydrateRelease();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workId]);

  useEffect(() => {
    void vibeApi
      .getCreatorHub()
      .then((hub) => setConnections(((hub as { connections?: ConnectionCard[] }).connections || []) as ConnectionCard[]))
      .catch(() => setConnections([]));
  }, []);

  async function runQc(id: string) {
    const result = (await vibeApi.qcRelease(id)) as { qc?: Qc };
    setQc(result.qc || (result as Qc));
  }

  async function uploadCover() {
    if (!workId) return;
    const w = copy.worksUi;
    let filePath: string | undefined;
    try {
      const pick = await Taro.chooseImage({ count: 1, sizeType: ["compressed"] });
      filePath = pick.tempFilePaths?.[0];
    } catch {
      return;
    }
    if (!filePath) return;
    try {
      Taro.showLoading({ title: w.coverUploading, mask: true });
      await uploadFile("/studio/cover-upload", filePath, "file", { work_id: workId });
      Taro.hideLoading();
      Taro.showToast({ title: w.coverUploaded, icon: "success" });
      const work = await vibeApi.getWork(workId).catch(() => null);
      if (work?.cover_url) {
        setWorks((prev) => prev.map((row) => (row.id === workId ? { ...row, cover_url: work.cover_url } : row)));
      }
      const id = await ensureRelease();
      if (id) await runQc(id);
    } catch {
      Taro.hideLoading();
      Taro.showToast({ title: w.coverUploadFail, icon: "none" });
    }
  }

  function qcFixMessage(result: Qc | null) {
    const checks = result?.checks || {};
    if (!checks.has_cover) return c.qcFixCover;
    if (!checks.loudness_ok) return c.qcFixLoudness;
    if (!checks.duration_ok) return c.qcFixDuration;
    if (!checks.has_title) return c.qcFixTitle;
    if (!checks.has_artist) return c.needArtist;
    if (!checks.ai_disclosed) return c.qcFixAi;
    if (!checks.originality_ok) return c.qcFixOriginal;
    return c.qcNeedPass;
  }

  async function loadCatalog(created?: ReleasePayload | null) {
    try {
      const ch = await vibeApi.listReleaseChannels();
      setCatalog(ch.channels);
      setPortals((ch.portals || []).map((p) => ({ code: p.code, name: p.name })));
      setCatalogError(false);
      const routeStores = String(router.params.stores || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const suggested = (created?.automation?.channel_suggestion?.channels || channelSuggest?.channels || []).filter(
        (code) => shipChannelGroup(code) !== "metrics",
      );
      const defaults = (ch.default_channels || []).filter((code) => shipChannelGroup(code) !== "metrics");
      const selected = created?.selected_channels || [];
      if (routeStores.length) setChannels(routeStores);
      else if (!selected.length && defaults.length) setChannels(defaults);
      else if (suggested.length && !selected.length) setChannels(suggested);
      else if (!selected.length) setChannels((prev) => (prev.length ? prev : defaults));
      return { defaults, suggested, routeStores, selected, ok: true as const };
    } catch {
      setCatalogError(true);
      return {
        defaults: [] as string[],
        suggested: [] as string[],
        routeStores: [] as string[],
        selected: [] as string[],
        ok: false as const,
      };
    }
  }

  async function refreshLanes(codes: string[]) {
    if (!releaseId) return;
    try {
      const updated = (await vibeApi.updateRelease(releaseId, { selected_channels: codes })) as ReleasePayload;
      if (updated?.asset_status) setAssetStatus(updated.asset_status);
    } catch {
      /* chips still update locally */
    }
  }

  async function next() {
    setBusy(true);
    try {
      const id = await ensureRelease();
      if (!id) return;
      if (step === 0) {
        if (!title.trim()) {
          Taro.showToast({ title: c.needTitle, icon: "none" });
          return;
        }
        if (!artist.trim()) {
          Taro.showToast({ title: c.needArtist, icon: "none" });
          return;
        }
        if (!aiDisclosed) {
          Taro.showToast({ title: c.needAiDisclose, icon: "none" });
          return;
        }
        await vibeApi.updateRelease(id, {
          mode,
          title,
          artist_name: artist,
          isrc: isrc.trim() || undefined,
          ai_disclosed: aiDisclosed,
        });
        const loaded = await loadCatalog();
        if (!loaded.ok) {
          Taro.showToast({ title: c.catalogLoadFail, icon: "none" });
          setStep(1);
          return;
        }
        let qcNow = qc;
        if (!qcNow?.passed) {
          const result = (await vibeApi.qcRelease(id)) as { qc?: Qc };
          qcNow = result.qc || (result as Qc);
          setQc(qcNow);
        }
        if (qcNow && !qcNow.passed) {
          Taro.showToast({ title: qcFixMessage(qcNow), icon: "none" });
          return;
        }
        Taro.vibrateShort({ type: "light" }).catch(() => undefined);
        setStep(1);
        return;
      }
      if (step === 1) {
        if (!channels.length) {
          Taro.showToast({ title: c.needChannels, icon: "none" });
          return;
        }
        const listingBody: Record<string, unknown> = {};
        for (const key of ["featured_artists", "lyricist", "composer", "arranger", "producer", "explicit", "copyright_line", "sound_recording_line", "label_name", "release_date", "territories"]) {
          if (listing[key]) listingBody[key] = listing[key];
        }
        if (listing.instrumental === "1") listingBody.instrumental = true;
        if (listing.price_minor) listingBody.price_minor = Number(listing.price_minor);
        const genres = (listing.genres || "").split(/[,，]/).map((item) => item.trim()).filter(Boolean);
        const updated = (await vibeApi.updateRelease(id, {
          selected_channels: channels,
          lyrics: listing.lyrics || undefined,
          language: listing.language || undefined,
          genres: genres.length ? genres : undefined,
          upc: listing.upc || undefined,
          listing: listingBody,
        })) as ReleasePayload;
        if (updated?.asset_status) setAssetStatus(updated.asset_status);
        Taro.vibrateShort({ type: "light" }).catch(() => undefined);
        setStep(2);
      }
    } catch (err) {
      const raw = String((err as Error)?.message || "");
      Taro.showToast({ title: raw.includes("403") || raw.toLowerCase().includes("not enabled") ? c.featureOff : copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  async function waitForQueue(id: string) {
    let latest: {
      kit_url?: string;
      has_kit?: boolean;
      deliveries?: Array<{ channel_code?: string; status?: string; user_status?: string }>;
    } | null = null;
    let delay = 300;
    for (let i = 0; i < 10; i += 1) {
      try {
        latest = (await vibeApi.getRelease(id)) as {
          kit_url?: string;
          has_kit?: boolean;
          deliveries?: Array<{ channel_code?: string; status?: string; user_status?: string }>;
        };
        const dels = latest.deliveries || [];
        if (dels.length > 0 && dels.every((d) => d.status && d.status !== "submitting")) {
          return latest;
        }
      } catch {
        /* poll again — submit already persisted */
      }
      await new Promise((resolve) => setTimeout(resolve, delay));
      delay = Math.min(1200, delay + 200);
    }
    return latest;
  }

  async function submit() {
    if (busy) return;
    if (weapp) {
      const copied = await copyWeappCreatorLink(creatorPage("release", { workId: workId || undefined }));
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    if (!releaseId) return;
    if (!agreed) {
      Taro.showToast({ title: c.agreeFirst, icon: "none" });
      return;
    }
    if (!aiDisclosed) {
      Taro.showToast({ title: c.needAiDisclose, icon: "none" });
      return;
    }
    if (!qcPassed) {
      Taro.showToast({ title: qcFixMessage(qc), icon: "none" });
      return;
    }
    const names = channels
      .map((code) => channelName(code, c.channels) || catalog.find((ch) => ch.code === code)?.name || code)
      .filter(Boolean)
      .join("、");
    const hasMetrics =
      catalog.some((ch) => channels.includes(ch.code) && ch.automation_level === "metrics_only") ||
      routePreview.some((row) => channels.includes(row.channel_code || "") && (row.automation_level === "metrics_only" || row.route === "metrics"));
    const confirmed = await confirmCreatorAction({
      title: c.confirmOnce,
      content: [
        c.confirmOnceHint,
        `${c.channelsSelected.replace("{n}", String(channels.length))}${names ? `：${names}` : ""}`,
        hasMetrics ? c.routePreviewMetrics : "",
      ]
        .filter(Boolean)
        .join("\n"),
      confirmText: c.confirmGo,
      cancelText: c.back,
    });
    if (!confirmed) return;
    setBusy(true);
    try {
      await vibeApi.updateRelease(releaseId, { ai_disclosed: true });
    } catch {
      /* submit still carries the attestation in the wizard */
    }
    let lastError = "";
    let ok = false;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        let result = (await vibeApi.autoSubmitRelease(releaseId, {
          consent: true,
          mode,
          title,
          artist_name: artist,
          isrc: isrc.trim() || undefined,
          selected_channels: channels,
          commission_rate: Number(rate),
        })) as {
          kit_url?: string;
          has_kit?: boolean;
          deliveries?: Array<{ channel_code?: string; status?: string; user_status?: string }>;
        };
        const accepted = (result.deliveries || []).length > 0;
        const stillSubmitting = (result.deliveries || []).some((d) => d.status === "submitting");
        if (!accepted || stillSubmitting) {
          result = (await waitForQueue(releaseId)) || result;
        }
        const n = (result.deliveries || []).length;
        if (n === 0) {
          lastError = c.submitRetrying;
          continue;
        }
        setKitUrl(result.kit_url || "");
        setReceipt(result.deliveries || []);
        setSubmitted(true);
        if (workId) {
          vibeApi
            .getRadioTrial(workId)
            .then((trial) => setRadioTrial(trial as typeof radioTrial))
            .catch(() => setRadioTrial(null));
        }
        Taro.showToast({ title: c.queuedChannels.replace("{n}", String(n)), icon: "success" });
        void sendPollToExtension();
        lastError = "";
        ok = true;
        break;
      } catch (err) {
        lastError = humanizeDeliveryError(String((err as Error)?.message || ""), c, copy.adminUi.actionFail) || copy.adminUi.actionFail;
      }
    }
    if (lastError && !ok) {
      Taro.showToast({ title: lastError, icon: "none" });
    }
    setBusy(false);
  }

  const qcPassed = Boolean(qc?.passed);
  const capGroups = useMemo(() => {
    const metrics = catalog.filter((x) => x.automation_level === "metrics_only");
    const rest = catalog.filter((x) => x.automation_level !== "metrics_only");
    const auto = rest.filter((x) => x.capability === "auto" || x.auto_default);
    const wait = rest.filter((x) => x.capability === "wait_connector");
    const link = rest.filter((x) => x.capability === "needs_link");
    return { auto, wait, link, metrics };
  }, [catalog]);

  const selectedNeeds = useMemo(() => {
    const selected = catalog.filter((ch) => channels.includes(ch.code));
    return {
      evidence: selected.some((ch) => ch.asset_profile?.needs_stems_evidence),
      clips: selected.some((ch) => ch.asset_profile?.needs_clips) || portals.length > 0,
      instrumental: selected.some((ch) => ch.asset_profile?.needs_instrumental),
    };
  }, [catalog, channels, portals.length]);

  const askedFields = useMemo(() => {
    const skip = new Set(["title", "artist_name", "cover_url", "ai_disclosed", "isrc"]);
    const order = ["lyrics", "language", "genres", "lyricist", "composer", "arranger", "producer", "featured_artists", "explicit", "copyright_line", "sound_recording_line", "label_name", "upc", "release_date", "territories", "price_minor"];
    const need = new Set<string>();
    for (const code of channels) {
      const row = catalog.find((item) => item.code === code);
      for (const field of row?.required_fields || []) {
        if (!skip.has(field)) need.add(field);
      }
    }
    return order.filter((field) => need.has(field));
  }, [catalog, channels]);

  const fieldLabel = (field: string) => {
    const zh: Record<string, string> = {
      lyrics: "歌词",
      language: "语种",
      genres: "流派，用逗号分开",
      lyricist: "作词",
      composer: "作曲",
      arranger: "编曲",
      producer: "制作人",
      featured_artists: "合作艺人",
      explicit: "内容分级",
      copyright_line: "词曲版权",
      sound_recording_line: "录音版权",
      label_name: "厂牌名",
      upc: "UPC",
      release_date: "发行日期",
      territories: "发行地区",
      price_minor: "售价，单位是分",
    };
    const en: Record<string, string> = {
      lyrics: "Lyrics",
      language: "Language",
      genres: "Genres, separated by commas",
      lyricist: "Lyricist",
      composer: "Composer",
      arranger: "Arranger",
      producer: "Producer",
      featured_artists: "Featured artists",
      explicit: "Explicit or clean",
      copyright_line: "Copyright line",
      sound_recording_line: "Sound recording line",
      label_name: "Label",
      upc: "UPC",
      release_date: "Release date",
      territories: "Territories",
      price_minor: "Price in minor units",
    };
    return (locale === "en" ? en : zh)[field] || field;
  };

  const selectedWork = works.find((w) => w.id === workId);
  const receiptBuckets = deliveryBuckets(receipt);
  const receiptUploadOnly = receiptBuckets.upload > 0 && receiptBuckets.login === 0;
  const receiptNeedLogin = receipt.some((d) => isWaitingLogin(d.status, d.user_status, d.last_error));
  const receiptWaitCta = sessionWaitCta(c, {
    weapp: process.env.TARO_ENV === "weapp",
    connectorOnline: process.env.TARO_ENV !== "weapp",
    waiting: receiptBuckets.login || 1,
  });
  const checkItems = [
    { key: "has_audio", label: c.qcHasAudio },
    { key: "duration_ok", label: c.qcDuration },
    { key: "loudness_ok", label: c.qcLoudness },
    { key: "originality_ok", label: c.qcOriginal },
    { key: "has_title", label: c.qcTitle },
    { key: "has_artist", label: c.qcArtist },
    { key: "has_cover", label: c.qcCover },
    { key: "ai_disclosed", label: c.qcAi },
  ];

  function toggleChannel(code: string) {
    const connectedCodes = (connections || [])
      .filter((row) => row.status === "settle" || row.status === "metrics")
      .map((row) => row.channel_code);
    if (shipChannelGroup(code) === "metrics" && !connectedCodes.includes(code)) {
      Taro.showToast({ title: c.shipMetricsNeedSeat, icon: "none" });
      return;
    }
    setChannels((prev) => {
      const nextCodes = prev.includes(code) ? prev.filter((x) => x !== code) : [...prev, code];
      void refreshLanes(nextCodes);
      return nextCodes;
    });
  }

  function renderChannelList(list: Array<{
    code: string;
    name: string;
    region: string;
    delivery_mode?: string;
    capability?: "auto" | "wait_connector" | "needs_link";
    sop?: string;
    automation_level?: string;
    asset_profile?: { needs_stems_evidence?: boolean; needs_clips?: boolean; needs_instrumental?: boolean };
  }>) {
    return (
      <View className="creator-channel-grid">
        {list.map((ch) => {
          const on = channels.includes(ch.code);
          const cap =
            ch.capability === "auto"
              ? c.channelCapAuto
              : ch.capability === "needs_link"
                ? c.channelCapLink
                : c.channelCapWait;
          return (
            <View
              key={ch.code}
              className={`creator-mode${on ? " creator-mode--on" : ""}${ch.automation_level === "metrics_only" ? " creator-mode--metrics" : ""}`}
              onClick={() => {
                Taro.vibrateShort({ type: "light" }).catch(() => undefined);
                toggleChannel(ch.code);
              }}
            >
              <View className="creator-mode__head">
                <ChannelMark code={ch.code} />
                <Text className="creator-mode__title">{channelName(ch.code, c.channels) || ch.name}</Text>
                {on ? <Text className="creator-mode__check">{c.channelPicked}</Text> : null}
              </View>
              <AssetChips
                evidence={Boolean(ch.asset_profile?.needs_stems_evidence)}
                clips={Boolean(ch.asset_profile?.needs_clips)}
                instrumental={Boolean(ch.asset_profile?.needs_instrumental)}
              />
              <Text className="creator-mode__desc">{cap}</Text>
              {ch.automation_level === "metrics_only" ? (
                <Text className="typo-meta">{c.routePreviewMetrics}</Text>
              ) : routePreview.some((row) => row.channel_code === ch.code && row.degraded) ? (
                <Text className="typo-meta">{c.routePreviewDegraded}</Text>
              ) : ch.automation_level === "connector_assist" ? (
                <Text className="typo-meta">{c.routePreviewAssist}</Text>
              ) : null}
            </View>
          );
        })}
      </View>
    );
  }

  if (credits && (credits as { dspDistribution?: boolean }).dspDistribution === false) {
    return (
      <PageShell title={c.goRelease} subtitle={c.hubSubtitle} ambient>
        <EmptyState
          iconName="sigil"
          title={c.featureOff}
          description={c.dataHint}
          actionLabel={c.goWallet}
          onAction={() => Taro.navigateTo({ url: creatorPage("wallet") })}
        />
      </PageShell>
    );
  }

  if (!workId) {
    return (
      <PageShell title={c.goRelease} subtitle={c.pickWorkHint} ambient>
        <View className="creator">
          <View className="creator-hero">
            <Text className="creator-hero__kicker">{c.goRelease}</Text>
            <Text className="creator-hero__title">{c.pickWork}</Text>
            <Text className="creator-hero__sub">{c.pickWorkHint}</Text>
          </View>
          <SectionLabel>{c.pickWork}</SectionLabel>
          {works.length === 0 && (
            <EmptyState iconName="music" title={c.noWork} description={c.emptyHub} actionLabel={c.goCreate} onAction={() => Taro.switchTab({ url: "/pages/create/index" })} />
          )}
          {works
            .filter((w) => Boolean(w.audio_url))
            .map((w) => {
            const targetId = releaseTargetId(w, works);
            const target = works.find((row) => row.id === targetId) || w;
            const publishing =
              ["queued", "delivering", "live"].includes(target.release_status || "") ||
              Number(target.live_stores) > 0;
            const retargeted = targetId !== w.id;
            return (
            <View
              key={w.id}
              className="creator-pick"
              onClick={() => {
                if (publishing) {
                  Taro.navigateTo({ url: creatorPage("deliveries", { workId: targetId }) });
                  return;
                }
                setWorkId(targetId);
                setTitle(target.title);
                setPreferMaster(retargeted || isWorkbenchMaster(target));
                setArtist((prev) => prev || target.artist_name || defaultArtist);
                Taro.vibrateShort({ type: "light" }).catch(() => undefined);
              }}
            >
              <View className="creator-pick__cover">
                {w.cover_url ? <Image className="creator-pick__cover-img" src={w.cover_url} mode="aspectFill" /> : null}
              </View>
              <View className="creator-pick__body">
                <Text className="creator-pick__title">{w.title}</Text>
                <Text className="creator-pick__meta">
                  {publishing
                    ? c.alreadyPublishing
                    : retargeted
                      ? c.releasePreferMaster
                      : isWorkbenchMaster(w)
                        ? copy.worksUi.beautifyMaster
                    : w.release_status
                      ? c.status[w.release_status as keyof typeof c.status] || w.release_status
                      : c.selectedWork}
                </Text>
              </View>
              {publishing && <Badge tone="warning">{c.viewProgress}</Badge>}
              {retargeted && !publishing ? <Badge tone="warning">{copy.worksUi.hasBeautifyMaster}</Badge> : null}
              {isWorkbenchMaster(w) && !publishing ? <Badge tone="accent">{copy.worksUi.beautifyMaster}</Badge> : null}
            </View>
            );
          })}
        </View>
      </PageShell>
    );
  }

  return (
    <PageShell title={c.goRelease} subtitle={selectedWork?.title || c.selectedWork} ambient>
      <View className="creator">
        <WeappH5Bridge path={`${CREATOR_PAGE_ROUTES.release}?workId=${encodeURIComponent(workId)}`} />
        {weapp ? <StatusLine tone="info" density="quiet">{c.weappDeskHint}</StatusLine> : null}
        <StatusLine tone="info" density="quiet">{c.storeNotDiscover}</StatusLine>
        {workId ? (
          <ShipCompleteCard
            workId={workId}
            surface="desk"
            embedAuth
            weapp={weapp}
          />
        ) : null}
        {(credits as { dspDistribution?: boolean } | null)?.dspDistribution === false ? <StatusLine tone="info">{c.featureOff}</StatusLine> : null}
        {preferMaster ? <StatusLine tone="info">{c.releasePreferMaster}</StatusLine> : null}
        <StepRail steps={steps} current={step} />
        {autoReady && !submitted && step === 1 ? <StatusLine tone="success">{c.qcDraftHint}</StatusLine> : null}

        {selectedWork && (
          <View className="creator-workchip">
            {selectedWork.cover_url ? (
              <Image className="creator-workchip__cover" src={selectedWork.cover_url} mode="aspectFill" />
            ) : (
              <View className="creator-workchip__dot" />
            )}
            <Text className="creator-workchip__title">{selectedWork.title || title}</Text>
          </View>
        )}
        {skuKind === "instrumental" ? <Text className="typo-meta">{c.instrumentalSkuBanner}</Text> : null}

        {step === 0 && (
          <>
            <View className="creator-card">
              <SectionLabel>{c.qcChecks}</SectionLabel>
              {qc && <StatusLine tone={qcPassed ? "success" : "error"}>{qcPassed ? c.qcPass : qcFixMessage(qc)}</StatusLine>}
              {checkItems.map((item) => {
                const ok = item.key === "ai_disclosed" ? Boolean(aiDisclosed && qc?.checks?.[item.key]) : qc?.checks?.[item.key];
                return (
                  <View key={item.key} className={ok ? "creator-check creator-check--ok" : qc && item.key !== "has_cover" ? "creator-check creator-check--fail" : "creator-check"}>
                    <Text className="creator-check__label">{item.label}</Text>
                    <Badge tone={ok ? "success" : qc ? (item.key === "has_cover" ? "accent" : "danger") : "accent"}>
                      {ok ? "OK" : qc ? "—" : "…"}
                    </Badge>
                  </View>
                );
              })}
              {Array.isArray((qc as { metadata_gaps?: { label?: string }[] } | null)?.metadata_gaps) &&
              (qc as { metadata_gaps: { label?: string }[] }).metadata_gaps.length ? (
                <Text className="typo-meta">
                  {(qc as { metadata_gaps: { label?: string }[] }).metadata_gaps.map((row) => row.label).filter(Boolean).join("、")}
                  {" 还要补。各店清单还在核对，先不拦住提交。"}
                </Text>
              ) : null}
              {(!qc?.checks?.has_cover || !selectedWork?.cover_url) && (
                <Button size="sm" variant="secondary" block onClick={() => void uploadCover()}>
                  {c.qcCoverUpload}
                </Button>
              )}
              <ConsentCheckbox checked={aiDisclosed} onChange={setAiDisclosed}>
                {c.aiDisclose}
              </ConsentCheckbox>
            </View>
            <Collapsible label={c.beatSongMeta} storageKey="release-beat0-meta">
              <ModeTileGrid
                layout="rail"
                activeId={mode}
                onSelect={(id) => setMode(id as "label" | "self_release")}
                items={[
                  { id: "label", icon: "sigil", title: c.modeB, description: c.modeBDesc, accent: true },
                  { id: "self_release", icon: "grimoire", title: c.modeA, description: c.modeADesc },
                ]}
              />
              <View className="creator-card">
                <Input label={c.metaTitle} value={title} maxlength={80} onInput={(e) => setTitle(e.detail.value)} />
                <Input label={c.metaArtist} value={artist} maxlength={80} hint={c.artistPlaceholder} onInput={(e) => setArtist(e.detail.value)} />
                <Input label={c.metaIsrc} value={isrc} maxlength={15} hint={c.trackCodeAuto} onInput={(e) => setIsrc(e.detail.value)} />
              </View>
            </Collapsible>
            <Button variant="ghost" size="sm" onClick={() => setWorkId("")}>
              {c.changeWork}
            </Button>
          </>
        )}

        {step === 1 && (
          <View className="creator-card">
            {catalogError ? (
              <>
                <StatusLine tone="error">{c.catalogLoadFail}</StatusLine>
                <Button size="sm" variant="secondary" block loading={busy} onClick={() => void loadCatalog()}>
                  {c.retry}
                </Button>
              </>
            ) : null}
            {channelSuggest?.reason ? (
              <>
                <Text className="creator-pick__title">{c.suggestedShipTitle}</Text>
                <Text className="creator-pick__meta">{channelSuggest.reason}</Text>
                <Text className="typo-meta">{c.coverageOrderHint}</Text>
                {(channelSuggest.channels || []).length > 0 ? (
                  <View className="creator-next__chips">
                    {(channelSuggest.channels || []).map((code) => (
                      <Text key={code} className="creator-next__chip">
                        {channelName(code, c.channels)}
                      </Text>
                    ))}
                  </View>
                ) : (
                  <StatusLine tone="info" density="quiet">{c.suggestedShipEmpty}</StatusLine>
                )}
                {(channelSuggest.channels || []).length > 0 && (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => {
                      const nextCodes = (channelSuggest.channels || []).filter((code) => shipChannelGroup(code) !== "metrics");
                      setChannels(nextCodes.length ? nextCodes : channels);
                      void refreshLanes(nextCodes.length ? nextCodes : channels);
                    }}
                  >
                    {c.applySuggestedChannels}
                  </Button>
                )}
                {(channelSuggest.blocked || []).length > 0 ? (
                  <Text className="typo-meta">{c.suggestedShipBlocked}</Text>
                ) : null}
              </>
            ) : (
              <Text className="typo-meta">{c.storesPickHint}</Text>
            )}
            <Text className="typo-meta">{c.channelsSelected.replace("{n}", String(channels.length))}</Text>
            {channels.length > 0 ? (
              <AssetLanes
                status={assetStatus}
                density="compact"
                skuKind={skuKind}
                forceEvidence={selectedNeeds.evidence}
                forceClips={selectedNeeds.clips}
                forceInstrumental={selectedNeeds.instrumental || skuKind === "instrumental"}
                spawningInstrumental={spawningInstrumental}
                onSpawnInstrumental={
                  workId
                    ? () => {
                        void (async () => {
                          setSpawningInstrumental(true);
                          try {
                            const res = await vibeApi.spawnInstrumentalSku(workId);
                            Taro.showToast({ title: copy.lightEditorUi.instrumentalSkuOk, icon: "success" });
                            if (res.work_id) {
                              const updated = (await vibeApi.updateRelease(releaseId, { selected_channels: channels })) as ReleasePayload;
                              if (updated?.asset_status) setAssetStatus(updated.asset_status);
                            }
                          } catch {
                            Taro.showToast({ title: copy.lightEditorUi.instrumentalSkuFail, icon: "none" });
                          } finally {
                            setSpawningInstrumental(false);
                          }
                        })();
                      }
                    : undefined
                }
              />
            ) : null}
            <Collapsible label={c.allChannelsDoor} defaultOpen={false}>
              <View className="creator-actions">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setChannels([]);
                    void refreshLanes([]);
                  }}
                >
                  {c.clearAll}
                </Button>
              </View>
              {capGroups.auto.length > 0 && <SectionLabel>{c.channelAutoGroup}</SectionLabel>}
              {renderChannelList(capGroups.auto)}
              {capGroups.wait.length > 0 ? (
                <Collapsible label={c.channelWaitGroup} defaultOpen={false}>
                  {renderChannelList(capGroups.wait)}
                </Collapsible>
              ) : null}
              {capGroups.link.length > 0 ? (
                <Collapsible label={c.channelLinkGroup} defaultOpen={false}>
                  {renderChannelList(capGroups.link)}
                </Collapsible>
              ) : null}
              {capGroups.metrics.length > 0 ? (
                <Collapsible label={c.shipMetricsGroup} defaultOpen={false}>
                  <Text className="typo-meta">{c.routePreviewMetrics}</Text>
                  {renderChannelList(capGroups.metrics)}
                </Collapsible>
              ) : null}
              {portals.length > 0 && (
                <>
                  <SectionLabel>{c.clipLaneTitle}</SectionLabel>
                  <StatusLine tone="info" density="quiet">{c.portalClipHint}</StatusLine>
                  {portals.map((p) => (
                    <View key={p.code} className="creator-check">
                      <Text className="creator-check__label">{channelName(p.code, c.channels) || p.name}</Text>
                      <Badge tone="accent">{c.clipPack}</Badge>
                    </View>
                  ))}
                </>
              )}
            </Collapsible>
            {askedFields.length > 0 ? (
              <View className="creator-card">
                <SectionLabel>{locale === "en" ? "What these stores need" : "这些店要的资料"}</SectionLabel>
                <Text className="typo-meta">
                  {locale === "en"
                    ? "Fill what the selected stores ask for. The checklist is still being checked, so this does not block submit."
                    : "按你勾的店来填。清单还在核对，先不拦住提交。"}
                </Text>
                {askedFields.includes("lyrics") ? (
                  <Text className={listing.instrumental === "1" ? "creator-check creator-check--ok" : "creator-check"} onClick={() => setListing((prev) => ({ ...prev, instrumental: prev.instrumental === "1" ? "" : "1" }))}>
                    {locale === "en" ? "Instrumental, no lyrics" : "纯音乐，没有歌词"}
                  </Text>
                ) : null}
                {askedFields.includes("lyrics") && listing.instrumental !== "1" ? (
                  <Textarea
                    className="creator-input"
                    value={listing.lyrics || ""}
                    maxlength={4000}
                    placeholder={fieldLabel("lyrics")}
                    onInput={(e) => setListing((prev) => ({ ...prev, lyrics: e.detail.value }))}
                  />
                ) : null}
                {askedFields.filter((field) => field !== "lyrics").map((field) => (
                  <Input
                    key={field}
                    label={fieldLabel(field)}
                    value={listing[field] || ""}
                    maxlength={field === "genres" ? 120 : 200}
                    onInput={(e) => setListing((prev) => ({ ...prev, [field]: e.detail.value }))}
                  />
                ))}
              </View>
            ) : null}
          </View>
        )}

        {step === 2 && !submitted && (
          <View className="creator-card">
            <View className="creator-summary">
              <Text className="creator-hero__kicker">{c.recapTitle}</Text>
              <View className="creator-summary__row">
                <Text className="creator-summary__k">{c.metaTitle}</Text>
                <Text className="creator-summary__v">{title || c.releaseUntitled}</Text>
              </View>
              <View className="creator-summary__row">
                <Text className="creator-summary__k">{c.metaArtist}</Text>
                <Text className="creator-summary__v">{artist || "—"}</Text>
              </View>
              <View className="creator-summary__row">
                <Text className="creator-summary__k">{c.stepMode}</Text>
                <Text className="creator-summary__v">{mode === "label" ? c.modeB : c.modeA}</Text>
              </View>
              {mode === "label" && (
                <View className="creator-summary__row">
                  <Text className="creator-summary__k">{c.splitTake}</Text>
                  <Text className="creator-summary__v">{`${rate}%`}</Text>
                </View>
              )}
              <View className="creator-summary__row">
                <Text className="creator-summary__k">{c.stepChannels}</Text>
                <Text className="creator-summary__v">{c.recapChannels.replace("{n}", String(channels.length))}</Text>
              </View>
              {askedFields.map((field) => (
                <View key={field} className="creator-summary__row">
                  <Text className="creator-summary__k">{fieldLabel(field)}</Text>
                  <Text className="creator-summary__v">
                    {field === "lyrics" && listing.instrumental === "1" ? (locale === "en" ? "Instrumental" : "纯音乐") : listing[field] || "—"}
                  </Text>
                </View>
              ))}
            </View>
            <AssetLanes
              status={assetStatus}
              density="full"
              skuKind={skuKind}
              forceEvidence={selectedNeeds.evidence}
              forceClips={selectedNeeds.clips}
              forceInstrumental={selectedNeeds.instrumental || skuKind === "instrumental"}
              onDownloadOriginality={workId && assetStatus?.evidence?.ready ? () => void saveOriginalityPack(workId, c) : undefined}
              onDownloadClips={workId && selectedNeeds.clips && assetStatus?.clips?.ready ? () => void saveClipPack(workId, c) : undefined}
              spawningInstrumental={spawningInstrumental}
              onSpawnInstrumental={
                workId
                  ? () => {
                      void (async () => {
                        setSpawningInstrumental(true);
                        try {
                          await vibeApi.spawnInstrumentalSku(workId);
                          Taro.showToast({ title: copy.lightEditorUi.instrumentalSkuOk, icon: "success" });
                        } catch {
                          Taro.showToast({ title: copy.lightEditorUi.instrumentalSkuFail, icon: "none" });
                        } finally {
                          setSpawningInstrumental(false);
                        }
                      })();
                    }
                  : undefined
              }
            />
            {mode === "label" && (
              <>
                <ChipGroup
                  options={[
                    { value: "10", label: c.rate10 },
                    { value: "20", label: c.rate20 },
                    { value: "30", label: c.rate30 },
                  ].filter((opt) => allowedRates.includes(Number(opt.value)))}
                  value={rate}
                  onChange={setRate}
                />
                {allowedRates[0] > 10 ? (
                  <StatusLine tone="info">{c.rateLocked.replace("{n}", String(allowedRates[0]))}</StatusLine>
                ) : null}
              </>
            )}
            {weapp ? (
              <StatusLine tone="info">{c.weappDeskHint}</StatusLine>
            ) : (
              <>
                <StatusLine tone="info">{busy ? c.submitRetrying : c.submitHint}</StatusLine>
                <ConsentCheckbox
                  checked={agreed}
                  onChange={setAgreed}
                  links={[{ label: legalDocLabel(copy.legalUi.distributionLicense, locale), route: LEGAL_ROUTES.distributionLicense }]}
                >
                  {copy.legalUi.agreePrefix}
                </ConsentCheckbox>
              </>
            )}
          </View>
        )}

        {step === 2 && submitted && (
          <View className="creator-receipt">
            <StatusLine tone="success">{mode === "self_release" ? c.submittedSelfStay : c.submittedStay}</StatusLine>
            {receipt.length > 0 && (
              <>
                <View className="creator-metrics creator-metrics--quad">
                  <View className="creator-stat">
                    <Text className="creator-stat__n">{receiptBuckets.pushing}</Text>
                    <Text className="creator-stat__l">{c.bucketPushing}</Text>
                  </View>
                  <View className={`creator-stat ${receiptBuckets.login ? "creator-stat--hot" : ""}`}>
                    <Text className="creator-stat__n">{receiptBuckets.login}</Text>
                    <Text className="creator-stat__l">{c.bucketLogin}</Text>
                  </View>
                  <View className={`creator-stat ${receiptBuckets.upload ? "creator-stat--hot" : ""}`}>
                    <Text className="creator-stat__n">{receiptBuckets.upload}</Text>
                    <Text className="creator-stat__l">{c.bucketUpload}</Text>
                  </View>
                  <View className="creator-stat">
                    <Text className="creator-stat__n">{receiptBuckets.live}</Text>
                    <Text className="creator-stat__l">{c.bucketLive}</Text>
                  </View>
                </View>
                <ChannelTimeline
                  deliveries={receipt.map((d, i) => ({
                    id: String(i),
                    channel_code: d.channel_code || "",
                    status: d.status || "submitting",
                    user_status: d.user_status,
                  }))}
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
                <SectionLabel>{c.queuedChannels.replace("{n}", String(receipt.length))}</SectionLabel>
                {receipt.map((d, idx) => (
                  <View key={`${d.channel_code || "ch"}-${idx}`} className="creator-check">
                    <View className="creator-channel__head">
                      <View
                        className={`creator-channel__pip ${
                          isLiveDelivery(d)
                            ? "creator-channel__pip--live"
                            : d.status === "rejected"
                              ? "creator-channel__pip--warn"
                              : isStoreAssist(d.status, d.user_status)
                                ? "creator-channel__pip--warn"
                                : "creator-channel__pip--mute"
                        }`}
                      />
                      <Text className="creator-check__label">{channelName(d.channel_code || "", c.channels) || d.channel_code}</Text>
                    </View>
                    <Badge tone={statusTone(d.user_status || d.status)}>
                      {statusLabel(d.user_status || d.status || "", c.status)}
                    </Badge>
                  </View>
                ))}
              </>
            )}
            {receiptNeedLogin && !workId ? (
              <AuthDesk
                connections={connections}
                weapp={weapp}
                onChanged={() =>
                  void vibeApi
                    .getCreatorHub()
                    .then((hub) => setConnections(((hub as { connections?: ConnectionCard[] }).connections || []) as ConnectionCard[]))
                    .catch(() => null)
                }
              />
            ) : null}
            {receipt.some((d) => isStoreAssist(d.status, d.user_status, d.last_error)) ? (
              <NextActionCard
                kicker={c.waitingNow}
                title={receiptNeedLogin ? receiptWaitCta.title : receiptUploadOnly ? c.nextStoresUpload : c.machineUploading}
                hint={receiptNeedLogin ? receiptWaitCta.hint : receiptUploadOnly ? c.nextStoresUploadHint : c.machineUploadingHint}
                go={c.nextGo}
                urgent
                onClick={() => Taro.navigateTo({ url: creatorPage(receiptNeedLogin ? "accounts" : "deliveries") })}
              />
            ) : null}
            {radioTrial?.live ? (
              <NextActionCard
                kicker={c.radioTrialTitle}
                title={c.radioTrialLive}
                hint={radioTrial.station ? `${c.radioTrialHint} · ${radioTrial.station}` : c.radioTrialHint}
                go={c.goRadio}
                onClick={() => Taro.navigateTo({ url: socialPage("radio", { workId }) })}
              />
            ) : null}
            {radioTrial?.status === "ended" ? (
              <NextActionCard
                kicker={c.radioTrialTitle}
                title={c.trialEndedRelease}
                hint={radioTrial.channel_suggestion?.reason || c.applySuggestedChannels}
                go={c.nextGo}
                onClick={() => {
                  const suggested = (radioTrial.channel_suggestion?.channels || []).filter(
                    (code) => shipChannelGroup(code) !== "metrics",
                  );
                  if (suggested.length) setChannels(suggested);
                  Taro.navigateTo({ url: creatorPage("deliveries", { releaseId, workId }) });
                }}
              />
            ) : null}
            {mode === "self_release" || kitUrl ? (
              <>
                <Text className="creator-wait">{c.kitReady}</Text>
                <Button
                  variant="secondary"
                  block
                  loading={busy}
                  onClick={() => {
                    void (async () => {
                      setBusy(true);
                      try {
                        await saveReleaseKit(releaseId, c);
                      } catch {
                        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                      } finally {
                        setBusy(false);
                      }
                    })();
                  }}
                >
                  {c.kitShare}
                </Button>
              </>
            ) : (
              <>
                <StatusLine tone="info">{c.noKitYet}</StatusLine>
                <Button
                  size="sm"
                  variant="secondary"
                  block
                  loading={busy}
                  onClick={() => {
                    void (async () => {
                      setBusy(true);
                      try {
                        const latest = (await vibeApi.getRelease(releaseId)) as { kit_url?: string };
                        if (latest.kit_url) setKitUrl(latest.kit_url);
                        else await saveReleaseKit(releaseId, c);
                      } catch {
                        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                      } finally {
                        setBusy(false);
                      }
                    })();
                  }}
                >
                  {c.kitShare}
                </Button>
              </>
            )}
          </View>
        )}

        <View className="creator-footer creator-dock">
          {step > 0 && !submitted && (
            <Button variant="secondary" onClick={() => setStep((s) => Math.max(0, s - 1))}>
              {c.back}
            </Button>
          )}
          <View className="creator-footer__main">
            {submitted ? (
              <Button
                variant="primary"
                block
                onClick={() => Taro.navigateTo({ url: creatorPage("deliveries", { releaseId, workId }) })}
              >
                {c.goSeeDeliveries}
              </Button>
            ) : weapp && step >= 2 ? (
              <Button
                variant="primary"
                block
                onClick={() => void copyWeappCreatorLink(creatorPage("release", { workId }))}
              >
                {c.weappGoRelease}
              </Button>
            ) : step < 2 ? (
              <Button variant="primary" block loading={busy} onClick={() => void next()}>
                {step === 0 && !qc ? c.runQc : c.nextStep}
              </Button>
            ) : (
              <Button variant="primary" block loading={busy} onClick={() => void submit()}>
                {autoReady ? c.confirmOnce : mode === "label" ? c.submitRelease : c.submitSelfRelease}
              </Button>
            )}
            {step >= 2 && (routePreview.length > 0 || channels.length > 0) ? (
              <View className="creator-route-chips">
                {(routePreview.length ? routePreview : channels.map((code) => ({ channel_code: code, route: "connector" }))).map((row) => {
                  const name = channelName(row.channel_code || "", c.channels);
                  return (
                    <Text
                      key={`${row.channel_code || "ch"}-${row.route || "connector"}`}
                      className={`creator-chip ${row.automation_level === "metrics_only" || row.route === "metrics" ? "creator-chip--aggregator" : "creator-chip--session"}`}
                    >
                      {name} · {routePreviewLabel(row, c)}
                    </Text>
                  );
                })}
              </View>
            ) : null}
          </View>
        </View>
      </View>
    </PageShell>
  );
}
