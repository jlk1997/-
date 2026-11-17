import { useMemo, useState, useEffect, useRef, lazy, Suspense } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh, useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { PageShell } from "../../../components/PageShell";
import { WorkRow } from "../../../components/community/WorkRow";
import { WorkCoverCard } from "../../../components/community/WorkCoverCard";
import { PublishDialog } from "../../../components/community/PublishDialog";
import { RenameWorkSheet, type RenameWorkTarget } from "../../../components/community/RenameWorkSheet";
import { CelebrationSheet } from "../../../components/ui";
import type { DerivativeMode } from "../../../components/studio/DerivativeSheet";
import { AuthBanner, Button, ChipGroup, EmptyState, LoadingSkeleton, OverflowMenu, showSuccess, showError, StatusLine, ViewModeToggle } from "../../../components/ui";
import { vibeApi, type Work } from "../../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../../utils/auth";
import { useCreditsOptional } from "../../../contexts/CreditsProvider";
import { usePlayerTransport } from "../../../contexts/PlayerProvider";
import { syncAfterFeedMutation } from "../../../utils/feedMutationSync";
import { copyEmbedLink } from "../../../platform/share";
import { uploadFile } from "../../../platform/upload";
import { filterWorks, isWorkPublished, openWorkDetail, parseWorkFilter, type WorkFilter } from "../../../utils/workNav";
import { isWorkbenchMaster, successorByParentId } from "../../../utils/workbenchWorks";
import { openWorkbench } from "../../../utils/workbenchNav";
import { isPostProcessDegraded } from "../../../utils/postProcess";
import { hapticLight } from "../../../utils/haptic";
import { showCoverUnavailable } from "../../../utils/coverUnavailable";
import { STACK_PAGE_ROUTES } from "../../../constants/routes";
import { goShipBand } from "../../../packageCreator/nextActionNav";
import { statusLabel } from "../../../packageCreator/lib";
import "./index.scss";

const LazyDerivativeSheet = lazy(() =>
  import("../../../components/studio/DerivativeSheet").then((m) => ({ default: m.DerivativeSheet }))
);

type ViewMode = "grid" | "list";
type ExtendedWork = Work & { visibility?: string; parent_work_id?: string; version?: number; post_process_status?: Record<string, unknown> };
type PostMeta = { postId: string; caption?: string | null };

export default function WorksPage() {
  const router = useRouter();
  const { copy } = useLocale();
  const w = copy.worksUi;
  const creditsCtx = useCreditsOptional();
  const { patchTrackTitle } = usePlayerTransport();
  const [works, setWorks] = useState<ExtendedWork[]>([]);
  const [postByWork, setPostByWork] = useState<Record<string, PostMeta>>({});
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState("newest");
  const [filter, setFilter] = useState<WorkFilter>("all");
  const [view, setView] = useState<ViewMode>("grid");
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [publishTarget, setPublishTarget] = useState<ExtendedWork | null>(null);
  const [renameTarget, setRenameTarget] = useState<RenameWorkTarget | null>(null);
  const [celebrateOpen, setCelebrateOpen] = useState(false);
  const [derivative, setDerivative] = useState<{ work: ExtendedWork; mode: DerivativeMode } | null>(null);
  const [filterMoreOpen, setFilterMoreOpen] = useState(false);
  const lastWorksFetch = useRef(0);
  const sortReady = useRef(false);
  const isH5 = process.env.TARO_ENV === "h5";

  useDidShow(() => {
    setFilter(parseWorkFilter(router.params.filter));
    void loadWorks();
  });

  usePullDownRefresh(() => loadWorks(true));

  async function loadWorks(force = false) {
    bootstrapAuth();
    if (!isLoggedIn()) {
      setWorks([]);
      setLoading(false);
      Taro.stopPullDownRefresh();
      return;
    }
    const now = Date.now();
    if (!force && lastWorksFetch.current && now - lastWorksFetch.current < 1600 && works.length > 0) {
      Taro.stopPullDownRefresh();
      return;
    }
    if (works.length === 0) setLoading(true);
    try {
      const list = (await vibeApi.listWorks(sort)) as ExtendedWork[];
      lastWorksFetch.current = Date.now();
      setWorks(list);
      const map: Record<string, PostMeta> = {};
      list.forEach((item) => {
        if (item.community_post_id) {
          map[item.id] = { postId: item.community_post_id, caption: item.community_caption ?? null };
        }
      });
      setPostByWork(map);
    } catch {
      showError(w.loadFail);
    } finally {
      setLoading(false);
      Taro.stopPullDownRefresh();
    }
  }

  useEffect(() => {
    if (!sortReady.current) {
      sortReady.current = true;
      return;
    }
    if (isLoggedIn()) void loadWorks(true);
  }, [sort]);

  const publishedCount = useMemo(
    () => works.filter((item) => isWorkPublished(item, postByWork)).length,
    [works, postByWork]
  );

  const degradedCount = useMemo(
    () => works.filter((item) => isPostProcessDegraded(item.post_process_status)).length,
    [works],
  );

  const visibleWorks = useMemo(
    () => filterWorks(works, filter, postByWork),
    [works, filter, postByWork]
  );

  const queue = useMemo(
    () => visibleWorks.map((item) => workToPlayerTrack(item, { source: "works", isOwner: true })),
    [visibleWorks]
  );

  const masterByParent = useMemo(() => successorByParentId(works), [works]);

  async function publishWork(
    workId: string,
    caption: string,
    opts?: { allowRemix: boolean; license: string; contentComplianceAcknowledged?: boolean },
  ) {
    if (!requireAuth(STACK_PAGE_ROUTES.works)) return;
    const post = await vibeApi.createPost(workId, caption, {
      allow_remix: opts?.allowRemix,
      license: opts?.license,
      content_compliance_acknowledged: opts?.contentComplianceAcknowledged ?? true,
    });
    setPostByWork((prev) => ({ ...prev, [workId]: { postId: post.id || "", caption: post.caption ?? null } }));
    await syncAfterFeedMutation(creditsCtx, post);
    showSuccess(w.publishSuccess);
    setCelebrateOpen(true);
    void loadWorks();
  }

  async function unpublishWork(workId: string) {
    const postId = postByWork[workId]?.postId;
    if (!postId) return;
    const ok = await Taro.showModal({ title: w.unpublish, content: w.unpublishConfirm });
    if (!ok.confirm) return;
    try {
      await vibeApi.deletePost(postId);
      await syncAfterFeedMutation(creditsCtx);
      setPostByWork((prev) => {
        const next = { ...prev };
        delete next[workId];
        return next;
      });
      showSuccess(w.unpublishSuccess);
      void loadWorks();
    } catch {
      showError(w.deleteFail);
    }
  }

  async function batchDelete() {
    if (selected.size === 0) return;
    const ok = await Taro.showModal({
      title: w.deleteSelected.replace("{n}", String(selected.size)),
      content: w.deleteConfirm.replace("{n}", String(selected.size)),
    });
    if (!ok.confirm) return;
    try {
      await vibeApi.batchDeleteWorks([...selected]);
      showSuccess(w.deleteSuccess);
      setSelected(new Set());
      setSelectMode(false);
      void loadWorks();
    } catch {
      showError(w.deleteFail);
    }
  }

  async function generateCover(workId: string) {
    try {
      await vibeApi.generateCoverImage(workId);
      showSuccess(w.coverSuccess);
      void loadWorks();
    } catch {
      showError(w.deleteFail);
    }
  }

  async function uploadCover(workId: string) {
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
      showSuccess(w.coverUploaded);
      void loadWorks();
    } catch {
      Taro.hideLoading();
      showError(w.coverUploadFail);
    }
  }

  async function triggerPostProcess(workId: string) {
    const item = works.find((row) => row.id === workId);
    hapticLight();
    try {
      if (isPostProcessDegraded(item?.post_process_status)) {
        await vibeApi.reprocessWork(workId).catch(() => vibeApi.triggerPostProcess(workId));
      } else {
        await vibeApi.triggerPostProcess(workId);
      }
      showSuccess(w.reprocessQueued);
    } catch {
      showError(w.reprocessFail);
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleRenameSaved(result: { id: string; title: string; version: number; postCaptionSynced: boolean }) {
    setWorks((prev) =>
      prev.map((w) => (w.id === result.id ? { ...w, title: result.title, version: result.version } : w)),
    );
    patchTrackTitle(result.id, result.title);
    if (result.postCaptionSynced) {
      setPostByWork((prev) => {
        const meta = prev[result.id];
        if (!meta) return prev;
        return { ...prev, [result.id]: { ...meta, caption: result.title } };
      });
    }
  }

  function workProps(item: ExtendedWork) {
    const postMeta = postByWork[item.id];
    const postId = postMeta?.postId ?? null;
    const published = isWorkPublished(item, postByWork);
    return {
      id: item.id,
      title: item.title,
      moods: item.moods,
      coverUrl: item.cover_url,
      c2paVerified: item.c2pa_verified,
      hlsReady: !!item.hls_url,
      published,
      postId,
      postProcessStatus: item.post_process_status,
      track: item.audio_url ? workToPlayerTrack(item, { source: "works", isOwner: true }) : undefined,
      queue,
      selectMode,
      selected: selected.has(item.id),
      onSelect: () => toggleSelect(item.id),
      onOpen: selectMode ? undefined : () => openWorkDetail(item.id),
      onPublish: !postId && !selectMode ? () => setPublishTarget(item) : undefined,
      onUnpublish: postId && !selectMode ? () => unpublishWork(item.id) : undefined,
      fromWorkbench: isWorkbenchMaster(item),
      hasBeautifyMaster: masterByParent.has(item.id),
      onBeautify: selectMode ? undefined : () => openWorkbench(item.id),
      onRemix: selectMode ? undefined : () => setDerivative({ work: item, mode: "remix" }),
      onCover: selectMode ? undefined : () => showCoverUnavailable(),
      onGenerateCover: selectMode ? undefined : () => generateCover(item.id),
      onUploadCover: selectMode ? undefined : () => uploadCover(item.id),
      onPostProcess: selectMode ? undefined : () => triggerPostProcess(item.id),
      onEmbed: isH5 && !selectMode ? () => copyEmbedLink(item.id) : undefined,
      onRename:
        !selectMode
          ? () =>
              setRenameTarget({
                id: item.id,
                title: item.title,
                version: item.version,
                postId,
                postCaption: postMeta?.caption ?? null,
              })
          : undefined,
    };
  }

  const subtitle =
    works.length > 0
      ? w.subtitleWithPublished.replace("{n}", String(works.length)).replace("{m}", String(publishedCount))
      : undefined;

  if (!isLoggedIn()) {
    return (
      <PageShell label={copy.nav.works} title={copy.pages.works.title} subtitle={w.loginSubtitle} ambient wide>
        <AuthBanner message={copy.settingsUi.authBanner} loginLabel={copy.loginUi.login} next={STACK_PAGE_ROUTES.works} />
        <Button variant="primary" block className="auth-gate__cta" onClick={() => requireAuth(STACK_PAGE_ROUTES.works)}>
          {copy.loginUi.login}
        </Button>
      </PageShell>
    );
  }

  return (
    <PageShell
      label={copy.nav.works}
      title={copy.pages.works.title}
      subtitle={subtitle}
      wide
      ambient
      actions={
        <Button size="sm" variant="ghost" onClick={() => { setSelectMode(!selectMode); setSelected(new Set()); }}>
          {selectMode ? copy.actions.cancel : w.selectMode}
        </Button>
      }
    >
      {degradedCount > 0 && filter !== "needsFix" ? (
        <View className="works-fix-banner">
          <StatusLine tone="warning" onClick={() => setFilter("needsFix")}>
            {w.needsFixBanner.replace("{n}", String(degradedCount))}
          </StatusLine>
        </View>
      ) : null}
      <View className="works-toolbar">
        <ChipGroup
          options={[
            { value: "all", label: w.filterAll },
            { value: "draft", label: w.filterDraft },
            { value: "published", label: w.filterPublished },
          ]}
          value={
            filter === "all" || filter === "draft" || filter === "published" ? filter : ("" as "all")
          }
          onChange={(v) => setFilter(v as WorkFilter)}
        />
        <Button size="sm" variant="ghost" onClick={() => setFilterMoreOpen(true)}>
          {filter === "derivative"
            ? w.filterDerivative
            : filter === "needsFix"
              ? degradedCount > 0
                ? `${w.filterNeedsFix} ${degradedCount}`
                : w.filterNeedsFix
              : copy.actions.more}
        </Button>
      </View>
      <OverflowMenu
        open={filterMoreOpen}
        title={copy.actions.more}
        onClose={() => setFilterMoreOpen(false)}
        items={[
          {
            id: "derivative",
            label: w.filterDerivative,
            onClick: () => setFilter("derivative"),
          },
          ...(degradedCount > 0 || filter === "needsFix"
            ? [
                {
                  id: "needsFix",
                  label: degradedCount > 0 ? `${w.filterNeedsFix} ${degradedCount}` : w.filterNeedsFix,
                  onClick: () => setFilter("needsFix"),
                },
              ]
            : []),
        ]}
      />
      <View className="works-toolbar works-toolbar--secondary">
        <ChipGroup
          options={[
            { value: "newest", label: copy.discoverUi.sortLatest },
            { value: "oldest", label: w.sortOldest },
          ]}
          value={sort}
          onChange={setSort}
        />
        <ViewModeToggle
          options={[
            { value: "grid", icon: "grid", label: w.viewGrid },
            { value: "list", icon: "list", label: w.viewList },
          ]}
          value={view}
          onChange={(v) => setView(v as ViewMode)}
        />
      </View>
      {selectMode && selected.size > 0 && (
        <Button variant="danger" block onClick={batchDelete} className="works-batch-delete">
          {w.deleteSelected.replace("{n}", String(selected.size))}
        </Button>
      )}
      {loading && <LoadingSkeleton count={4} variant="line" />}
      {!loading && visibleWorks.length === 0 && (
        <EmptyState
          iconName="music"
          title={filter === "needsFix" ? w.needsFixEmpty : w.emptyTitle}
          description={filter === "needsFix" ? w.needsFixEmptyDesc : w.emptyDesc}
          actionLabel={filter === "needsFix" ? w.filterAll : w.actionLabel}
          onAction={() => (filter === "needsFix" ? setFilter("all") : Taro.switchTab({ url: "/pages/create/index" }))}
        />
      )}
      {view === "grid" ? (
        <View className="works-grid">
          {visibleWorks.map((item) => (
            <View key={item.id} className="works-grid__cell">
              <WorkCoverCard {...workProps(item)} />
              {!selectMode && isPostProcessDegraded(item.post_process_status) ? (
                <View className="works-release works-release--fix" onClick={() => void triggerPostProcess(item.id)}>
                  <Text className="works-release__cta">{w.retryArtifacts}</Text>
                </View>
              ) : !selectMode && creditsCtx?.dspDistribution !== false ? (
                <View
                  className="works-release"
                  onClick={() => goShipBand(item.id)}
                >
                  <Text className="works-release__cta">{w.releaseCta}</Text>
                  {item.release_status && (
                    <Text className="works-release__status">
                      {statusLabel(item.release_status, copy.creatorUi.status)}
                    </Text>
                  )}
                </View>
              ) : null}
            </View>
          ))}
        </View>
      ) : (
        <View className="works-list">
          {visibleWorks.map((item) => {
            const p = workProps(item);
            return (
              <View key={item.id} className="works-list__item">
                <WorkRow
                  id={p.id}
                  title={p.title}
                  moods={p.moods}
                  coverUrl={p.coverUrl}
                  c2paVerified={p.c2paVerified}
                  hlsReady={p.hlsReady}
                  published={p.published}
                  postId={p.postId}
                  postProcessStatus={p.postProcessStatus}
                  track={p.track}
                  queue={p.queue}
                  onOpen={p.onOpen}
                  onPublish={p.onPublish}
                  onUnpublish={p.onUnpublish}
                  onRemix={p.onRemix}
                  onCover={p.onCover}
                  onGenerateCover={p.onGenerateCover}
                  onPostProcess={p.onPostProcess}
                  onEmbed={p.onEmbed}
                  onRename={p.onRename}
                />
                {!selectMode && isPostProcessDegraded(item.post_process_status) ? (
                  <View className="works-release works-release--row works-release--fix" onClick={() => void triggerPostProcess(item.id)}>
                    <Text className="works-release__cta">{w.retryArtifacts}</Text>
                  </View>
                ) : !selectMode && creditsCtx?.dspDistribution !== false ? (
                  <View
                    className="works-release works-release--row"
                    onClick={() => goShipBand(item.id)}
                  >
                    <Text className="works-release__cta">{w.releaseCta}</Text>
                    {item.release_status && (
                    <Text className="works-release__status">
                      {statusLabel(item.release_status, copy.creatorUi.status)}
                    </Text>
                  )}
                  </View>
                ) : null}
              </View>
            );
          })}
        </View>
      )}
      {!loading && visibleWorks.length > 0 && (
        <Button variant="secondary" block onClick={() => Taro.switchTab({ url: "/pages/create/index" })} className="works-continue">
          {w.continueCreate}
        </Button>
      )}
      {renameTarget && (
        <RenameWorkSheet
          target={renameTarget}
          onClose={() => setRenameTarget(null)}
          onSaved={handleRenameSaved}
        />
      )}
      {publishTarget && (
        <PublishDialog
          workTitle={publishTarget.title}
          finishing={isPostProcessDegraded(publishTarget.post_process_status)}
          onClose={() => setPublishTarget(null)}
          onPublish={(caption, opts) => publishWork(publishTarget.id, caption, opts)}
        />
      )}
      <CelebrationSheet open={celebrateOpen} variant="publish" onClose={() => setCelebrateOpen(false)} />
      {derivative && (
        <Suspense fallback={null}>
          <LazyDerivativeSheet
            workId={derivative.work.id}
            workTitle={derivative.work.title}
            initialMode={derivative.mode}
            onClose={() => setDerivative(null)}
          />
        </Suspense>
      )}
    </PageShell>
  );
}
