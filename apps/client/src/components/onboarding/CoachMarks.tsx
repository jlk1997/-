import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { AUTH_EVENTS } from "../../constants/events";
import {
  AUTO_COACH_PAGES,
  disableAllOnboarding,
  isCoachPageActive,
  markPageOnboardingDone,
  ONBOARDING_RESET_EVENT,
  setJourneyGuideCollapsed,
  shouldShowPageCoach,
  type CoachPage,
} from "../../utils/onboarding";
import { currentLayoutRoute } from "../../constants/routes";
import { useRouteTick } from "../../hooks/useRouteTick";
import { isLoggedIn } from "../../utils/auth";
import { hasLocalPrivacyConsent } from "../legal/PrivacyConsentGate";
import "./CoachMarks.scss";

type Props = {
  page: CoachPage;
  onVisibilityChange?: (visible: boolean, anchor?: string) => void;
  suppressed?: boolean;
};

type Anchor =
  | "prompt"
  | "generate"
  | "doors"
  | "wall"
  | "adventure"
  | "next"
  | "lamps"
  | "ship"
  | "shelf"
  | "credits"
  | "menu";

type SpotRect = { top: number; left: number; width: number; height: number };

function px(n: number) {
  return `${Math.round(n)}Px`;
}

function viewport() {
  if (typeof window !== "undefined") {
    return { width: window.innerWidth || 0, height: window.innerHeight || 0 };
  }
  try {
    const info = Taro.getSystemInfoSync();
    return { width: Number(info.windowWidth) || 0, height: Number(info.windowHeight) || 0 };
  } catch {
    return { width: 0, height: 0 };
  }
}

function fallbackSpot(anchor: Anchor, vw: number, vh: number): SpotRect {
  const side = Math.max(16, vw * 0.05);
  if (anchor === "generate") {
    return { top: Math.max(80, vh - 150), left: side, width: vw - side * 2, height: 88 };
  }
  if (anchor === "doors") {
    return { top: Math.max(80, vh - 210), left: side, width: 168, height: 44 };
  }
  if (anchor === "prompt") {
    return { top: Math.max(88, vh * 0.2), left: side, width: vw - side * 2, height: 168 };
  }
  if (anchor === "credits") {
    return { top: Math.max(72, vh * 0.3), left: side, width: vw - side * 2, height: 64 };
  }
  if (anchor === "menu") {
    return { top: Math.max(80, vh - 240), left: side, width: vw - side * 2, height: 160 };
  }
  return { top: Math.max(88, vh * 0.22), left: side, width: vw - side * 2, height: 140 };
}

function readDomRect(anchor: Anchor): SpotRect | null {
  if (typeof document === "undefined") return null;
  const el = document.querySelector(`.coach-anchor-${anchor}`) as HTMLElement | null;
  if (!el) return null;
  const box = el.getBoundingClientRect();
  if (box.width < 8 || box.height < 8) return null;
  const pad = 8;
  return {
    top: Math.max(0, box.top - pad),
    left: Math.max(0, box.left - pad),
    width: box.width + pad * 2,
    height: box.height + pad * 2,
  };
}

function measureAnchor(anchor: Anchor): Promise<SpotRect | null> {
  const fromDom = readDomRect(anchor);
  if (fromDom) return Promise.resolve(fromDom);
  return new Promise((resolve) => {
    try {
      Taro.createSelectorQuery()
        .select(`.coach-anchor-${anchor}`)
        .boundingClientRect((rect) => {
          const box = Array.isArray(rect) ? rect[0] : rect;
          if (box && typeof box === "object" && Number(box.width) > 8) {
            const pad = 8;
            resolve({
              top: Math.max(0, Number(box.top) - pad),
              left: Math.max(0, Number(box.left) - pad),
              width: Number(box.width) + pad * 2,
              height: Number(box.height) + pad * 2,
            });
            return;
          }
          resolve(readDomRect(anchor));
        })
        .exec();
    } catch {
      resolve(readDomRect(anchor));
    }
  });
}

function veilsAround(spot: SpotRect, vw: number, vh: number): SpotRect[] {
  const right = spot.left + spot.width;
  const bottom = spot.top + spot.height;
  return [
    { top: 0, left: 0, width: vw, height: Math.max(0, spot.top) },
    { top: spot.top, left: 0, width: Math.max(0, spot.left), height: spot.height },
    { top: spot.top, left: right, width: Math.max(0, vw - right), height: spot.height },
    { top: bottom, left: 0, width: vw, height: Math.max(0, vh - bottom) },
  ].filter((veil) => veil.width >= 1 && veil.height >= 1);
}

function panelStyleFor(spot: SpotRect | null, vh: number): Record<string, string> | undefined {
  if (!spot || !vh) return undefined;
  const gap = 12;
  const spaceBelow = vh - (spot.top + spot.height + gap);
  const spaceAbove = spot.top - gap;
  if (spaceBelow >= 188 || spaceBelow >= spaceAbove) {
    return { top: px(spot.top + spot.height + gap), bottom: "auto", transform: "none" };
  }
  return { top: "auto", bottom: px(Math.max(12, vh - spot.top + gap)), transform: "none" };
}

export function CoachMarks({ page, onVisibilityChange, suppressed }: Props) {
  const { copy } = useLocale();
  const o = copy.onboarding;
  const j = copy.journeyUi;
  const d = copy.discoverUi;
  const l = copy.libraryUi;
  const pr = copy.profileUi;
  const cr = copy.creatorUi;
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);
  const [spot, setSpot] = useState<SpotRect | null>(null);
  const [authTick, setAuthTick] = useState(0);
  const notifyRef = useRef(onVisibilityChange);
  notifyRef.current = onVisibilityChange;
  const routeTick = useRouteTick();
  const hostActive = isCoachPageActive(page, currentLayoutRoute());
  const privacyReady = process.env.TARO_ENV !== "h5" || hasLocalPrivacyConsent();
  const signedIn = isLoggedIn();
  const requiresLogin = AUTO_COACH_PAGES.includes(page);
  const open = Boolean(visible && !suppressed && hostActive && privacyReady && (!requiresLogin || signedIn));

  const steps = useMemo(() => {
    if (requiresLogin && !signedIn) return [];
    if (page === "create") {
      return [
        { title: o.step1Title, desc: o.step1Desc, anchor: "prompt" as Anchor },
        { title: o.step2Title, desc: o.step2Desc, anchor: "generate" as Anchor },
        { title: o.step3Title, desc: o.step3Desc, anchor: "doors" as Anchor },
      ];
    }
    if (page === "journey") {
      return [
        { title: j.coachStep1Title, desc: j.coachStep1Desc },
        { title: j.coachStep2Title, desc: j.coachStep2Desc },
        { title: j.coachStep3Title, desc: j.coachStep3Desc },
      ];
    }
    if (page === "feed") {
      return [
        { title: d.coachStep1Title, desc: d.coachStep1Desc, anchor: "wall" as Anchor },
        { title: d.coachStep2Title, desc: d.coachStep2Desc, anchor: "adventure" as Anchor },
        { title: d.coachStep3Title, desc: d.coachStep3Desc, anchor: "wall" as Anchor },
      ];
    }
    if (page === "library") {
      return [
        { title: l.coachStep1Title, desc: l.coachStep1Desc, anchor: "shelf" as Anchor },
        { title: l.coachStep2Title, desc: l.coachStep2Desc },
        { title: l.coachStep3Title, desc: l.coachStep3Desc },
      ];
    }
    if (page === "creator") {
      return [
        { title: cr.coachStep1Title, desc: cr.coachStep1Desc, anchor: "next" as Anchor },
        { title: cr.coachStep2Title, desc: cr.coachStep2Desc, anchor: "lamps" as Anchor },
        { title: cr.coachStep3Title, desc: cr.coachStep3Desc, anchor: "ship" as Anchor },
      ];
    }
    return [
      { title: pr.coachStep1Title, desc: pr.coachStep1Desc, anchor: "shelf" as Anchor },
      { title: pr.coachStep2Title, desc: pr.coachStep2Desc, anchor: "credits" as Anchor },
      { title: pr.coachStep3Title, desc: pr.coachStep3Desc, anchor: "menu" as Anchor },
    ];
  }, [page, signedIn, requiresLogin, o, j, d, l, pr, cr]);

  useEffect(() => {
    const bump = () => setAuthTick((n) => n + 1);
    Taro.eventCenter.on(AUTH_EVENTS.login, bump);
    Taro.eventCenter.on(AUTH_EVENTS.logout, bump);
    Taro.eventCenter.on(ONBOARDING_RESET_EVENT, bump);
    return () => {
      Taro.eventCenter.off(AUTH_EVENTS.login, bump);
      Taro.eventCenter.off(AUTH_EVENTS.logout, bump);
      Taro.eventCenter.off(ONBOARDING_RESET_EVENT, bump);
    };
  }, []);

  useEffect(() => {
    if (!privacyReady) {
      setVisible(false);
      return;
    }
    if (requiresLogin && !isLoggedIn()) {
      setVisible(false);
      return;
    }
    if (shouldShowPageCoach(page)) {
      setStep(0);
      setVisible(true);
    }
  }, [page, privacyReady, routeTick, signedIn, authTick, requiresLogin]);

  const current = steps[step];
  const anchor = current && "anchor" in current ? current.anchor : undefined;

  useEffect(() => {
    notifyRef.current?.(open, open ? anchor : undefined);
  }, [open, anchor]);

  useEffect(() => {
    return () => notifyRef.current?.(false);
  }, []);

  useEffect(() => {
    if (process.env.TARO_ENV !== "h5" || typeof document === "undefined") return undefined;
    document.documentElement.classList.toggle("coach-blocking", open);
    return () => document.documentElement.classList.remove("coach-blocking");
  }, [open]);

  useEffect(() => {
    if (!open || !anchor) {
      setSpot(null);
      return undefined;
    }
    let cancelled = false;
    const apply = async () => {
      if (typeof document !== "undefined") {
        document.querySelector(`.coach-anchor-${anchor}`)?.scrollIntoView({ block: "center", inline: "nearest" });
      }
      const view = viewport();
      const measured = await measureAnchor(anchor);
      if (cancelled) return;
      setSpot(measured || fallbackSpot(anchor, view.width || 360, view.height || 640));
    };
    const timers = [50, 200, 450].map((ms) => setTimeout(() => void apply(), ms));
    const onResize = () => void apply();
    if (typeof window !== "undefined") window.addEventListener("resize", onResize);
    void apply();
    return () => {
      cancelled = true;
      timers.forEach((id) => clearTimeout(id));
      if (typeof window !== "undefined") window.removeEventListener("resize", onResize);
    };
  }, [open, anchor, step, page, routeTick]);

  if (!open) return null;
  if (!current) return null;

  function dismissPage() {
    markPageOnboardingDone(page);
    if (page === "journey") setJourneyGuideCollapsed(true);
    setVisible(false);
  }

  function dismissAll() {
    disableAllOnboarding();
    setVisible(false);
    Taro.showToast({ title: o.neverAgainDone, icon: "none" });
  }

  function next() {
    if (step >= steps.length - 1) dismissPage();
    else setStep(step + 1);
  }

  const view = viewport();
  const panelStyle = panelStyleFor(spot, view.height);
  const spotStyle = spot
    ? {
        top: px(spot.top),
        left: px(spot.left),
        width: px(spot.width),
        height: px(spot.height),
      }
    : undefined;
  const veils = spot && view.width && view.height ? veilsAround(spot, view.width, view.height) : [];
  const variantClass = `coach-marks--${page}${anchor ? ` coach-marks--${anchor}` : ""}${spot ? " coach-marks--cutout" : ""}`;

  return (
    <View className={`coach-marks ${variantClass}`} catchMove>
      {veils.length === 0 ? <View className="coach-marks__catch" onClick={next} /> : null}
      {veils.map((veil, index) => (
        <View
          key={`${veil.top}-${veil.left}-${index}`}
          className="coach-marks__veil"
          style={{
            top: px(veil.top),
            left: px(veil.left),
            width: px(veil.width),
            height: px(veil.height),
          }}
          onClick={next}
        />
      ))}
      {anchor ? <View className="coach-marks__spot" style={spotStyle} /> : null}
      <View className="coach-marks__panel" style={panelStyle}>
        <View className="coach-marks__card">
          <View className="coach-marks__badge">
            <Text className="coach-marks__step">
              {o.stepCounter.replace("{current}", String(step + 1)).replace("{total}", String(steps.length))}
            </Text>
          </View>
          <Text className="coach-marks__title">{current.title}</Text>
          <Text className="coach-marks__desc">{current.desc}</Text>
          <View className="coach-marks__actions">
            <View className="coach-marks__never" hoverClass="none" onClick={dismissAll}>
              <Text>{o.neverAgain}</Text>
            </View>
            <View className="coach-marks__skip" hoverClass="none" onClick={dismissPage}>
              <Text>{o.skip}</Text>
            </View>
            <View className="coach-marks__next" hoverClass="none" onClick={next}>
              <Text>{step >= steps.length - 1 ? o.done : o.next}</Text>
            </View>
          </View>
        </View>
      </View>
    </View>
  );
}
