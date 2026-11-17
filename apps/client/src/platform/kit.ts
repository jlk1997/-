import Taro from "@tarojs/taro";
import { API_BASE, getAuthToken } from "@vibe-sorcery/api-client";

export function releaseKitUrl(releaseId: string) {
  return `${API_BASE}/releases/${releaseId}/kit`;
}

export function workClipPackUrl(workId: string) {
  return `${API_BASE}/creator/works/${workId}/clip-pack`;
}

export function workOriginalityUrl(workId: string) {
  return `${API_BASE}/creator/works/${workId}/originality`;
}

export async function downloadReleaseKit(releaseId: string, filename = `vibe-release-${releaseId.slice(0, 8)}.zip`) {
  return downloadAuthZip(releaseKitUrl(releaseId), filename);
}

export async function downloadWorkClipPack(workId: string, filename = `vibe-clips-${workId.slice(0, 8)}.zip`) {
  return downloadAuthZip(workClipPackUrl(workId), filename);
}

export async function downloadWorkOriginality(workId: string, filename = `vibe-originality-${workId.slice(0, 8)}.zip`) {
  return downloadAuthZip(workOriginalityUrl(workId), filename);
}

async function downloadAuthZip(url: string, filename: string) {
  const token = getAuthToken();
  const header = token ? { Authorization: `Bearer ${token}` } : {};

  if (process.env.TARO_ENV === "weapp") {
    const dl = await Taro.downloadFile({ url, header, timeout: 120000 });
    if (dl.statusCode !== 200 || !dl.tempFilePath) {
      throw new Error(`kit_download_failed:${dl.statusCode || 0}`);
    }
    const share = (Taro as typeof Taro & { shareFileMessage?: (opts: { filePath: string; fileName?: string }) => Promise<unknown> })
      .shareFileMessage;
    if (typeof share === "function") {
      try {
        await share({ filePath: dl.tempFilePath, fileName: filename });
        return "shared";
      } catch {
        /* fall through to open / copy */
      }
    }
    try {
      await Taro.openDocument({ filePath: dl.tempFilePath, showMenu: true });
      return "opened";
    } catch {
      await Taro.setClipboardData({ data: url });
      return "copied";
    }
  }

  if (typeof window !== "undefined" && typeof fetch === "function") {
    const res = await fetch(url, { headers: header });
    if (!res.ok) throw new Error(`download failed:${res.status}`);
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
    return "saved";
  }

  await Taro.setClipboardData({ data: url });
  return "copied";
}
