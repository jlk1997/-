import Taro from "@tarojs/taro";

/** Download a text file on H5; clipboard fallback on mini-program. */
export async function downloadTextFile(
  filename: string,
  content: string,
  mime = "text/csv",
): Promise<"saved" | "copied"> {
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    const blob = new Blob([content], { type: `${mime};charset=utf-8` });
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
  await Taro.setClipboardData({ data: content });
  return "copied";
}
