import { useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { PageShell, SectionLabel } from "../../../components/PageShell";
import { Button, EmptyState, LoadingSkeleton, RingGauge, StatusLine } from "../../../components/ui";
import { usePlayer } from "../../../contexts/PlayerProvider";
import { commercePage, creatorPage, socialPage, stackPage } from "../../../constants/routes";
import { goShipBand } from "../../../packageCreator/nextActionNav";
import { vibeApi } from "../../../services/api";
import { bootstrapAuth, isLoggedIn } from "../../../utils/auth";
import { openRadioPage } from "../../../utils/navigation";
import "./index.scss";

type Entry = {
  id: string;
  entry_date: string;
  arousal?: number;
  valence?: number;
  work_id?: string;
  mood_tags?: string[];
};

type WeekDrop = {
  station?: string;
  station_name?: string;
  station_blurb?: string;
  station_of_day?: string;
  why?: string;
  next_action?: string;
  work?: { work_id: string; title?: string; cover_url?: string; qc_ready?: boolean; from_workbench?: boolean } | null;
  radio_trial?: { live?: boolean; status?: string } | null;
};

export default function EmotionCalendarPage() {
  const { copy } = useLocale();
  const cal = copy.emotionCalendarUi;
  const { playTrack } = usePlayer();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [album, setAlbum] = useState<Awaited<ReturnType<typeof vibeApi.getMonthlyEmotionAlbum>> | null>(null);
  const [suggestions, setSuggestions] = useState<
    Array<{
      work_id: string;
      title?: string;
      why?: string;
      qc_ready?: boolean;
      channel_suggestion?: { reason?: string };
    }>
  >([]);
  const [weekDrop, setWeekDrop] = useState<WeekDrop | null>(null);
  const [loading, setLoading] = useState(true);
  const [loggedIn, setLoggedIn] = useState(isLoggedIn());
  const [playing, setPlaying] = useState(false);
  const [trialBusy, setTrialBusy] = useState(false);

  useDidShow(() => {
    bootstrapAuth();
    const ok = isLoggedIn();
    setLoggedIn(ok);
    if (!ok) {
      setLoading(false);
      return;
    }
    setLoading(true);
    Promise.all([
      vibeApi.getEmotionCalendar(),
      vibeApi.getMonthlyEmotionAlbum(),
      vibeApi.getReleaseCalendar().catch(() => ({ suggestions: [] })),
    ])
      .then(([res, alb, calRes]) => {
        setEntries(res.entries);
        setAlbum(alb);
        setSuggestions(calRes.suggestions || []);
        setWeekDrop(res.week_drop || calRes.week_drop || null);
      })
      .catch(() => Taro.showToast({ title: cal.loadFail, icon: "none" }))
      .finally(() => setLoading(false));
  });

  async function playAlbum() {
    if (!album?.track_count || playing) return;
    if (album.playlist_id) {
      Taro.navigateTo({ url: `/pages/playlist/index?id=${album.playlist_id}` });
      return;
    }
    if (!album.work_ids?.length) return;
    setPlaying(true);
    try {
      const works = await Promise.all(album.work_ids.map((id) => vibeApi.getWork(id)));
      const tracks = works.filter((w) => w.audio_url).map((w) => workToPlayerTrack(w, { source: "emotion-calendar" }));
      if (!tracks.length) {
        Taro.showToast({ title: cal.playFail, icon: "none" });
        return;
      }
      playTrack(tracks[0], { queue: tracks, navigate: true });
    } catch {
      Taro.showToast({ title: cal.playFail, icon: "none" });
    } finally {
      setPlaying(false);
    }
  }

  async function startTrial() {
    const workId = weekDrop?.work?.work_id;
    if (!workId || trialBusy) return;
    setTrialBusy(true);
    try {
      const trial = (await vibeApi.startRadioTrial(workId, weekDrop?.station)) as {
        work_id?: string;
        station?: string;
      };
      Taro.showToast({ title: cal.trialOk, icon: "success" });
      Taro.navigateTo({
        url: socialPage("radio", {
          workId: trial.work_id || workId,
          station: typeof trial.station === "string" ? trial.station : weekDrop?.station,
        }),
      });
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setTrialBusy(false);
    }
  }

  const byDate = entries.reduce<Record<string, Entry[]>>((acc, e) => {
    (acc[e.entry_date] ||= []).push(e);
    return acc;
  }, {});

  if (!loggedIn) {
    return (
      <PageShell title={cal.title} subtitle={cal.subtitle} wide ambient>
        <EmptyState
          iconName="journey"
          title={cal.loginTitle}
          description={cal.loginDesc}
          actionLabel={copy.profileUi.loginButton}
          onAction={() =>
            Taro.navigateTo({
              url: stackPage("login", { next: stackPage("emotionCalendar") }),
            })
          }
        />
      </PageShell>
    );
  }

  return (
    <PageShell title={cal.title} subtitle={cal.subtitle} wide ambient>
      {loading && <LoadingSkeleton count={4} />}
      {!loading && weekDrop && (
        <View className="emotion-cal__album">
          <Text className="emotion-cal__album-title">{cal.weekDropTitle}</Text>
          <Text className="typo-meta">
            {cal.stationOfDay.replace("{s}", weekDrop.station_name || weekDrop.station || "—")}
          </Text>
          {weekDrop.station_blurb ? <StatusLine tone="info">{weekDrop.station_blurb}</StatusLine> : null}
          {weekDrop.work ? (
            <>
              <Text className="emotion-cal__entry-moods">
                {[weekDrop.work.title || weekDrop.work.work_id, weekDrop.work.from_workbench ? copy.worksUi.beautifyMaster : ""]
                  .filter(Boolean)
                  .join(" · ")}
              </Text>
              <Text className="typo-meta">
                {weekDrop.why === "emotion_week"
                  ? cal.weekDropWhy
                  : weekDrop.why === "trial_ended"
                    ? copy.creatorUi.trialEndedRelease
                    : cal.releaseThisWeek}
              </Text>
              <View className="emotion-cal__album-stats">
                {weekDrop.next_action === "radio_trial" && (
                  <Button variant="primary" size="sm" loading={trialBusy} onClick={() => void startTrial()}>
                    {copy.creatorUi.radioTrialStart}
                  </Button>
                )}
                {weekDrop.next_action === "watch_trial" && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() =>
                      Taro.navigateTo({
                        url: socialPage("radio", {
                          workId: weekDrop.work?.work_id,
                          station: weekDrop.station,
                        }),
                      })
                    }
                  >
                    {copy.creatorUi.goRadio}
                  </Button>
                )}
                {weekDrop.work.work_id && weekDrop.next_action === "sync" && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() =>
                      Taro.navigateTo({ url: commercePage("syncDesk", { workId: weekDrop.work?.work_id }) })
                    }
                  >
                    {copy.creatorUi.nextSync}
                  </Button>
                )}
                {weekDrop.work.work_id && weekDrop.next_action === "wallet" && (
                  <Button variant="primary" size="sm" onClick={() => Taro.navigateTo({ url: creatorPage("wallet") })}>
                    {copy.creatorUi.nextWallet}
                  </Button>
                )}
                {weekDrop.work.work_id && weekDrop.next_action === "stores" && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() =>
                      Taro.navigateTo({ url: creatorPage("deliveries", { workId: weekDrop.work?.work_id }) })
                    }
                  >
                    {copy.creatorUi.nextStores}
                  </Button>
                )}
                {weekDrop.work.work_id &&
                  weekDrop.next_action !== "sync" &&
                  weekDrop.next_action !== "wallet" &&
                  weekDrop.next_action !== "stores" &&
                  weekDrop.next_action !== "radio_trial" &&
                  weekDrop.next_action !== "watch_trial" && (
                  <Button
                    variant={weekDrop.next_action === "release" ? "primary" : "ghost"}
                    size="sm"
                    onClick={() =>
                      goShipBand(weekDrop.work?.work_id || "")
                    }
                  >
                    {weekDrop.next_action === "release" ? copy.creatorUi.trialEndedRelease : cal.goRelease}
                  </Button>
                )}
                {!weekDrop.next_action ||
                (weekDrop.next_action !== "radio_trial" &&
                  weekDrop.next_action !== "watch_trial" &&
                  weekDrop.next_action !== "sync" &&
                  weekDrop.next_action !== "wallet" &&
                  weekDrop.next_action !== "stores" &&
                  weekDrop.next_action !== "release") ? (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() =>
                      Taro.navigateTo({
                        url: socialPage("radio", {
                          workId: weekDrop.work?.work_id,
                          station: weekDrop.station,
                        }),
                      })
                    }
                  >
                    {cal.goRadio}
                  </Button>
                ) : null}
              </View>
            </>
          ) : (
            <Text className="typo-meta">{cal.weekDropEmpty}</Text>
          )}
        </View>
      )}
      {!loading && album && (
        <View className="emotion-cal__album">
          <Text className="emotion-cal__album-title">{album.title}</Text>
          <View className="emotion-cal__album-stats">
            <RingGauge value={Math.round((album.avg_valence || 3) * 20)} max={100} label={cal.avgMood} />
            <RingGauge value={Math.round((album.avg_arousal || 3) * 20)} max={100} label={cal.avgEnergy} />
          </View>
          <Text className="typo-meta">{cal.trackCount.replace("{n}", String(album.track_count))}</Text>
          {album.track_count > 0 && (
            <Button variant="secondary" size="sm" loading={playing} onClick={() => void playAlbum()}>
              {cal.playAlbum}
            </Button>
          )}
          {album.track_count > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                const text = `${album.title} · ${cal.trackCount.replace("{n}", String(album.track_count))} · A${Math.round((album.avg_arousal || 3) * 10) / 10} V${Math.round((album.avg_valence || 3) * 10) / 10}`;
                Taro.setClipboardData({ data: text });
                Taro.showToast({ title: cal.shareAlbumCopied, icon: "success" });
              }}
            >
              {cal.shareAlbum}
            </Button>
          )}
        </View>
      )}

      {suggestions.length > 0 && (
        <>
          <SectionLabel>{cal.releaseThisWeek}</SectionLabel>
          {suggestions.map((item) => (
            <View
              key={item.work_id}
              className="emotion-cal__entry"
              onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId: item.work_id }) })}
            >
              <Text className="emotion-cal__entry-moods">{item.title || item.work_id}</Text>
              <Text className="typo-meta">
                {item.channel_suggestion?.reason ||
                  (item.why === "emotion_week"
                    ? cal.weekDropWhy
                    : item.why === "winner"
                      ? copy.creatorUi.whyWinner
                      : item.why === "listens"
                        ? copy.creatorUi.whyListens
                        : item.why === "qc_ready"
                          ? copy.creatorUi.whyQc
                          : cal.goRelease)}
              </Text>
            </View>
          ))}
        </>
      )}

      <SectionLabel>{cal.recentLabel}</SectionLabel>
      {!loading && entries.length === 0 && (
        <EmptyState
          iconName="journey"
          title={cal.empty}
          description={cal.emptyDesc}
          actionLabel={copy.engagementUi.radioOpen}
          onAction={() => openRadioPage()}
        />
      )}
      {Object.keys(byDate)
        .sort((a, b) => b.localeCompare(a))
        .map((day) => (
          <View key={day} className="emotion-cal__day">
            <Text className="emotion-cal__day-label">{day}</Text>
            {byDate[day].map((e) => (
              <View key={e.id} className="emotion-cal__entry" onClick={() => e.work_id && Taro.navigateTo({ url: stackPage("work", { workId: e.work_id }) })}>
                <Text className="emotion-cal__entry-moods">{e.mood_tags?.join(" · ") || cal.noMoods}</Text>
                <Text className="typo-meta">A{e.arousal ?? "—"} V{e.valence ?? "—"}</Text>
              </View>
            ))}
          </View>
        ))}
    </PageShell>
  );
}
