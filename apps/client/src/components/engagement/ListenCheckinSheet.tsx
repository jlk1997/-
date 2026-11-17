import { useEffect, useRef, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { CREATOR_TAB_ROUTE, stackPage, socialPage } from "../../constants/routes";
import { goShipBand } from "../../packageCreator/nextActionNav";
import { vibeApi } from "../../services/api";
import { isLoggedIn, requireAuth } from "../../utils/auth";
import { consumePendingCheckin, peekPendingCheckin, savePendingCheckin } from "../../platform/pendingCheckin";
import { setItem } from "../../platform/storage";
import { openRadioPage, openStackPage } from "../../utils/navigation";
import { Button, StatusLine } from "../ui";
import { hapticLight } from "../../utils/haptic";
import { MoodSharePoster } from "./MoodSharePoster";
import "./ListenCheckinSheet.scss";

type Props = {
  workId: string;
  workTitle?: string;
  listenRatio: number;
  station?: string;
  isOwner?: boolean;
  onDone?: () => void;
  onDismiss?: () => void;
};

type CheckinMood = { key: "calm" | "joy" | "melancholy" | "energy"; arousal: number; valence: number; label: string };

export function ListenCheckinSheet({ workId, workTitle, listenRatio, station, isOwner, onDone, onDismiss }: Props) {
  const { copy } = useLocale();
  const e = copy.engagementUi;
  const [submitting, setSubmitting] = useState(false);
  const [trialBusy, setTrialBusy] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [channelHint, setChannelHint] = useState("");
  const [ownerMetaReady, setOwnerMetaReady] = useState(!isOwner);
  const [pickedMood, setPickedMood] = useState<CheckinMood | null>(null);
  const [inviteLine, setInviteLine] = useState("");
  const [payoutMinor, setPayoutMinor] = useState(0);
  const autoResumeRef = useRef(false);

  const moods: CheckinMood[] = [
    { key: "calm" as const, arousal: 3, valence: 6, label: e.moodCalm },
    { key: "joy" as const, arousal: 6, valence: 8, label: e.moodJoy },
    { key: "melancholy" as const, arousal: 3, valence: 3, label: e.moodMelancholy },
    { key: "energy" as const, arousal: 8, valence: 7, label: e.moodEnergy },
  ];
  const guest = !isLoggedIn();

  useEffect(() => {
    if (autoResumeRef.current || !isLoggedIn()) return;
    const pending = peekPendingCheckin();
    if (!pending || pending.work_id !== workId) return;
    const mood = moods.find((m) => m.key === pending.mood_tags?.[0]);
    if (!mood) return;
    autoResumeRef.current = true;
    void submit(mood);
    // Resume once after login.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workId]);

  async function submit(mood: (typeof moods)[number]) {
    if (!isLoggedIn()) {
      savePendingCheckin({
        work_id: workId,
        workTitle,
        listen_ratio: listenRatio,
        arousal: mood.arousal,
        valence: mood.valence,
        mood_tags: [mood.key],
        station,
      });
      onDone?.();
      requireAuth(stackPage("work", { workId, play: "1" }));
      return;
    }
    setSubmitting(true);
    try {
      const res = await vibeApi.listenCheckin({
        work_id: workId,
        listen_ratio: listenRatio,
        arousal: mood.arousal,
        valence: mood.valence,
        mood_tags: [mood.key],
        station,
      });
      consumePendingCheckin();
      const paid = Boolean(res.settled && Number(res.payout_minor) > 0);
      if (res.credits_granted) {
        Taro.showToast({ title: e.checkinReward.replace("{n}", String(res.credits_granted)), icon: "success" });
      } else if (res.duplicate) {
        Taro.showToast({ title: e.checkinDuplicate, icon: "none" });
      } else if (!paid) {
        Taro.showToast({ title: e.checkinThanks, icon: "success" });
      }
      setPayoutMinor(Number(res.payout_minor) || 0);
      setCompleted(true);
      setPickedMood(mood);
      vibeApi
        .getReferral()
        .then((ref) => {
          if (ref?.referral_code) setInviteLine(`${e.checkinSharePoster} · ${ref.referral_code}`);
        })
        .catch(() => {});
      if (isOwner) {
        vibeApi
          .getCreatorWork(workId)
          .then((ledger) => {
            const reason =
              (ledger as { channel_suggestion?: { reason?: string }; radio_trial?: { channel_suggestion?: { reason?: string } } } | null)
                ?.channel_suggestion?.reason ||
              (ledger as { radio_trial?: { channel_suggestion?: { reason?: string } } } | null)?.radio_trial?.channel_suggestion?.reason;
            if (reason) setChannelHint(reason);
          })
          .finally(() => setOwnerMetaReady(true));
      }
    } catch {
      Taro.showToast({ title: e.checkinFail, icon: "none" });
    } finally {
      setSubmitting(false);
    }
  }

  function goVariation() {
    onDone?.();
    setItem("create:seedWorkId", workId);
    setItem("create:mode", "variation");
    if (workTitle) setItem("create:seedTitle", workTitle);
    Taro.switchTab({ url: "/pages/create/index" });
  }

  function goDuel() {
    if (!requireAuth(stackPage("work", { workId, play: "1" }))) return;
    onDone?.();
    openStackPage(socialPage("duels", { workId }));
    void vibeApi.createDuel(workId).then((res) => {
      Taro.redirectTo({ url: socialPage("duel", { id: res.duel_id || res.id }) });
    }).catch(() => {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    });
  }

  function finish() {
    onDone?.();
  }

  function goRelease() {
    onDone?.();
    if (!requireAuth(CREATOR_TAB_ROUTE)) return;
    goShipBand(workId);
  }

  function goTrial() {
    if (!requireAuth(stackPage("work", { workId, play: "1" }))) return;
    setTrialBusy(true);
    onDone?.();
    openRadioPage({ workId, station, trial: "1" });
    void vibeApi
      .startRadioTrial(workId, station)
      .then((trial) => {
        Taro.showToast({ title: copy.creatorUi.radioTrialLive, icon: "success" });
        const nextWork = (trial as { work_id?: string }).work_id;
        const nextStation = (trial as { station?: string }).station;
        if (nextWork && nextWork !== workId) {
          openRadioPage({
            workId: nextWork,
            station: typeof nextStation === "string" ? nextStation : station,
          });
        }
      })
      .catch(() => {
        Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
      })
      .finally(() => setTrialBusy(false));
  }

  function goRadio() {
    onDone?.();
    openRadioPage({ workId, station });
  }

  return (
    <View className="listen-checkin">
      <View className="listen-checkin__backdrop" onClick={onDismiss} />
      <View className="listen-checkin__panel">
        {!completed ? (
          <>
            <Text className="listen-checkin__title">
              {submitting && autoResumeRef.current ? e.checkinResuming : e.checkinTitle}
            </Text>
            {workTitle ? <Text className="listen-checkin__sub">{workTitle}</Text> : null}
            {submitting && autoResumeRef.current ? (
              <Text className="listen-checkin__hint">{e.checkinResuming}</Text>
            ) : (
              <>
                <Text className="listen-checkin__hint">{isOwner ? e.radioDisplayOnly : guest ? e.checkinGuestHint : e.checkinHint}</Text>
                <View className="listen-checkin__moods">
                  {moods.map((m) => (
                    <View
                      key={m.key}
                      className="listen-checkin__mood"
                      onClick={() => {
                        if (submitting) return;
                        hapticLight();
                        void submit(m);
                      }}
                    >
                      <Text className="listen-checkin__mood-label">{m.label}</Text>
                    </View>
                  ))}
                </View>
                <Button size="sm" variant="ghost" disabled={submitting} onClick={onDismiss}>
                  {e.checkinSkip}
                </Button>
              </>
            )}
          </>
        ) : (
          <>
            <Text className="listen-checkin__title">{e.checkinThanks}</Text>
            {payoutMinor > 0 && !isOwner ? (
              <Text className="listen-checkin__sub listen-checkin__sub--paid">
                {e.checkinPaidCreator.replace("{n}", String(payoutMinor))}
              </Text>
            ) : null}
            {pickedMood ? (
              <MoodSharePoster
                title={workTitle || e.checkinTitle}
                before={pickedMood.key === "calm" || pickedMood.key === "melancholy" ? 7 : 4}
                after={Math.max(1, Math.min(10, Math.round(pickedMood.valence)))}
                inviteLine={inviteLine || e.checkinSharePoster}
                workId={workId}
              />
            ) : null}
            {isOwner && channelHint ? <Text className="listen-checkin__sub">{channelHint}</Text> : null}
            {isOwner && !ownerMetaReady ? (
              <Button variant="primary" block loading>
                {e.checkinCtaTrial}
              </Button>
            ) : isOwner ? (
              <Button variant="primary" block loading={trialBusy} onClick={() => void goTrial()}>
                {e.checkinCtaTrial}
              </Button>
            ) : (
              <Button variant="primary" block onClick={goRadio}>
                {e.checkinCtaRadio}
              </Button>
            )}
            {showMore ? (
              <>
                {isOwner ? (
                  <>
                    <StatusLine tone="info" density="quiet">
                      {e.checkinReleaseHint}
                    </StatusLine>
                    <Button size="sm" variant="ghost" block onClick={goRelease}>
                      {e.checkinCtaRelease}
                    </Button>
                  </>
                ) : null}
                <Button size="sm" variant="ghost" block onClick={goVariation}>
                  {e.checkinCtaVariation}
                </Button>
                <Button size="sm" variant="ghost" block onClick={() => void goDuel()}>
                  {e.checkinCtaDuel}
                </Button>
                <Button size="sm" variant="ghost" block onClick={finish}>
                  {e.checkinDone}
                </Button>
              </>
            ) : (
              <Button size="sm" variant="ghost" block onClick={() => setShowMore(true)}>
                {e.checkinMore}
              </Button>
            )}
          </>
        )}
      </View>
    </View>
  );
}
