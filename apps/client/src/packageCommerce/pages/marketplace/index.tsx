import { useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro, { useDidShow, useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell, SectionLabel } from "../../../components/PageShell";
import { Button, ChipGroup, EmptyState, LoadingSkeleton, Tag, showError, showSuccess } from "../../../components/ui";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, requireAuth } from "../../../utils/auth";
import { useCreditsOptional } from "../../../contexts/CreditsProvider";
import { usePlayer } from "../../../contexts/PlayerProvider";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { commercePage, studioPage } from "../../../constants/routes";
import { openWorkbench } from "../../../utils/workbenchNav";
import { setItem } from "../../../platform/storage";
import { startSameStyle } from "../../../utils/sameStyleNav";
import "./index.scss";

type Template = {
  id: string;
  title: string;
  description?: string;
  price_credits: number;
  author_username?: string;
  moods?: string[];
  genres?: string[];
  cover_url?: string;
};
type WorkPack = { id: string; title: string; price_credits: number; work_count: number; owner_username?: string };
type EffectPack = {
  id: string;
  slug?: string | null;
  title: string;
  description?: string | null;
  price_credits: number;
  is_official: boolean;
  owned?: boolean;
  author_username?: string;
  locale_titles?: Record<string, string>;
  preview_url?: string | null;
  need_tags?: string[];
  tags?: string[];
  kind?: string;
};
type Demand = { id: string; work_id?: string; brief: string; bid_credits: number; status: string; work_title?: string };

export default function MarketplacePage() {
  const { copy, locale } = useLocale();
  const router = useRouter();
  const m = copy.marketplaceUi;
  const recipesOnly = String(router.params.shelf || "") === "recipes";
  const creditsCtx = useCreditsOptional();
  const { playTrack } = usePlayer();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [packs, setPacks] = useState<WorkPack[]>([]);
  const [effectPacks, setEffectPacks] = useState<EffectPack[]>([]);
  const [demands, setDemands] = useState<Demand[]>([]);
  const [needFilter, setNeedFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [buying, setBuying] = useState<string | null>(null);

  useDidShow(() => {
    bootstrapAuth();
    setLoading(true);
    Promise.all([
      vibeApi.listRecipeTemplates(),
      vibeApi.listWorkPacks(),
      vibeApi.listEffectPacks("all", process.env.TARO_ENV === "weapp" ? "weapp" : "h5"),
      process.env.TARO_ENV === "weapp" ? Promise.resolve([]) : vibeApi.listPackDemands("open").catch(() => []),
    ])
      .then(([tpls, wp, fx, openDemands]) => {
        setTemplates(tpls);
        setPacks(wp);
        setEffectPacks(fx);
        setDemands(openDemands as Demand[]);
      })
      .catch(() => showError(m.loadFail))
      .finally(() => setLoading(false));
  });

  async function buyTemplate(templateId: string) {
    if (!requireAuth(commercePage("marketplace"))) return;
    setBuying(`tpl-${templateId}`);
    try {
      const res = await vibeApi.purchaseRecipeTemplate(templateId);
      await creditsCtx?.refresh();
      showSuccess(m.recipeReady);
      if (res.spec) {
        setItem("create:importSpec", JSON.stringify(res.spec));
        setItem("create:recipeReady", "1");
        const refId = String((res as { reference_work_id?: string }).reference_work_id || res.spec.reference_work_id || "");
        if (refId) {
          setItem("create:seedWorkId", refId);
          setItem("create:mode", "sameStyle");
          setItem("create:referenceWorkId", refId);
        }
        Taro.switchTab({ url: "/pages/create/index" });
      }
    } catch {
      showError(m.purchaseFail);
    } finally {
      setBuying(null);
    }
  }

  async function buyPack(packId: string) {
    if (!requireAuth(commercePage("marketplace"))) return;
    setBuying(`pack-${packId}`);
    try {
      const res = await vibeApi.purchaseWorkPack(packId);
      await creditsCtx?.refresh();
      const first = res.work_ids?.[0];
      showSuccess(m.packUnlocked);
      if (first) {
        startSameStyle(first, res.title);
        return;
      }
    } catch {
      showError(m.purchaseFail);
    } finally {
      setBuying(null);
    }
  }

  async function previewEffect(pack: EffectPack) {
    if (!requireAuth(commercePage("marketplace"))) return;
    setBuying(`fx-preview-${pack.id}`);
    try {
      const queued = await vibeApi.previewEffectPack(pack.id);
      let url = queued.preview_url || pack.preview_url;
      if (!url && queued.job_id) {
        showSuccess(copy.workbenchUi.previewing);
        for (let i = 0; i < 40; i += 1) {
          const job = await vibeApi.getJob(queued.job_id);
          if (job.status === "failed" || job.status === "cancelled") throw new Error(job.status);
          url = (job.result as { preview_url?: string } | null)?.preview_url;
          if (url || job.status === "audio_ready" || job.status === "completed") break;
          await new Promise((resolve) => setTimeout(resolve, 1200));
        }
        if (!url) {
          const again = await vibeApi.previewEffectPack(pack.id);
          url = again.preview_url;
        }
      }
      if (url) {
        playTrack(workToPlayerTrack({ id: `fx-preview-${pack.id}`, title: pack.title, audio_url: url }));
      }
    } catch {
      showError(m.purchaseFail);
    } finally {
      setBuying(null);
    }
  }

  async function buyEffect(pack: EffectPack) {
    if (!requireAuth(commercePage("marketplace"))) return;
    setBuying(`fx-${pack.id}`);
    try {
      if (!pack.owned && (pack.price_credits || 0) > 0) {
        await vibeApi.purchaseEffectPack(pack.id);
        await creditsCtx?.refresh();
        setEffectPacks((prev) => prev.map((row) => (row.id === pack.id ? { ...row, owned: true } : row)));
      }
      showSuccess(m.beautifyUnlocked);
      const routerWorkId = String(Taro.getCurrentInstance().router?.params?.workId || "");
      const works = (await vibeApi.listWorks()).filter((row) => row.audio_url);
      let targetId = works.find((row) => row.id === routerWorkId)?.id || "";
      if (!targetId && works.length === 1) targetId = works[0].id;
      if (!targetId && works.length > 1) {
        targetId = await new Promise<string>((resolve) => {
          Taro.showActionSheet({
            itemList: works.slice(0, 6).map((row) => row.title || m.beautifyPickWork),
            success: (res) => resolve(works[res.tapIndex]?.id || ""),
            fail: () => resolve(""),
          });
        });
      }
      if (!targetId) {
        showError(m.beautifyNeedWork);
        return;
      }
      try {
        const sess = await vibeApi.openWorkbenchSession(targetId);
        await vibeApi.applyEffectPack(sess.id, pack.id, 1);
      } catch {
        /* desk will retry via packId */
      }
      openWorkbench(targetId, undefined, { packId: pack.id });
    } catch {
      showError(m.purchaseFail);
    } finally {
      setBuying(null);
    }
  }

  const visibleFx = effectPacks.filter((pack) => {
    if (kindFilter && String(pack.kind || "scene") !== kindFilter) return false;
    if (!needFilter) return true;
    const tags = [...(pack.need_tags || []), ...(pack.tags || [])].map((tag) => String(tag).toLowerCase());
    return tags.includes(needFilter);
  });

  return (
    <PageShell title={recipesOnly ? m.recipesTitle : m.title} subtitle={recipesOnly ? m.recipesHint : m.subtitle} wide ambient>
      <View className="marketplace-banner" onClick={() => Taro.navigateTo({ url: commercePage("syncDesk") })}>
        <Text className="marketplace-banner__kicker">{m.syncEntry}</Text>
        <Text className="marketplace-banner__title">{m.syncEntryHint}</Text>
      </View>
      {process.env.TARO_ENV === "weapp" ? (
        <Text className="typo-meta">
          {m.weappOfficialOnly} {m.weappNoMixer}
        </Text>
      ) : null}

      {recipesOnly ? (
        <>
          <SectionLabel>{m.templatesLabel}</SectionLabel>
          <Text className="typo-meta">{m.recipesHint}</Text>
        </>
      ) : (
        <>
          <SectionLabel>{m.beautifyLabel}</SectionLabel>
          <Text className="typo-meta">{m.beautifyHint}</Text>
          <ChipGroup
            value={needFilter || "all"}
            onChange={(value) => setNeedFilter(value === "all" ? "" : value)}
            options={[
              { value: "all", label: m.beautifyNeeds },
              ...["vocal", "club", "radio", "lofi", "warm", "space", "voice", "width", "close", "bright"].map((need) => ({
                value: need,
                label: copy.workbenchUi[`need${need[0].toUpperCase()}${need.slice(1)}` as keyof typeof copy.workbenchUi] as string,
              })),
            ]}
          />
          <ChipGroup
            value={kindFilter || "all"}
            onChange={(value) => setKindFilter(value === "all" ? "" : value)}
            options={[
              { value: "all", label: m.beautifyNeeds },
              { value: "scene", label: copy.workbenchUi.publishKindScene },
              { value: "lane", label: copy.workbenchUi.publishKindLane },
              { value: "demand", label: copy.workbenchUi.demandTitle },
            ]}
          />
          {!loading && effectPacks.length === 0 && <Text className="typo-meta">{m.beautifyEmpty}</Text>}
          {visibleFx.map((pack) => {
            const named = pack.slug ? copy.workbenchUi.packs[pack.slug as keyof typeof copy.workbenchUi.packs] : undefined;
            const title = named?.title || pack.locale_titles?.[locale] || pack.title;
            const hint = named?.hint || pack.description || "";
            return (
              <View key={pack.id} className="marketplace-card">
                <Text className="marketplace-card__title">{title}</Text>
                {pack.author_username && <Text className="marketplace-card__author">{m.byAuthor.replace("{user}", pack.author_username)}</Text>}
                {hint ? <Text className="typo-meta">{hint}</Text> : null}
                <View className="marketplace-card__row">
                  <Text className="marketplace-card__price">
                    {(pack.price_credits || 0) > 0 && !pack.owned ? m.priceCredits.replace("{n}", String(pack.price_credits)) : m.free}
                  </Text>
                  <Button size="sm" variant="ghost" loading={buying === `fx-preview-${pack.id}`} onClick={() => void previewEffect(pack)}>
                    {copy.workbenchUi.previewPack}
                  </Button>
                  <Button size="sm" variant="secondary" loading={buying === `fx-${pack.id}`} onClick={() => void buyEffect(pack)}>
                    {(pack.price_credits || 0) > 0 && !pack.owned ? m.beautifyBuy : m.beautifyUse}
                  </Button>
                </View>
              </View>
            );
          })}
          {process.env.TARO_ENV !== "weapp" && (
            <>
              <SectionLabel>{m.demandLabel}</SectionLabel>
              <Text className="typo-meta">{m.demandHint}</Text>
              {demands.length === 0 && <Text className="typo-meta">{copy.workbenchUi.demandEmpty}</Text>}
              {demands.map((row) => (
                <View key={row.id} className="marketplace-card">
                  <Text className="marketplace-card__title">{row.brief}</Text>
                  {row.work_title ? <Text className="typo-meta">{row.work_title}</Text> : null}
                  <View className="marketplace-card__row">
                    <Text className="marketplace-card__price">{m.priceCredits.replace("{n}", String(row.bid_credits || 0))}</Text>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={buying === `demand-${row.id}`}
                      onClick={() => {
                        if (!requireAuth(commercePage("marketplace"))) return;
                        setBuying(`demand-${row.id}`);
                        void vibeApi
                          .claimPackDemand(row.id)
                          .then((claimed) => {
                            showSuccess(copy.workbenchUi.demandClaim);
                            const workId = claimed.work_id || row.work_id;
                            if (workId) {
                              Taro.navigateTo({ url: studioPage("workbenchLite", { workId }) });
                            }
                          })
                          .catch(() => showError(m.purchaseFail))
                          .finally(() => setBuying(null));
                      }}
                    >
                      {copy.workbenchUi.demandClaim}
                    </Button>
                  </View>
                </View>
              ))}
            </>
          )}
          <SectionLabel>{m.templatesLabel}</SectionLabel>
        </>
      )}

      {loading && <LoadingSkeleton count={3} />}
      {!loading && templates.length === 0 && packs.length === 0 && (recipesOnly || effectPacks.length === 0) && (
        <EmptyState
          iconName="music"
          title={m.empty}
          description={m.emptyDesc}
          actionLabel={copy.tabBar.create}
          onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
        />
      )}
      {templates.map((tpl) => (
        <View key={tpl.id} className="marketplace-card">
          {tpl.cover_url ? <Image className="marketplace-card__cover" src={tpl.cover_url} mode="aspectFill" /> : <View className="marketplace-card__cover" />}
          <Text className="marketplace-card__title">{tpl.title}</Text>
          {tpl.author_username && <Text className="marketplace-card__author">{m.byAuthor.replace("{user}", tpl.author_username)}</Text>}
          {tpl.description && <Text className="typo-meta">{tpl.description}</Text>}
          {(tpl.moods?.length || tpl.genres?.length) ? (
            <View className="marketplace-card__chips">
              {[...(tpl.moods || []), ...(tpl.genres || [])].slice(0, 4).map((chip) => (
                <Tag key={chip}>{chip}</Tag>
              ))}
            </View>
          ) : null}
          <View className="marketplace-card__row">
            <Text className="marketplace-card__price">
              {tpl.price_credits > 0 ? m.priceCredits.replace("{n}", String(tpl.price_credits)) : m.free}
            </Text>
            <Button size="sm" variant="secondary" loading={buying === `tpl-${tpl.id}`} onClick={() => void buyTemplate(tpl.id)}>
              {tpl.price_credits > 0 ? m.buy : m.use}
            </Button>
          </View>
        </View>
      ))}

      {packs.length > 0 && <SectionLabel>{m.packsLabel}</SectionLabel>}
      {packs.map((pack) => (
        <View key={pack.id} className="marketplace-card">
          <Text className="marketplace-card__title">{pack.title}</Text>
          {pack.owner_username && <Text className="marketplace-card__author">{m.byAuthor.replace("{user}", pack.owner_username)}</Text>}
          <Text className="typo-meta">{m.packWorks.replace("{n}", String(pack.work_count))}</Text>
          <View className="marketplace-card__row">
            <Text className="marketplace-card__price">{m.priceCredits.replace("{n}", String(pack.price_credits))}</Text>
            <Button size="sm" variant="secondary" loading={buying === `pack-${pack.id}`} onClick={() => void buyPack(pack.id)}>
              {m.packBuy}
            </Button>
          </View>
        </View>
      ))}
    </PageShell>
  );
}
