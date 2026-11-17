import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { Button, Input, StatusLine } from "../ui";
import { showSuccess, toastFromError } from "../ui/toast";
import {
  changeAccountEmail,
  changeAccountPassword,
  sendEmailOtp,
  verifyAccountEmail,
} from "../../platform/auth";
import { confirmAction, looksLikeEmail, maskEmail } from "../../utils/confirmAction";
import "./AccountSecurityCard.scss";

type Props = {
  email: string;
  emailBound: boolean;
  emailVerified: boolean;
  onAccountChange?: (next: { email: string; emailBound: boolean; emailVerified: boolean }) => void;
};

export function AccountSecurityCard({ email, emailBound, emailVerified, onAccountChange }: Props) {
  const { copy } = useLocale();
  const s = copy.settingsUi;
  const l = copy.loginUi;
  const [newEmail, setNewEmail] = useState("");
  const [currentOtp, setCurrentOtp] = useState("");
  const [newOtp, setNewOtp] = useState("");
  const [verifyOtp, setVerifyOtp] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [passwordOtp, setPasswordOtp] = useState("");
  const [busy, setBusy] = useState("");
  const [cooldown, setCooldown] = useState<Record<string, number>>({});
  const [sent, setSent] = useState<Record<string, string>>({});
  const otpType = process.env.TARO_ENV === "weapp" ? "digit" : "tel";
  const emailType = process.env.TARO_ENV === "weapp" ? "text" : "email";

  useEffect(() => {
    const active = Object.values(cooldown).some((n) => n > 0);
    if (!active) return;
    const timer = setTimeout(() => {
      setCooldown((prev) => {
        const next: Record<string, number> = {};
        for (const [key, value] of Object.entries(prev)) {
          next[key] = Math.max(0, value - 1);
        }
        return next;
      });
    }, 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  async function sendCode(purpose: "rebind" | "bind" | "reset", addr: string) {
    if (!looksLikeEmail(addr)) {
      toastFromError(new Error(l.invalidEmail), l.invalidEmail);
      return;
    }
    const key = `${purpose}:${addr}`;
    setBusy(key);
    try {
      await sendEmailOtp(addr, purpose);
      setCooldown((prev) => ({ ...prev, [key]: 60 }));
      setSent((prev) => ({ ...prev, [purpose]: addr }));
      showSuccess(l.otpSent);
    } catch (err) {
      toastFromError(err, l.networkFail);
    } finally {
      setBusy("");
    }
  }

  function otpButton(purpose: "rebind" | "bind" | "reset", addr: string) {
    const key = `${purpose}:${addr}`;
    const left = cooldown[key] || 0;
    return (
      <Button size="sm" disabled={!!busy || left > 0} loading={busy === key} onClick={() => void sendCode(purpose, addr)}>
        {left > 0 ? l.otpWait.replace("{n}", String(left)) : l.sendOtp}
      </Button>
    );
  }

  async function submitVerify() {
    if (!verifyOtp.trim()) {
      toastFromError(new Error(l.otpNeedCode), l.otpNeedCode);
      return;
    }
    setBusy("verify");
    try {
      const res = await verifyAccountEmail(verifyOtp.trim());
      setVerifyOtp("");
      onAccountChange?.({ email: res.email || email, emailBound: true, emailVerified: true });
      showSuccess(s.verifyEmailDone);
    } catch (err) {
      toastFromError(err, s.emailChangeFail);
    } finally {
      setBusy("");
    }
  }

  async function submitEmail() {
    const addr = newEmail.trim().toLowerCase();
    if (!looksLikeEmail(addr)) {
      toastFromError(new Error(l.invalidEmail), l.invalidEmail);
      return;
    }
    if (emailBound && addr === email.trim().toLowerCase()) {
      toastFromError(new Error(s.sameEmail), s.sameEmail);
      return;
    }
    if (!newOtp.trim()) {
      toastFromError(new Error(l.otpNeedCode), l.otpNeedCode);
      return;
    }
    if (emailBound && !currentOtp.trim()) {
      toastFromError(new Error(l.otpNeedCode), l.otpNeedCode);
      return;
    }
    const ok = await confirmAction({
      title: emailBound ? s.changeEmail : s.bindEmail,
      content: l.otpSentTo.replace("{email}", maskEmail(addr)),
      confirmText: emailBound ? s.changeEmail : s.bindEmail,
    });
    if (!ok) return;
    setBusy("email");
    try {
      const res = await changeAccountEmail(addr, newOtp.trim(), emailBound ? currentOtp.trim() : undefined);
      setNewEmail("");
      setNewOtp("");
      setCurrentOtp("");
      onAccountChange?.({
        email: res.email || addr,
        emailBound: res.email_bound !== false,
        emailVerified: res.email_verified !== false,
      });
      showSuccess(s.emailChanged);
    } catch (err) {
      toastFromError(err, s.emailChangeFail);
    } finally {
      setBusy("");
    }
  }

  async function submitPassword() {
    if (!emailBound) {
      toastFromError(new Error(s.changePasswordNeedEmail), s.changePasswordNeedEmail);
      return;
    }
    if (password.length < 6) {
      toastFromError(new Error(l.weakPassword), l.weakPassword);
      return;
    }
    if (password !== password2) {
      toastFromError(new Error(l.passwordMismatch), l.passwordMismatch);
      return;
    }
    if (!currentPassword && !passwordOtp.trim()) {
      toastFromError(new Error(l.otpNeedCode), l.otpNeedCode);
      return;
    }
    setBusy("password");
    try {
      await changeAccountPassword(password, {
        currentPassword: currentPassword || undefined,
        otp: passwordOtp.trim() || undefined,
      });
      setCurrentPassword("");
      setPassword("");
      setPassword2("");
      setPasswordOtp("");
      showSuccess(s.passwordChanged);
    } catch (err) {
      toastFromError(err, s.passwordChangeFail);
    } finally {
      setBusy("");
    }
  }

  const displayEmail = emailBound ? maskEmail(email) : s.accountUnbound;

  return (
    <View id="settings-account" className="account-security">
      <StatusLine tone="info" density="quiet">
        {emailBound ? s.accountHint : s.accountWechatHint}
      </StatusLine>
      <View className="account-security__row">
        <Text className="account-security__label">{s.accountEmail}</Text>
        <Text className="account-security__value">{displayEmail}</Text>
        <Text className={`account-security__badge ${emailBound && emailVerified ? "is-ok" : ""}`}>
          {!emailBound ? s.accountUnbound : emailVerified ? s.accountVerified : s.accountUnverified}
        </Text>
      </View>

      {emailBound && !emailVerified ? (
        <View className="account-security__block">
          <View className="account-security__otp">
            <View className="account-security__otp-field">
              <Input
                label={l.otp}
                type={otpType}
                maxlength={6}
                placeholder={l.otpPlaceholder}
                value={verifyOtp}
                onInput={(e) => setVerifyOtp(e.detail.value.replace(/\D/g, "").slice(0, 6))}
              />
            </View>
            {otpButton("rebind", email)}
          </View>
          {sent.rebind ? (
            <StatusLine tone="success" density="quiet">
              {l.otpSentTo.replace("{email}", maskEmail(sent.rebind))}
            </StatusLine>
          ) : null}
          <Button block loading={busy === "verify"} onClick={() => void submitVerify()}>
            {s.verifyEmail}
          </Button>
        </View>
      ) : null}

      <View className="account-security__block">
        <Text className="account-security__title">{emailBound ? s.changeEmail : s.bindEmail}</Text>
        {emailBound ? (
          <View className="account-security__otp">
            <View className="account-security__otp-field">
              <Input
                label={s.currentOtp}
                type={otpType}
                maxlength={6}
                placeholder={l.otpPlaceholder}
                value={currentOtp}
                onInput={(e) => setCurrentOtp(e.detail.value.replace(/\D/g, "").slice(0, 6))}
              />
            </View>
            {otpButton("rebind", email)}
          </View>
        ) : null}
        <Input
          label={s.newEmail}
          type={emailType}
          placeholder={l.emailPlaceholder}
          value={newEmail}
          onInput={(e) => setNewEmail(e.detail.value)}
        />
        <View className="account-security__otp">
          <View className="account-security__otp-field">
            <Input
              label={s.newOtp}
              type={otpType}
              maxlength={6}
              placeholder={l.otpPlaceholder}
              value={newOtp}
              onInput={(e) => setNewOtp(e.detail.value.replace(/\D/g, "").slice(0, 6))}
            />
          </View>
          {otpButton("bind", newEmail.trim().toLowerCase())}
        </View>
        {sent.bind ? (
          <StatusLine tone="success" density="quiet">
            {l.otpSentTo.replace("{email}", maskEmail(sent.bind))}
          </StatusLine>
        ) : null}
        <Button variant="primary" block loading={busy === "email"} onClick={() => void submitEmail()}>
          {emailBound ? s.changeEmail : s.bindEmail}
        </Button>
      </View>

      <View className="account-security__block">
        <Text className="account-security__title">{s.changePassword}</Text>
        <StatusLine tone="info" density="quiet">
          {emailBound ? s.changePasswordHint : s.changePasswordNeedEmail}
        </StatusLine>
        {emailBound ? (
          <>
            <Input
              label={s.currentPassword}
              password
              placeholder={s.currentPassword}
              value={currentPassword}
              onInput={(e) => setCurrentPassword(e.detail.value)}
            />
            <View className="account-security__otp">
              <View className="account-security__otp-field">
                <Input
                  label={l.otp}
                  type={otpType}
                  maxlength={6}
                  placeholder={l.otpPlaceholder}
                  value={passwordOtp}
                  onInput={(e) => setPasswordOtp(e.detail.value.replace(/\D/g, "").slice(0, 6))}
                />
              </View>
              {otpButton("reset", email)}
            </View>
            <Input
              label={l.newPassword}
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
            <Button variant="secondary" block loading={busy === "password"} onClick={() => void submitPassword()}>
              {s.changePassword}
            </Button>
          </>
        ) : null}
      </View>
    </View>
  );
}
