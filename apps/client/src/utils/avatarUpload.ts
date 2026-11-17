import Taro from "@tarojs/taro";
import { vibeApi } from "../services/api";

export async function uploadUserAvatar(): Promise<string | undefined> {
  let pick: { tempFilePaths: string[] };
  try {
    pick = await Taro.chooseImage({ count: 1, sizeType: ["compressed"] });
  } catch {
    return undefined;
  }
  const filePath = pick.tempFilePaths[0];
  if (!filePath) return undefined;
  const lower = filePath.toLowerCase();
  const contentType = lower.endsWith(".png") ? "image/png" : lower.endsWith(".webp") ? "image/webp" : "image/jpeg";
  const { storage_key, upload_url } = await vibeApi.requestAvatarUpload(contentType);
  const fileData = Taro.getFileSystemManager().readFileSync(filePath);
  if (process.env.TARO_ENV === "weapp") {
    await new Promise<void>((resolve, reject) => {
      Taro.request({
        url: upload_url,
        method: "PUT",
        header: { "Content-Type": contentType },
        data: fileData,
        success: () => resolve(),
        fail: (err) => reject(err),
      });
    });
  } else {
    await fetch(upload_url, {
      method: "PUT",
      headers: { "Content-Type": contentType },
      body: fileData as unknown as BodyInit,
    });
  }
  const confirmed = await vibeApi.confirmAvatarUpload(storage_key);
  return confirmed.avatar_url;
}
