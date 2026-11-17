import { useEffect, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { vibeApi } from "../../services/api";
import { Button, Icon, Tag } from "../ui";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { usePlayerTransport } from "../../contexts/PlayerProvider";
import { hapticLight } from "../../utils/haptic";
import { startRemelt } from "../../utils/sameStyleNav";
import { isReleaseInFlight } from "../../packageCreator/quickReleaseAction";
import { commercePage } from "../../constants/routes";
import { goShipBand } from "../../packageCreator/nextActionNav";
import { openRadioPage, openStackPage } from "../../utils/navigation";
import { openWorkbench } from "../../utils/workbenchNav";
import { nextCoreDoor } from "../../utils/nextCoreDoor";
import { isPostProcessDegraded } from "../../utils/postProcess";
import { PublishDialog } from "../community/PublishDialog";
import { syncAfterFeedMutation } from "../../utils/feedMutationSync";
import "./VariationPicker.scss";

type VariationWork = {
  id: string;
  title: string;
  audio_url?: string;
  hls_url?: string;
  cover_url?: string;
  moods?: string[];
  release_status?: string;
  post_process_status?: Record<string, unknown>;
  from_workbench?: boolean;
};

type Props = {
  jobId: string;
  workIds: string[];
  hero?: boolean;
  showNext?: boolean;
  onPicked?: (workId: string) => void;
};

export function VariationPicker({ jobId, workIds, hero = false, showNext = true, onPicked }: Props) {
  const { copy } = useLocale();
  const v = copy.variationLab;
  const r = copy.generation.reveal;
  const creditsCtx = useCreditsOptional();
  const { playTrack, currentTrackId, isPlaying } = usePlayerTransport();
  const [works, setWorks] = useState<VariationWork[]>([]);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState<string | null>(null);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [heardIds, setHeardIds] = useState<Set<string>>(new Set());
  const [showMore, setShowMore] = useState(false);
  const [nextBusy, setNextBusy] = useState("");
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishWorkId, setPublishWorkId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const list = await Promise.all(
          workIds.map(async (id) => {
            try {
              return (await vibeApi.getWork(id)) as VariationWork;
            } catch {
              return { id, title: v.variantLabel.replace("{n}", id.slice(0, 6)), audio_url: "" };
            }
          }),
        );
        if (!cancelled) setWorks(list.filter((w) => w.audio_url));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (workIds.length > 1) load();
    else setLoading(false);
    return () => {
      cancelled = true;
    };
  }, [workIds, v.variantLabel]);

  const picked = works.find((w) => w.id === pickedId);
  const nextWork = picked || works.find((row) => heardIds.has(row.id));
  const publishWork = works.find((w) => w.id === publishWorkId) || nextWork;
  const pickedStatus = nextWork?.release_status;
  const pickedDegraded = isPostProcessDegraded(nextWork?.post_process_status);
  useEffect(() => {
    if (currentTrackId && workIds.includes(currentTrackId)) {
      setHeardIds((prev) => new Set(prev).add(currentTrackId));
    }
  }, [currentTrackId, workIds]);

  const door = nextCoreDoor({
    hasResult: Boolean(nextWork?.from_workbench),
    releaseStatus: pickedStatus,
    degraded: pickedDegraded,
  });
  const releaseReady = door === "release" || isReleaseInFlight(pickedStatus);

  useEffect(() => {
    if (!pickedId || releaseReady) return undefined;
    let ticks = 0;
    const timer = setInterval(() => {
      ticks += 1;
      vibeApi
        .getWork(pickedId)
        .then((w) => {
          setWorks((prev) =>
            prev.map((row) =>
              row.id === pickedId
                ? {
                    ...row,
                    release_status: (w as VariationWork).release_status,
                    post_process_status: (w as VariationWork).post_process_status,
                  }
                : row,
            ),
          );
        })
        .catch(() => {});
      if (ticks >= 8) clearInterval(timer);
    }, 4000);
    return () => clearInterval(timer);
  }, [pickedId, releaseReady]);

  function playWork(w: VariationWork) {
    if (!w.audio_url) return;
    hapticLight();
    setHeardIds((prev) => new Set(prev).add(w.id));
    const queue = works
      .filter((row) => row.audio_url)
      .map((row) =>
        workToPlayerTrack(
          { id: row.id, title: row.title, audio_url: row.audio_url as string, cover_url: row.cover_url },
          { source: "generation", isOwner: true },
        ),
      );
    const idx = queue.findIndex((t) => t.id === w.id);
    playTrack(queue[idx] || queue[0], { queue, startIndex: Math.max(0, idx), navigate: false });
  }

  function openPublish(workId: string) {
    hapticLight();
    setPublishWorkId(workId);
    setPublishOpen(true);
  }

  async function pickPrimary(workId: string) {
    hapticLight();
    setPicking(workId);
    try {
      await vibeApi.pickVariationPrimary(jobId, workId);
      setPickedId(workId);
      onPicked?.(workId);
      Taro.showToast({ title: v.pickSuccess, icon: "success" });
    } catch {
      Taro.showToast({ title: v.pickFail, icon: "none" });
    } finally {
      setPicking(null);
    }
  }

  return (
    <View className={`variation-picker${hero ? " variation-picker--hero" : ""}`}>
      <Text className="typo-meta">
        {(workIds.length === 2 ? v.pickerHintTwo : v.pickerHint).replace("{n}", String(workIds.length))}
      </Text>
      {workIds.length === 2 ? <Text className="typo-meta">{copy.workbenchUi.abHint}</Text> : null}
      {loading && (
        <View className="variation-picker__grid">
          {[0, 1].map((i) => (
            <View key={i} className="variation-picker__card variation-picker__card--skeleton" />
          ))}
        </View>
      )}
      <View className="variation-picker__grid">
        {works.map((w, i) => {
          const playing = currentTrackId === w.id && isPlaying;
          const heard = heardIds.has(w.id);
          return (
            <View
              key={w.id}
              className={`variation-picker__card${pickedId === w.id ? " variation-picker__card--picked" : ""}${playing ? " variation-picker__card--playing" : ""}`}
            >
              <View className="variation-picker__cover-wrap" onClick={() => playWork(w)}>
                {w.cover_url ? (
                  <Image className="variation-picker__cover" src={w.cover_url} mode="aspectFill" lazyLoad />
                ) : (
                  <View className="variation-picker__cover variation-picker__cover--empty" />
                )}
                <View className="variation-picker__play">
                  <Icon name={playing ? "pause" : "play"} size="sm" tone="dark" />
                  <Text className="variation-picker__play-label">{playing ? v.playing : v.listen}</Text>
                </View>
                <Text className="variation-picker__badge">{v.variantLabel.replace("{n}", String(i + 1))}</Text>
              </View>
              <Text className="variation-picker__title">{w.title}</Text>
              {(w.moods || []).length > 0 && (
                <View className="variation-picker__chips">
                  {(w.moods || []).slice(0, 2).map((mood) => (
                    <Tag key={mood}>{mood}</Tag>
                  ))}
                </View>
              )}
              {heard ? (
                <>
                  <Button size="sm" block variant="primary" onClick={() => openPublish(w.id)}>
                    {r.publishToDiscover || r.publishCommunity}
                  </Button>
                  <Button
                    size="sm"
                    block
                    variant={pickedId === w.id ? "primary" : "secondary"}
                    loading={picking === w.id}
                    onClick={() => pickPrimary(w.id)}
                  >
                    {pickedId === w.id ? v.primary : v.pickPrimary}
                  </Button>
                  <Button size="sm" block variant="ghost" onClick={() => openWorkbench(w.id)}>
                    {v.nextBeautify}
                  </Button>
                </>
              ) : (
                <Button size="sm" block variant="ghost" onClick={() => playWork(w)}>
                  {v.listen}
                </Button>
              )}
            </View>
          );
        })}
      </View>
      {showNext && nextWork && (
        <View className="variation-picker__next">
          <Text className="typo-meta">{v.nextHint}</Text>
          <View className="variation-picker__actions">
            <Button size="sm" variant="primary" onClick={() => openPublish(nextWork.id)}>
              {r.publishToDiscover || r.publishCommunity}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => openWorkbench(nextWork.id)}>
              {v.nextBeautify}
            </Button>
            {showMore ? (
              <>
                <Button size="sm" variant="ghost" onClick={() => playWork(nextWork)}>
                  {v.listen}
                </Button>
                {door !== "fix" ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={nextBusy === "radio"}
                    onClick={() => {
                      hapticLight();
                      setNextBusy("radio");
                      openRadioPage({ workId: nextWork.id });
                      void vibeApi
                        .startRadioTrial(nextWork.id)
                        .then((trial) => {
                          Taro.showToast({ title: copy.creatorUi.radioTrialLive, icon: "success" });
                          const next = (trial as { work_id?: string }).work_id;
                          if (next && next !== nextWork.id) openRadioPage({ workId: next });
                        })
                        .catch(() => {
                          Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                        })
                        .finally(() => setNextBusy(""));
                    }}
                  >
                    {v.nextRadio}
                  </Button>
                ) : null}
                {releaseReady ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={nextBusy === "release"}
                    onClick={() => {
                      setNextBusy("release");
                      void (async () => {
                        try {
                          goShipBand(nextWork.id);
                        } catch {
                          Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
                        } finally {
                          setNextBusy("");
                        }
                      })();
                    }}
                  >
                    {v.nextRelease}
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => openStackPage(commercePage("syncDesk", { workId: nextWork.id }))}
                >
                  {r.syncLicense}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => startRemelt(nextWork.id, nextWork.title)}>
                  {r.remelt}
                </Button>
              </>
            ) : (
              <Button size="sm" variant="ghost" onClick={() => setShowMore(true)}>
                {r.more}
              </Button>
            )}
          </View>
        </View>
      )}
      {publishOpen && publishWork ? (
        <PublishDialog
          workTitle={publishWork.title || "Track"}
          onClose={() => setPublishOpen(false)}
          onPublish={async (caption, opts) => {
            const post = await vibeApi.createPost(publishWork.id, caption, {
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
