import { useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import {
  AsyncPanel,
  Badge,
  Button,
  Collapsible,
  EmptyState,
  Input,
  MetricCard,
  SectionLabel,
  SegmentedControl,
  StatusLine,
} from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { CREATOR_PAGE_ROUTES, STACK_PAGE_ROUTES, creatorPage } from "../../../constants/routes";
import { LEGAL_ROUTES, legalDocLabel } from "../../../utils/legal";
import { ConsentCheckbox } from "../../../components/legal/ConsentCheckbox";
import { useCreditsOptional } from "../../../contexts/CreditsProvider";
import { formatFen, formatPayoutCountdown, formatWarmup, ledgerTypeLabel, statusLabel, statusTone, yuanToFen } from "../../lib";
import { LaunchHonestyBanner } from "../../../components/commercial/LaunchHonestyBanner";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import { downloadCreatorStatement } from "../../exportReports";
import "../../creator.scss";
import "./index.scss";

type WalletRow = { currency: string; pending_minor: number; available_minor: number; frozen_minor: number; lifetime_earned_minor?: number };
type LedgerRow = {
  id: string;
  type: string;
  amount_minor: number;
  note?: string;
  created_at?: string;
  currency?: string;
  accounting_subject?: string;
  ref_id?: string;
};
type WithdrawalRow = { id: string; status: string; amount_minor: number; currency?: string; created_at?: string; risk_flag?: boolean; receipt_no?: string };
type Payout = { id: string; channel: string; account_name?: string; account_no?: string; account_no_masked?: string; is_default?: boolean };

type WalletPayload = {
  enabled?: boolean;
  wallets: WalletRow[];
  ledger: LedgerRow[];
  withdrawals?: WithdrawalRow[];
  withdraw_config?: { min_withdraw_cny_fen?: number; min_withdraw_usd_cents?: number; period?: string; fee_fen?: number; fee_usd_cents?: number };
  kyc_status?: string;
  kyc_provider_configured?: boolean;
  can_withdraw?: boolean;
  payout_calendar?: { next_payout_date?: string; weekday_label?: string; note?: string; days_until_payout?: number; is_payout_day?: boolean };
  source_split?: { radio_minor?: number; sync_minor?: number; embed_minor?: number; dsp_minor?: number; harvest_minor?: number };
};

export default function RoyaltyWalletPage() {
  const { copy, locale } = useLocale();
  const c = copy.creatorUi;
  const credits = useCreditsOptional();
  const [amount, setAmount] = useState("10");
  const [currency, setCurrency] = useState(locale === "en" ? "USD" : "CNY");
  const [payoutId, setPayoutId] = useState("");
  const [busy, setBusy] = useState(false);
  const [royaltyAgreed, setRoyaltyAgreed] = useState(false);

  const { data, loading, error, reload } = useAsyncQuery<WalletPayload | null>(async () => {
    if (!requireAuth(creatorPage("wallet"))) return null;
    const [wallet, payouts, platform] = await Promise.all([
      vibeApi.getRoyaltyWallet() as Promise<WalletPayload>,
      vibeApi.listPayoutAccounts().catch(() => ({ accounts: [] as Payout[] })),
      vibeApi.getPlatformConfig().catch(() => ({ kyc_provider_configured: false })),
    ]);
    return {
      ...wallet,
      payouts: payouts.accounts as Payout[],
      kyc_provider_configured: platform.kyc_provider_configured === true,
    } as WalletPayload & { payouts?: Payout[] };
  }, []);

  useDidShow(() => {
    void reload();
  });
  usePullDownRefresh(async () => {
    await reload();
    Taro.stopPullDownRefresh();
  });

  const payload = data as (WalletPayload & { payouts?: Payout[] }) | null;
  const wallets = payload?.wallets || [];
  const w = wallets.find((row) => row.currency === currency) || wallets[0];
  const payouts = payload?.payouts || [];
  const selectedPayout = payouts.find((row) => row.id === payoutId) || payouts.find((row) => row.is_default) || payouts[0];
  const minFen =
    (w?.currency || currency) === "USD"
      ? payload?.withdraw_config?.min_withdraw_usd_cents || 500
      : payload?.withdraw_config?.min_withdraw_cny_fen || 1000;
  const feeFen =
    (w?.currency || currency) === "USD"
      ? payload?.withdraw_config?.fee_usd_cents || 0
      : payload?.withdraw_config?.fee_fen || 0;
  const quoteFen = yuanToFen(amount);
  const debitFen = quoteFen + feeFen;
  const walletOn = credits?.royaltyWallet !== false && payload?.enabled !== false;
  const weapp = process.env.TARO_ENV === "weapp";

  async function withdraw() {
    if (busy) return;
    if (weapp) {
      const copied = await copyWeappCreatorLink(CREATOR_PAGE_ROUTES.wallet);
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    if (!royaltyAgreed) {
      Taro.showToast({ title: copy.legalUi.mustAgree, icon: "none" });
      return;
    }
    const fen = yuanToFen(amount);
    if (!fen || fen < minFen) {
      Taro.showToast({ title: c.minWithdraw.replace("{n}", formatFen(minFen, w?.currency || currency)), icon: "none" });
      return;
    }
    if (fen + feeFen > (w?.available_minor || 0)) {
      Taro.showToast({ title: c.withdrawNeedFee, icon: "none" });
      return;
    }
    if (!payouts.length) {
      Taro.showToast({ title: c.withdrawNeedAccount, icon: "none" });
      Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.accounts });
      return;
    }
    if (payload?.kyc_status !== "verified") {
      Taro.showToast({ title: c.withdrawNeedKyc, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      const res = await vibeApi.requestRoyaltyWithdraw({
        amount_minor: fen,
        currency: w?.currency || "CNY",
        channel: selectedPayout?.channel || (locale === "en" ? "paypal" : "alipay"),
        payout_account_id: selectedPayout?.id,
      });
      const receipt = typeof res.receipt_no === "string" ? res.receipt_no : "";
      Taro.showToast({ title: receipt ? c.withdrawSubmitted.replace("{n}", receipt) : c.withdraw, icon: "success" });
      void reload();
    } catch (err) {
      Taro.showToast({ title: String((err as Error)?.message || copy.adminUi.actionFail), icon: "none" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell title={c.goWallet} subtitle={c.fiatTitle} ambient>
      <View className="creator">
        <WeappH5Bridge path={CREATOR_PAGE_ROUTES.wallet} />
        <LaunchHonestyBanner surface="wallet" />
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void reload()}
        >
          <View className="creator-wallet-hero">
            <Text className="creator-wallet-hero__label">{c.availableHero}</Text>
            <Text className="creator-wallet-hero__value">{formatFen(w?.available_minor, w?.currency)}</Text>
            <Text className="creator-wallet-hero__hint">
              {walletOn
                ? `${c.minWithdraw.replace("{n}", formatFen(minFen, w?.currency || currency))} · ${c.pending} ${formatFen(w?.pending_minor, w?.currency)}`
                : c.walletOff}
            </Text>
          </View>
          {wallets.length > 1 && (
            <SegmentedControl
              options={wallets.map((row) => ({
                value: row.currency,
                label: row.currency === "USD" ? c.currencyUsd : c.currencyCny,
              }))}
              value={w?.currency || "CNY"}
              onChange={setCurrency}
            />
          )}
          {!walletOn ? (
            <StatusLine tone="info">{c.walletOff}</StatusLine>
          ) : payload?.kyc_status !== "verified" ? (
            <StatusLine tone="error">
              {payload?.kyc_status === "pending"
                ? payload.kyc_provider_configured === false
                  ? c.kycManualNote
                  : c.kycPending
                : c.alertKyc}
            </StatusLine>
          ) : (w?.pending_minor || 0) > 0 && (w?.available_minor || 0) === 0 ? (
            <StatusLine tone="info" density="quiet">{c.pendingNeedConfirm}</StatusLine>
          ) : walletOn ? (
            <StatusLine tone="info" density="quiet">{c.withdrawHint}</StatusLine>
          ) : null}
          {weapp ? <StatusLine tone="info">{c.weappDeskHint}</StatusLine> : null}
          {(payload?.source_split?.radio_minor || 0) > 0 ? (
            <StatusLine tone="info" density="quiet">
              {`${c.walletRadio} ${formatWarmup(payload?.source_split?.radio_minor, c.warmupNotCash)}`}
            </StatusLine>
          ) : null}
          {payload?.payout_calendar?.next_payout_date ? (
            <StatusLine tone="info" density="quiet">
              {formatPayoutCountdown(payload.payout_calendar, c)}
            </StatusLine>
          ) : null}
          {walletOn && (w?.pending_minor || 0) > 0 && (w?.available_minor || 0) === 0 ? (
            <Button variant="primary" block onClick={() => Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.settlements })}>
              {c.goSettlements}
            </Button>
          ) : null}
          {walletOn && !weapp && (
            <ConsentCheckbox
              checked={royaltyAgreed}
              onChange={setRoyaltyAgreed}
              links={[
                {
                  label: legalDocLabel(copy.legalUi.royaltyPayout, locale),
                  route: LEGAL_ROUTES.royaltyPayout,
                },
              ]}
            >
              {copy.legalUi.agreeRoyalty.replace(legalDocLabel(copy.legalUi.royaltyPayout, locale), "")}
            </ConsentCheckbox>
          )}
          <View className="creator-card">
            {walletOn && payouts.length > 0 && <SectionLabel>{c.addPayout}</SectionLabel>}
            {walletOn &&
              payouts.map((row) => {
                const on = (selectedPayout?.id || payoutId) === row.id;
                return (
                  <View
                    key={row.id}
                    className={on ? "creator-pick creator-pick--on" : "creator-pick"}
                    onClick={() => setPayoutId(row.id)}
                  >
                    <View>
                      <Text className="creator-pick__title">{row.account_name || row.channel}</Text>
                      <Text className="creator-pick__meta">{`${row.channel} · ${row.account_no_masked || row.account_no || ""}`}</Text>
                    </View>
                  </View>
                );
              })}
            {walletOn && !weapp && (
              <>
                <Input
                  label={(w?.currency || currency) === "USD" ? c.amountUsd : c.amountYuan}
                  type="digit"
                  value={amount}
                  hint={c.kycHint}
                  onInput={(e) => setAmount(e.detail.value)}
                />
                {quoteFen > 0 && (
                  <View className={debitFen > (w?.available_minor || 0) ? "creator-quote creator-quote--warn" : "creator-quote"}>
                    <View>
                      <Text className="creator-quote__label">{c.quoteReceive}</Text>
                      <Text className="creator-quote__value creator-quote__value--net">{formatFen(quoteFen, w?.currency || currency)}</Text>
                    </View>
                    <View>
                      <Text className="creator-quote__label">{c.quoteFee}</Text>
                      <Text className="creator-quote__value">{formatFen(feeFen, w?.currency || currency)}</Text>
                    </View>
                    <View>
                      <Text className="creator-quote__label">{c.quoteDebit}</Text>
                      <Text className="creator-quote__value">{formatFen(debitFen, w?.currency || currency)}</Text>
                    </View>
                  </View>
                )}
                <Button
                  variant="primary"
                  block
                  loading={busy}
                  disabled={payload?.kyc_status !== "verified"}
                  onClick={() => void withdraw()}
                >
                  {c.withdraw}
                </Button>
                {payload?.kyc_status !== "verified" && (
                  <Button
                    variant="secondary"
                    block
                    loading={busy}
                    onClick={() => {
                      setBusy(true);
                      void vibeApi
                        .requestKycReview()
                        .then((res) => {
                          Taro.showToast({
                            title: res.provider_configured === false ? c.kycManualNote : c.kycSubmitted,
                            icon: res.provider_configured === false ? "none" : "success",
                          });
                          void reload();
                        })
                        .catch((err) => Taro.showToast({ title: String((err as Error)?.message || copy.adminUi.actionFail), icon: "none" }))
                        .finally(() => setBusy(false));
                    }}
                  >
                    {payload?.kyc_status === "pending" ? c.kycPending : c.kycSubmit}
                  </Button>
                )}
                <Button variant="ghost" block onClick={() => Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.accounts })}>
                  {c.addPayout}
                </Button>
              </>
            )}
          </View>
          <Collapsible label={c.workNumbersMore} defaultOpen={false}>
            <View className="creator-metrics creator-metrics--pair">
              <MetricCard icon="flask" label={c.walletCreditsFuel} value={String(credits?.balance ?? 0)} />
              <MetricCard icon="sigil" label={c.walletFiatRoyalty} value={formatFen(w?.available_minor, w?.currency)} variant="info" />
            </View>
            <View className="creator-metrics creator-metrics--quad">
              <MetricCard icon="flask" label={c.pending} value={formatFen(w?.pending_minor, w?.currency)} />
              <MetricCard icon="bookmark" label={c.frozen} value={formatFen(w?.frozen_minor, w?.currency)} variant="warning" />
              <MetricCard icon="music" label={c.walletRadio} value={formatWarmup(payload?.source_split?.radio_minor, c.warmupNotCash)} />
              <MetricCard icon="bookmark" label={c.walletDsp} value={formatFen(payload?.source_split?.dsp_minor, w?.currency)} />
            </View>
            <View className="creator-metrics creator-metrics--pair">
              <MetricCard icon="flask" label={c.walletSync} value={formatFen(payload?.source_split?.sync_minor, w?.currency)} />
              <MetricCard icon="feed" label={c.walletEmbed} value={formatFen(payload?.source_split?.embed_minor, w?.currency)} />
            </View>
            <Button variant="ghost" onClick={() => Taro.navigateTo({ url: CREATOR_PAGE_ROUTES.settlements })}>
              {c.goSettlements}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (weapp) {
                  void copyWeappCreatorLink(CREATOR_PAGE_ROUTES.settlements);
                  return;
                }
                void downloadCreatorStatement(c);
              }}
            >
              {c.shareReceipt}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => Taro.navigateTo({ url: creatorPage("help") })}>
              {c.seeHelp}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => Taro.navigateTo({ url: STACK_PAGE_ROUTES.creatorEarnings })}>
              {c.creditsTitle}
            </Button>
          </Collapsible>

          <SectionLabel>{c.ledgerTitle}</SectionLabel>
          {(payload?.ledger || []).length === 0 && (
            <EmptyState
              iconName="profile"
              title={c.emptyWalletShort}
              description={c.waitStatementShort}
              actionLabel={c.goSettlements}
              onAction={() => Taro.navigateTo({ url: creatorPage("settlements") })}
            />
          )}
          <View className="creator-ledger">
            {(payload?.ledger || [])
              .filter((e) => !w?.currency || !e.currency || e.currency === w.currency)
              .map((e) => (
              <View
                key={e.id}
                className={e.ref_id ? "creator-channel creator-channel--tap" : "creator-channel"}
                onClick={() => {
                  if (!e.ref_id) return;
                  Taro.navigateTo({ url: creatorPage("settlements") });
                }}
              >
                <View>
                  <Text className="creator-channel__name">{ledgerTypeLabel(e.type, c.ledgerTypes)}</Text>
                  <Text className="creator-channel__meta">
                    {e.accounting_subject === "warmup"
                      ? `${c.walletRadio} · `
                      : e.accounting_subject === "label_royalty"
                        ? `${c.walletDsp} · `
                        : e.accounting_subject === "sync"
                          ? `${c.walletSync} · `
                          : e.accounting_subject === "embed"
                            ? `${c.walletEmbed} · `
                            : ""}
                    {e.note || ""}
                    {e.created_at ? ` · ${e.created_at.slice(0, 16).replace("T", " ")}` : ""}
                  </Text>
                </View>
                <Text className="creator-channel__name">{formatFen(e.amount_minor, e.currency || w?.currency)}</Text>
              </View>
            ))}
          </View>

          {(payload?.withdrawals || []).length > 0 && <SectionLabel>{c.withdrawalsTitle}</SectionLabel>}
          {(payload?.withdrawals || []).map((row) => (
            <View
              key={row.id}
              className={row.receipt_no ? "creator-channel creator-channel--tap" : "creator-channel"}
              onClick={() => {
                if (!row.receipt_no) return;
                Taro.setClipboardData({
                  data: row.receipt_no,
                  success: () => Taro.showToast({ title: c.receiptCopied.replace("{n}", row.receipt_no || ""), icon: "none" }),
                });
              }}
            >
              <View>
                <Text className="creator-channel__name">{formatFen(row.amount_minor, row.currency)}</Text>
                <Text className="creator-channel__meta">
                  {row.receipt_no ? c.receiptNo.replace("{n}", row.receipt_no) : ""}
                  {row.created_at ? ` · ${row.created_at.slice(0, 16).replace("T", " ")}` : ""}
                  {row.risk_flag ? ` · ${c.riskReview}` : ""}
                  {row.receipt_no ? ` · ${c.copyReceipt}` : ""}
                </Text>
              </View>
              <Badge tone={statusTone(row.status)}>{statusLabel(row.status, c.status)}</Badge>
            </View>
          ))}
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
