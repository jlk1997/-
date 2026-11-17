import { useState, useEffect, useMemo, useRef, useCallback, lazy, Suspense } from "react";
import { Image, Text, View } from "@tarojs/components";
import Taro, { useRouter, useDidShow, useShareAppMessage } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../components/PageShell";
import { CreateModePicker, type CreateMode } from "../../components/studio/CreateModePicker";
import {
  Button,
  BottomSheet,
  LoadingSkeleton,
  TextArea,
  showSuccess,
  showError,
  CreditEstimateMeter,
} from "../../components/ui";
import { vibeApi, isInsufficientCredits, isRemixForbidden, generateIdempotencyKey, isActiveJobLimit, isRateLimited, isQueueOverload, getRateLimitRetryAfter } from "../../services/api";
import { AUTH_EVENTS } from "../../constants/events";
import { bootstrapAuth, requireAuth, isLoggedIn } from "../../utils/auth";
import { useCreditsOptional } from "../../contexts/CreditsProvider";
import { useActiveJobOptional } from "../../contexts/ActiveJobProvider";
import { useTheme } from "../../contexts/ThemeProvider";
import { getItem, removeItem, setItem } from "../../platform/storage";
import { requestGenerationSubscribeMessages } from "../../platform/wechatSubscribe";
import { CommercialAlertBanners } from "../../components/commercial/CommercialAlertBanners";
import { LaunchHonestyBanner } from "../../components/commercial/LaunchHonestyBanner";
import { hapticLight } from "../../utils/haptic";
import { showCoverUnavailable } from "../../utils/coverUnavailable";
import { applyCreditsResponse, ensureSufficientCredits, taskCreditsGranted, type CreditsApiPayload } from "../../utils/creditsSync";
import type { RemixSourceSnapshot } from "../../utils/generationStorage";
import { clearActiveGeneration } from "../../utils/generationStorage";
import { openStackPage } from "../../utils/navigation";
import { openWorkbench } from "../../utils/workbenchNav";
import { goShipBand } from "../../packageCreator/nextActionNav";
import { usePlayerTransport } from "../../contexts/PlayerProvider";
import { needsBeautifyMaster } from "../../utils/workbenchWorks";
import { prefetchCoreChunks } from "../../utils/prefetchH5";
import { STUDIO_PAGE_ROUTES } from "../../constants/routes";
import { workSharePayload } from "../../platform/share";
import { trackActivation, trackActivationOnce } from "../../utils/activationEvents";
import { useServerDraftSync } from "../../hooks/useServerDraftSync";
import { persistActiveGeneration, resolveRestorableJobId } from "../../utils/restoreGeneration";
import { isTerminalJobStatus } from "../../utils/generationPhases";
import { CoachMarks } from "../../components/onboarding/CoachMarks";
import { AiDisclaimerSheet } from "../../components/legal/AiDisclaimerSheet";
import { fetchConsentStatus, ensureAiNoticeConsent } from "../../utils/consent";
import { resolveWorkTitle } from "../../utils/workTitle";
import { emptyCreativeSpec, workToPlayerTrack, type MusicCreativeSpec, type SoundRecipeOptions } from "@vibe-sorcery/types";
import {
  buildPayloadSpec,
  hasCreativeConstraints,
  mergeParsedSpec,
  mergePresetApplied,
  STUDIO_CREATIVE_SPEC_KEY,
} from "../../utils/creativeSpec";

import "./index.scss";
import "../../styles/tab-page.scss";

import { PresetCarousel, type StylePreset } from "../../components/studio/PresetCarousel";
import { CreateFormulaPanel } from "../../components/studio/CreateFormulaPanel";

const CREATE_NEXT = "/pages/create/index";

const SoundRecipePanel = lazy(() =>
  import("../../components/studio/SoundRecipePanel").then((m) => ({ default: m.SoundRecipePanel }))
);
const EmotionDiagnosisCard = lazy(() =>
  import("../../components/studio/EmotionDiagnosisCard").then((m) => ({ default: m.EmotionDiagnosisCard }))
);
const RemixFlowPanel = lazy(() =>
  import("../../components/studio/RemixFlowPanel").then((m) => ({ default: m.RemixFlowPanel }))
);
const WorkPicker = lazy(() =>
  import("../../components/studio/WorkPicker").then((m) => ({ default: m.WorkPicker }))
);
const SongSetupBar = lazy(() =>
  import("../../components/studio/SongSetupBar").then((m) => ({ default: m.SongSetupBar }))
);
const LyricsStructureEditor = lazy(() =>
  import("../../components/studio/LyricsStructureEditor").then((m) => ({ default: m.LyricsStructureEditor }))
);
const PromptPreviewBar = lazy(() =>
  import("../../components/studio/PromptPreviewBar").then((m) => ({ default: m.PromptPreviewBar }))
);
const ReferenceTrackPicker = lazy(() =>
  import("../../components/studio/ReferenceTrackPicker").then((m) => ({ default: m.ReferenceTrackPicker }))
);
const WorkTitleSheet = lazy(() =>
  import("../../components/studio/WorkTitleSheet").then((m) => ({ default: m.WorkTitleSheet }))
);
const GenerationProgress = lazy(() =>
  import("../../components/studio/GenerationProgress").then((m) => ({ default: m.GenerationProgress }))
);

const CreditsPaywallSheet = lazy(() =>
  import("../../components/ui/CreditsPaywallSheet").then((m) => ({ default: m.CreditsPaywallSheet }))
);

function shouldPromptWorkTitle(mode: CreateMode, coverStep: "pick" | "preprocess" | "generate") {
  if (mode === "quickTrack" || mode === "lyrics") return false;
  if (mode === "playlist" || mode === "variation" || mode === "remix") return true;
  if (mode === "cover" && coverStep === "generate") return true;
  return false;
}

type CreateAction = "compose" | "sameStyle" | "regenerate";

function resolveSeedMode(seedMode: string | null): { mode: CreateMode; action: CreateAction } {
  if (seedMode === "cover") return { mode: "cover", action: "compose" };
  if (seedMode === "variation") return { mode: "variation", action: "compose" };
  if (seedMode === "remix") return { mode: "remix", action: "compose" };
  if (seedMode === "lyrics") return { mode: "lyrics", action: "compose" };
  if (seedMode === "sameStyle") return { mode: "quickTrack", action: "sameStyle" };
  if (seedMode === "regenerate") return { mode: "quickTrack", action: "regenerate" };
  return { mode: "quickTrack", action: "sameStyle" };
}

export default function CreatePage() {
  const router = useRouter();
  const { copy, locale } = useLocale();
  const c = copy.createUi;
  const modes = copy.studioSummary.modes;
  const creditsCtx = useCreditsOptional();
  const { playTrack } = usePlayerTransport();
  const activeJobCtx = useActiveJobOptional();

  useShareAppMessage((res) => {
    const ds = (res?.target as { dataset?: Record<string, string> } | undefined)?.dataset;
    if (ds?.workid) return workSharePayload(ds.workid, ds.title || copy.brand.name);
    return { title: copy.brand.name };
  });
  const [mode, setMode] = useState<CreateMode>("quickTrack");
  const [createAction, setCreateAction] = useState<CreateAction>("compose");
  const [recipeReady, setRecipeReady] = useState(false);
  const [revisingLyrics, setRevisingLyrics] = useState(false);
  const [remeltPreferred, setRemeltPreferred] = useState(false);
  const [presets, setPresets] = useState<StylePreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);
  const [textIntent, setTextIntent] = useState("");
  const [diagnosisOpen, setDiagnosisOpen] = useState(true);
  const [diagnosisSummary, setDiagnosisSummary] = useState("");
  const [workTitle, setWorkTitle] = useState("");
  const [lyrics, setLyrics] = useState("");
  const [lyricsStyleTags, setLyricsStyleTags] = useState("");
  const [seedWorkId, setSeedWorkId] = useState("");
  const [seedWorkTitle, setSeedWorkTitle] = useState("");
  const [seedRemixAllowed, setSeedRemixAllowed] = useState(true);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobType, setActiveJobType] = useState<"single" | "playlist" | "variations" | "remix" | "workbench">("single");
  const [activeJobStartedAt, setActiveJobStartedAt] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);
  const [generatingLyrics, setGeneratingLyrics] = useState(false);
  const [polishingIntent, setPolishingIntent] = useState(false);
  const [titleSheetOpen, setTitleSheetOpen] = useState(false);
  const [aiDisclaimerOpen, setAiDisclaimerOpen] = useState(false);
  const [aiConsentLoading, setAiConsentLoading] = useState(false);
  const pendingGenerateTitleRef = useRef<string | undefined>(undefined);
  const [titleDraft, setTitleDraft] = useState("");
  const [coverStep, setCoverStep] = useState<"pick" | "preprocess" | "generate">("pick");
  const [coverLyrics, setCoverLyrics] = useState("");
  const [coverLyricLock, setCoverLyricLock] = useState(false);
  const [draftsOpen, setDraftsOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [drafts, setDrafts] = useState<
    Array<{ id: string; title: string; mode: string; payload: Record<string, unknown>; version?: number }>
  >([]);
  const generateLatchRef = useRef(false);
  const generateJobRef = useRef<string | null>(null);
  const generateIdempotencyRef = useRef<string | null>(null);
  const lastShowRefreshRef = useRef(0);
  const deferredShowRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { setMood } = useTheme();
  const credits = creditsCtx?.balance ?? null;
  const gateEnabled = creditsCtx?.gateEnabled ?? false;
  const creditsReady = creditsCtx?.ready ?? false;
  const [worksCount, setWorksCount] = useState(0);
  const [recentWork, setRecentWork] = useState<{
    id: string;
    title: string;
    from_workbench?: boolean;
    superseded_by_work_id?: string | null;
  } | null>(null);
  const [checkinToday, setCheckinToday] = useState<boolean | null>(null);
  const [checkingIn, setCheckingIn] = useState(false);
  const [completedWorkId, setCompletedWorkId] = useState<string | null>(null);
  const [paywallOpen, setPaywallOpen] = useState(false);
  const [paywallCredits, setPaywallCredits] = useState(1);
  const [paywallSource, setPaywallSource] = useState("create_dock");
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachAnchor, setCoachAnchor] = useState<string | undefined>();
  const onCoachVisibility = useCallback((visible: boolean, anchor?: string) => {
    setCoachOpen(visible);
    setCoachAnchor(visible ? anchor : undefined);
  }, []);
  const [, setAuthTick] = useState(0);
  useEffect(() => {
    const bump = () => setAuthTick((n) => n + 1);
    Taro.eventCenter.on(AUTH_EVENTS.login, bump);
    Taro.eventCenter.on(AUTH_EVENTS.logout, bump);
    return () => {
      Taro.eventCenter.off(AUTH_EVENTS.login, bump);
      Taro.eventCenter.off(AUTH_EVENTS.logout, bump);
    };
  }, []);
  const [paywallTab, setPaywallTab] = useState<"member" | "pack">("pack");
  const subscription = creditsCtx?.subscription ?? null;
  const [estimatedCredits, setEstimatedCredits] = useState(1);
  const [activeRemixSource, setActiveRemixSource] = useState<RemixSourceSnapshot | null>(null);
  const [referenceWorkId, setReferenceWorkId] = useState<string | null>(null);
  const [referenceAvOffset, setReferenceAvOffset] = useState<{ arousal: number; valence: number }>({ arousal: 0, valence: 0 });
  const [pickerWorks, setPickerWorks] = useState<Array<{ id: string; title: string; cover_url?: string }>>([]);
  const [progressOpen, setProgressOpen] = useState(true);
  const [creativeSpec, setCreativeSpec] = useState<MusicCreativeSpec>(emptyCreativeSpec);
  const [songMode, setSongMode] = useState<"auto_lyrics" | "lyrics" | "instrumental">("auto_lyrics");
  const [freedom, setFreedom] = useState<"literal" | "balanced" | "open">("balanced");
  const [takes, setTakes] = useState<1 | 2>(2);
  const [songQuality, setSongQuality] = useState<"standard" | "master">("standard");
  const [quickSong, setQuickSong] = useState(false);
  const [soundRecipeOptions, setSoundRecipeOptions] = useState<SoundRecipeOptions | null>(null);
  const [keyOptions, setKeyOptions] = useState<string[]>(["auto"]);
  const [bpmPresets, setBpmPresets] = useState<Array<{ label: string; range: [number, number] }>>([]);

  const titleSuggestOpts = useMemo(
    () => ({ spec: creativeSpec, soundRecipe: soundRecipeOptions, locale }),
    [creativeSpec, soundRecipeOptions, locale],
  );

  const songWrite = mode === "quickTrack" || mode === "lyrics";
  const specNeedsLabels = Boolean(
    creativeSpec.instruments.length ||
      creativeSpec.genres.length ||
      creativeSpec.moods.length ||
      creativeSpec.tempo_feel ||
      (creativeSpec.key && creativeSpec.key !== "auto") ||
      creativeSpec.texture ||
      creativeSpec.meter ||
      creativeSpec.era ||
      creativeSpec.vocal_gender ||
      creativeSpec.vocal_style ||
      creativeSpec.language ||
      creativeSpec.bpm,
  );
  const twoTakes = (songWrite && takes === 2) || (!songWrite && createAction !== "compose" && mode !== "playlist" && mode !== "remix" && mode !== "cover");

  const choiceChips = useMemo(() => {
    const chips: Array<{ id: string; label: string }> = [];
    const labelOf = (
      list: Array<{ id: string; label_zh?: string; label_en?: string; label?: string }> | undefined,
      id: string,
    ) => {
      const item = list?.find((row) => row.id === id);
      if (!item) return "";
      return locale === "zh" ? item.label_zh || item.label || item.label_en || "" : item.label_en || item.label || item.label_zh || "";
    };
    if (songWrite) {
      chips.push({
        id: "write",
        label: songMode === "lyrics" ? c.songModeLyrics : songMode === "instrumental" ? c.songModeInst : c.songModeAuto,
      });
    }
    const preset = presets.find((row) => row.id === selectedPresetId);
    if (preset?.label) chips.push({ id: "style", label: preset.label });
    if (lyrics.trim()) chips.push({ id: "lyrics", label: c.choiceLyrics });
    if (diagnosisSummary.trim()) {
      const text = diagnosisSummary.trim();
      chips.push({ id: "mood", label: text.length > 18 ? `${text.slice(0, 18)}…` : text });
    } else if (creativeSpec.arousal != null || creativeSpec.valence != null) {
      chips.push({ id: "mood", label: c.choiceMoodSet });
    }
    for (const id of creativeSpec.instruments) {
      const label = labelOf(soundRecipeOptions?.instruments, id);
      if (label) chips.push({ id: `inst-${id}`, label });
    }
    for (const id of creativeSpec.genres) {
      const label = labelOf(soundRecipeOptions?.genres, id);
      if (label) chips.push({ id: `genre-${id}`, label });
    }
    for (const id of creativeSpec.moods) {
      const label = labelOf(soundRecipeOptions?.moods, id);
      if (label) chips.push({ id: `feel-${id}`, label });
    }
    if (creativeSpec.tempo_feel) {
      const label = labelOf(soundRecipeOptions?.tempo_feel, creativeSpec.tempo_feel);
      if (label) chips.push({ id: "tempo", label });
    }
    if (creativeSpec.key && creativeSpec.key !== "auto") chips.push({ id: "key", label: creativeSpec.key });
    if (creativeSpec.bpm) chips.push({ id: "bpm", label: `BPM ${creativeSpec.bpm}` });
    for (const [field, list] of [
      ["texture", soundRecipeOptions?.textures],
      ["era", soundRecipeOptions?.eras],
      ["meter", soundRecipeOptions?.meters],
      ["vocal_gender", soundRecipeOptions?.vocal_genders],
      ["vocal_style", soundRecipeOptions?.vocal_styles],
      ["language", soundRecipeOptions?.languages],
    ] as const) {
      const id = creativeSpec[field];
      if (!id) continue;
      const label = labelOf(list, id);
      if (label) chips.push({ id: field, label });
    }
    if (creativeSpec.custom_prompt_override?.trim()) chips.push({ id: "override", label: c.choicePromptEdited });
    return chips;
  }, [songWrite, songMode, presets, selectedPresetId, lyrics, diagnosisSummary, creativeSpec, soundRecipeOptions, locale, c]);

  const estimateMode = useMemo(() => {
    if (mode === "playlist") return "playlist";
    if (mode === "variation") return "variation";
    if (songWrite && takes === 2) return "twoTakes";
    if (songWrite) return "single";
    if (twoTakes) return "twoTakes";
    return mode;
  }, [mode, songWrite, takes, twoTakes]);

  const creditCost = estimatedCredits;
  const creditsShort = gateEnabled && creditsReady && (credits == null || credits < creditCost);
  const creditsLoading = Boolean(isLoggedIn() && gateEnabled && (!creditsReady || checkinToday === null));
  const creditsBlocked = creditsShort && checkinToday !== null && !creditsLoading;

  const remixReady = mode !== "remix" || (!!seedWorkId && textIntent.trim().length >= 3 && seedRemixAllowed);

  const jobBlocking = useMemo(() => {
    if (!activeJobId) return false;
    const ctxJob = activeJobCtx?.job;
    if (ctxJob?.jobId === activeJobId && isTerminalJobStatus(ctxJob.status)) return false;
    return true;
  }, [activeJobId, activeJobCtx?.job]);

  useEffect(() => {
    if (!activeJobId) {
      generateJobRef.current = null;
      generateLatchRef.current = false;
      return;
    }
    generateLatchRef.current = false;
    generateIdempotencyRef.current = null;
    const t = setTimeout(() => {
      generateJobRef.current = null;
    }, 0);
    return () => clearTimeout(t);
  }, [activeJobId]);

  useServerDraftSync(
    isLoggedIn() && !activeJobId,
    mode,
    { textIntent, lyrics, lyricsStyleTags, seedWorkId, selectedPresetId, referenceWorkId, referenceAvOffset, creativeSpec },
    textIntent.slice(0, 40) || workTitle || "Draft",
    (draft) => {
      const p = draft.payload || {};
      if (typeof p.textIntent === "string") setTextIntent(p.textIntent);
      if (typeof p.lyrics === "string") setLyrics(p.lyrics);
      if (typeof p.lyricsStyleTags === "string") setLyricsStyleTags(p.lyricsStyleTags);
      if (typeof p.seedWorkId === "string") setSeedWorkId(p.seedWorkId);
      if (typeof p.selectedPresetId === "string") setSelectedPresetId(p.selectedPresetId);
      if (typeof p.referenceWorkId === "string") setReferenceWorkId(p.referenceWorkId);
      if (p.referenceAvOffset && typeof p.referenceAvOffset === "object") {
        const off = p.referenceAvOffset as { arousal?: number; valence?: number };
        setReferenceAvOffset({
          arousal: typeof off.arousal === "number" ? off.arousal : 0,
          valence: typeof off.valence === "number" ? off.valence : 0,
        });
      }
      if (p.creativeSpec && typeof p.creativeSpec === "object") {
        setCreativeSpec({ ...emptyCreativeSpec(), ...(p.creativeSpec as MusicCreativeSpec) });
      }
      setItem(`studio:draftId:${mode}`, draft.id);
      setItem(`studio:draftVersion:${mode}`, String(draft.version));
    },
    c.draftConflict,
  );

  useEffect(() => {
    bootstrapAuth();
    creditsCtx?.refresh();
    vibeApi.getPresets().then(setPresets).catch(() => {});

    const seed = getItem("create:seedWorkId");
    const seedMode = getItem("create:mode") as CreateMode | null;
    const seedIntent = getItem("create:seedIntent");
    const presetFromCopilot = getItem("create:presetId");
    const refFromCopilot = getItem("create:referenceWorkId");
    const creativeSpecFromCopilot = getItem("create:creativeSpec");
    const importSpecRaw = getItem("create:importSpec");
    if (importSpecRaw) {
      try {
        const parsed = JSON.parse(importSpecRaw) as Record<string, unknown>;
        const refId = parsed.reference_work_id ? String(parsed.reference_work_id) : "";
        const { seed: _seed, reference_work_id: _ref, ...creative } = parsed;
        setCreativeSpec({ ...emptyCreativeSpec(), ...creative });
        if (refId) {
          const resolved = resolveSeedMode("sameStyle");
          setReferenceWorkId(refId);
          setSeedWorkId(refId);
          setMode(resolved.mode);
          setCreateAction(resolved.action);
        }
        setAdvancedOpen(true);
        setRecipeReady(true);
        showSuccess(copy.marketplaceUi.recipeReady);
      } catch {
        /* ignore */
      }
      removeItem("create:importSpec");
    }
    if (getItem("create:recipeReady") === "1") {
      setAdvancedOpen(true);
      setRecipeReady(true);
      removeItem("create:recipeReady");
    }
    if (creativeSpecFromCopilot) {
      try {
        setCreativeSpec({ ...emptyCreativeSpec(), ...JSON.parse(creativeSpecFromCopilot) });
      } catch {
        /* ignore */
      }
      removeItem("create:creativeSpec");
    }
    if (presetFromCopilot) {
      setSelectedPresetId(presetFromCopilot);
      removeItem("create:presetId");
    }
    if (refFromCopilot) {
      setReferenceWorkId(refFromCopilot);
      removeItem("create:referenceWorkId");
    }
    const lyricsFromCopilot = getItem("create:lyrics");
    if (lyricsFromCopilot) {
      setLyrics(lyricsFromCopilot);
      setMode("lyrics");
      removeItem("create:lyrics");
    }
    const optimizeHint = getItem("create:optimizeHint");
    if (optimizeHint) {
      setTextIntent((prev) => (prev.trim() ? `${prev.trim()} · ${optimizeHint}` : optimizeHint));
      removeItem("create:optimizeHint");
    }
    const targetBpm = getItem("create:targetBpm");
    const targetKey = getItem("create:targetKey");
    if (targetBpm || targetKey) {
      setCreativeSpec((prev) => {
        const next = { ...prev };
        if (targetBpm) {
          const bpmVal = parseInt(targetBpm, 10);
          if (!Number.isNaN(bpmVal)) {
            next.bpm = bpmVal;
            next.bpm_range = [Math.max(40, bpmVal - 8), Math.min(200, bpmVal + 8)];
          }
        }
        if (targetKey) next.key = targetKey;
        return next;
      });
      removeItem("create:targetBpm");
      removeItem("create:targetKey");
    }
    if (seed && seedMode === "cover") {
      removeItem("create:seedWorkId");
      removeItem("create:mode");
      removeItem("create:seedIntent");
      removeItem("create:seedTitle");
      removeItem("create:coverLyricLock");
      showCoverUnavailable();
    } else if (seed) {
      const resolved = resolveSeedMode(seedMode);
      setSeedWorkId(seed);
      setMode(resolved.mode);
      setCreateAction(resolved.action);
      if (resolved.action !== "compose") {
        setReferenceWorkId(seed);
      }
      if (getItem("create:remelt") === "1") {
        setRemeltPreferred(true);
        removeItem("create:remelt");
      }
      if (getItem("create:coverLyricLock") === "1") {
        setCoverLyricLock(true);
        removeItem("create:coverLyricLock");
      }
      if (seedIntent) {
        setTextIntent(seedIntent);
      } else if (resolved.mode === "remix") {
        setTextIntent(copy.derivative.remix.example);
      }
      const seedTitle = getItem("create:seedTitle");
      if (seedTitle) setSeedWorkTitle(seedTitle);
      removeItem("create:seedWorkId");
      removeItem("create:mode");
      removeItem("create:seedIntent");
      removeItem("create:seedTitle");
    }

    const journeyRaw = getItem("journey:waypoints");
    if (journeyRaw && !seed) {
      try {
        const data = JSON.parse(journeyRaw) as { customIntent?: string };
        if (data.customIntent) setTextIntent(data.customIntent);
      } catch {
        /* ignore */
      }
    }

    const challengeSlug = router.params.challenge || getItem("create:challengeSlug");
    if (challengeSlug) {
      removeItem("create:challengeSlug");
      vibeApi
        .getChallenge(challengeSlug)
        .then((data) => {
          setTextIntent(data.description || `#${data.hashtag} ${data.title}`);
        })
        .catch(() => {});
    } else {
      const seedIntentOnly = getItem("create:seedIntent");
      if (seedIntentOnly && !seed) setTextIntent(seedIntentOnly);
    }
  }, [router.params.challenge, copy.derivative.remix.example]);

  useEffect(() => {
    prefetchCoreChunks();
  }, []);

  useEffect(() => {
    if (soundRecipeOptions || (!advancedOpen && !specNeedsLabels)) return;
    vibeApi
      .getPlatformConfig()
      .then((cfg) => {
        if (cfg.studio.sound_recipe) setSoundRecipeOptions(cfg.studio.sound_recipe as SoundRecipeOptions);
        if (cfg.studio.keys?.length) setKeyOptions(cfg.studio.keys);
        if (cfg.studio.bpm_presets?.length) setBpmPresets(cfg.studio.bpm_presets);
      })
      .catch(() => {
        vibeApi.getSoundRecipeOptions().then((opts) => setSoundRecipeOptions(opts as SoundRecipeOptions)).catch(() => {});
      });
  }, [advancedOpen, soundRecipeOptions, specNeedsLabels]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setItem(STUDIO_CREATIVE_SPEC_KEY, JSON.stringify(creativeSpec));
    }, 400);
    return () => clearTimeout(timer);
  }, [creativeSpec]);

  useDidShow(() => {
    const seed = getItem("create:seedWorkId");
    if (seed && getItem("create:mode") === "cover") {
      removeItem("create:seedWorkId");
      removeItem("create:mode");
      removeItem("create:seedIntent");
      removeItem("create:seedTitle");
      removeItem("create:coverLyricLock");
      showCoverUnavailable();
    } else if (seed) {
      const seedMode = getItem("create:mode");
      const seedIntent = getItem("create:seedIntent");
      const resolved = resolveSeedMode(seedMode);
      setSeedWorkId(seed);
      setMode(resolved.mode);
      setCreateAction(resolved.action);
      if (resolved.action !== "compose") setReferenceWorkId(seed);
      if (getItem("create:remelt") === "1") {
        setRemeltPreferred(true);
        removeItem("create:remelt");
      }
      if (getItem("create:coverLyricLock") === "1") {
        setCoverLyricLock(true);
        removeItem("create:coverLyricLock");
      }
      if (seedIntent) {
        setTextIntent(seedIntent);
      } else if (resolved.mode === "remix") {
        setTextIntent(copy.derivative.remix.example);
      }
      const seedTitle = getItem("create:seedTitle");
      if (seedTitle) setSeedWorkTitle(seedTitle);
      removeItem("create:seedWorkId");
      removeItem("create:mode");
      removeItem("create:seedIntent");
      removeItem("create:seedTitle");
    }

    const showFresh = Date.now() - lastShowRefreshRef.current > 30_000;
    if (showFresh) {
      lastShowRefreshRef.current = Date.now();
      void creditsCtx?.refresh();
    }
    if (deferredShowRef.current) clearTimeout(deferredShowRef.current);
    deferredShowRef.current = setTimeout(() => {
      vibeApi.trackEvent("create_page_view", { logged_in: isLoggedIn() }).catch(() => {});
      if (isLoggedIn()) {
        vibeApi
          .getProgress()
          .then((progress) => setCheckinToday(Boolean(progress.checked_in_today)))
          .catch(() => setCheckinToday(true));
      }
    }, 1200);
    if (!isLoggedIn()) {
      setCheckinToday(null);
    }
    if (activeJobId) return;
    const ctxJob = activeJobCtx?.job;
    if (ctxJob?.jobId && !isTerminalJobStatus(ctxJob.status)) {
      if (ctxJob.jobType === "workbench" && ctxJob.returnUrl.includes("workbench")) {
        openStackPage(ctxJob.returnUrl);
        return;
      }
      setActiveJobId(ctxJob.jobId);
      setActiveJobStartedAt(ctxJob.startedAt);
      if (ctxJob.jobType) setActiveJobType(ctxJob.jobType);
      return;
    }
    resolveRestorableJobId().then((restored) => {
      if (!restored) return;
      if (restored.jobType === "workbench" && restored.returnUrl.includes("workbench")) {
        openStackPage(restored.returnUrl);
        return;
      }
      setActiveJobId(restored.jobId);
      setActiveJobStartedAt(restored.startedAt);
      if (restored.jobType === "playlist" || restored.jobType === "variations" || restored.jobType === "remix") {
        setActiveJobType(restored.jobType);
      }
      if (restored.remixSource) {
        setActiveRemixSource(restored.remixSource);
        setMode("remix");
      }
    });
    if (isLoggedIn() && showFresh) {
      vibeApi
        .listWorks("newest", undefined, 12)
        .then((list) => {
          setWorksCount(list.length);
          const latest = list[0] as {
            id: string;
            title: string;
            from_workbench?: boolean;
            superseded_by_work_id?: string | null;
          } | undefined;
          setRecentWork(
            latest
              ? {
                  id: latest.id,
                  title: latest.title,
                  from_workbench: latest.from_workbench,
                  superseded_by_work_id: latest.superseded_by_work_id,
                }
              : null,
          );
          setPickerWorks(list.slice(0, 12).map((w) => ({ id: w.id, title: w.title, cover_url: w.cover_url })));
        })
        .catch(() => {});
      void loadDrafts();
    } else if (!isLoggedIn()) {
      setWorksCount(0);
      setRecentWork(null);
    }

    const copilotConfirm = getItem("create:copilotConfirm");
    const copilotEstimate = getItem("create:copilotEstimate");
    if (copilotConfirm === "1") {
      removeItem("create:copilotConfirm");
      removeItem("create:copilotEstimate");
      const estLabel = copilotEstimate
        ? c.copilotConfirmBody.replace("{n}", copilotEstimate)
        : c.copilotConfirmBodyShort;
      Taro.showModal({
        title: c.copilotConfirmTitle,
        content: estLabel,
        confirmText: c.copilotConfirmGo,
        cancelText: c.copilotConfirmCancel,
        success: (r) => {
          if (r.confirm) void generate();
        },
      });
    }
  });

  useEffect(() => {
    if (!seedWorkId || seedWorkTitle || !isLoggedIn()) return;
    let cancelled = false;
    vibeApi
      .getWork(seedWorkId)
      .then((work) => {
        if (!cancelled) setSeedWorkTitle(work.title);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [seedWorkId, seedWorkTitle]);

  function handleModeSelect(id: CreateMode) {
    if (id === "cover") {
      showCoverUnavailable();
      return;
    }
    setMode(id);
    setCreateAction("compose");
    setCoverStep("pick");
    if (id === "remix" && !seedWorkId) {
      setTextIntent("");
    }
  }

  async function loadDrafts() {
    if (!isLoggedIn()) return;
    try {
      setDrafts(await vibeApi.listDrafts());
    } catch {
      setDrafts([]);
    }
  }

  async function selectPreset(p: StylePreset) {
    setSelectedPresetId(p.id);
    trackActivation("activation_preset_selected", { preset_id: p.id });
    setMood({ presetKey: p.id, hue: 42 + (p.id.length % 30) });
    try {
      const applied = await vibeApi.applyPreset(p.id, 6, textIntent);
      if (applied.text_intent) setTextIntent(applied.text_intent);
      setCreativeSpec((prev) => mergePresetApplied(prev, applied, soundRecipeOptions ?? undefined));
    } catch {
      if (p.example_intent) setTextIntent(p.example_intent);
    }
  }

  async function parseIntentOnBlur() {
    const draft = textIntent.trim();
    if (draft.length < 3 || !isLoggedIn()) return;
    try {
      const res = await vibeApi.parseMusicIntent(draft);
      setCreativeSpec((prev) =>
        mergeParsedSpec(prev, res.creative_spec as Partial<MusicCreativeSpec>, draft),
      );
    } catch {
      /* optional parse */
    }
  }

  async function handle402(required = creditCost, source = "create") {
    await creditsCtx?.refresh();
    vibeApi
      .trackEvent("402_insufficient", {
        source,
        required,
        balance: creditsCtx?.balance ?? 0,
      })
      .catch(() => {});
    openPaywall({ required, source, tab: "pack" });
  }

  function openPaywall(opts?: { required?: number; source?: string; tab?: "member" | "pack" }) {
    setPaywallCredits(opts?.required ?? creditCost);
    setPaywallSource(opts?.source ?? "create_dock");
    setPaywallTab(opts?.tab ?? "pack");
    setPaywallOpen(true);
  }

  function modeLabel(m: CreateMode) {
    const map: Record<CreateMode, string> = {
      quickTrack: modes.quickTrack,
      playlist: modes.playlist || c.modeQuickPlaylist,
      lyrics: modes.lyrics || c.lyricsLabel,
      remix: modes.remix || "Remix",
      cover: modes.cover || c.modeCover,
      variation: modes.variation || c.modeVariation,
    };
    return map[m];
  }

  async function polishIntentAi() {
    if (!requireAuth(CREATE_NEXT)) return;
    const draft = textIntent.trim();
    if (draft.length < 3) {
      showError(c.polishNeedIntent);
      return;
    }
    setPolishingIntent(true);
    try {
      const res = await vibeApi.polishIntent(draft);
      setTextIntent(res.text_intent);
      showSuccess(c.polishSuccess);
    } catch {
      showError(c.generateFail);
    } finally {
      setPolishingIntent(false);
    }
  }

  async function generateLyricsAi() {
    if (!requireAuth(CREATE_NEXT)) return;
    setGeneratingLyrics(true);
    try {
      const res = await vibeApi.generateLyrics(textIntent, [], "zh");
      setLyrics(res.lyrics);
      setLyricsStyleTags(res.style_tags?.trim() || "");
      if (res.style_tags?.trim()) {
        setCreativeSpec((prev) => ({ ...prev, style_tags: res.style_tags!.trim() }));
      }
      if (res.song_title?.trim() && !workTitle.trim()) {
        setWorkTitle(res.song_title.trim().slice(0, 60));
      }
      applyCreditsResponse(creditsCtx, res);
      showSuccess(c.lyricsGenerated);
    } catch (e) {
      if (isInsufficientCredits(e)) handle402();
      else showError(c.generateFail);
    } finally {
      setGeneratingLyrics(false);
    }
  }

  async function reviseLyricsAi(instruction: string, lineIndex?: number) {
    if (!requireAuth(CREATE_NEXT) || !lyrics.trim()) return;
    setRevisingLyrics(true);
    try {
      const res = await vibeApi.reviseLyrics({ lyrics, instruction, line_index: lineIndex, language: "zh" });
      if (res.lyrics) setLyrics(res.lyrics);
      showSuccess(c.lyricsGenerated);
    } catch (e) {
      if (isInsufficientCredits(e)) handle402();
      else showError(c.generateFail);
    } finally {
      setRevisingLyrics(false);
    }
  }

  async function coverPreprocess() {
    if (!seedWorkId) return;
    setSubmitting(true);
    try {
      const res = await vibeApi.coverPreprocess(seedWorkId);
      if (res.formatted_lyrics) setCoverLyrics(res.formatted_lyrics);
      setCoverStep("generate");
      showSuccess(c.coverPreprocessDone);
    } catch {
      showError(c.generateFail);
    } finally {
      setSubmitting(false);
    }
  }

  async function saveDraft() {
    if (!requireAuth(CREATE_NEXT)) return;
    setSavingDraft(true);
    try {
      await vibeApi.saveDraft(textIntent.slice(0, 40) || "Draft", mode, {
        textIntent,
        lyrics,
        lyricsStyleTags,
        seedWorkId,
        selectedPresetId,
      });
      showSuccess(c.draftSaved);
      void loadDrafts();
    } catch {
      showError(c.generateFail);
    } finally {
      setSavingDraft(false);
    }
  }

  function openCopilot() {
    setAdvancedOpen(false);
    if (!requireAuth("/packageCopilot/pages/copilot/index")) return;
    openStackPage("/packageCopilot/pages/copilot/index");
  }

  function applyDraft(d: { id: string; title: string; mode: string; payload: Record<string, unknown> }) {
    const p = d.payload || {};
    setMode((d.mode as CreateMode) || "quickTrack");
    if (typeof p.textIntent === "string") setTextIntent(p.textIntent);
    if (typeof p.lyrics === "string") setLyrics(p.lyrics);
    if (typeof p.lyricsStyleTags === "string") setLyricsStyleTags(p.lyricsStyleTags);
    if (typeof p.seedWorkId === "string") setSeedWorkId(p.seedWorkId);
    if (typeof p.selectedPresetId === "string") setSelectedPresetId(p.selectedPresetId);
    setDraftsOpen(false);
  }

  async function removeDraft(id: string) {
    if (!requireAuth(CREATE_NEXT)) return;
    try {
      await vibeApi.deleteDraft(id);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      showSuccess(c.draftDeleted);
    } catch {
      showError(c.generateFail);
    }
  }

  async function generate() {
    if (mode === "cover") {
      showCoverUnavailable();
      return;
    }
    if (submitting || jobBlocking || generateLatchRef.current || generateJobRef.current || creditsLoading) return;
    if (!requireAuth(CREATE_NEXT)) return;
    const cost = creditCost;
    if (!(await ensureSufficientCredits(creditsCtx, cost, () => handle402(cost)))) return;
    if (mode === "remix") {
      if (!seedWorkId) {
        showError(c.remixFlow.needSource);
        return;
      }
      if (textIntent.trim().length < 3) {
        showError(c.remixFlow.needIntent);
        return;
      }
      if (!seedRemixAllowed) {
        showError(copy.derivative.remixNotAllowed);
        return;
      }
    } else if (
      createAction === "compose" &&
      !textIntent.trim() &&
      !selectedPresetId &&
      !hasCreativeConstraints(creativeSpec)
    ) {
      showError(c.needIntent);
      return;
    }
    if (mode === "lyrics" && !lyrics.trim()) {
      showError(c.needLyrics);
      return;
    }
    if (mode === "cover" && coverStep === "pick") {
      setCoverStep("preprocess");
      return;
    }
    if (mode === "cover" && coverStep === "preprocess") {
      await coverPreprocess();
      return;
    }
    if ((mode === "variation" || mode === "cover") && !seedWorkId) {
      showError(c.needSeed);
      return;
    }
    if (shouldPromptWorkTitle(mode, coverStep)) {
      const fallback =
        mode === "playlist"
          ? c.defaultPlaylistTitle
          : mode === "lyrics"
            ? c.defaultLyricsTitle
            : mode === "remix"
              ? c.remixFlow.defaultTitle
              : c.defaultTrackTitle;
      const remixSuggest =
        mode === "remix" && seedWorkTitle.trim()
          ? `${c.remixFlow.defaultTitle} · ${seedWorkTitle.trim()}`.slice(0, 60)
          : "";
      setTitleDraft(
        workTitle.trim() ||
          remixSuggest ||
          resolveWorkTitle("", textIntent, fallback, titleSuggestOpts),
      );
      setTitleSheetOpen(true);
      return;
    }
    await requestGenerate();
  }

  async function requestGenerate(titleOverride?: string) {
    if (!requireAuth(CREATE_NEXT)) return;
    try {
      const status = await fetchConsentStatus();
      if (status.missing.includes("ai_notice")) {
        pendingGenerateTitleRef.current = titleOverride;
        setAiDisclaimerOpen(true);
        return;
      }
    } catch {
      pendingGenerateTitleRef.current = titleOverride;
      setAiDisclaimerOpen(true);
      return;
    }
    await executeGenerate(titleOverride);
  }

  async function confirmAiDisclaimer() {
    setAiConsentLoading(true);
    try {
      await ensureAiNoticeConsent();
      setAiDisclaimerOpen(false);
      await executeGenerate(pendingGenerateTitleRef.current);
      pendingGenerateTitleRef.current = undefined;
    } catch {
      showError(c.generateFail);
    } finally {
      setAiConsentLoading(false);
    }
  }

  async function executeGenerate(titleOverride?: string) {
    if (submitting || jobBlocking || generateLatchRef.current || generateJobRef.current) return;
    generateLatchRef.current = true;
    hapticLight();
    if (titleOverride !== undefined && titleOverride.trim()) {
      setWorkTitle(titleOverride.trim());
    }
    setTitleSheetOpen(false);
    if (!(await ensureSufficientCredits(creditsCtx, creditCost, () => handle402(creditCost)))) {
      generateLatchRef.current = false;
      return;
    }
    await requestGenerationSubscribeMessages();
    setSubmitting(true);
    if (!generateIdempotencyRef.current) generateIdempotencyRef.current = generateIdempotencyKey();
    const idempotencyKey = generateIdempotencyRef.current;
    vibeApi.trackEvent("studio_generate_start", { mode }).catch(() => {});
    trackActivationOnce("activation_first_generate_start", { mode });
    const fallback =
      mode === "playlist"
        ? c.defaultPlaylistTitle
        : mode === "lyrics"
          ? c.defaultLyricsTitle
          : mode === "remix"
            ? c.remixFlow.defaultTitle
            : c.defaultTrackTitle;
    const remixFallback =
      mode === "remix" && seedWorkTitle.trim()
        ? `${c.remixFlow.defaultTitle} · ${seedWorkTitle.trim()}`.slice(0, 60)
        : fallback;
    const resolvedTitle = resolveWorkTitle(titleOverride ?? workTitle, textIntent, remixFallback, titleSuggestOpts);
    const payloadSpec = buildPayloadSpec(creativeSpec, textIntent, lyricsStyleTags);
    const resolvedSongMode = mode === "playlist" ? "instrumental" : mode === "lyrics" ? "lyrics" : songMode;
    const generationFields = {
      mode: resolvedSongMode,
      freedom,
      quality: songQuality,
      quick: quickSong && resolvedSongMode === "auto_lyrics",
      vocal: {
        vocal_gender: creativeSpec.vocal_gender || "",
        vocal_style: creativeSpec.vocal_style || "",
        language: creativeSpec.language || "",
      },
    };
    if ((resolvedSongMode === "lyrics" || mode === "lyrics") && !lyrics.trim()) {
      showError(c.needLyrics);
      generateLatchRef.current = false;
      generateIdempotencyRef.current = null;
      setSubmitting(false);
      return;
    }
    if ((resolvedSongMode === "auto_lyrics" || resolvedSongMode === "instrumental") && !textIntent.trim() && !creativeSpec.custom_prompt_override?.trim()) {
      showError(resolvedSongMode === "instrumental" ? c.needMusicLine : c.needLine);
      generateLatchRef.current = false;
      generateIdempotencyRef.current = null;
      setSubmitting(false);
      return;
    }
    let jobId: string | undefined;
    let resolvedJobType: "single" | "playlist" | "variations" | "remix" = "single";
    let creditsPayload: CreditsApiPayload | undefined;
    try {
      if (songWrite && takes === 1 && createAction === "compose") {
        const job = await vibeApi.generateSingle({
          text_intent: textIntent,
          seed_work_id: seedWorkId || undefined,
          title: resolvedTitle,
          instrumental: resolvedSongMode === "instrumental",
          lyrics: resolvedSongMode === "instrumental" ? undefined : lyrics.trim() || undefined,
          style_tags: lyricsStyleTags.trim() || undefined,
          creative_spec: payloadSpec,
          moods: payloadSpec.moods,
          genres: payloadSpec.genres,
          bpm: payloadSpec.bpm ?? undefined,
          key: payloadSpec.key !== "auto" ? payloadSpec.key : undefined,
          ...generationFields,
          idempotencyKey,
        });
        jobId = job.id;
        resolvedJobType = "single";
        creditsPayload = job;
      } else if (twoTakes) {
        const job = await vibeApi.generateVariations({
          text_intent: textIntent,
          seed_work_id: seedWorkId || undefined,
          title: resolvedTitle,
          count: songWrite ? takes : 2,
          instrumental: resolvedSongMode === "instrumental",
          lyrics: resolvedSongMode === "instrumental" ? undefined : lyrics.trim() || undefined,
          style_tags: lyricsStyleTags.trim() || undefined,
          creative_spec: payloadSpec,
          moods: payloadSpec.moods,
          genres: payloadSpec.genres,
          bpm: payloadSpec.bpm ?? undefined,
          key: payloadSpec.key !== "auto" ? payloadSpec.key : undefined,
          remelt: remeltPreferred || createAction === "regenerate",
          ...generationFields,
          reference: referenceWorkId
            ? {
                work_id: referenceWorkId,
                av_offset:
                  referenceAvOffset.arousal || referenceAvOffset.valence
                    ? referenceAvOffset
                    : undefined,
              }
            : undefined,
          idempotencyKey,
        });
        jobId = job.id;
        resolvedJobType = "variations";
        creditsPayload = job;
      } else if (mode === "playlist") {
        let journey = {
          mode: "prompt_journey",
          steps: 6,
          target_curve: "calm_to_energy",
          instrumental: true,
          title: resolvedTitle,
          waypoints: [] as Array<{ step: number; arousal: number; valence: number }>,
        };
        let musicParams = { bpm_range: [80, 120], key: "auto", duration_preference: "medium" };
        if (selectedPresetId) {
          const applied = await vibeApi.applyPreset(selectedPresetId, 6, textIntent);
          if (applied.journey) journey = applied.journey as typeof journey;
          if (applied.music_params) musicParams = applied.music_params as typeof musicParams;
        }
        if (referenceWorkId) {
          journey = {
            ...journey,
            reference: {
              work_id: referenceWorkId,
              av_offset:
                referenceAvOffset.arousal || referenceAvOffset.valence
                  ? referenceAvOffset
                  : undefined,
            },
          };
        }
        const job = await vibeApi.generatePlaylistBody(
          {
            text_intent: textIntent,
            preset_id: selectedPresetId || undefined,
            generation_mode: "prompt_journey",
            journey,
            music_params: musicParams,
            creative_spec: payloadSpec,
            moods: payloadSpec.moods,
            genres: payloadSpec.genres,
          },
          idempotencyKey,
        );
        jobId = job.id;
        resolvedJobType = "playlist";
        creditsPayload = job;
      } else if (mode === "remix" && seedWorkId) {
        const res = await vibeApi.remix(seedWorkId, textIntent, { title: resolvedTitle, idempotencyKey });
        jobId = res.job_id;
        resolvedJobType = "remix";
        creditsPayload = res;
      } else if (mode === "cover" && seedWorkId) {
        const coverPrompt = coverLyricLock
          ? `${textIntent} Keep original lyrics and melody structure; change vocal timbre only.`
          : textIntent;
        const res = await vibeApi.musicCover(seedWorkId, coverPrompt, {
          cover_mode: "two_step",
          modified_lyrics: coverLyrics || undefined,
          style_lock: coverLyricLock,
          idempotencyKey,
        });
        jobId = res.job_id;
        creditsPayload = res;
      } else if (mode === "variation" && seedWorkId) {
        const job = await vibeApi.generateVariations({
          seed_work_id: seedWorkId,
          text_intent: textIntent,
          title: resolvedTitle,
          count: 3,
          idempotencyKey,
        });
        jobId = job.id;
        resolvedJobType = "variations";
        creditsPayload = job;
      } else {
        showError(c.needSeed);
        return;
      }
    } catch (e) {
      if (isActiveJobLimit(e)) {
        const modal = await Taro.showModal({
          title: copy.generationErrors.ACTIVE_JOB_LIMIT.title,
          content: copy.generationErrors.ACTIVE_JOB_LIMIT.body,
          confirmText: copy.generation.viewActiveJob,
          cancelText: copy.actions.cancel,
        });
        if (modal.confirm) {
          try {
            const active = await vibeApi.getActiveJob();
            if (active?.id) {
              generateJobRef.current = active.id;
              setActiveJobId(active.id);
              setActiveJobType((active.job_type as typeof resolvedJobType) || "single");
            }
          } catch {
            showError(c.activeJobLimit);
          }
        }
        return;
      }
      if (isQueueOverload(e)) {
        showError(copy.generation.queueOverload);
        return;
      }
      if (isRateLimited(e)) {
        const wait = getRateLimitRetryAfter(e);
        showError(
          wait != null
            ? copy.generation.rateLimitedWithSeconds.replace("{n}", String(wait))
            : copy.generation.rateLimited
        );
        return;
      }
      if (isInsufficientCredits(e)) {
        handle402();
        return;
      }
      if (mode === "remix" && isRemixForbidden(e)) {
        showError(copy.derivative.remixNotAllowed);
        return;
      }
      showError(c.generateFail);
      return;
    } finally {
      if (jobId) generateJobRef.current = jobId;
      if (!jobId) {
        generateLatchRef.current = false;
        generateIdempotencyRef.current = null;
      }
      setSubmitting(false);
    }

    if (!jobId) return;

    const startedAt = new Date().toISOString();
    const jobType = resolvedJobType;
    const remixSource: RemixSourceSnapshot | undefined =
      mode === "remix" && seedWorkId
        ? { workId: seedWorkId, title: seedWorkTitle, intent: textIntent.trim() }
        : undefined;
    activeJobCtx?.setJob({
      jobId,
      progress: 0,
      status: "running",
      message: "",
      returnUrl: "/pages/create/index",
      startedAt,
      jobType,
      remixSourceTitle: remixSource?.title,
    });
      setProgressOpen(true);
      setActiveJobId(jobId);
    setActiveJobType(jobType);
    setActiveJobStartedAt(startedAt);
    if (remixSource) setActiveRemixSource(remixSource);
    persistActiveGeneration({
      jobId,
      returnUrl: "/pages/create/index",
      startedAt,
      jobType,
      remixSource,
    });
    setItem("create:lastDraft", JSON.stringify({ textIntent, lyrics, mode, seedWorkId }));
    applyCreditsResponse(creditsCtx, creditsPayload);
    const taskGrant = taskCreditsGranted(creditsPayload);
    if (taskGrant) {
      showSuccess(copy.progressUi.taskReward.replace("{n}", String(taskGrant)));
    }
  }

  const needsSeed = mode === "cover" || mode === "variation";
  const offerCheckin = Boolean(isLoggedIn() && creditsShort && checkinToday === false);
  const dockCta = !isLoggedIn()
    ? c.dockLogin
    : creditsLoading
      ? c.dockCreditsLoading
      : offerCheckin
      ? c.dockCheckin
      : creditsBlocked
        ? c.dockTopUp
        : mode === "cover" && coverStep === "preprocess"
          ? c.coverPreprocess
          : mode === "cover" && coverStep === "generate"
            ? c.coverStepGenerate
            : c.dockGenerate;

  async function claimDailyCheckin() {
    if (checkingIn) return;
    setCheckingIn(true);
    try {
      const res = await vibeApi.dailyCheckin();
      creditsCtx?.setBalance(res.balance);
      setCheckinToday(true);
      showSuccess(copy.progressUi.checkinSuccess);
      await creditsCtx?.refresh();
    } catch {
      Taro.showToast({ title: copy.progressUi.checkinFail, icon: "none" });
    } finally {
      setCheckingIn(false);
    }
  }

  const titleFallback =
    mode === "playlist"
      ? c.defaultPlaylistTitle
      : mode === "lyrics"
        ? c.defaultLyricsTitle
        : mode === "remix"
          ? c.remixFlow.defaultTitle
          : c.defaultTrackTitle;
  const suggestedTitleForSheet =
    mode === "remix" && seedWorkTitle.trim()
      ? `${c.remixFlow.defaultTitle} · ${seedWorkTitle.trim()}`.slice(0, 60)
      : resolveWorkTitle("", textIntent, titleFallback, titleSuggestOpts);
  /** Same-style / remelt / cover / variation / remix: banner + spell + dock — no mode wall. */
  const followAlong =
    createAction !== "compose" || mode === "cover" || mode === "variation" || mode === "remix";
  const followBanner =
    createAction === "sameStyle"
      ? c.sameStyleBanner
      : createAction === "regenerate"
        ? c.regenerateBanner
        : mode === "cover"
          ? c.coverBanner
          : mode === "variation"
            ? c.variationBanner
            : mode === "remix"
              ? c.remixBanner
              : "";

  return (
    <PageShell
      title={copy.pages.create.title}
      subtitle={copy.brand.tagline}
      showCredits={false}
      ambient
      tabVariant
      wide
      noPadTop
      hideHeader
    >
      <View className={`tab-page create-home${jobBlocking ? " create-home--generating" : ""}${activeJobId && !jobBlocking ? " create-home--review" : ""}${coachOpen ? " create-home--coach-open" : ""}${coachOpen && coachAnchor ? ` create-home--coach-${coachAnchor}` : ""}${!isLoggedIn() ? " create-home--guest" : ""}`}>
        <View className="create-appbar">
          <Text className="create-appbar__brand">{copy.pages.create.title}</Text>
          <Text className="create-appbar__credits" onClick={() => isLoggedIn() && openPaywall({ source: "create_appbar", tab: "pack" })}>
            {isLoggedIn() ? c.homeDeckCredits.replace("{n}", String(credits ?? "—")) : copy.profileUi.loginButton}
          </Text>
          <Text className="create-appbar__me" onClick={() => (isLoggedIn() ? Taro.switchTab({ url: "/pages/profile/index" }) : requireAuth(CREATE_NEXT))}>
            {isLoggedIn() ? "我" : copy.profileUi.loginButton}
          </Text>
        </View>
        {isLoggedIn() && <CommercialAlertBanners subscription={subscription} />}
        <LaunchHonestyBanner surface="create" />
        {!isLoggedIn() && (
          <View
            className="create-home__guest-banner"
            hoverClass="none"
            onClick={() => {
              hapticLight();
              requireAuth(CREATE_NEXT);
            }}
          >
            <Text className="create-home__guest-hint">{c.authBanner}</Text>
            <Text className="create-home__guest-login">{copy.profileUi.loginButton}</Text>
          </View>
        )}
        <View className="create-home__form">

        {followAlong && (seedWorkTitle || followBanner) && (
          <View className="create-home__same-banner">
            <Text className="create-home__same-banner-text">
              {(followBanner || c.sameStyleBanner).replace("{title}", seedWorkTitle || "…")}
            </Text>
          </View>
        )}
        {recipeReady && !followAlong && (
          <View className="create-home__same-banner">
            <Text className="create-home__same-banner-text">{copy.marketplaceUi.recipeReady}</Text>
          </View>
        )}

        {followAlong && needsSeed && (
          <View className="create-home__section create-home__section--seed">
            <Suspense fallback={<LoadingSkeleton count={1} />}>
              <WorkPicker
                value={seedWorkId}
                authNext={CREATE_NEXT}
                onChange={(id, title) => {
                  setSeedWorkId(id);
                  setSeedWorkTitle(title || "");
                  if (title) setItem("create:seedTitle", title);
                  setCoverStep("pick");
                }}
              />
            </Suspense>
          </View>
        )}

        {mode !== "remix" && (
          <View className="create-home__prompt coach-anchor-prompt">
          <Suspense fallback={<LoadingSkeleton count={2} />}>
          <CreateFormulaPanel
            intentLabel={c.homePromptLabel}
            intentHint={c.homePromptHint}
            intentPlaceholder={c.oneBoxPlaceholder}
            textIntent={textIntent}
            onTextIntentChange={(v) => {
              setTextIntent(v);
              if (creativeSpec.custom_prompt_override?.trim()) {
                setCreativeSpec((prev) => ({ ...prev, custom_prompt_override: "" }));
              }
            }}
            polishLabel={c.polishIntent}
            polishingLabel={c.polishingIntent}
            polishing={polishingIntent}
            onPolish={followAlong ? undefined : polishIntentAi}
            onIntentBlur={followAlong ? undefined : parseIntentOnBlur}
            maxlength={2000}
            draftLabel={followAlong ? undefined : c.draftEntry}
            onDraft={
              followAlong
                ? undefined
                : () => {
                    if (!requireAuth(CREATE_NEXT)) return;
                    void loadDrafts();
                    setDraftsOpen(true);
                  }
            }
            adjustLabel={followAlong ? undefined : c.choiceAdjust}
            onAdjust={followAlong ? undefined : () => setAdvancedOpen(true)}
            choicesLabel={followAlong ? undefined : c.choiceThis}
            choices={followAlong || jobBlocking ? undefined : choiceChips}
            onChoice={() => setAdvancedOpen(true)}
          />
          </Suspense>
          </View>
        )}

        {songWrite && !followAlong && !jobBlocking && (
          <View className="create-home__write">
            <Suspense fallback={<LoadingSkeleton count={1} />}>
              <SongSetupBar
                modesOnly
                songMode={songMode}
                freedom={freedom}
                takes={takes}
                quality={songQuality}
                quick={quickSong}
                onSongMode={setSongMode}
                onFreedom={setFreedom}
                onTakes={setTakes}
                onQuality={setSongQuality}
                onQuick={setQuickSong}
              />
            </Suspense>
          </View>
        )}

        {!followAlong && !jobBlocking && mode !== "remix" && mode !== "cover" && mode !== "variation" && (
          <View className="create-home__write">
            <Suspense fallback={<LoadingSkeleton count={2} />}>
              <PresetCarousel
                compact
                className="create-home__presets"
                presets={presets}
                selectedId={selectedPresetId}
                onSelect={selectPreset}
                isMember={creditsCtx?.isMember}
                onMemberGate={() => {
                  vibeApi.trackEvent("member_preset_gate", { preset_id: selectedPresetId }).catch(() => {});
                  if (worksCount === 0) {
                    showError(c.memberPresetLater);
                    return;
                  }
                  openPaywall({ source: "create_member_preset", tab: "member" });
                }}
              />
            </Suspense>
          </View>
        )}

        {songWrite && songMode !== "instrumental" && (songMode === "lyrics" || mode === "lyrics" || lyrics.trim()) && !followAlong && !jobBlocking && (
          <Suspense fallback={<LoadingSkeleton count={2} />}>
            <LyricsStructureEditor
              lyrics={lyrics}
              onChange={setLyrics}
              onGenerate={generateLyricsAi}
              generating={generatingLyrics}
              revising={revisingLyrics}
              onReviseSection={(instruction, index) => reviseLyricsAi(instruction, index)}
            />
          </Suspense>
        )}

        {!followAlong && !jobBlocking && recentWork ? (
          <View className="create-home__song">
            <Text className="create-shelf__title">{c.continueTitle}</Text>
            <Text className="create-home__song-title">{recentWork.title}</Text>
            <Text
              className="create-home__song-play"
              onClick={() => {
                void vibeApi.getWork(recentWork.id).then((work) => {
                  playTrack(workToPlayerTrack(work, { source: "library", isOwner: true }), { navigate: false });
                });
              }}
            >
              {c.recentListen}
            </Text>
            <Text
              className="create-home__song-next"
              onClick={() => {
                if (!requireAuth(CREATE_NEXT)) return;
                if (needsBeautifyMaster(recentWork)) {
                  openWorkbench(recentWork.id);
                  return;
                }
                goShipBand(recentWork.superseded_by_work_id || recentWork.id);
              }}
            >
              {needsBeautifyMaster(recentWork)
                ? copy.generation.reveal.beautify
                : copy.generation.reveal.releaseThisVersion}
            </Text>
          </View>
        ) : null}

        {!followAlong && !jobBlocking && pickerWorks.length > 0 ? (
          <View className="create-shelf">
            <Text className="create-shelf__title">{c.myWorks}</Text>
            <View className="create-shelf__row">
              {pickerWorks.slice(0, 8).map((work) => (
                <View
                  key={work.id}
                  className="create-shelf__card"
                  onClick={() => {
                    void vibeApi.getWork(work.id).then((full) => {
                      playTrack(workToPlayerTrack(full, { source: "library", isOwner: true }), { navigate: false });
                    });
                  }}
                >
                  {work.cover_url ? <Image className="create-shelf__cover" src={work.cover_url} mode="aspectFill" /> : <View className="create-shelf__cover" />}
                  <Text className="create-shelf__name">{work.title}</Text>
                </View>
              ))}
            </View>
          </View>
        ) : null}

        {mode === "remix" && !jobBlocking && (
          <View className="create-home__section create-home__section--remix">
            {!seedWorkId ? <Text className="typo-meta">{c.needSeed}</Text> : null}
            <Suspense fallback={<LoadingSkeleton count={2} />}>
              <RemixFlowPanel
              sourceWorkId={seedWorkId}
              intent={textIntent}
              onSourceChange={(id, title) => {
                setSeedWorkId(id);
                setSeedWorkTitle(title || "");
                if (title) setItem("create:seedTitle", title);
              }}
              onIntentChange={setTextIntent}
              onRemixAllowedChange={setSeedRemixAllowed}
              polishLabel={c.polishIntent}
              polishingLabel={c.polishingIntent}
              polishing={polishingIntent}
              onPolish={polishIntentAi}
            />
            </Suspense>
          </View>
        )}

        </View>
        {activeJobId && progressOpen && (
          <View className="create-stage">
            <Text className="create-stage__leave" onClick={() => setProgressOpen(false)}>{c.leaveGeneration}</Text>
          <Suspense fallback={<LoadingSkeleton count={3} />}>
            <GenerationProgress
              jobId={activeJobId}
              returnUrl="/pages/create/index"
              startedAt={activeJobStartedAt}
              jobType={activeJobType}
              remixSource={activeRemixSource ?? undefined}
              onComplete={(result) => {
                const id = result.workIds?.[0];
                if (!id) return;
                setCompletedWorkId(id);
                setWorksCount((n) => Math.max(n, result.workIds?.length || 1));
              }}
              onRetry={() => {
                setRemeltPreferred(true);
                generateJobRef.current = null;
                generateLatchRef.current = false;
                setActiveJobId(null);
                void generate();
              }}
              onEditIntent={() => {
                generateJobRef.current = null;
                generateLatchRef.current = false;
                setActiveJobId(null);
                activeJobCtx?.setJob(null);
                clearActiveGeneration();
              }}
            />
          </Suspense>
          </View>
        )}
        {activeJobId && !progressOpen ? (
          <View className="create-stage__bar" onClick={() => setProgressOpen(true)}>
            <Text>{copy.generation.stillWorking}</Text>
          </View>
        ) : null}

        {!jobBlocking && (
        <View className="create-home__dock">
          {isLoggedIn() ? <View className="create-home__dock-glow" /> : null}
          <View className="create-home__dock-inner">
            {isLoggedIn() ? (
              <CreditEstimateMeter
                mode={estimateMode}
                variations={twoTakes ? undefined : mode === "variation" ? 3 : undefined}
                onCreditsChange={setEstimatedCredits}
                silent
                showShortfall={false}
              />
            ) : null}
            {isLoggedIn() ? (
              <Text className="create-home__dock-cost typo-meta">
                {c.homeDeckCredits.replace("{n}", String(credits ?? "—"))}
              </Text>
            ) : null}
            <Button
              className="create-home__generate coach-anchor-generate"
              variant="primary"
              block
              loading={submitting || jobBlocking || checkingIn || creditsLoading}
              disabled={creditsBlocked || offerCheckin || creditsLoading || !isLoggedIn() ? false : !remixReady}
              onClick={() => {
                if (!requireAuth(CREATE_NEXT)) return;
                if (creditsLoading) return;
                if (offerCheckin) {
                  void claimDailyCheckin();
                  return;
                }
                if (creditsBlocked) {
                  openPaywall({ source: "create_dock", tab: "pack" });
                  return;
                }
                void generate();
              }}
            >
              {dockCta}
            </Button>
          </View>
        </View>
        )}
      </View>

      <CoachMarks page="create" onVisibilityChange={onCoachVisibility} suppressed={jobBlocking || submitting || aiDisclaimerOpen} />

      <BottomSheet
        open={advancedOpen}
        title={c.moreSheetTitle}
        onClose={() => setAdvancedOpen(false)}
        footer={
          <View className="create-home__sheet-footer">
            <Button variant="secondary" size="sm" block loading={savingDraft} onClick={saveDraft}>
              {c.saveDraft}
            </Button>
          </View>
        }
      >
        <CreateModePicker
          value={mode}
          hasWorks={worksCount > 0}
          onChange={(next) => handleModeSelect(next)}
          onJourney={() => {
            setAdvancedOpen(false);
            openStackPage(STUDIO_PAGE_ROUTES.journey);
          }}
        />
        {mode !== "remix" && soundRecipeOptions && (
          <Suspense fallback={<LoadingSkeleton count={1} />}>
            <SoundRecipePanel
              spec={creativeSpec}
              options={soundRecipeOptions}
              keyOptions={keyOptions}
              bpmPresets={bpmPresets}
              onChange={(next) => setCreativeSpec({ ...next, custom_prompt_override: "" })}
            />
          </Suspense>
        )}
        {mode !== "remix" && mode !== "lyrics" && !lyrics.trim() && (
          <Button
            variant="ghost"
            size="sm"
            className="create-home__lyrics-door"
            onClick={() => {
              setMode("lyrics");
              setCreateAction("compose");
              setSongMode("lyrics");
            }}
          >
            {c.addLyrics}
          </Button>
        )}
        {mode !== "remix" && diagnosisOpen && !activeJobId && (mode === "quickTrack" || mode === "lyrics") && (
          <Suspense fallback={null}>
            <EmotionDiagnosisCard
              onApply={({ arousal, valence, intentHint, genres, summary }) => {
                setCreativeSpec((prev) => ({
                  ...prev,
                  arousal,
                  valence,
                  genres: prev.genres.length ? prev.genres : genres,
                }));
                if (!textIntent.trim() || textIntent === c.defaultIntent) setTextIntent(intentHint);
                setDiagnosisSummary(summary);
                setDiagnosisOpen(false);
              }}
              onDismiss={() => setDiagnosisOpen(false)}
            />
          </Suspense>
        )}
        {mode !== "remix" && !diagnosisOpen && diagnosisSummary && !activeJobId && (mode === "quickTrack" || mode === "lyrics") && (
          <View className="create-home__diagnosis-echo" onClick={() => setDiagnosisOpen(true)}>
            <Text className="create-home__diagnosis-echo-text">{diagnosisSummary}</Text>
            <Text className="create-home__diagnosis-echo-edit">{c.diagnosisReopen}</Text>
          </View>
        )}
        {mode !== "remix" && soundRecipeOptions && (
          <Suspense fallback={null}>
            <PromptPreviewBar
              spec={creativeSpec}
              textIntent={textIntent}
              styleTags={lyricsStyleTags}
              onOverrideChange={(override) => setCreativeSpec((prev) => ({ ...prev, custom_prompt_override: override }))}
            />
          </Suspense>
        )}
        {(mode === "quickTrack" || mode === "playlist") && (
          <Suspense fallback={null}>
          <ReferenceTrackPicker
            works={pickerWorks}
            selectedId={referenceWorkId}
            avOffset={referenceAvOffset}
            onSelect={setReferenceWorkId}
            onOffsetChange={setReferenceAvOffset}
          />
          </Suspense>
        )}
        {mode === "lyrics" && (
          <>
            <TextArea
              label={c.lyricsLabel}
              placeholder={c.lyricsPlaceholder}
              value={lyrics}
              onInput={(e) => setLyrics(e.detail.value)}
              maxlength={8000}
            />
            <Button variant="secondary" size="sm" loading={generatingLyrics} onClick={generateLyricsAi}>
              {c.generateLyrics}
            </Button>
          </>
        )}
        {mode === "cover" && coverStep === "generate" && !coverLyricLock && (
          <TextArea
            label={c.lyricsLabel}
            value={coverLyrics}
            onInput={(e) => setCoverLyrics(e.detail.value)}
            maxlength={2000}
          />
        )}
        {mode === "cover" && coverStep === "generate" && coverLyricLock ? (
          <Text className="typo-meta">{c.coverLyricLockHint}</Text>
        ) : null}
        {needsSeed && !followAlong && (
          <Suspense fallback={<LoadingSkeleton count={2} />}>
            <WorkPicker
              value={seedWorkId}
              authNext={CREATE_NEXT}
              onChange={(id, title) => {
                setSeedWorkId(id);
                if (title) setItem("create:seedTitle", title);
                setCoverStep("pick");
              }}
            />
          </Suspense>
        )}
      </BottomSheet>

      <BottomSheet open={draftsOpen} title={c.draftsLabel} onClose={() => setDraftsOpen(false)}>
        {drafts.length === 0 && <Text className="typo-meta">{isLoggedIn() ? c.draftsEmpty : c.draftsEmptyGuest}</Text>}
        {drafts.map((d) => (
          <View key={d.id} className="create-draft-row">
            <Button variant="ghost" block onClick={() => applyDraft(d)}>
              {d.title} · {d.mode}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => removeDraft(d.id)}>
              {c.deleteDraft}
            </Button>
          </View>
        ))}
      </BottomSheet>

      <Suspense fallback={null}>
        <CreditsPaywallSheet
          open={paywallOpen}
          requiredCredits={paywallCredits}
          source={paywallSource}
          initialTab={paywallTab}
          returnPath="/pages/create/index"
          onClose={() => setPaywallOpen(false)}
          onSuccess={() => {
            setPaywallOpen(false);
            void creditsCtx?.refresh();
            showSuccess(c.paywallReady);
          }}
        />
      </Suspense>

      <Suspense fallback={null}>
      <WorkTitleSheet
        open={titleSheetOpen}
        sheetTitle={c.workTitleSheetTitle}
        body={c.workTitleSheetBody}
        label={c.workTitleLabel}
        placeholder={c.workTitlePlaceholder}
        hint={c.workTitleHint}
        suggestLabel={c.workTitleSheetSuggest}
        suggestedTitle={suggestedTitleForSheet}
        skipLabel={c.workTitleSheetSkip}
        confirmLabel={c.workTitleSheetConfirm}
        title={titleDraft}
        loading={submitting}
        onTitleChange={setTitleDraft}
        onUseSuggested={() => setTitleDraft(suggestedTitleForSheet)}
        onSkip={() => void requestGenerate("")}
        onConfirm={() => void requestGenerate(titleDraft)}
        onClose={() => setTitleSheetOpen(false)}
      />
      </Suspense>
      <AiDisclaimerSheet
        open={aiDisclaimerOpen}
        loading={aiConsentLoading}
        onClose={() => setAiDisclaimerOpen(false)}
        onConfirm={() => void confirmAiDisclaimer()}
      />
    </PageShell>
  );
}
