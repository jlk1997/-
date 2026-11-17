import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh, useRouter, useShareAppMessage } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { PageShell } from "../../../components/PageShell";
import { AsyncPanel, Badge, ChipGroup, EmptyState, SectionLabel, ShareButton, StatusLine } from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { usePlayerTransport } from "../../../contexts/PlayerProvider";
import { openWorkForOwner } from "../../../utils/workNav";
import { sharePage, workSharePayload } from "../../../platform/share";
import { captureReferralFromQuery, myReferralCode } from "../../../platform/referral";
import { getItem, setItem } from "../../../platform/storage";
import { socialPage } from "../../../constants/routes";
import { isLoggedIn } from "../../../utils/auth";
import { startSameStyle } from "../../../utils/sameStyleNav";
import { hapticLight } from "../../../utils/haptic";
import "./index.scss";

const LAST_STATION_KEY = "radio:lastStation";

type Station = { code: string; name?: string; blurb?: string; of_the_day?: boolean };
type Track = {
  work_id: string;
  title?: string;
  author?: string;
  cover_url?: string;
  audio_url?: string;
  featured?: boolean;
  trial?: boolean;
  badge?: string;
  lineage_seed?: boolean;
  station?: string;
  is_mine?: boolean;
};
type ChartRow = { rank: number; work_id: string; title?: string; cover_url?: string; completes?: number };

type RadioPayload = {
  stations?: Station[];
  station_of_day?: string;
  tracks?: Track[];
  chart?: ChartRow[];
  lineage_seed?: { work_id: string; title?: string; remixes?: number } | null;
  usable_for_settlement?: boolean;
  rules?: { min_listen_ratio?: number; revenue_minor_per_complete?: number; member_revenue_minor_per_complete?: number };
};

export default function RadioNetworkPage() {
  const { copy } = useLocale();
  const e = copy.engagementUi;
  const { playTrack, currentTrackId, isPlaying } = usePlayerTransport();
  const router = useRouter();
  const focusWorkId = String(router.params.workId || "");
  const [station, setStation] = useState(String(router.params.station || getItem(LAST_STATION_KEY) || ""));
  const [mineIds, setMineIds] = useState<Set<string>>(new Set());
  const [focusTrack, setFocusTrack] = useState<Track | null>(null);
  const [catalogTracks, setCatalogTracks] = useState<Track[]>([]);
  const autoPlayedRef = useRef("");

  const mineAt = useRef(0);
  const { data, loading, error, reload } = useAsyncQuery<RadioPayload | null>(
    async () => {
      return (await vibeApi.getRadioStation(station || undefined, 8)) as RadioPayload;
    },
    [station],
    { staleMs: 15_000 },
  );

  useDidShow(() => {
    captureReferralFromQuery(router.params as Record<string, unknown>);
    const nextStation = String(router.params.station || "");
    if (nextStation && nextStation !== station) setStation(nextStation);
    void reload();
    if (!isLoggedIn()) {
      setMineIds(new Set());
      mineAt.current = 0;
    } else if (!mineAt.current || Date.now() - mineAt.current > 30_000) {
      vibeApi
        .listWorks("newest", undefined, 40)
        .then((list) => {
          mineAt.current = Date.now();
          setMineIds(new Set(list.map((w) => w.id)));
        })
        .catch(() => setMineIds(new Set()));
    }
  });
  usePullDownRefresh(async () => {
    await reload(true);
    Taro.stopPullDownRefresh();
  });

  useEffect(() => {
    if (!focusWorkId) {
      setFocusTrack(null);
      return;
    }
    vibeApi
      .getRadioTrial(focusWorkId)
      .then((trial) => {
        const code = typeof trial.station === "string" ? trial.station : "";
        if (code && !router.params.station) setStation(code);
        const hop = typeof trial.work_id === "string" && trial.work_id ? trial.work_id : focusWorkId;
        return vibeApi.getWork(hop);
      })
      .catch(() => vibeApi.getWork(focusWorkId))
      .then((w) => {
        if (!w.audio_url) return;
        setFocusTrack({
          work_id: w.id,
          title: w.title,
          author: w.artist_name || w.owner_username,
          cover_url: w.cover_url,
          audio_url: w.audio_url,
          trial: true,
          is_mine: Boolean(w.is_owner),
        });
      })
      .catch(() => setFocusTrack(null));
  }, [focusWorkId, router.params.station]);

  const stations = (data?.stations || []).length
    ? data?.stations || []
    : [
        { code: "daily", name: "daily" },
        { code: "night", name: "night" },
        { code: "calm", name: "calm" },
        { code: "focus", name: "focus" },
        { code: "commute", name: "commute" },
      ];
  const current = station || data?.station_of_day || "daily";

  useEffect(() => {
    vibeApi
      .listOfficialCatalog(current)
      .then((res) => {
        setCatalogTracks(
          (res.tracks || []).map((row) => ({
            work_id: row.id,
            title: row.title,
            author: row.author,
            audio_url: row.audio_url,
            featured: true,
            station: current,
          })),
        );
      })
      .catch(() => setCatalogTracks([]));
  }, [current]);

  const tracks = useMemo(() => {
    const list = (data?.tracks || []).length ? data?.tracks || [] : catalogTracks;
    if (!focusTrack) return list;
    if (list.some((t) => t.work_id === focusTrack.work_id)) {
      return list.map((t) => (t.work_id === focusTrack.work_id ? { ...t, trial: t.trial || focusTrack.trial } : t));
    }
    return [focusTrack, ...list];
  }, [data?.tracks, catalogTracks, focusTrack]);

  useEffect(() => {
    if (current) setItem(LAST_STATION_KEY, current);
  }, [current]);

  useShareAppMessage((res) => {
    const ds = (res?.target as { dataset?: Record<string, string> } | undefined)?.dataset;
    if (ds?.workid) return workSharePayload(ds.workid, ds.title || copy.brand.name);
    return {
      title: e.radioNetworkTitle,
      path: socialPage("radio", { station: current || undefined, ref: myReferralCode() || undefined }),
    };
  });
  const queue = useMemo(
    () =>
      tracks
        .filter((t) => t.audio_url)
        .map((t) =>
          workToPlayerTrack(
            { id: t.work_id, title: t.title || e.radioUntitled.replace("{n}", "1"), audio_url: t.audio_url || "", cover_url: t.cover_url },
            {
              artist: t.author,
              source: t.work_id.startsWith("catalog:") ? "catalog" : "radio",
              station: t.station || current,
              isOwner: t.is_mine === true || mineIds.has(t.work_id) || undefined,
            },
          ),
        ),
    [tracks, current, e.radioUntitled, mineIds],
  );

  useEffect(() => {
    if (!queue.length) return;
    if (focusWorkId) {
      if (autoPlayedRef.current === focusWorkId) return;
      const idx = queue.findIndex((t) => t.id === focusWorkId);
      if (idx < 0) return;
      autoPlayedRef.current = focusWorkId;
      playTrack(queue[idx], { queue, startIndex: idx, navigate: false });
      return;
    }
    const stationKey = `station:${current}`;
    // Station enter is tap-to-play. Only a deep-linked track auto-starts.
    autoPlayedRef.current = stationKey;
  }, [focusWorkId, queue, current, playTrack]);

  function play(track: Track, index: number) {
    if (!track.audio_url) {
      Taro.showToast({ title: e.radioNoAudio, icon: "none" });
      return;
    }
    const item = queue[index] || queue[0];
    if (!item) return;
    hapticLight();
    playTrack(item, { queue, startIndex: index, navigate: false });
    Taro.showToast({ title: e.radioPlaying, icon: "none" });
  }

  const heroTrack = useMemo(() => {
    const playing = tracks.find((t) => t.work_id === currentTrackId);
    if (playing) return playing;
    if (focusTrack) return focusTrack;
    return tracks[0] || null;
  }, [tracks, currentTrackId, focusTrack]);

  return (
    <PageShell
      title={e.radioNetworkTitle}
      subtitle={e.radioNetworkHint}
      ambient
      actions={
        <ShareButton
          className="ui-btn ui-btn--ghost ui-btn--sm"
          onShare={() =>
            sharePage(
              e.radioNetworkTitle,
              socialPage("radio", { station: current || undefined, ref: myReferralCode() || undefined }),
            )
          }
        >
          {copy.player.share}
        </ShareButton>
      }
    >
      <AsyncPanel
        loading={loading}
        error={Boolean(error) && catalogTracks.length === 0}
        errorTitle={copy.worksUi.loadFail}
        errorActionLabel={copy.discoverUi.retry}
        onRetry={() => void reload()}
      >
        <ChipGroup
          options={stations.map((row) => ({
            value: row.code,
            label: row.of_the_day ? `${row.name || row.code} · ${e.radioOfDay}` : row.name || row.code,
          }))}
          value={current}
          onChange={setStation}
        />
        <Text className="radio-net__blurb">{stations.find((row) => row.code === current)?.blurb || e.radioNetworkHint}</Text>
        <StatusLine tone="info" density="quiet">{e.radioDiscoveryOnly}</StatusLine>
        <Text className="typo-meta">{e.radioHeroHint}</Text>
        {data?.lineage_seed && (current === "lineage" || !station) ? (
          <Text className="radio-net__lineage">
            {e.radioLineageSeed.replace("{title}", data.lineage_seed.title || data.lineage_seed.work_id)}
            {` · ${e.radioLineageRemixes.replace("{n}", String(data.lineage_seed.remixes || 0))}`}
          </Text>
        ) : null}

        <SectionLabel>{e.radioNowPlaying}</SectionLabel>
        {heroTrack ? (
          <>
            <View
              className="radio-net__hero"
              onClick={() => play(heroTrack, Math.max(0, tracks.findIndex((t) => t.work_id === heroTrack.work_id)))}
            >
              {heroTrack.cover_url ? (
                <Image className="radio-net__hero-cover" src={heroTrack.cover_url} mode="aspectFill" />
              ) : (
                <View className="radio-net__hero-cover" />
              )}
              <View className="radio-net__hero-body">
                {heroTrack.trial ? <Badge tone="info">{e.radioTrialBadge}</Badge> : null}
                <Text className="radio-net__hero-title">{heroTrack.title || e.radioUntitled.replace("{n}", "1")}</Text>
                <Text className="radio-net__hero-hint">{e.radioHeroHint}</Text>
              </View>
            </View>
            <Text
              className="radio-net__hero-same"
              onClick={() => startSameStyle(heroTrack.work_id, heroTrack.title)}
            >
              {copy.derivative.startSameStyle}
            </Text>
          </>
        ) : null}
        {tracks.length === 0 && (
          <EmptyState
            iconName="music"
            title={e.radioEmpty}
            description={e.radioEmptyDesc}
            actionLabel={e.radioEmptyCta}
            onAction={() => Taro.switchTab({ url: "/pages/feed/index" })}
          />
        )}
        <View className="radio-net__list">
          {tracks.map((track, index) => {
            const playing = currentTrackId === track.work_id && isPlaying;
            return (
              <View
                key={track.work_id}
                className={playing ? "radio-net__item radio-net__item--playing" : "radio-net__item"}
                onClick={() => play(track, index)}
              >
                <View className="radio-net__cover-wrap">
                  {track.cover_url ? <Image className="radio-net__cover" src={track.cover_url} mode="aspectFill" /> : <View className="radio-net__cover" />}
                  {playing ? <View className="radio-net__play-dot">{e.radioPlaying}</View> : null}
                </View>
                <View className="radio-net__meta">
                  <Text className="radio-net__title">{track.title || e.radioUntitled.replace("{n}", String(index + 1))}</Text>
                  <Text className="radio-net__author">@{track.author || "?"}</Text>
                </View>
                {track.featured ? <Badge tone="accent">{e.radioFeatured}</Badge> : null}
                {track.trial ? <Badge tone="info">{e.radioTrialBadge}</Badge> : null}
                {track.badge === "lineage_seed" || track.lineage_seed ? <Badge tone="warning">{e.radioLineageBadge}</Badge> : null}
              </View>
            );
          })}
        </View>

        <SectionLabel>{e.radioChartTitle}</SectionLabel>
        <Text className="typo-meta">{e.radioDisplayOnly}</Text>
        {(data?.chart || []).length === 0 && (
          <EmptyState
            iconName="music"
            title={e.radioChartEmpty}
            actionLabel={copy.socialUi.chartsEntry}
            onAction={() => Taro.navigateTo({ url: socialPage("charts") })}
          />
        )}
        {(data?.chart || []).map((row) => (
          <View
            key={row.work_id}
            className="radio-net__item"
            onClick={() => openWorkForOwner(row.work_id, mineIds.has(row.work_id))}
          >
            <Text className="radio-net__rank">{row.rank}</Text>
            {row.cover_url ? <Image className="radio-net__cover" src={row.cover_url} mode="aspectFill" /> : <View className="radio-net__cover" />}
            <View className="radio-net__meta">
              <Text className="radio-net__title">{row.title || row.work_id}</Text>
              <Text className="radio-net__author">{e.radioCompletes.replace("{n}", String(row.completes || 0))}</Text>
            </View>
          </View>
        ))}
      </AsyncPanel>
    </PageShell>
  );
}
