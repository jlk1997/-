import { useEffect, useState } from "react";
import Taro, { useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { Button, Collapsible, EmptyState, LoadingSkeleton } from "../../../components/ui";
import { VariationLab, type VariationWork } from "../../../components/studio/VariationLab";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, isLoggedIn, requireAuth } from "../../../utils/auth";
import { creatorPage, studioPage } from "../../../constants/routes";
import { startSameStyle } from "../../../utils/sameStyleNav";
import "./index.scss";

export default function VariationLabPage() {
  const router = useRouter();
  const { copy } = useLocale();
  const v = copy.variationLabUi;
  const lab = copy.variationLab;
  const jobId = router.params.jobId || "";
  const [works, setWorks] = useState<VariationWork[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [heardIds, setHeardIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(false);

  useEffect(() => {
    bootstrapAuth();
    if (!jobId) {
      setLoading(false);
      return;
    }
    const labNext = studioPage("variationLab", { jobId });
    if (!isLoggedIn()) {
      requireAuth(labNext);
      setLoading(false);
      return;
    }
    vibeApi
      .getJob(jobId)
      .then(async (job) => {
        const ids = (job.result as { work_ids?: string[] } | undefined)?.work_ids || [];
        if (!ids.length) {
          setWorks([]);
          return;
        }
        const list = await vibeApi.listWorks();
        const mapped = ids
          .map((id) => list.find((w) => w.id === id))
          .filter(Boolean)
          .map((w) => ({
            id: w!.id,
            title: w!.title,
            audio_url: w!.audio_url,
            hls_url: w!.hls_url,
            cover_url: w!.cover_url,
          }));
        setWorks(mapped);
      })
      .catch(() => Taro.showToast({ title: lab.pickFail, icon: "none" }))
      .finally(() => setLoading(false));
  }, [jobId, lab.pickFail]);

  async function pickPrimary(workId: string) {
    if (!jobId || !requireAuth(studioPage("variationLab", { jobId }))) return;
    setPicking(true);
    try {
      await vibeApi.pickVariationPrimary(jobId, workId);
      setSelectedId(workId);
      Taro.showToast({ title: lab.pickSuccess, icon: "success" });
      Taro.navigateTo({ url: creatorPage("work", { workId }) });
    } catch {
      Taro.showToast({ title: lab.pickFail, icon: "none" });
    } finally {
      setPicking(false);
    }
  }

  const selectedHeard = Boolean(selectedId && heardIds.has(selectedId));

  return (
    <PageShell title={v.title} subtitle={lab.description} wide ambient>
      {loading && <LoadingSkeleton count={3} />}
      {!loading && !jobId && (
        <EmptyState
          iconName="music"
          title={v.needJob}
          description={v.needJobHint}
          actionLabel={copy.actions.enterStudio}
          onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
        />
      )}
      {!loading && jobId && !isLoggedIn() && (
        <EmptyState
          iconName="profile"
          title={copy.loginUi.login}
          description={copy.settingsUi.authBanner}
          actionLabel={copy.loginUi.login}
          onAction={() => requireAuth(studioPage("variationLab", { jobId }))}
        />
      )}
      {!loading && jobId && isLoggedIn() && works.length === 0 && (
        <EmptyState
          iconName="music"
          title={v.needJob}
          description={v.needJobHint}
          actionLabel={copy.actions.enterStudio}
          onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
        />
      )}
      {!loading && jobId && works.length > 0 && (
        <>
          <VariationLab
            works={works}
            selectedId={selectedId}
            heardIds={heardIds}
            onSelect={setSelectedId}
            onHeard={(id) => setHeardIds((prev) => new Set(prev).add(id))}
          />
          {selectedId && selectedHeard && (
            <Button variant="primary" block loading={picking} onClick={() => pickPrimary(selectedId)}>
              {lab.pickPrimary}
            </Button>
          )}
          {selectedId && selectedHeard && (
            <Collapsible label={copy.generation.reveal.more} defaultOpen={false}>
              <Button
                variant="ghost"
                block
                onClick={() => startSameStyle(selectedId, works.find((row) => row.id === selectedId)?.title)}
              >
                {copy.derivative.startSameStyle}
              </Button>
            </Collapsible>
          )}
        </>
      )}
    </PageShell>
  );
}
