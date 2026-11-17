import Taro from "@tarojs/taro";
import { vibeApi } from "../services/api";
import { downloadTextFile } from "../platform/downloadText";

type ExportCopy = {
  exportSaved: string;
  exportCopied: string;
  exportFail: string;
  receiptCopied: string;
  proCopied: string;
};

export async function downloadCreatorStatement(copy: ExportCopy, periodKey?: string) {
  try {
    const res = await vibeApi.getCreatorStatement(periodKey);
    if (res.csv) {
      const mode = await downloadTextFile(res.filename || "vibe-statement.csv", res.csv);
      Taro.showToast({
        title: mode === "saved" ? copy.exportSaved : res.receipt_no ? copy.receiptCopied.replace("{n}", res.receipt_no) : copy.exportCopied,
        icon: "success",
      });
      return;
    }
    const text = res.receipt_text || "";
    if (!text) throw new Error("empty");
    await Taro.setClipboardData({ data: text });
    Taro.showToast({ title: res.receipt_no ? copy.receiptCopied.replace("{n}", res.receipt_no) : copy.exportCopied, icon: "success" });
  } catch {
    Taro.showToast({ title: copy.exportFail, icon: "none" });
  }
}

export async function downloadProExport(copy: ExportCopy) {
  try {
    const res = await vibeApi.getProExport();
    if (res.csv) {
      const mode = await downloadTextFile("vibe-pro-export.csv", res.csv);
      Taro.showToast({ title: mode === "saved" ? copy.exportSaved : copy.proCopied, icon: "success" });
      return;
    }
    await Taro.setClipboardData({ data: res.note || "" });
    Taro.showToast({ title: copy.proCopied, icon: "success" });
  } catch {
    Taro.showToast({ title: copy.exportFail, icon: "none" });
  }
}
