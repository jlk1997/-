import { useState, useEffect, useRef } from "react";
import { View, Text, Image } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { Button, Collapsible } from "../ui";
import { vibeApi } from "../../services/api";
import { usePlayer } from "../../contexts/PlayerProvider";
import { startCover, startRemelt, startSameStyle } from "../../utils/sameStyleNav";
import { creatorPage } from "../../constants/routes";
import { goShipBand } from "../../packageCreator/nextActionNav";
import { isDesktopWorkbench, openWorkbench } from "../../utils/workbenchNav";
import { startWorkbenchRegen } from "../../utils/workbenchRegen";
import { saveFileFromUrl } from "../../platform/media";
import "./WorkLightEditor.scss";

type Props = {
  workId: string;
  title: string;
  bpm?: number;
  musicKey?: string;
  arousal?: number;
  valence?: number;
};

const SECTION_LABEL: Record<string, "sectionVerse" | "sectionChorus" | "sectionBridge"> = {
  verse: "sectionVerse",
  chorus: "sectionChorus",
  bridge: "sectionBridge",
};

export function WorkLightEditor({ workId, title, bpm, musicKey, arousal, valence }: Props) {
  const { copy } = useLocale();
  const e = copy.lightEditorUi;
  const { playTrack } = usePlayer();
  const [hints, setHints] = useState<{
    bpm?: number | null;
    key?: string | null;
    arousal?: number | null;
    valence?: number | null;
    suggested_intent?: string;
    sections?: Array<{ id: string; start: number; end: number }>;
    clip_windows?: Array<{ length?: number; start?: number; end?: number }>;
    human_edits?: Array<{ kind?: string; section?: string }>;
    duration?: number | null;
    waveform_url?: string | null;
    audio_url?: string | null;
    remelt_explain?: string | null;
    stems?: { quality?: string; grade?: string; stems?: string[] };
    sku_kind?: string | null;
  } | null>(null);
  const [busy, setBusy] = useState("");
  const [semitones, setSemitones] = useState(0);
  const [tempo, setTempo] = useState(1);
  const dragRef = useRef<{ id: string; x: number } | null>(null);
  const draftIdRef = useRef<string | undefined>();
  const draftVerRef = useRef<number | undefined>();
  const draftReadyRef = useRef(false);

  useEffect(() => {
    vibeApi
      .getWorkRefineHints(workId)
      .then((res) => setHints(res))
      .catch(() => {});
    vibeApi
      .listDrafts()
      .then((rows) => {
        const hit = rows.find((row) => row.mode === "lightEditor" && row.payload?.workId === workId);
        if (!hit) return;
        draftIdRef.current = hit.id;
        draftVerRef.current = hit.version;
        if (typeof hit.payload.semitones === "number") setSemitones(hit.payload.semitones as number);
        if (typeof hit.payload.tempo === "number") setTempo(hit.payload.tempo as number);
      })
      .catch(() => {})
      .finally(() => {
        draftReadyRef.current = true;
      });
  }, [workId]);

  useEffect(() => {
    if (!draftReadyRef.current) return undefined;
    const timer = setTimeout(() => {
      vibeApi
        .saveDraft(
          `${title || "light"} polish`,
          "lightEditor",
          { workId, semitones, tempo, sections: hints?.sections || [] },
          draftIdRef.current,
          draftVerRef.current,
        )
        .then((row) => {
          draftIdRef.current = row.id;
          draftVerRef.current = row.version;
        })
        .catch(() => {});
    }, 900);
    return () => clearTimeout(timer);
  }, [workId, title, semitones, tempo, hints?.sections]);

  const resolvedBpm = bpm ?? hints?.bpm ?? undefined;
  const resolvedKey = musicKey ?? hints?.key ?? undefined;
  const resolvedArousal = arousal ?? hints?.arousal ?? undefined;
  const resolvedValence = valence ?? hints?.valence ?? undefined;
  const sections = hints?.sections || [];
  const clips = hints?.clip_windows || [];

  async function persistSection(next: { id: string; start: number; end: number }, note?: string) {
    try {
      await vibeApi.recordHumanEdit(workId, {
        kind: "section",
        section: next.id,
        start: next.start,
        end: next.end,
        note,
      });
      Taro.showToast({ title: e.humanEdit, icon: "success" });
      setHints((prev) => ({
        ...(prev || {}),
        sections: (prev?.sections || []).map((row) => (row.id === next.id ? next : row)),
        human_edits: [...(prev?.human_edits || []), { kind: "section", section: next.id }],
      }));
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    }
  }

  function nudgeSection(id: string, delta: number) {
    const current = sections.find((row) => row.id === id);
    if (!current) return;
    const start = Math.max(0, Math.round((current.start + delta) * 10) / 10);
    const end = Math.max(start + 4, Math.round((current.end + delta) * 10) / 10);
    void persistSection({ id, start, end }, "nudge");
  }

  function previewSection(sec: { start: number }) {
    const url = hints?.audio_url;
    if (!url) {
      Taro.showToast({ title: e.previewFail, icon: "none" });
      return;
    }
    playTrack(workToPlayerTrack({ id: workId, title, audio_url: url }, { source: "studio" }), {
      navigate: false,
      startAt: Math.max(0, Number(sec.start) || 0),
    });
  }

  function onSectionTouchStart(id: string, clientX?: number) {
    if (clientX == null) return;
    dragRef.current = { id, x: clientX };
  }

  function onSectionTouchEnd(id: string, clientX?: number) {
    const start = dragRef.current;
    dragRef.current = null;
    if (!start || start.id !== id || clientX == null) return;
    const dx = clientX - start.x;
    if (Math.abs(dx) < 24) return;
    nudgeSection(id, dx < 0 ? -2 : 2);
  }

  async function applyTransform() {
    setBusy("transform");
    try {
      await vibeApi.syncWorkbenchFromLight({ work_id: workId, semitones, tempo });
      Taro.showToast({ title: copy.workbenchUi.lightMapped, icon: "success" });
      openWorkbench(workId, "lite");
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy("");
    }
  }

  async function applyMaster() {
    setBusy("master");
    try {
      await vibeApi.syncWorkbenchFromLight({ work_id: workId, semitones, tempo, master: true });
      Taro.showToast({ title: copy.workbenchUi.lightMapped, icon: "success" });
      openWorkbench(workId, "lite");
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy("");
    }
  }

  async function undoEdit() {
    setBusy("undo");
    try {
      await vibeApi.undoWorkEdit(workId);
      Taro.showToast({ title: e.undoEdit, icon: "success" });
    } catch {
      Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
    } finally {
      setBusy("");
    }
  }

  async function regenOnBench(kind: "extend" | "remelt" | "same_style", seconds: 15 | 30 = 15) {
    setBusy(kind === "extend" ? `extend${seconds}` : kind);
    try {
      await startWorkbenchRegen(workId, kind, seconds);
      Taro.showToast({ title: copy.workbenchUi.regenQueued, icon: "success" });
    } catch {
      if (kind === "extend") {
        try {
          await vibeApi.extendWork(workId, seconds);
          Taro.showToast({ title: e.extendQueued, icon: "success" });
        } catch {
          Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" });
        }
      } else if (kind === "remelt") {
        startRemelt(workId, title, hints?.suggested_intent);
      } else {
        startSameStyle(workId, title, hints?.suggested_intent);
      }
    } finally {
      setBusy("");
    }
  }

  async function makeInstrumentalSku() {
    setBusy("instrumental");
    try {
      const res = await vibeApi.spawnInstrumentalSku(workId);
      Taro.showToast({ title: e.instrumentalSkuOk, icon: "success" });
      if (res.work_id) {
        goShipBand(res.work_id);
      }
    } catch {
      Taro.showToast({ title: e.instrumentalSkuFail, icon: "none" });
    } finally {
      setBusy("");
    }
  }

  const stemQuality = String(hints?.stems?.quality || "");
  const reviewStems = stemQuality === "demucs";
  const isInstrumentalSku = hints?.sku_kind === "instrumental";

  async function exportStems() {
    setBusy("stems");
    try {
      const res = await vibeApi.exportWork(workId, "stems");
      const isolation = String(res.meta?.isolation || "");
      const format = String(res.meta?.format || "");
      if (!res.download_url || format !== "zip" || isolation === "unavailable") {
        Taro.showToast({ title: e.stemsFail, icon: "none" });
        return;
      }
      await saveFileFromUrl(res.download_url, `${title || "export"}-stems.zip`);
      Taro.showToast({ title: e.stemsSoon, icon: "success" });
    } catch {
      Taro.showToast({ title: e.stemsFail, icon: "none" });
    } finally {
      setBusy("");
    }
  }

  return (
    <View className="work-light-editor">
      <View className="work-light-editor__workbench">
        <Button
          variant="primary"
          size="sm"
          block
          loading={busy === "bounce"}
          onClick={() => {
            setBusy("bounce");
            void vibeApi
              .syncWorkbenchFromLight({ work_id: workId, semitones, tempo })
              .then(() => {
                Taro.showToast({ title: copy.workbenchUi.lightMapped, icon: "success" });
                openWorkbench(workId, "lite");
              })
              .catch(() => Taro.showToast({ title: copy.adminUi.actionFail, icon: "none" }))
              .finally(() => setBusy(""));
          }}
        >
          {e.bounceNewWork}
        </Button>
        <Button variant="secondary" size="sm" block onClick={() => openWorkbench(workId)}>
          {e.openBeautify}
        </Button>
        {isDesktopWorkbench() ? (
          <Button variant="ghost" size="sm" block onClick={() => openWorkbench(workId, "pro")}>
            {e.openMixer}
          </Button>
        ) : null}
        <Text className="typo-meta">{e.editLanesHint}</Text>
        <Text className="typo-meta">{e.editLanesNotReview}</Text>
      </View>
      {(() => {
        const railEnd = Number(hints?.duration || Math.max(0, ...sections.map((row) => row.end), 1));
        function onRailTouch(ev: { detail?: { x?: number }; changedTouches?: Array<{ clientX: number }> }) {
          const clientX = ev.changedTouches?.[0]?.clientX ?? ev.detail?.x;
          if (clientX == null) return;
          Taro.createSelectorQuery()
            .select("#light-editor-rail")
            .boundingClientRect((rect: { left?: number; width?: number } | null) => {
              if (!rect?.width) return;
              const ratio = Math.min(1, Math.max(0, (clientX - (rect.left || 0)) / rect.width));
              previewSection({ start: Math.round(ratio * railEnd * 10) / 10 });
            })
            .exec();
        }
        return (
          <View id="light-editor-rail" className="work-light-editor__rail" onClick={onRailTouch}>
            {hints?.waveform_url ? (
              <Image className="work-light-editor__wave" src={hints.waveform_url} mode="scaleToFill" />
            ) : (
              <View className="work-light-editor__wave work-light-editor__wave--empty" />
            )}
            {sections.map((sec) => (
              <View
                key={`rail-${sec.id}`}
                className={`work-light-editor__span work-light-editor__span--${sec.id}`}
                style={{
                  left: `${(sec.start / railEnd) * 100}%`,
                  width: `${(Math.max(sec.end - sec.start, 1) / railEnd) * 100}%`,
                }}
              />
            ))}
          </View>
        );
      })()}
      <Text className="typo-meta">{e.railHint}</Text>
      <View className="work-light-editor__sections">
        {sections.map((sec) => (
          <View
            key={sec.id}
            className="work-light-editor__chip work-light-editor__chip--drag"
            onTouchStart={(ev) => onSectionTouchStart(sec.id, ev.touches?.[0]?.clientX)}
            onTouchEnd={(ev) => onSectionTouchEnd(sec.id, ev.changedTouches?.[0]?.clientX)}
          >
            <Text className="work-light-editor__drag-handle">↕</Text>
            <Text onClick={() => void persistSection(sec)}>
              {e[SECTION_LABEL[sec.id] || "sectionVerse"]} {sec.start}-{sec.end}
            </Text>
            <View className="work-light-editor__nudge">
              <Text className="work-light-editor__nudge-btn" onClick={() => previewSection(sec)}>
                {e.previewSection}
              </Text>
              <Text className="work-light-editor__nudge-btn" onClick={() => nudgeSection(sec.id, -2)}>
                {e.nudgeEarlier}
              </Text>
              <Text className="work-light-editor__nudge-btn" onClick={() => nudgeSection(sec.id, 2)}>
                {e.nudgeLater}
              </Text>
            </View>
          </View>
        ))}
      </View>
      <View className="work-light-editor__tracks">
        <Text className="work-light-editor__label">{e.stemsPanelTitle}</Text>
        <Text className="typo-meta">{reviewStems ? e.stemsReview : e.stemsPreview}</Text>
        <View className="work-light-editor__nudge">
          <Text className="work-light-editor__nudge-btn" onClick={() => setSemitones((n) => Math.max(-6, n - 1))}>
            {e.pitch} {semitones - 1}
          </Text>
          <Text className="typo-meta">{e.pitch} {semitones}</Text>
          <Text className="work-light-editor__nudge-btn" onClick={() => setSemitones((n) => Math.min(6, n + 1))}>
            {e.pitch} +{semitones + 1}
          </Text>
        </View>
        <View className="work-light-editor__nudge">
          <Text className="work-light-editor__nudge-btn" onClick={() => setTempo((n) => Math.max(0.8, Math.round((n - 0.05) * 100) / 100))}>
            {e.tempo} −
          </Text>
          <Text className="typo-meta">{e.tempo} {tempo.toFixed(2)}×</Text>
          <Text className="work-light-editor__nudge-btn" onClick={() => setTempo((n) => Math.min(1.25, Math.round((n + 0.05) * 100) / 100))}>
            {e.tempo} +
          </Text>
        </View>
        <Button variant="primary" size="sm" block loading={busy === "transform"} onClick={() => void applyTransform()}>
          {e.applyTransform}
        </Button>
        <Collapsible label={copy.celebrationUi.moreActions} defaultOpen={false}>
          <Button variant="secondary" size="sm" block loading={busy === "stems"} onClick={() => void exportStems()}>
            {e.stemsExport}
          </Button>
          {!isInstrumentalSku ? (
            <Button
              variant="ghost"
              size="sm"
              block
              loading={busy === "instrumental"}
              onClick={() => void makeInstrumentalSku()}
            >
              {e.instrumentalSku}
            </Button>
          ) : null}
          <Button variant="secondary" size="sm" block loading={busy === "master"} onClick={() => void applyMaster()}>
            {e.master}
          </Button>
          <Button variant="ghost" size="sm" block loading={busy === "undo"} onClick={() => void undoEdit()}>
            {e.undoEdit}
          </Button>
          <Button variant="ghost" size="sm" block onClick={() => startCover(workId, title, hints?.suggested_intent, { lyricLock: true })}>
            {e.lyricLock}
          </Button>
          <Button variant="ghost" size="sm" block onClick={() => startCover(workId, title, hints?.suggested_intent)}>
            {e.vocalReplace}
          </Button>
          <Button variant="ghost" size="sm" block loading={busy === "extend15"} onClick={() => void regenOnBench("extend", 15)}>
            {e.extend15}
          </Button>
          <Button variant="ghost" size="sm" block loading={busy === "extend30"} onClick={() => void regenOnBench("extend", 30)}>
            {e.extend30}
          </Button>
          <Button variant="ghost" size="sm" block onClick={() => Taro.navigateTo({ url: creatorPage("work", { workId }) })}>
            {copy.creatorUi.workLedgerTitle}
          </Button>
          <Button variant="ghost" size="sm" block loading={busy === "same_style"} onClick={() => void regenOnBench("same_style")}>
            {e.sameStyle}
          </Button>
          <Button variant="ghost" size="sm" block loading={busy === "remelt"} onClick={() => void regenOnBench("remelt")}>
            {e.remelt}
          </Button>
        </Collapsible>
      </View>
      <Text className="work-light-editor__label">{e.clipsTitle}</Text>
      <Text className="typo-meta">{e.clipHint}</Text>
      {clips.map((clip) => (
        <View key={`${clip.length}-${clip.start}`} className="work-light-editor__clip">
          <Text className="typo-meta">
            {clip.length}s · {clip.start}–{clip.end}
          </Text>
          <Text className="work-light-editor__nudge-btn" onClick={() => previewSection({ start: Number(clip.start) || 0 })}>
            {e.previewSection}
          </Text>
        </View>
      ))}
    </View>
  );
}
