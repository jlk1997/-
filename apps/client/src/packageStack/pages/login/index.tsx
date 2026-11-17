import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, useRouter } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { Button, Card, Input, SegmentedControl, StatusLine } from "../../../components/ui";
import {
  loginWithEmail,
  loginWithEmailOtp,
  registerWithEmail,
  resetPasswordWithEmail,
  sendEmailOtp,
  loginWithWechat,
} from "../../../platform/auth";
import { ApiError } from "../../../services/api";
import { getItem, setItem } from "../../../platform/storage";
import { captureReferralFromQuery, peekPendingReferral } from "../../../platform/referral";
import { ConsentCheckbox } from "../../../components/legal/ConsentCheckbox";
import { LegalFooter } from "../../../components/legal/LegalFooter";
import { BrandLogo } from "../../../components/brand/BrandLogo";
import { LEGAL_ROUTES, legalDocLabel } from "../../../utils/legal";
import { getRequiredVersions } from "../../../utils/consent";
import { isLoggedIn } from "../../../utils/auth";
import { navigateAfterLogin, showAuthSuccessAndLeave } from "../../../utils/loginNavigation";
import { confirmAction, looksLikeEmail, maskEmail } from "../../../utils/confirmAction";
import "./index.scss";

const EMAIL_KEY = "auth:lastEmail";
type AuthPane = "login" | "register" | "reset";
type LoginMethod = "password" | "otp";

export default function LoginPage() {
  const router = useRouter();
  const { copy, locale } = useLocale();
  const l = copy.loginUi;
  const next = router.params.next;
  const nextPath = (() => {
    try {
      return next ? decodeURIComponent(String(next)) : "";
    } catch {
      return String(next || "");
    }
  })();
  const fromCreate = /\/pages\/create|create\/index/i.test(nextPath);
  const loginHint = fromCreate ? l.subtitleCreate : l.subtitle;

  function errorCode(err: unknown) {
    return err instanceof ApiError ? err.errorCode || err.message : "";
  }

  function authErrorMessage(err: unknown, fallback: string) {
    const status = err instanceof ApiError ? err.status : (err as { status?: number })?.status;
    const detail = err instanceof Error ? err.message : String(err || "");
    const code = errorCode(err);
    if (code === "wrong_password" || /wrong_password|密码不对/i.test(detail)) return l.wrongPasswordHint;
    if (code === "unknown_email" || /unknown_email|还没有账户/i.test(detail)) return l.unknownEmailHint;
    if (code === "email_taken" || /email_taken|已经注册|已被使用/i.test(detail)) return l.emailTakenHint;
    if (code === "otp_invalid" || /otp_invalid|验证码不对/i.test(detail)) return detail;
    if (code === "otp_unavailable" || /otp_unavailable/i.test(detail)) return detail;
    if (code === "otp_cooldown" || code === "RATE_LIMITED" || /otp_cooldown|RATE_LIMITED/i.test(detail)) {
      return l.otpWait.replace("{n}", "60");
    }
    if (status === 429) return l.otpWait.replace("{n}", "60");
    if (status === 422 || /password|too short|弱/i.test(detail)) return l.weakPassword;
    if (status === 0 || /network|timeout|failed to fetch|request:fail/i.test(detail)) return l.networkFail;
    return fallback;
  }

  async function offerNextStep(err: unknown) {
    const code = errorCode(err);
    const detail = err instanceof Error ? err.message : "";
    if (code === "email_taken" || /email_taken|已经注册|已被使用/i.test(detail)) {
      const goLogin = await confirmAction({
        title: l.emailTaken,
        content: l.emailTakenHint,
        confirmText: l.goLogin,
        cancelText: l.goReset,
      });
      setPane(goLogin ? "login" : "reset");
      return;
    }
    if (code === "unknown_email" || /unknown_email|还没有账户/i.test(detail)) {
      const goRegister = await confirmAction({
        title: l.unknownEmail,
        content: l.unknownEmailHint,
        confirmText: l.goRegister,
        cancelText: l.backToLogin,
      });
      if (goRegister) setPane("register");
      return;
    }
    if (code === "wrong_password" || /wrong_password|密码不对/i.test(detail)) {
      const useOtp = await confirmAction({
        title: l.loginFail,
        content: l.wrongPasswordHint,
        confirmText: l.loginWithOtp,
        cancelText: l.goReset,
      });
      if (useOtp) {
        setPane("login");
        setLoginMethod("otp");
      } else {
        setPane("reset");
      }
    }
  }

  const [pane, setPane] = useState<AuthPane>("login");
  const [loginMethod, setLoginMethod] = useState<LoginMethod>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [otp, setOtp] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [otpBusy, setOtpBusy] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [formError, setFormError] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const [otpSentTo, setOtpSentTo] = useState("");
  const [legalVersions, setLegalVersions] = useState({ terms: "2026-07-20", privacy: "2026-07-20" });

  useEffect(() => {
    getRequiredVersions().then((v) =>
      setLegalVersions({ terms: v.terms || "2026-07-20", privacy: v.privacy || "2026-07-20" }),
    );
  }, []);

  useEffect(() => {
    const saved = getItem(EMAIL_KEY);
    if (saved) setEmail(saved);
    captureReferralFromQuery(router.params as Record<string, unknown>);
    const ref = router.params.ref || peekPendingReferral();
    if (ref) {
      setReferralCode(ref.toUpperCase());
      if (!saved) setPane("register");
    }
  }, [router.params.ref]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((n) => Math.max(0, n - 1)), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  useDidShow(() => {
    if (isLoggedIn()) navigateAfterLogin(next);
  });

  function persistEmail(value: string) {
    const trimmed = value.trim().toLowerCase();
    if (trimmed) setItem(EMAIL_KEY, trimmed);
  }

  function changePane(nextPane: AuthPane) {
    setPane(nextPane);
    setFormError("");
    setOtp("");
    setPassword("");
    setPassword2("");
    setOtpSentTo("");
  }

  function requireAgreement() {
    if (agreed) {
      setFormError("");
      return true;
    }
    setFormError(copy.legalUi.mustAgree);
    Taro.showToast({ title: copy.legalUi.mustAgree, icon: "none" });
    return false;
  }

  function currentPurpose(): "register" | "login" | "reset" {
    if (pane === "register") return "register";
    if (pane === "reset") return "reset";
    return "login";
  }

  function readyEmail() {
    const addr = email.trim().toLowerCase();
    if (!looksLikeEmail(addr)) {
      setFormError(l.invalidEmail);
      Taro.showToast({ title: l.invalidEmail, icon: "none" });
      return "";
    }
    return addr;
  }

  async function requestOtp() {
    const addr = readyEmail();
    if (!addr) return;
    setOtpBusy(true);
    try {
      await sendEmailOtp(addr, currentPurpose());
      persistEmail(addr);
      setCooldown(60);
      setOtpSentTo(addr);
      setFormError("");
      Taro.showToast({ title: l.otpSent, icon: "success" });
    } catch (err) {
      const message = authErrorMessage(err, l.networkFail);
      setFormError(message);
      Taro.showToast({ title: message, icon: "none" });
      await offerNextStep(err);
    } finally {
      setOtpBusy(false);
    }
  }

  function needMatchingPasswords() {
    if (password.length < 6) {
      setFormError(l.weakPassword);
      return false;
    }
    if (password !== password2) {
      setFormError(l.passwordMismatch);
      return false;
    }
    return true;
  }

  async function submitLogin() {
    const addr = readyEmail();
    if (!addr) return;
    if (loginMethod === "otp" && !otp.trim()) {
      setFormError(l.otpNeedCode);
      return;
    }
    if (loginMethod === "password" && !password) {
      setFormError(l.needPassword);
      return;
    }
    setLoading(true);
    try {
      if (loginMethod === "otp") await loginWithEmailOtp(addr, otp.trim());
      else await loginWithEmail(addr, password);
      persistEmail(addr);
      showAuthSuccessAndLeave(l.loginSuccess, next);
    } catch (err) {
      console.error("[login] email login failed:", err);
      const message = authErrorMessage(err, l.loginFail);
      setFormError(message);
      Taro.showToast({ title: message, icon: "none" });
      await offerNextStep(err);
    } finally {
      setLoading(false);
    }
  }

  async function submitRegister() {
    if (!requireAgreement()) return;
    if (!needMatchingPasswords()) return;
    const addr = readyEmail();
    if (!addr) return;
    if (!otp.trim()) {
      setFormError(l.otpNeedCode);
      return;
    }
    setLoading(true);
    try {
      await registerWithEmail(
        addr,
        undefined,
        password,
        referralCode.trim() || undefined,
        legalVersions.terms,
        legalVersions.privacy,
        otp.trim(),
      );
      persistEmail(addr);
      showAuthSuccessAndLeave(l.registerWelcome, next);
    } catch (err) {
      console.error("[login] register failed:", err);
      const message = authErrorMessage(err, l.registerFail);
      setFormError(message);
      Taro.showToast({ title: message, icon: "none" });
      await offerNextStep(err);
    } finally {
      setLoading(false);
    }
  }

  async function submitReset() {
    if (!needMatchingPasswords()) return;
    const addr = readyEmail();
    if (!addr) return;
    if (!otp.trim()) {
      setFormError(l.otpNeedCode);
      return;
    }
    setLoading(true);
    try {
      await resetPasswordWithEmail(addr, otp.trim(), password);
      persistEmail(addr);
      showAuthSuccessAndLeave(l.resetSuccess, next);
    } catch (err) {
      console.error("[login] reset failed:", err);
      const message = authErrorMessage(err, l.resetFail);
      setFormError(message);
      Taro.showToast({ title: message, icon: "none" });
      await offerNextStep(err);
    } finally {
      setLoading(false);
    }
  }

  async function wechat() {
    if (process.env.TARO_ENV !== "weapp") {
      Taro.showToast({ title: l.wechatOnly, icon: "none" });
      return;
    }
    setLoading(true);
    try {
      await loginWithWechat(legalVersions.terms, legalVersions.privacy, referralCode.trim() || undefined);
      showAuthSuccessAndLeave(l.wechatSuccess, next);
    } catch (err) {
      console.error("[login] wechat login failed:", err);
      Taro.showToast({ title: l.wechatFail, icon: "none" });
    } finally {
      setLoading(false);
    }
  }

  const title = pane === "register" ? l.register : pane === "reset" ? l.reset : l.login;
  const needsOtp = pane === "register" || pane === "reset" || loginMethod === "otp";
  const paneHint =
    pane === "register" ? l.registerHint : pane === "reset" ? l.resetHint : loginMethod === "otp" ? l.otpLoginHint : l.passwordLoginHint;

  return (
    <PageShell label={copy.navGroups.account} title={title} subtitle={loginHint} hideHeader noPadTop showCredits={false} wide ambient ambientVariant="warm">
      <View className="login-page">
        <View className="login-hero">
          <BrandLogo variant="icon" size="md" showName={false} />
          <Text className="login-hero__logo">{copy.brand.name}</Text>
          <Text className="login-hero__hint">{loginHint}</Text>
        </View>

        <Card flat className="login-form">
          {pane === "reset" ? (
            <View className="login-reset-head">
              <Text className="login-reset-head__title">{l.reset}</Text>
              <Text className="login-forgot" onClick={() => changePane("login")}>{l.backToLogin}</Text>
            </View>
          ) : (
            <SegmentedControl
              options={[
                { value: "login", label: l.login },
                { value: "register", label: l.register },
              ]}
              value={pane === "register" ? "register" : "login"}
              onChange={(nextPane) => changePane(nextPane)}
            />
          )}
          {pane === "login" ? (
            <SegmentedControl
              options={[
                { value: "password", label: l.loginWithPassword },
                { value: "otp", label: l.loginWithOtp },
              ]}
              value={loginMethod}
              onChange={(method) => {
                setLoginMethod(method);
                setFormError("");
                setOtp("");
              }}
            />
          ) : null}

          <StatusLine tone="info" density="quiet">{paneHint}</StatusLine>

          {process.env.TARO_ENV === "weapp" && pane === "login" && (
            <Button variant="primary" block loading={loading} onClick={wechat} className="login-wechat">
              {l.wechatLogin}
            </Button>
          )}

          <Input
            label={l.email}
            type={process.env.TARO_ENV === "weapp" ? "text" : "email"}
            placeholder={l.emailPlaceholder}
            value={email}
            onInput={(e) => {
              setEmail(e.detail.value);
              if (otpSentTo && e.detail.value.trim().toLowerCase() !== otpSentTo) setOtpSentTo("");
            }}
          />

          {needsOtp ? (
            <View className="login-otp-row">
              <View className="login-otp-row__field">
                <Input
                  label={l.otp}
                  type={process.env.TARO_ENV === "weapp" ? "digit" : "tel"}
                  maxlength={6}
                  placeholder={l.otpPlaceholder}
                  value={otp}
                  onInput={(e) => setOtp(e.detail.value.replace(/\D/g, "").slice(0, 6))}
                />
              </View>
              <Button size="sm" disabled={otpBusy || cooldown > 0} loading={otpBusy} onClick={() => void requestOtp()}>
                {cooldown > 0 ? l.otpWait.replace("{n}", String(cooldown)) : l.sendOtp}
              </Button>
            </View>
          ) : null}

          {otpSentTo ? (
            <StatusLine tone="success" density="quiet">
              {l.otpSentTo.replace("{email}", maskEmail(otpSentTo))}
            </StatusLine>
          ) : null}

          {pane === "register" ? (
            <Input
              label={l.referralCode}
              placeholder={l.referralCode}
              value={referralCode}
              onInput={(e) => setReferralCode(e.detail.value.toUpperCase())}
            />
          ) : null}

          {pane === "login" && loginMethod === "password" ? (
            <>
              <Input label={l.password} password placeholder={l.password} value={password} onInput={(e) => setPassword(e.detail.value)} />
              <Text className="login-forgot" onClick={() => changePane("reset")}>
                {l.forgotPassword}
              </Text>
            </>
          ) : null}

          {pane === "register" || pane === "reset" ? (
            <>
              <Input
                label={pane === "reset" ? l.newPassword : l.password}
                password
                placeholder={l.password}
                value={password}
                onInput={(e) => setPassword(e.detail.value)}
              />
              <Input
                label={l.passwordConfirm}
                password
                placeholder={l.passwordConfirm}
                value={password2}
                onInput={(e) => setPassword2(e.detail.value)}
              />
            </>
          ) : null}

          {pane === "register" ? (
            <ConsentCheckbox
              checked={agreed}
              onChange={(nextAgreed) => {
                setAgreed(nextAgreed);
                if (nextAgreed) setFormError("");
              }}
              links={[
                { label: legalDocLabel(copy.legalUi.termsOfService, locale), route: LEGAL_ROUTES.terms },
                { label: legalDocLabel(copy.legalUi.privacyPolicy, locale), route: LEGAL_ROUTES.privacy },
              ]}
            >
              {copy.legalUi.agreeTermsAndPrivacy
                .replace(legalDocLabel(copy.legalUi.termsOfService, locale), "")
                .replace(legalDocLabel(copy.legalUi.privacyPolicy, locale), "")
                .replace(locale === "en" ? /\band\b/i : "和", "")}
            </ConsentCheckbox>
          ) : null}

          {formError ? <Text className="login-form__error">{formError}</Text> : null}

          <Button
            variant={process.env.TARO_ENV === "weapp" && pane === "login" ? "secondary" : "primary"}
            block
            loading={loading}
            onClick={pane === "register" ? submitRegister : pane === "reset" ? submitReset : submitLogin}
          >
            {title}
          </Button>
        </Card>
        <LegalFooter />
      </View>
    </PageShell>
  );
}
