import Taro from "@tarojs/taro";

function clipModalLabel(value: string) {
  return Array.from((value || "").trim()).slice(0, 4).join("");
}

export async function confirmAction(opts: {
  title: string;
  content: string;
  confirmText?: string;
  cancelText?: string;
}): Promise<boolean> {
  const payload: { title: string; content: string; confirmText?: string; cancelText?: string } = {
    title: opts.title,
    content: opts.content,
  };
  const confirmText = clipModalLabel(opts.confirmText || "");
  const cancelText = clipModalLabel(opts.cancelText || "");
  if (confirmText) payload.confirmText = confirmText;
  if (cancelText) payload.cancelText = cancelText;
  const res = await Taro.showModal(payload);
  return Boolean(res.confirm);
}

export function isPlaceholderEmail(value: string) {
  return (value || "").trim().toLowerCase().endsWith("@wechat.local");
}

export function looksLikeEmail(value: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((value || "").trim()) && !isPlaceholderEmail(value);
}

export function maskEmail(value: string) {
  const trimmed = (value || "").trim().toLowerCase();
  const at = trimmed.indexOf("@");
  if (at < 1) return trimmed;
  const name = trimmed.slice(0, at);
  const domain = trimmed.slice(at + 1);
  const keep = name.slice(0, name.length <= 2 ? 1 : 2);
  return `${keep}***@${domain}`;
}
