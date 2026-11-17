import Taro from "@tarojs/taro";
import type { StudioAction } from "@vibe-sorcery/types";
import { setItem } from "../platform/storage";
import { COMMERCE_PAGE_ROUTES, CREATOR_PAGE_ROUTES, CREATOR_TAB_ROUTE, commercePage, creatorPage, openCreatorDesk, STACK_PAGE_ROUTES } from "../constants/routes";
import { openStackPage } from "./navigation";
import { showCoverUnavailable } from "./coverUnavailable";

const CREATOR_NAV: Record<string, keyof typeof CREATOR_PAGE_ROUTES> = {
  hub: "hub",
  release: "release",
  dataImport: "dataImport",
  import: "dataImport",
  accounts: "accounts",
  connector: "accounts",
  seats: "accounts",
  "/packageCreator/pages/accounts/index": "accounts",
  wallet: "wallet",
  settlements: "settlements",
  deliveries: "deliveries",
  passport: "passport",
  commune: "commune",
  remoteLogin: "remoteLogin",
  help: "help",
  "/packageCreator/pages/hub/index": "hub",
  "/packageCreator/pages/help/index": "help",
  "/packageCreator/pages/release/index": "release",
  "/packageCreator/pages/data-import/index": "dataImport",
  "/packageCreator/pages/wallet/index": "wallet",
  "/packageCreator/pages/settlements/index": "settlements",
  "/packageCreator/pages/deliveries/index": "deliveries",
  "/packageCreator/pages/passport/index": "passport",
  "/packageCreator/pages/commune/index": "commune",
  "/packageCreator/pages/remote-login/index": "remoteLogin",
};

const COMMERCE_NAV: Record<string, keyof typeof COMMERCE_PAGE_ROUTES> = {
  sync: "syncDesk",
  syncDesk: "syncDesk",
  "/packageCommerce/pages/sync-desk/index": "syncDesk",
  emotionCalendar: "emotionCalendar",
  calendar: "emotionCalendar",
  "/packageCommerce/pages/emotion-calendar/index": "emotionCalendar",
};

/** Apply Copilot StudioAction list — prefill storage keys then navigate. */
export function applyStudioActions(actions: StudioAction[]): void {
  let navigatePath: string | null = null;
  let navigateParams: Record<string, string> | undefined;
  let coverPaused = false;
  const pauseCover = () => {
    if (!coverPaused) showCoverUnavailable();
    coverPaused = true;
  };

  for (const action of actions) {
    switch (action.type) {
      case "prefill_create": {
        if (action.mode === "cover") {
          pauseCover();
          break;
        }
        setItem("create:mode", action.mode);
        if (action.payload.text_intent) setItem("create:seedIntent", action.payload.text_intent);
        if (action.payload.preset_id) setItem("create:presetId", action.payload.preset_id);
        if (action.payload.seed_work_id) setItem("create:seedWorkId", action.payload.seed_work_id);
        if (action.payload.reference_work_id) setItem("create:referenceWorkId", action.payload.reference_work_id);
        if (action.payload.lyrics) setItem("create:lyrics", action.payload.lyrics);
        if (action.payload.creative_spec) {
          setItem("create:creativeSpec", JSON.stringify(action.payload.creative_spec));
        }
        break;
      }
      case "prefill_journey": {
        if (action.payload.text_intent) setItem("journey:seedIntent", action.payload.text_intent);
        setItem("journey:waypoints", JSON.stringify(action.payload.journey));
        if (action.payload.title) setItem("journey:title", action.payload.title);
        break;
      }
      case "navigate": {
        if (action.params?.mode === "cover" || action.path.includes("mode=cover")) {
          pauseCover();
          break;
        }
        const raw = action.path.replace(/^\//, "");
        const alias = CREATOR_NAV[action.path] || CREATOR_NAV[raw];
        const commerceAlias = COMMERCE_NAV[action.path] || COMMERCE_NAV[raw];
        if (alias === "hub") {
          navigatePath = CREATOR_TAB_ROUTE;
          navigateParams = undefined;
        } else if (alias) {
          navigatePath = creatorPage(alias, action.params);
          navigateParams = undefined;
        } else if (commerceAlias) {
          navigatePath = commercePage(commerceAlias, action.params);
          navigateParams = undefined;
        } else {
          navigatePath = action.path;
          navigateParams = action.params;
        }
        break;
      }
      case "show_paywall":
        navigatePath = STACK_PAGE_ROUTES.pricing;
        break;
      case "start_generation":
        if (action.mode === "cover") {
          pauseCover();
          break;
        }
        setItem("create:mode", action.mode);
        if (action.estimate?.cost != null) {
          setItem("create:copilotEstimate", String(action.estimate.cost));
        }
        setItem("create:copilotConfirm", "1");
        navigatePath = "/pages/create/index";
        navigateParams = { mode: action.mode };
        break;
      default:
        break;
    }
  }

  if (!navigatePath) return;

  const query = navigateParams
    ? Object.entries(navigateParams)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join("&")
    : "";
  const url = query ? `${navigatePath}?${query}` : navigatePath;

  if (navigatePath.includes("/pages/create/") || navigatePath.includes("/pages/creator/")) {
    if (navigatePath.includes("/pages/creator/")) openCreatorDesk();
    else Taro.switchTab({ url: navigatePath.split("?")[0] });
    return;
  }
  openStackPage(url);
}
