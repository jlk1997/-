import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { bootstrapAuth, isLoggedIn } from "../utils/auth";
import { useCreditsOptional } from "../contexts/CreditsProvider";
import { currentLayoutRoute, isImmersiveRoute, LIBRARY_PAGE_ROUTE, STACK_PAGE_ROUTES } from "../constants/routes";
import { useRouteTick } from "../hooks/useRouteTick";
import { syncRootLayoutFromRoute } from "../platform/layout";
import { openRadioPage, openStackPage } from "../utils/navigation";
import { fetchUnreadCount, peekUnread } from "../utils/unreadBadge";
import { prefetchCoreChunks } from "../utils/prefetchH5";
import { subscribeNavPending } from "../utils/navPending";
import { Icon, StatPill } from "./ui";
import { BrandLogo } from "./brand/BrandLogo";
import "./AppShell.scss";

/** H5 global top bar — rendered as sibling of tab pages (not wrapping them). */
export function AppHeader() {
  const { copy } = useLocale();
  const credits = useCreditsOptional();
  const [unread, setUnread] = useState(peekUnread);
  const [opening, setOpening] = useState(false);
  const routeTick = useRouteTick();
  const route = currentLayoutRoute();
  const immersive = isImmersiveRoute(route);
  const createFocus = route.includes("pages/create");

  useEffect(() => {
    syncRootLayoutFromRoute({ showAppHeader: !immersive });
  }, [immersive, routeTick]);

  useEffect(() => subscribeNavPending((url) => setOpening(Boolean(url))), []);

  useEffect(() => {
    prefetchCoreChunks();
    if (!isLoggedIn()) {
      setUnread(0);
      return;
    }
    bootstrapAuth();
    const pull = (force = false) => {
      void fetchUnreadCount(force).then(setUnread);
    };
    pull();
    const id = setInterval(() => pull(), 45_000);
    const onShow = () => pull();
    Taro.onAppShow(onShow);
    return () => {
      clearInterval(id);
      try {
        Taro.offAppShow(onShow);
      } catch {
        /* older runtimes */
      }
    };
  }, []);

  if (process.env.TARO_ENV !== "h5" || immersive) return null;

  return (
    <View className={`app-shell__header app-shell__header--global${opening ? " app-shell__header--opening" : ""}`}>
      {opening ? <Text className="app-shell__opening">{copy.appShellUi.opening}</Text> : null}
      <View className="app-shell__brand" onClick={() => Taro.switchTab({ url: "/pages/create/index" })}>
        <BrandLogo variant="icon" size="sm" showName={false} className="app-shell__brand-mark" />
        <Text className="app-shell__logo">{copy.brand.name}</Text>
      </View>
      <View className="app-shell__actions">
        <View className="app-shell__action" onClick={() => openRadioPage()}>
          <Icon name="music" accent />
        </View>
        {createFocus ? null : (
          <View
            className="app-shell__action"
            onClick={() =>
              Taro.switchTab({ url: LIBRARY_PAGE_ROUTE }).catch(() => {
                void Taro.redirectTo({ url: LIBRARY_PAGE_ROUTE });
              })
            }
          >
            <Icon name="list" />
          </View>
        )}
        <View className="app-shell__action" onClick={() => openStackPage(STACK_PAGE_ROUTES.search)}>
          <Icon name="search" accent />
        </View>
        <View className="app-shell__action app-shell__action--notify" onClick={() => openStackPage(STACK_PAGE_ROUTES.notifications)}>
          <Icon name="bell" />
          {unread > 0 && (
            <StatPill
              label={unread > 99 ? "99+" : String(unread)}
              variant="danger"
              className="app-shell__notify-pill"
            />
          )}
        </View>
        {credits?.balance != null && (
          <StatPill
            label={copy.appShellUi.credits.replace("{n}", String(credits.balance))}
            onClick={() => openStackPage(STACK_PAGE_ROUTES.pricing)}
          />
        )}
      </View>
    </View>
  );
}
