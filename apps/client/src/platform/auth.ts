import Taro from "@tarojs/taro";
import { vibeApi } from "../services/api";
import { saveAuthToken, clearToken } from "../utils/auth";
import { consumePendingReferral, peekPendingReferral, normalizeReferralCode } from "./referral";

export async function loginWithEmail(email: string, password: string) {
  const res = await vibeApi.login(email, password);
  saveAuthToken(res.access_token);
  consumePendingReferral();
  return res;
}

export async function loginWithEmailOtp(email: string, otp: string) {
  const res = await vibeApi.loginOtp(email, otp);
  saveAuthToken(res.access_token);
  consumePendingReferral();
  return res;
}

export async function registerWithEmail(
  email: string,
  username: string | undefined,
  password: string,
  referralCode?: string,
  acceptedTermsVersion?: string,
  acceptedPrivacyVersion?: string,
  otp?: string,
) {
  const res = await vibeApi.register(
    email,
    username,
    password,
    referralCode,
    acceptedTermsVersion,
    acceptedPrivacyVersion,
    otp,
  );
  saveAuthToken(res.access_token);
  consumePendingReferral();
  return res;
}

export async function resetPasswordWithEmail(email: string, otp: string, password: string) {
  const res = await vibeApi.resetPassword(email, otp, password);
  saveAuthToken(res.access_token);
  consumePendingReferral();
  return res;
}

export async function sendEmailOtp(
  email: string,
  purpose: "register" | "login" | "reset" | "rebind" | "bind",
) {
  return vibeApi.sendEmailOtp(email, purpose);
}

export async function changeAccountEmail(newEmail: string, newOtp: string, currentOtp?: string) {
  return vibeApi.changeEmail(newEmail, newOtp, currentOtp);
}

export async function verifyAccountEmail(otp: string) {
  return vibeApi.verifyEmail(otp);
}

export async function changeAccountPassword(password: string, opts?: { currentPassword?: string; otp?: string }) {
  return vibeApi.changePassword(password, opts);
}

export async function loginWithWechat(
  acceptedTermsVersion?: string,
  acceptedPrivacyVersion?: string,
  referralCode?: string,
) {
  if (process.env.TARO_ENV !== "weapp") {
    throw new Error("WeChat login is only available in mini-program");
  }
  const { requireWechatPrivacyAuthorize } = await import("../components/legal/WechatPrivacyGate");
  const ok = await requireWechatPrivacyAuthorize();
  if (!ok) throw new Error("privacy not authorized");
  const { code } = await Taro.login();
  if (!code) throw new Error("no code");
  const referral = normalizeReferralCode(referralCode) || peekPendingReferral();
  const res = await vibeApi.wechatLogin(code, acceptedTermsVersion, acceptedPrivacyVersion, referral || undefined);
  saveAuthToken(res.access_token);
  consumePendingReferral();
  return res;
}

export function logout() {
  clearToken();
}
