import { useCallback, useMemo, useRef, useState } from "react";
import { Text, View } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh, useShareAppMessage } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { PageShell } from "../../components/PageShell";
import { PlaylistTile } from "../../components/community/PlaylistTile";
import {
  AsyncPanel,
  Button,
  EmptyState,
  LibraryShelf,
  OverflowMenu,
  SectionLabel,
  SegmentedControl,
  TrackRow,
} from "../../components/ui";
import { PublishDialog } from "../../components/community/PublishDialog";
import { usePlayer } from "../../contexts/PlayerProvider";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { stackPage, STUDIO_PAGE_ROUTES } from "../../constants/routes";
import { openStackPage } from "../../utils/navigation";
import { vibeApi, isAlreadyPublished } from "../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../utils/auth";
import { syncAfterFeedMutation } from "../../utils/feedMutationSync";
import { getItem, removeItem } from "../../platform/storage";
import { openWorkForOwner } from "../../utils/workNav";
import { openCommunityPost, openExistingDiscoverPost } from "../../utils/communityNav";
import { isWorkbenchMaster, preferWorkbenchMasters, releaseTargetId, resolveWorkCoreDoor, successorByParentId } from "../../utils/workbenchWorks";
import { coreDoorActionLabel, goWorkCoreDoor } from "../../utils/coreDoorNav";
import { workSharePayload } from "../../platform/share";
import { CoachMarks } from "../../components/onboarding/CoachMarks";
import { isPostProcessDegraded } from "../../utils/postProcess";
import "./index.scss";

type Tab = "works" | "playlists" | "collections";

const LIBRARY_NEXT = "/pages/library/index";

export default function LibraryPage() {
  const { copy, locale } = useLocale();
  const l = copy.libraryUi;
  const { playTrack } = usePlayer();
  const creditsCtx = useCreditsOptional();

  useShareAppMessage((res) => {
    const ds = (res?.target as { dataset?: Record<string, string> } | undefined)?.dataset;
    if (ds?.workid) return workSharePayload(ds.workid, ds.title || copy.brand.name);
    return { title: copy.brand.name };
  });
  const [tab, setTab] = useState<Tab>("works");
  const [shelfMore, setShelfMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [works, setWorks] = useState<
    Array<{
      id: string;
      title: string;
      cover_url?: string;
      moods: string[];
      audio_url: string;
      post_process_status?: Record<string, unknown>;
      parent_work_id?: string;
      from_workbench?: boolean;
      release_status?: string | null;
      superseded_by_work_id?: string | null;
      community_post_id?: string | null;
    }>
  >([]);
  const [playlists, setPlaylists] = useState<Array<{ id: string; title: string; track_count: number }>>([]);
  const [publicPlaylists, setPublicPlaylists] = useState<Array<{ id: string; title: string; track_count: number; owner_username?: string }>>([]);
  const [subscribedPlaylists, setSubscribedPlaylists] = useState<Array<{ id: string; title: string; track_count: number; owner_username?: string }>>([]);
  const [collections, setCollections] = useState<Array<{ id: string; work: { id: string; title: string; cover_url?: string; moods: string[]; audio_url: string } }>>([]);
  const loggedIn = isLoggedIn();
  const hasWorksRef = useRef(false);
  const worksLoadedRef = useRef(false);
  const lastWorksAt = useRef(0);
  const lastPlaylistsAt = useRef(0);
  const lastCollectionsAt = useRef(0);
  const [menuWork, setMenuWork] = useState<(typeof works)[number] | null>(null);
  const [publishWork, setPublishWork] = useState<(typeof works)[number] | null>(null);

  const load = useCallback(async (force = false, lane: Tab = "works") => {
    bootstrapAuth();
    if (!isLoggedIn()) {
      setWorks([]);
      setPlaylists([]);
      setPublicPlaylists([]);
      setSubscribedPlaylists([]);
      setCollections([]);
      setLoading(false);
      Taro.stopPullDownRefresh();
      return;
    }
    const now = Date.now();
    const stale = (at: number) => !force && at && now - at < 30_000;
    setLoadError(false);
    try {
      if (lane === "works") {
        if (stale(lastWorksAt.current) && worksLoadedRef.current) {
          Taro.stopPullDownRefresh();
          return;
        }
        if (!worksLoadedRef.current) setLoading(true);
        const w = await vibeApi.listWorks();
        setWorks(w);
        hasWorksRef.current = w.length > 0;
        worksLoadedRef.current = true;
        lastWorksAt.current = Date.now();
      } else if (lane === "playlists") {
        if (stale(lastPlaylistsAt.current)) {
          Taro.stopPullDownRefresh();
          return;
        }
        const [pl, pub, subs] = await Promise.all([
          vibeApi.listPlaylists(),
          vibeApi.listPublicPlaylists().catch(() => []),
          vibeApi.listPlaylistSubscriptions().catch(() => []),
        ]);
        setPlaylists(pl);
        setPublicPlaylists(pub);
        setSubscribedPlaylists(subs);
        lastPlaylistsAt.current = Date.now();
      } else {
        if (stale(lastCollectionsAt.current)) {
          Taro.stopPullDownRefresh();
          return;
        }
        const col = await vibeApi.listCollections().catch(() => []);
        setCollections(col);
        lastCollectionsAt.current = Date.now();
      }
      setLoadError(false);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
      Taro.stopPullDownRefresh();
    }
  }, []);

  useDidShow(() => {
    let next: Tab = tab;
    const savedTab = getItem("library:tab") as Tab | null;
    if (savedTab === "works" || savedTab === "playlists" || savedTab === "collections") {
      next = savedTab;
      setTab(savedTab);
      if (savedTab !== "works") setShelfMore(true);
      removeItem("library:tab");
    }
    void load(false, next);
  });
  usePullDownRefresh(() => void load(true, tab));

  const workTracks = useMemo(
    () => works.filter((w) => w.audio_url).map((w) => workToPlayerTrack(w, { source: "library", isOwner: true })),
    [works]
  );

  const degradedWorks = useMemo(() => works.filter((w) => isPostProcessDegraded(w.post_process_status)), [works]);
  const masterByParent = useMemo(() => successorByParentId(works), [works]);

  const orderedWorks = useMemo(() => {
    const preferred = preferWorkbenchMasters(works);
    const mastersFirst = [...preferred].sort((a, b) => Number(isWorkbenchMaster(b)) - Number(isWorkbenchMaster(a)));
    if (degradedWorks.length === 0) return mastersFirst;
    const rest = mastersFirst.filter((w) => !isPostProcessDegraded(w.post_process_status));
    return [...degradedWorks.filter((w) => mastersFirst.some((row) => row.id === w.id)), ...rest];
  }, [works, degradedWorks]);

  const shelfItems = useMemo(
    () => orderedWorks.slice(0, 6).map((w) => ({ id: w.id, title: w.title, coverUrl: w.cover_url })),
    [orderedWorks]
  );

  function playWork(workId: string) {
    const source = works.find((item) => item.id === workId);
    const targetId = source ? releaseTargetId(source, works) : workId;
    const track = workTracks.find((t) => t.id === targetId) || workTracks.find((t) => t.id === workId);
    if (!track) return;
    playTrack(track, { queue: workTracks, navigate: true });
  }

  if (!loggedIn) {
    return (
      <PageShell title={l.title} ambient wide tabVariant>
        <View className="library-page">
        <EmptyState
          iconName="music"
          title={l.loginTitle}
          description={l.loginDesc}
          actionLabel={copy.profileUi.loginButton}
          onAction={() => openStackPage(stackPage("login", { next: "/pages/library/index" }))}
        />
        </View>
      </PageShell>
    );
  }

  return (
    <PageShell title={l.title} showCredits={false} ambient wide tabVariant>
      <View className="library-page">
      {shelfMore ? (
      <SegmentedControl
        className="library-tabs"
        options={[
          { value: "works", label: l.tabWorks },
          { value: "playlists", label: l.tabPlaylists },
          { value: "collections", label: l.tabCollections },
        ]}
        value={tab}
        onChange={(next) => {
          setTab(next);
          void load(false, next);
        }}
      />
      ) : null}

      <AsyncPanel
        loading={loading}
        error={loadError}
        skeletonCount={4}
        errorIcon="music"
        errorTitle={copy.discoverUi.loadError}
        errorActionLabel={copy.discoverUi.retry}
        onRetry={() => void load()}
      >
      {tab === "works" && (
        <View className="library-panel">
          <View className="coach-anchor-shelf">
          <LibraryShelf label={l.recentLabel} items={shelfItems} onSelect={playWork} />
          </View>
          {works.length === 0 ? (
            <EmptyState
              iconName="music"
              title={l.emptyWorks}
              description={l.emptyWorksDesc}
              actionLabel={l.goCreate}
              onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
            />
          ) : (
            orderedWorks.map((w, i) => {
              const degraded = isPostProcessDegraded(w.post_process_status);
              const sku = String((w.post_process_status as { sku_kind?: string } | undefined)?.sku_kind || "");
              const master = isWorkbenchMaster(w);
              const hasMaster = masterByParent.has(w.id);
              const door = resolveWorkCoreDoor(w, works).door;
              const shelf =
                w.release_status === "live"
                  ? locale === "en"
                    ? "Live"
                    : "已上架"
                  : w.release_status === "queued" || w.release_status === "delivering"
                    ? locale === "en"
                      ? "Waiting for receipt"
                      : "等待回执"
                    : w.release_status === "qc_ready"
                      ? locale === "en"
                        ? "Details needed"
                        : "资料待补"
                      : locale === "en"
                        ? "Draft"
                        : "草稿";
              return (
                <TrackRow
                  key={w.id}
                  index={i + 1}
                  title={w.title}
                  subtitle={w.moods?.slice(0, 2).join(" · ")}
                  coverUrl={w.cover_url}
                  badge={
                    degraded
                      ? l.needsFixBadge
                      : master
                        ? copy.worksUi.beautifyMaster
                        : hasMaster
                          ? copy.worksUi.hasBeautifyMaster
                        : sku === "instrumental"
                          ? copy.worksUi.instrumentalSku
                          : shelf
                  }
                  badgeTone={degraded || hasMaster ? "warning" : "accent"}
                  onClick={() => openWorkForOwner(w.id, true)}
                  onPlay={() => playWork(w.id)}
                  actionLabel={coreDoorActionLabel(door, copy)}
                  onAction={() => goWorkCoreDoor(w, works)}
                  onMenu={() => setMenuWork(w)}
                />
              );
            })
          )}
          {works.length > 0 && (
            <Button variant="ghost" block className="library-manage" onClick={() => setShelfMore((v) => !v)}>
              {shelfMore ? copy.createUi.formulaHide : `${l.tabPlaylists} / ${l.tabCollections}`}
            </Button>
          )}
        </View>
      )}

      {tab === "playlists" && (
        <View className="library-panel library-panel--grid">
          {playlists.length === 0 ? (
            <EmptyState
              iconName="create"
              title={l.emptyPlaylists}
              actionLabel={l.goCreate}
              onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
            />
          ) : (
            playlists.map((pl, i) => (
              <PlaylistTile
                key={pl.id}
                title={pl.title}
                trackCount={pl.track_count}
                trackLabel={l.trackCount.replace("{n}", String(pl.track_count))}
                index={i}
                onClick={() => openStackPage(stackPage("playlist", { id: pl.id }))}
              />
            ))
          )}
          {subscribedPlaylists.length > 0 && (
            <>
              <SectionLabel>{l.subscribedPlaylistsLabel}</SectionLabel>
              {subscribedPlaylists.map((pl, i) => (
                <PlaylistTile
                  key={`sub-${pl.id}`}
                  title={pl.title}
                  trackCount={pl.track_count}
                  trackLabel={
                    pl.owner_username
                      ? `@${pl.owner_username} · ${l.trackCount.replace("{n}", String(pl.track_count))}`
                      : l.trackCount.replace("{n}", String(pl.track_count))
                  }
                  index={i}
                  onClick={() => openStackPage(stackPage("playlist", { id: pl.id }))}
                />
              ))}
            </>
          )}
          {publicPlaylists.length > 0 && (
            <>
              <SectionLabel>{l.publicPlaylistsLabel}</SectionLabel>
              {publicPlaylists.map((pl, i) => (
                <PlaylistTile
                  key={pl.id}
                  title={pl.title}
                  trackCount={pl.track_count}
                  trackLabel={
                    pl.owner_username
                      ? `@${pl.owner_username} · ${l.trackCount.replace("{n}", String(pl.track_count))}`
                      : l.trackCount.replace("{n}", String(pl.track_count))
                  }
                  index={i + playlists.length}
                  onClick={() => openStackPage(stackPage("playlist", { id: pl.id }))}
                />
              ))}
            </>
          )}
        </View>
      )}

      {tab === "collections" && (
        <View className="library-panel">
          {collections.length === 0 ? (
            <EmptyState iconName="bookmark" title={l.emptyCollections} actionLabel={copy.nav.discover} onAction={() => Taro.switchTab({ url: "/pages/feed/index" })} />
          ) : (
            collections.map((c, i) => (
              <TrackRow
                key={c.id}
                index={i + 1}
                title={c.work.title}
                subtitle={c.work.moods?.slice(0, 2).join(" · ")}
                coverUrl={c.work.cover_url}
                onClick={() => openStackPage(`${STUDIO_PAGE_ROUTES.provenance}?workId=${c.work.id}`)}
                onPlay={() => {
                  const track = workToPlayerTrack(c.work, { source: "library" });
                  playTrack(track, { navigate: true });
                }}
              />
            ))
          )}
        </View>
      )}
      </AsyncPanel>
      <CoachMarks page="library" />
      {menuWork ? (
        <OverflowMenu
          open
          title={menuWork.title}
          onClose={() => setMenuWork(null)}
          items={[
            {
              id: "discover",
              icon: "feed",
              label: menuWork.community_post_id ? copy.worksUi.viewInCommunity : copy.generation.reveal.publishToDiscover,
              onClick: () => {
                if (!requireAuth(LIBRARY_NEXT)) return;
                if (menuWork.community_post_id) {
                  openCommunityPost(menuWork.community_post_id);
                  return;
                }
                setPublishWork(menuWork);
              },
            },
          ]}
        />
      ) : null}
      {publishWork ? (
        <PublishDialog
          workTitle={publishWork.title || "Track"}
          onClose={() => setPublishWork(null)}
          onPublish={async (caption, opts) => {
            try {
              const post = await vibeApi.createPost(publishWork.id, caption, {
                allow_remix: opts.allowRemix,
                license: opts.license,
                content_compliance_acknowledged: opts.contentComplianceAcknowledged,
              });
              await syncAfterFeedMutation(creditsCtx, post);
              Taro.showToast({ title: copy.generation.publishSuccess, icon: "success" });
              setPublishWork(null);
              if (post?.id) openCommunityPost(post.id);
            } catch (err) {
              if (isAlreadyPublished(err)) {
                const opened = await openExistingDiscoverPost(publishWork.id, publishWork.community_post_id);
                if (!opened) Taro.showToast({ title: copy.worksUi.viewInCommunity, icon: "none" });
                setPublishWork(null);
                return;
              }
              throw err;
            }
          }}
        />
      ) : null}
      </View>
    </PageShell>
  );
}
