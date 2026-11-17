import Taro from "@tarojs/taro";
import { ApiError } from "../../services/api";

type ToastKind = "success" | "error" | "info" | "none";

export function showToast(title: string, kind: ToastKind = "none", duration = 2200) {
  const icon = kind === "success" ? "success" : kind === "error" ? "error" : "none";
  Taro.showToast({ title, icon, duration });
}

export function showSuccess(title: string) {
  showToast(title, "success");
}

export function showError(title: string) {
  showToast(title, "none", 2800);
}

export function messageFromError(err: unknown, fallback: string) {
  if (err instanceof ApiError && err.message) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

export function toastFromError(err: unknown, fallback: string) {
  showError(messageFromError(err, fallback));
}
