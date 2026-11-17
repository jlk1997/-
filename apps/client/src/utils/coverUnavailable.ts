import Taro from "@tarojs/taro";
import { getLocaleCopy } from "./localeCopy";

/** Cover needs MiniMax music-cover. That path is down, so clicks stop here. */
export function showCoverUnavailable() {
  const c = getLocaleCopy().createUi;
  void Taro.showModal({
    title: c.coverUnavailableTitle,
    content: c.coverUnavailableBody,
    showCancel: false,
    confirmText: c.coverUnavailableOk,
  });
}
