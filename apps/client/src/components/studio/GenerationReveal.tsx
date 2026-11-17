import { useEffect, useRef, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { vibeApi } from "../../services/api";
import { commercePage, creatorPage, socialPage, studioPage, openLibrary } from "../../constants/routes";
import { openRadioPage, openStackPage } from "../../utils/navigation";
import { isWorkVersionConflict } from "@vibe-sorcery/api-client";
import { usePlayer } from "../../contexts/PlayerProvider";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { Button, Icon, Input } from "../ui";
import { AiGeneratedBadge } from "../legal/AiGeneratedBadge";
import { isQcReady, isReleaseInFlight } from "../../packageCreator/quickReleaseAction";
import { startRemelt, startSameStyle } from "../../utils/sameStyleNav";
import { isDesktopWorkbench, openWorkbench } from "../../utils/workbenchNav";
import { pickAndUploadCover } from "../../platform/upload";
import { isGenericWorkTitle } from "../../utils/workTitle";
import { isPostProcessDegraded } from "../../utils/postProcess";
import { needsBeautifyMaster } from "../../utils/workbenchWorks";
import { hapticLight } from "../../utils/haptic";
import { PublishDialog } from "../community/PublishDialog";
import { syncAfterFeedMutation } from "../../utils/feedMutationSync";
import { ShipCompleteCard } from "../../packageCreator/ShipCompleteCard";
import "./GenerationReveal.scss";

type Props = {
  workId: string;
  title?: string;
  coverUrl?: string;
  moods?: string[];
  clipsPrimary?: boolean;
  onDismiss?: () => void;
  onTitleChange?: (title: string) => void;
  fromWorkbench?: boolean;
  sourceWorkId?: string;
};

export function GenerationReveal({
  workId,
  title,
  coverUrl,
  moods = [],
  onDismiss,
  onTitleChange,
  fromWorkbench = false,
  sourceWorkId,
}: Props) {
  const { copy, locale } = useLocale();
  const r = copy.generation.reveal;
  const { playTrack, stop } = usePlayer();
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewingId = useRef("");
  const creditsCtx = useCreditsOptional();
  const [compact, setCompact] = useState(false);
  const [resolvedCover, setResolvedCover] = useState(coverUrl || "");
  const [resolvedTitle, setResolvedTitle] = useState(title || "");
  const [artistName, setArtistName] = useState("");
  const [workVersion, setWorkVersion] = useState<number | undefined>(undefined);
  const [editingTitle, setEditingTitle] = useState(false);
  const [savingTitle, setSavingTitle] = useState(false);
  const [qcReady, setQcReady] = useState(false);
  const [releaseStatus, setReleaseStatus] = useState("");
  const [uploadingCover, setUploadingCover] = useState(false);
  const [radioBusy, setRadioBusy] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [degraded, setDegraded] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [heard, setHeard] = useState(false);
  const [skuKind, setSkuKind] = useState("");
  const [winner, setWinner] = useState(false);
  const [supersededBy, setSupersededBy] = useState("");
  const [benchMaster, setBenchMaster] = useState(fromWorkbench);
  const [suggestions, setSuggestions] = useState<
    Array<{ id: string; title: string; slug?: string | null; locale_titles?: Record<string, string>; preview_url?: string | null }>
  >([]);
  const [suggestNeeds, setSuggestNeeds] = useState<string[]>([]);
  const [previewBusy, setPreviewBusy] = useState("");
  const [publishOpen, setPublishOpen] = useState(false);

  useEffect(() => {
    setCompact(false);
    setBenchMaster(fromWorkbench);
  }, [workId, fromWorkbench]);

  useEffect(() => {
    if (title) setResolvedTitle(title);
    if (coverUrl) setResolvedCover(coverUrl);
    vibeApi.getWork(workId).then((w) => {
      const nextTitle = title || w.title;
      if (!title) setResolvedTitle(w.title);
      if (!coverUrl && w.cover_url) setResolvedCover(w.cover_url);
      if (w.version != null) setWorkVersion(w.version);
      setArtistName(w.artist_name || w.owner_username || "");
      setQcReady(isQcReady((w as { release_status?: string }).release_status));
      setReleaseStatus((w as { release_status?: string }).release_status || "");
      setDegraded(isPostProcessDegraded(w.post_process_status));
      const pps = w.post_process_status as { sku_kind?: string } | undefined;
      setSkuKind(String(pps?.sku_kind || ""));
      const reason = String((w as { priority?: { reason?: string } }).priority?.reason || "");
      setWinner(reason === "duel_winner" || reason === "challenge_winner");
      setSupersededBy(String((w as { superseded_by_work_id?: string | null }).superseded_by_work_id || ""));
      setBenchMaster(Boolean((w as { from_workbench?: boolean }).from_workbench) || fromWorkbench);
      if (isGenericWorkTitle(nextTitle)) {
        const tags = (w.moods?.length ? w.moods : moods).slice(0, 2).join(" · ");
        if (tags) {
          void vibeApi.updateWork(workId, { title: tags, expectedVersion: w.version }).then((updated) => {
            setResolvedTitle(updated.title);
            setWorkVersion(updated.version);
            onTitleChange?.(updated.title);
          }).catch(() => {});
        }
      }
    }).catch(() => {});
  }, [workId, title, coverUrl]);

  useEffect(() => {
    if ((qcReady || isReleaseInFlight(releaseStatus)) && !degraded) return undefined;
    let ticks = 0;
    const timer = setInterval(() => {
      ticks += 1;
      vibeApi
        .getWork(workId)
        .then((w) => {
          const status = (w as { release_status?: string }).release_status || "";
          setQcReady(isQcReady(status));
          setReleaseStatus(status);
          setDegraded(isPostProcessDegraded(w.post_process_status));
        })
        .catch(() => {});
      if (ticks >= 8) clearInterval(timer);
    }, 4000);
    return () => clearInterval(timer);
  }, [workId, qcReady, releaseStatus, degraded]);

  useEffect(() => {
    if (!heard || fromWorkbench) return;
    vibeApi
      .suggestEffectPacks(workId, process.env.TARO_ENV === "weapp" ? "weapp" : "h5")
      .then((rows) => {
        setSuggestions(rows.slice(0, 3));
        const needs = Array.from(
          new Set(rows.flatMap((row) => [...(row.suggested_needs || []), ...(row.need_tags || [])])),
        ).slice(0, 3);
        setSuggestNeeds(needs);
      })
      .catch(() => {
        setSuggestions([]);
        setSuggestNeeds([]);
      });
  }, [heard, workId, fromWorkbench]);

  useEffect(() => {
    return () => {
      if (previewTimer.current) clearTimeout(previewTimer.current);
    };
  }, []);

  async function previewSuggest(pack: { id: string; title: string; locale_titles?: Record<string, string>; preview_url?: string | null }) {
    setPreviewBusy(pack.id);
    try {
      let url = pack.preview_url || "";
      if (!url) {
        const queued = await vibeApi.previewEffectPack(pack.id);
        url = queued.preview_url || "";
        if (!url && queued.job_id) {
          for (let i = 0; i < 20; i += 1) {
            await new Promise((resolve) => setTimeout(resolve, 1200));
            const job = await vibeApi.getJob(queued.job_id);
            url = ((job.result as { preview_url?: string } | null)?.preview_url) || "";
            if (url || job.status === "failed" || job.status === "cancelled") break;
            if (job.status === "audio_ready" || job.status === "completed") {
              url = url || (await vibeApi.previewEffectPack(pack.id)).preview_url || "";
              break;
            }
          }
        }
      }
      if (!url) {
        Taro.showToast({ title: copy.workbenchUi.applyFail, icon: "none" });
        return;
      }
      const previewId = `pack-preview-${pack.id}`;
      previewingId.current = previewId;
      playTrack(
        workToPlayerTrack({
          id: previewId,
          title: pack.locale_titles?.zh || pack.title,
          audio_url: url,
          cover_url: resolvedCover,
        }),
      );
      if (previewTimer.current) clearTimeout(previewTimer.current);
      previewTimer.current = setTimeout(() => {
        if (previewingId.current === previewId) {
          stop();
          previewingId.current = "";
        }
      }, 3000);
    } catch {
      Taro.showToast({ title: copy.workbenchUi.applyFail, icon: "none" });
    } finally {
      setPreviewBusy("");
    }
  }

  async function saveTitle(nextTitle: string) {
    const trimmed = nextTitle.trim();
    if (!trimmed || trimmed === resolvedTitle) {
      setEditingTitle(false);
      return;
    }
    setSavingTitle(true);
    try {
      const updated = await vibeApi.updateWork(workId, { title: trimmed, expectedVersion: workVersion });
      setResolvedTitle(updated.title);
      setWorkVersion(updated.version);
      onTitleChange?.(updated.title);
      Taro.showToast({ title: r.titleSaved, icon: "success" });
    } catch (err) {
      if (isWorkVersionConflict(err)) {
        try {
          const fresh = await vibeApi.getWork(workId);
          setResolvedTitle(fresh.title);
          if (fresh.version != null) setWorkVersion(fresh.version);
          Taro.showToast({ title: copy.generation.workVersionConflict, icon: "none" });
        } catch {
          Taro.showToast({ title: r.titleSaveFail, icon: "none" });
        }
      } else {
        Taro.showToast({ title: r.titleSaveFail, icon: "none" });
      }
    } finally {
      setSavingTitle(false);
      setEditingTitle(false);
    }
  }

  async function uploadCoverNow() {
    setUploadingCover(true);
    try {
      Taro.showLoading({ title: copy.worksUi.coverUploading, mask: true });
      await pickAndUploadCover(workId);
      Taro.hideLoading();
      const w = await vibeApi.getWork(workId);
      if (w.cover_url) setResolvedCover(w.cover_url);
      Taro.showToast({ title: copy.worksUi.coverUploaded, icon: "success" });
    } catch {
      Taro.hideLoading();
      Taro.showToast({ title: copy.worksUi.coverUploadFail, icon: "none" });
    } finally {
      setUploadingCover(false);
    }
  }

  async function playNow() {
    hapticLight();
    setHeard(true);
    const w = await vibeApi.getWork(workId);
    playTrack(workToPlayerTrack(w, { source: "generation", isOwner: true }), { navigate: true });
  }

  async function collect() {
    try {
      await vibeApi.collectWork(workId);
      Taro.showToast({ title: r.collectSuccess, icon: "success" });
    } catch {
      Taro.showToast({ title: r.collectFail, icon: "none" });
    }
  }

  function startRadioNow() {
    setRadioBusy(true);
    openRadioPage({ workId });
    void vibeApi
      .startRadioTrial(workId)
      .then((trial) => {
        Taro.showToast({ title: copy.creatorUi.radioTrialLive, icon: "success" });
        const next = (trial as { work_id?: string }).work_id;
        if (next && next !== workId) openRadioPage({ workId: next });
      })
      .catch(() => {
        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
      })
      .finally(() => setRadioBusy(false));
  }

  async function fixPostProcess() {
    if (reprocessing) return;
    setReprocessing(true);
    hapticLight();
    try {
      await vibeApi.reprocessWork(workId).catch(() => vibeApi.triggerPostProcess(workId));
      Taro.showToast({ title: copy.worksUi.reprocessQueued, icon: "success" });
      /* keep degraded until poll confirms recovery */
    } catch {
      Taro.showToast({ title: copy.worksUi.reprocessFail, icon: "none" });
    } finally {
      setReprocessing(false);
    }
  }

  const benchId = fromWorkbench ? sourceWorkId || workId : workId;
  const rawTake = needsBeautifyMaster({ from_workbench: benchMaster, superseded_by_work_id: supersededBy || null });
  const showMixer = process.env.TARO_ENV === "h5" && isDesktopWorkbench();

  return (
    <View className={compact ? "gen-reveal gen-reveal--compact" : "gen-reveal"}>
      <View className="gen-reveal__card">
        <View
          className="gen-reveal__cover-wrap"
          onClick={(e) => {
            e.stopPropagation();
            if (resolvedCover) {
              void playNow();
              return;
            }
            void uploadCoverNow();
          }}
        >
          {resolvedCover ? (
            <Image className="gen-reveal__cover" src={resolvedCover} mode="aspectFill" />
          ) : (
            <View className="gen-reveal__cover gen-reveal__cover--placeholder">
              <Text className="gen-reveal__cover-hint">{copy.worksUi.coverUpload}</Text>
            </View>
          )}
          {resolvedCover ? (
            <View className="gen-reveal__cover-play">
              <Icon name="play" size="sm" tone="dark" />
              <Text className="gen-reveal__cover-play-label">{r.play}</Text>
            </View>
          ) : null}
        </View>
        <View className="gen-reveal__body">
          <AiGeneratedBadge
            className="gen-reveal__ai-badge"
            prominent={!compact}
            compact={compact}
          />
          {!compact && <Text className="gen-reveal__eyebrow">{r.title}</Text>}
          {editingTitle ? (
            <Input
              className="gen-reveal__title-input"
              value={resolvedTitle}
              maxlength={60}
              focus
              onInput={(e) => setResolvedTitle(e.detail.value)}
              onBlur={() => void saveTitle(resolvedTitle)}
              onConfirm={() => void saveTitle(resolvedTitle)}
            />
          ) : (
            <View
              className="gen-reveal__title-row"
              onClick={(e) => {
                e.stopPropagation();
                setEditingTitle(true);
              }}
            >
              <Text className="gen-reveal__title">{resolvedTitle || "—"}</Text>
              <Text className="gen-reveal__title-edit">{r.titleEdit}</Text>
            </View>
          )}
          {artistName ? <Text className="gen-reveal__artist">@{artistName}</Text> : null}
          {savingTitle && <Text className="gen-reveal__title-saving typo-meta">{r.titleEdit}…</Text>}
          {!compact && r.nextHint ? <Text className="gen-reveal__subtitle">{r.nextHint}</Text> : null}
          {moods.length > 0 && (
            <Text className="gen-reveal__moods">{moods.slice(0, 3).join(" · ")}</Text>
          )}
          {heard && supersededBy && !fromWorkbench ? (
            <Text className="typo-meta">{copy.workbenchUi.hasMasterHint}</Text>
          ) : null}
          {degraded ? (
            <View className="gen-reveal__degraded" onClick={(e) => e.stopPropagation()}>
              <Text className="gen-reveal__degraded-text">{copy.generation.postProcessDegraded}</Text>
              <Button variant="secondary" size="sm" loading={reprocessing} onClick={() => void fixPostProcess()}>
                {copy.generation.postProcessFix}
              </Button>
            </View>
          ) : null}
          <View className="gen-reveal__actions" onClick={(e) => e.stopPropagation()}>
            {degraded ? (
              <Button variant="primary" loading={reprocessing} onClick={() => void fixPostProcess()}>
                {copy.generation.postProcessFix}
              </Button>
            ) : rawTake ? (
              <Button variant="primary" onClick={() => openWorkbench(benchId)}>
                {r.beautify}
              </Button>
            ) : (
              <Button variant="primary" onClick={() => openStackPage(creatorPage("release", { workId }))}>
                {r.releaseThisVersion}
              </Button>
            )}
            <Button variant="secondary" onClick={() => openStackPage(creatorPage("work", { workId }))}>
              {r.keepTake}
            </Button>
            <Button
              variant="ghost"
              onClick={() => (fromWorkbench ? openWorkbench(sourceWorkId || workId) : startRemelt(workId, resolvedTitle))}
            >
              {r.remelt}
            </Button>
            {heard ? (
              <>
                <Button variant="ghost" onClick={() => setPublishOpen(true)}>
                  {r.publishToDiscover || r.publishCommunity}
                </Button>
                <Text className="gen-reveal__verb-hint">{copy.publishUi.discoverNotStore}</Text>
              </>
            ) : null}
            <Button variant="ghost" size="sm" onClick={() => setShowMore((v) => !v)}>
              {r.more}
            </Button>
            {showMore && (
              <>
                {heard && suggestions.length > 0 && !fromWorkbench ? (
                  <View className="gen-reveal__suggest">
                    {suggestions.map((pack) => (
                      <Button
                        key={pack.id}
                        variant="ghost"
                        size="sm"
                        loading={previewBusy === pack.id}
                        onClick={() => void previewSuggest(pack)}
                      >
                        {r.suggestPreview} · {pack.locale_titles?.[locale] || pack.title}
                      </Button>
                    ))}
                  </View>
                ) : null}
                {showMixer ? (
                  <Button variant="ghost" size="sm" onClick={() => openWorkbench(fromWorkbench ? sourceWorkId || workId : workId, "pro")}>
                    {fromWorkbench ? copy.lightEditorUi.openMixer : r.openMixer}
                  </Button>
                ) : null}
                {heard && creditsCtx?.dspDistribution !== false ? (
                  <ShipCompleteCard
                    workId={workId}
                    surface="reveal"
                    compact
                    qcReady={qcReady}
                    releaseStatus={releaseStatus}
                    needsBeautify={rawTake}
                    onBeautify={() => openWorkbench(benchId)}
                  />
                ) : null}
                <Button variant="ghost" size="sm" onClick={() => openLibrary()}>
                  {r.libraryNext}
                </Button>
                {heard ? (
                  <Button variant="ghost" size="sm" onClick={() => void playNow()}>
                    {r.play}
                  </Button>
                ) : null}
                {heard && !fromWorkbench ? (
                  <Button variant="ghost" size="sm" onClick={() => startSameStyle(workId, resolvedTitle)}>
                    {r.sameStyle}
                  </Button>
                ) : null}
                {!resolvedCover && (
                  <Button variant="secondary" size="sm" loading={uploadingCover} onClick={() => void uploadCoverNow()}>
                    {copy.worksUi.coverUpload}
                  </Button>
                )}
                {heard && !qcReady && creditsCtx?.dspDistribution !== false ? (
                  <Text className="gen-reveal__qc-later">{r.qcLater}</Text>
                ) : null}
                {heard ? (
                  <Button variant="ghost" size="sm" onClick={() => openStackPage(creatorPage("work", { workId }))}>
                    {copy.creatorUi.workLedgerTitle}
                  </Button>
                ) : null}
                {heard ? (
                  <Button variant="ghost" size="sm" loading={radioBusy} onClick={() => void startRadioNow()}>
                    {r.radioNext}
                  </Button>
                ) : null}
                {skuKind === "instrumental" ? (
                  <Button variant="ghost" size="sm" onClick={() => void playNow()}>
                    {r.instrumentalListen}
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => openStackPage(socialPage("duels", { workId }))}
                >
                  {r.duelNext}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => openStackPage(studioPage("provenance", { workId }))}
                >
                  {r.provenance}
                </Button>
                <Button variant="ghost" size="sm" onClick={collect}>
                  {r.collect}
                </Button>
              </>
            )}
          </View>
        </View>
      </View>
      {publishOpen ? (
        <PublishDialog
          workTitle={resolvedTitle || "Track"}
          onClose={() => setPublishOpen(false)}
          onPublish={async (caption, opts) => {
            const post = await vibeApi.createPost(workId, caption, {
              allow_remix: opts.allowRemix,
              license: opts.license,
              content_compliance_acknowledged: opts.contentComplianceAcknowledged,
            });
            await syncAfterFeedMutation(creditsCtx, post);
            Taro.showToast({ title: copy.generation.publishSuccess, icon: "success" });
            setPublishOpen(false);
          }}
        />
      ) : null}
    </View>
  );
}
