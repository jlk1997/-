import Taro from "@tarojs/taro";
import { creatorPage } from "../constants/routes";
import { downloadReleaseKit, downloadWorkClipPack, downloadWorkOriginality } from "../platform/kit";
import { copyWeappCreatorLink } from "./WeappH5Bridge";

type KitCopy = {
  kitDownloading: string;
  kitShared: string;
  kitSaved: string;
  kitCopied: string;
  kitWeappHint: string;
  weappDeskHint?: string;
  stemsPending?: string;
  clipsPending?: string;
};

async function blockWeappDesk(copy: KitCopy, path: string) {
  if (process.env.TARO_ENV !== "weapp") return false;
  const copied = await copyWeappCreatorLink(path);
  if (!copied) Taro.showToast({ title: copy.weappDeskHint || copy.kitWeappHint, icon: "none" });
  return true;
}

function copiedHint(copy: KitCopy) {
  return process.env.TARO_ENV === "weapp" ? copy.kitWeappHint : copy.kitCopied;
}

function isPendingStatus(msg: string) {
  return msg.includes("409") || msg.includes(":409");
}

function toastPendingOrFail(msg: string, pending?: string) {
  if (msg.toLowerCase().includes("cancel")) return;
  if (isPendingStatus(msg) && pending) {
    Taro.showToast({ title: pending, icon: "none" });
    return;
  }
  if (msg.includes("kit_download_failed") || msg.includes("download failed")) {
    Taro.showToast({ title: pending || msg.slice(0, 24), icon: "none" });
    return;
  }
  throw new Error(msg);
}

export async function saveReleaseKit(releaseId: string, copy: KitCopy) {
  if (await blockWeappDesk(copy, creatorPage("release"))) return;
  Taro.showLoading({ title: copy.kitDownloading, mask: true });
  try {
    const result = await downloadReleaseKit(releaseId);
    Taro.hideLoading();
    const title = result === "shared" ? copy.kitShared : result === "copied" ? copiedHint(copy) : copy.kitSaved;
    Taro.showToast({ title, icon: result === "copied" ? "none" : "success" });
  } catch (err) {
    Taro.hideLoading();
    toastPendingOrFail(String((err as Error)?.message || err), copy.stemsPending);
  }
}

export async function saveOriginalityPack(workId: string, copy: KitCopy) {
  if (await blockWeappDesk(copy, creatorPage("work", { workId }))) return;
  Taro.showLoading({ title: copy.kitDownloading, mask: true });
  try {
    const result = await downloadWorkOriginality(workId);
    Taro.hideLoading();
    const title = result === "shared" ? copy.kitShared : result === "copied" ? copiedHint(copy) : copy.kitSaved;
    Taro.showToast({ title, icon: result === "copied" ? "none" : "success" });
  } catch (err) {
    Taro.hideLoading();
    toastPendingOrFail(String((err as Error)?.message || err), copy.stemsPending);
  }
}

export async function saveClipPack(workId: string, copy: KitCopy) {
  if (await blockWeappDesk(copy, creatorPage("work", { workId }))) return;
  Taro.showLoading({ title: copy.kitDownloading, mask: true });
  try {
    const result = await downloadWorkClipPack(workId);
    Taro.hideLoading();
    const title = result === "shared" ? copy.kitShared : result === "copied" ? copiedHint(copy) : copy.kitSaved;
    Taro.showToast({ title, icon: result === "copied" ? "none" : "success" });
  } catch (err) {
    Taro.hideLoading();
    toastPendingOrFail(String((err as Error)?.message || err), copy.clipsPending || copy.stemsPending);
  }
}
