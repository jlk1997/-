import { View, Text } from "@tarojs/components";
import { Component, PropsWithChildren, useEffect, useState, lazy, Suspense, type ReactNode } from "react";
import Taro, { useDidShow, useLaunch } from "@tarojs/taro";
import { LocaleProvider } from "@vibe-sorcery/i18n";
import { installTaroHttpAdapter } from "./services/http";
import { bootstrapAuth } from "./utils/auth";
import { bootstrapLocaleShell, createLocaleStorage } from "./utils/localeStorage";
import { CreditsProvider } from "./contexts/CreditsProvider";
import { PlayerProvider } from "./contexts/PlayerProvider";
import { ActiveJobProvider } from "./contexts/ActiveJobProvider";
import { ActiveJobHydrator } from "./components/ActiveJobHydrator";
import { TabBarLocaleSync } from "./components/TabBarLocaleSync";
import { AppShell } from "./components/AppShell";
import { getLocaleCopy } from "./utils/localeCopy";
import { ThemeProvider } from "./contexts/ThemeProvider";
import { LayoutVarsProvider } from "./contexts/LayoutVarsProvider";
import { installRouteAliases } from "./utils/navigation";
import { installH5TabRouterFix } from "./utils/h5TabRouter";
import { redirectLegacyBrowserPathToHash } from "./utils/h5Path";
import { syncRootLayoutFromRoute } from "./platform/layout";
import { AppHeader } from "./components/AppHeader";
import { PrivacyConsentGate, hasLocalPrivacyConsent } from "./components/legal/PrivacyConsentGate";
import { WechatPrivacyGate } from "./components/legal/WechatPrivacyGate";
import { captureReferralFromLaunch, captureReferralFromQuery } from "./platform/referral";
import { setClientSurface, vibeApi } from "./services/api";
setClientSurface(process.env.TARO_ENV === "weapp" ? "weapp" : "h5");
import { cachePlatformHonesty } from "./platform/platformConfig";
import { openCreatorDesk } from "./constants/routes";
import "./app.scss";
if (process.env.TARO_ENV === "h5") {
  require("./styles/h5-app-chrome.scss");
  require("./styles/motion.scss");
  require("./styles/h5-taro-reset.scss");
}
installTaroHttpAdapter();
installRouteAliases();
if (process.env.TARO_ENV === "h5") {
  redirectLegacyBrowserPathToHash();
  installH5TabRouterFix();
}

const localeStorage = createLocaleStorage();

const GlobalJobBanner = lazy(() =>
  import("./components/GlobalJobBanner").then((m) => ({ default: m.GlobalJobBanner }))
);
const ConsentUpdateBanner = lazy(() =>
  import("./components/legal/ConsentUpdateBanner").then((m) => ({ default: m.ConsentUpdateBanner }))
);

class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      const errTitle = getLocaleCopy().appUi.loadError;
      if (process.env.TARO_ENV === "h5") {
        return (
          <div className="app-error-fallback">
            <h2 className="app-error-fallback__title">{errTitle}</h2>
            <pre className="app-error-fallback__message">{this.state.error.message}</pre>
          </div>
        );
      }
      return (
        <View className="app-error-fallback">
          <Text className="app-error-fallback__title">{errTitle}</Text>
          <Text className="app-error-fallback__message">{this.state.error.message}</Text>
        </View>
      );
    }
    return this.props.children;
  }
}

export default function App({ children }: PropsWithChildren) {
  const [privacyOk, setPrivacyOk] = useState(
    process.env.TARO_ENV !== "h5" || hasLocalPrivacyConsent(),
  );
  // Taro H5 looks up the current page instance in `children`. Never replace
  // `{children}` with the privacy overlay — that throws「没有找到页面实例」.
  const [legalDocOpen, setLegalDocOpen] = useState(false);

  useLaunch((options) => {
    captureReferralFromQuery((options?.query || {}) as Record<string, unknown>);
  });
  useDidShow((options) => {
    captureReferralFromQuery((options?.query || {}) as Record<string, unknown>);
  });

  useEffect(() => {
    if (process.env.TARO_ENV !== "h5" || typeof window === "undefined") return;
    const syncLegalHash = () => {
      setLegalDocOpen(window.location.hash.includes("packageLegal/"));
    };
    syncLegalHash();
    window.addEventListener("hashchange", syncLegalHash);
    return () => window.removeEventListener("hashchange", syncLegalHash);
  }, []);

  useEffect(() => {
    if (process.env.TARO_ENV !== "h5" || typeof document === "undefined") return undefined;
    document.documentElement.classList.toggle("privacy-blocking", !privacyOk);
    return () => document.documentElement.classList.remove("privacy-blocking");
  }, [privacyOk]);

  useEffect(() => {
    bootstrapAuth();
    bootstrapLocaleShell();
    captureReferralFromLaunch();
    vibeApi
      .getPlatformConfig()
      .then((cfg) => cachePlatformHonesty(cfg))
      .catch(() => {});
    if (process.env.TARO_ENV === "weapp") {
      Taro.showShareMenu({ withShareTicket: true, showShareItems: ["shareAppMessage"] }).catch(() => {});
    }
    if (process.env.TARO_ENV === "h5" && typeof document !== "undefined") {
      syncRootLayoutFromRoute({ showAppHeader: true });
      const host = window.location.host;
      document.cookie = `vibe_tenant_host=${encodeURIComponent(host)};path=/;max-age=86400`;

      const fixLegacyHash = () => {
        const hash = window.location.hash;
        // Old landing tab
        if (hash.includes("pages/index/index")) {
          Taro.switchTab({ url: "/pages/create/index" }).catch(() => {
            Taro.reLaunch({ url: "/pages/create/index" });
          });
          return;
        }
        // Old /pages/journey/* bookmark → studio subpackage
        if (hash.includes("pages/journey/index") && !hash.includes("packageStudio/")) {
          Taro.redirectTo({ url: "/packageStudio/pages/journey/index" }).catch(() => {
            Taro.reLaunch({ url: "/packageStudio/pages/journey/index" });
          });
          return;
        }
        // Old creator hub bookmark → creator tab
        if (hash.includes("packageCreator/pages/hub")) {
          openCreatorDesk();
        }
      };

      fixLegacyHash();
      window.addEventListener("hashchange", fixLegacyHash);
      return () => window.removeEventListener("hashchange", fixLegacyHash);
    }
  }, []);

  return (
    <AppErrorBoundary>
      <LocaleProvider storage={localeStorage}>
        <TabBarLocaleSync />
        <ThemeProvider>
        <CreditsProvider>
          <ActiveJobProvider>
            <ActiveJobHydrator />
            <PlayerProvider>
              <LayoutVarsProvider>
                <Suspense fallback={null}>
                  <GlobalJobBanner />
                </Suspense>
                <AppHeader />
                <WechatPrivacyGate>
                    <View className="app-consent-slot">
                      <Suspense fallback={null}>
                        <ConsentUpdateBanner />
                      </Suspense>
                    </View>
                    <AppShell>{children}</AppShell>
                  </WechatPrivacyGate>
                {process.env.TARO_ENV === "h5" && !privacyOk ? (
                  <PrivacyConsentGate onAccepted={() => setPrivacyOk(true)} readingLegal={legalDocOpen} />
                ) : null}
              </LayoutVarsProvider>
            </PlayerProvider>
          </ActiveJobProvider>
        </CreditsProvider>
        </ThemeProvider>
      </LocaleProvider>
    </AppErrorBoundary>
  );
}
