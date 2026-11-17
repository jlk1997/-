import { useMemo, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { AsyncPanel, Badge, Button, Collapsible, EmptyState, SectionLabel, SegmentedControl, StatusLine } from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import { creatorPage } from "../../../constants/routes";
import { channelName, formatFen, formatMoneyMap, formatPayoutCountdown, formatWarmup, settlementSourceLabel, statusLabel, statusTone } from "../../lib";
import { downloadCreatorStatement, downloadProExport } from "../../exportReports";
import { MoneySplit } from "../../MoneySplit";
import "../../creator.scss";
import "./index.scss";

type HubLite = {
  wallet_split?: { sources?: { radio_minor?: number; sync_minor?: number; embed_minor?: number; dsp_minor?: number; harvest_minor?: number } };
  payout_calendar?: { next_payout_date?: string; weekday_label?: string; days_until_payout?: number; is_payout_day?: boolean };
  waiting_for_statement?: boolean;
  has_label_release?: boolean;
  pending_confirm_count?: number;
  label_period?: {
    expected_earliest?: string;
    expected_latest?: string;
    gross_minor?: number;
    commission_minor?: number;
    net_minor?: number;
    currency?: string;
  };
};

type StatementLite = { receipt_no?: string };

type Batch = {
  batch_id: string;
  period_key?: string;
  status?: string;
  withdrawable?: boolean;
  gross_minor?: number;
  commission_minor?: number;
  net_minor?: number;
  currency?: string;
  mixed_currency?: boolean;
  by_currency?: Array<{ currency?: string; gross_minor?: number; commission_minor?: number; net_minor?: number }>;
  lines?: Array<{
    channel_code: string;
    work_id?: string;
    work_title?: string;
    net_minor: number;
    gross_minor?: number;
    commission_minor?: number;
    commission_rate?: number;
    source: string;
    share_role?: string;
    accounting_subject?: string;
    currency?: string;
  }>;
};

export default function SettlementsPage() {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const [period, setPeriod] = useState("all");
  const [openBatch, setOpenBatch] = useState("");
  const { data, loading, error, reload, setData } = useAsyncQuery<{ rows: Batch[]; hub: HubLite | null; statement: StatementLite | null }>(async () => {
    if (!requireAuth(creatorPage("settlements"))) return { rows: [], hub: null, statement: null };
    const [res, hub, statement] = await Promise.all([
      vibeApi.getCreatorSettlements(),
      vibeApi.getCreatorHub().catch(() => null),
      vibeApi.getCreatorStatement().catch(() => null),
    ]);
    return {
      rows: (res.settlements || []) as Batch[],
      hub: hub as HubLite | null,
      statement: statement as StatementLite | null,
    };
  }, []);

  useDidShow(() => {
    void reload();
  });
  usePullDownRefresh(async () => {
    await reload();
    Taro.stopPullDownRefresh();
  });

  const periods = useMemo(() => {
    const keys = Array.from(new Set((data?.rows || []).map((b) => b.period_key).filter(Boolean))) as string[];
    return keys;
  }, [data]);
  const rows = (data?.rows || []).filter((b) => period === "all" || b.period_key === period);
  const sources = data?.hub?.wallet_split?.sources;
  const hasFirstParty = Boolean(sources?.radio_minor || sources?.sync_minor || sources?.embed_minor || sources?.dsp_minor);
  const canWithdraw = rows.some((b) => b.withdrawable);

  function moneyRows(pred: (b: Batch) => boolean) {
    const map: Record<string, { currency: string; net_minor: number }> = {};
    rows.filter(pred).forEach((b) => {
      const parts = b.by_currency?.length
        ? b.by_currency
        : [{ currency: b.currency || "CNY", net_minor: b.net_minor || 0 }];
      parts.forEach((row) => {
        const currency = row.currency || "CNY";
        map[currency] = { currency, net_minor: (map[currency]?.net_minor || 0) + (row.net_minor || 0) };
      });
    });
    return Object.values(map);
  }

  async function openDetail(batchId: string) {
    setOpenBatch(batchId);
    try {
      const detail = (await vibeApi.getCreatorSettlement(batchId)) as Batch;
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          rows: prev.rows.map((row) => (row.batch_id === batchId ? { ...row, ...detail, batch_id: batchId } : row)),
        };
      });
    } catch {
      Taro.showToast({ title: copy.worksUi.loadFail, icon: "none" });
    }
  }

  const [busy, setBusy] = useState(false);

  async function exportStatement() {
    if (busy) return;
    if (process.env.TARO_ENV === "weapp") {
      const copied = await copyWeappCreatorLink(creatorPage("settlements"));
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      await downloadCreatorStatement(c, period === "all" ? undefined : period);
    } finally {
      setBusy(false);
    }
  }

  async function exportPro() {
    if (busy) return;
    if (process.env.TARO_ENV === "weapp") {
      const copied = await copyWeappCreatorLink(creatorPage("settlements"));
      if (!copied) Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    setBusy(true);
    try {
      await downloadProExport(c);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell title={c.goSettlements} subtitle={c.dataHint} ambient>
      <View className="creator">
        <WeappH5Bridge path={creatorPage("settlements")} />
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void reload()}
        >
          <View className="creator-hero">
            <Text className="creator-hero__kicker">{c.fiatTitle}</Text>
            <Text className="creator-hero__title">{c.goSettlements}</Text>
            <Text className="creator-hero__sub">{c.waitStatementShort}</Text>
            {rows.length > 0 && (
              <View className="creator-metrics creator-metrics--pair">
                <View>
                  <Text className="creator-hero__kicker">{c.available}</Text>
                  <Text className="creator-amount">{formatMoneyMap(moneyRows((b) => Boolean(b.withdrawable)))}</Text>
                </View>
                <View>
                  <Text className="creator-hero__kicker">{c.pending}</Text>
                  <Text className="creator-amount">{formatMoneyMap(moneyRows((b) => !b.withdrawable))}</Text>
                </View>
              </View>
            )}
          </View>
          {periods.length > 1 && (
            <SegmentedControl
              options={[{ value: "all", label: c.periodAll }, ...periods.map((p) => ({ value: p, label: p }))]}
              value={period}
              onChange={setPeriod}
            />
          )}
          {(data?.hub?.pending_confirm_count || 0) > 0 ? (
            <StatusLine tone="info">{c.pendingDraftHint.replace("{n}", String(data?.hub?.pending_confirm_count))}</StatusLine>
          ) : data?.hub?.payout_calendar?.next_payout_date ? (
            <StatusLine tone="info" density="quiet">{formatPayoutCountdown(data.hub.payout_calendar, c)}</StatusLine>
          ) : (
            <StatusLine tone="info" density="quiet">{c.waitHarvestShort}</StatusLine>
          )}
          {canWithdraw && (
            <Button variant="primary" block onClick={() => Taro.navigateTo({ url: creatorPage("wallet") })}>
              {c.withdrawNow}
            </Button>
          )}
          {rows.length === 0 && (data?.rows || []).length === 0 && (
            <EmptyState
              iconName="grimoire"
              title={c.emptySettlements}
              description={c.waitStatementShort}
              actionLabel={hasFirstParty ? c.goWallet : c.goDeliveries}
              onAction={() => Taro.navigateTo({ url: creatorPage(hasFirstParty ? "wallet" : "deliveries") })}
            />
          )}
          <Collapsible label={c.moneyBreakdown} defaultOpen={false}>
            {(data?.hub?.label_period?.gross_minor || 0) > 0 ? (
              <MoneySplit
                gross={data?.hub?.label_period?.gross_minor || 0}
                take={data?.hub?.label_period?.commission_minor || 0}
                net={data?.hub?.label_period?.net_minor || 0}
                currency={data?.hub?.label_period?.currency}
                labels={{ gross: c.splitGross, take: c.splitTake, net: c.splitNet }}
              />
            ) : null}
            {data?.statement?.receipt_no && (
              <View
                className="creator-channel creator-channel--tap"
                onClick={() => {
                  const receipt = data.statement?.receipt_no || "";
                  Taro.setClipboardData({
                    data: receipt,
                    success: () => Taro.showToast({ title: c.receiptCopied.replace("{n}", receipt), icon: "none" }),
                  });
                }}
              >
                <Text className="creator-channel__meta">{`${c.receiptNo.replace("{n}", data.statement.receipt_no)} · ${c.copyReceipt}`}</Text>
              </View>
            )}
            <View className="creator-metrics creator-metrics--pair">
              <Text className="typo-meta">{`${c.walletRadio} ${formatWarmup(sources?.radio_minor, c.warmupNotCash)}`}</Text>
              <Text className="typo-meta">{`${c.walletSync} ${formatFen(sources?.sync_minor)}`}</Text>
              <Text className="typo-meta">{`${c.walletEmbed} ${formatFen(sources?.embed_minor)}`}</Text>
              <Text className="typo-meta">{`${c.walletDsp} ${formatFen(sources?.dsp_minor)}`}</Text>
            </View>
            {(data?.rows || []).length > 0 && (
              <View className="creator-actions">
                <Button size="sm" variant="ghost" loading={busy} onClick={() => void exportStatement()}>
                  {c.exportCsv}
                </Button>
                <Button size="sm" variant="ghost" loading={busy} onClick={() => void exportPro()}>
                  {c.proExport}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => Taro.navigateTo({ url: creatorPage("help") })}>
                  {c.seeHelp}
                </Button>
              </View>
            )}
          </Collapsible>
          {rows.map((b) => (
            <View key={b.batch_id} className="creator-card">
              <View className="creator-channel">
                <View>
                  <Text className="creator-channel__name">{b.period_key || b.batch_id}</Text>
                  <Text className="creator-channel__meta">
                    {`${c.splitGross} ${b.mixed_currency ? formatMoneyMap(b.by_currency, "gross_minor") : formatFen(b.gross_minor, b.currency)}`}
                  </Text>
                  <Text className="creator-amount">{b.mixed_currency ? formatMoneyMap(b.by_currency) : formatFen(b.net_minor, b.currency)}</Text>
                </View>
                <Badge tone={statusTone(b.status)}>{statusLabel(b.status || "", c.status)}</Badge>
              </View>
              {(b.by_currency?.length
                ? b.by_currency
                : [{ currency: b.currency, gross_minor: b.gross_minor, commission_minor: b.commission_minor, net_minor: b.net_minor }]
              ).map((row) => (
                <MoneySplit
                  key={`${b.batch_id}-${row.currency || "CNY"}`}
                  gross={row.gross_minor || 0}
                  take={row.commission_minor || 0}
                  net={row.net_minor || 0}
                  currency={row.currency}
                  labels={{ gross: c.splitGross, take: c.splitTake, net: c.splitNet }}
                />
              ))}
              <StatusLine tone={b.withdrawable ? "success" : "info"}>
                {b.withdrawable ? c.settlementConfirmedHint : c.settlementDraftHint}
              </StatusLine>
              {b.withdrawable && (
                <Button size="sm" variant="primary" onClick={() => Taro.navigateTo({ url: creatorPage("wallet") })}>
                  {c.withdrawNow}
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => void openDetail(b.batch_id)}>
                {c.batchDetail}
              </Button>
              {(b.lines || []).length > 0 && <SectionLabel>{c.byChannel}</SectionLabel>}
              {(b.lines || []).map((line, i) => (
                <View
                  key={`${b.batch_id}-${i}`}
                  className="creator-check"
                  onClick={() => {
                    if (line.work_id) Taro.navigateTo({ url: creatorPage("work", { workId: line.work_id }) });
                  }}
                >
                  <View>
                    <Text className="creator-check__label">
                      {line.work_title ? `${line.work_title} · ` : ""}
                      {channelName(line.channel_code, c.channels)}
                    </Text>
                    <Text className="creator-channel__meta">
                      {c.sourceLabel.replace("{s}", settlementSourceLabel(line.source, c.sources))}
                      {line.share_role ? ` · ${c.shareRoleLine.replace("{r}", line.share_role)}` : ""}
                      {line.commission_rate ? ` · ${line.commission_rate}%` : ""}
                      {line.gross_minor != null ? ` · ${formatFen(line.gross_minor, line.currency)} → ${formatFen(line.net_minor, line.currency)}` : ""}
                    </Text>
                  </View>
                  <Text className="creator-channel__name">{formatFen(line.net_minor, line.currency)}</Text>
                </View>
              ))}
            </View>
          ))}
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
