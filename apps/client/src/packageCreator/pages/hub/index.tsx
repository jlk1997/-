import { useDidShow, useRouter } from "@tarojs/taro";
import { openCreatorDesk, type CreatorDeskPane } from "../../../constants/routes";

/** Old bookmarks land here; the desk is now a tab. */
export default function CreatorHubRedirect() {
  const router = useRouter();
  useDidShow(() => {
    const pane = router.params.pane as CreatorDeskPane | undefined;
    openCreatorDesk(pane === "today" || pane === "release" || pane === "money" || pane === "tools" ? pane : undefined);
  });
  return null;
}
