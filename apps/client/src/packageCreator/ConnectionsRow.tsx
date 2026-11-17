import { useMemo, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { Button, StatusLine } from "../components/ui";
import { creatorPage } from "../constants/routes";
import { channelName, confirmCreatorAction } from "./lib";
import { pairFromMinted, sendCommandToExtension, sendPairToExtension, sendPollToExtension } from "./extensionPair";
import { vibeApi } from "../services/api";
import { LEGAL_ROUTES } from "../utils/legal";
import { copyWeappCreatorLink, WeappH5Bridge } from "./WeappH5Bridge";

export type ConnectionCard = {
  channel_code: string;
  name?: string;
  status?: string;
  suggest_connector?: boolean;
  seat_id?: string | null;
  portal?: string;
  first_page?: string;
  permissions?: string[];
  delivery_mode?: string;
  ownership?: string | null;
  scopes?: { metrics?: boolean; settle?: boolean; keep_sync?: boolean; upload?: boolean; auto_submit?: boolean } | null;
  has_license?: boolean;
  last_sync_at?: string | null;
  last_harvest_at?: string | null;
  relogin_due?: boolean;
  automation_level?: string;
  degraded?: boolean;
  degraded_to?: string;
  farm_health?: {
    ok?: boolean;
    rows?: number;
    matched?: number;
    official_csv?: boolean;
    license_blocked?: boolean;
    handed_to_extension?: boolean;
  };
  seat?: {
    farm_health?: {
      ok?: boolean;
      rows?: number;
      matched?: number;
      official_csv?: boolean;
      license_blocked?: boolean;
      handed_to_extension?: boolean;
    };
  };
};

type Copy = {
  myConnections: string;
  connDisconnected: string;
  connMetrics: string;
  connSettle: string;
  connNeedsLogin: string;
  connReloginDue: string;
  connDegraded: string;
  connPlatform: string;
  connSync: string;
  connOpen: string;
  connConnect: string;
  connLogin: string;
  connMore: string;
  connJustNow: string;
  connMinutesAgo: string;
  connHoursAgo: string;
  connSaveFail: string;
  connInstallHint: string;
  connLabelSkip: string;
  connShowMore: string;
  connShowFewer: string;
  connPairFirst: string;
    connOpened: string;
    connLastSync: string;
    keepSync: string;
  keepSyncHint: string;
  grantSettle: string;
  grantSettleHint: string;
    grantUpload: string;
    grantUploadHint: string;
    grantAutoSubmit: string;
    grantAutoSubmitHint: string;
    revokeScopes: string;
  revokeScopesHint: string;
  needLicense: string;
  syncThisStore: string;
  openRemoteLogin: string;
  disconnectSeat: string;
  disconnectSeatHint: string;
  revokeUploadHint: string;
  revokeAutoSubmitHint: string;
  metricsOnlyScopeHint: string;
  confirmGo: string;
  back: string;
  weappH5Copied: string;
};

const RANK: Record<string, number> = {
  needs_login: 0,
  settle: 1,
  metrics: 2,
  disconnected: 3,
  platform: 4,
};

function tone(status?: string): "success" | "info" | "error" | "loading" {
  if (status === "settle" || status === "metrics" || status === "platform") return "success";
  if (status === "needs_login") return "error";
  if (status === "disconnected") return "info";
  return "loading";
}

function label(row: ConnectionCard, c: Copy) {
  const name = row.name || channelName(row.channel_code);
  if (row.status === "platform") return c.connPlatform.replace("{name}", name);
  if (row.status === "settle") return c.connSettle.replace("{name}", name);
  if (row.status === "metrics") return c.connMetrics.replace("{name}", name);
  if (row.status === "needs_login") return c.connNeedsLogin.replace("{name}", name);
  return c.connDisconnected.replace("{name}", name);
}

export async function ensureSeatId(row: ConnectionCard) {
  if (row.seat_id) return String(row.seat_id);
  const seat = (await vibeApi.connectSeat(row.channel_code)) as { id?: string };
  return seat.id ? String(seat.id) : "";
}

export function SeatScopeToggles({
  seatId,
  scopes,
  copy,
  hasLicense,
  automationLevel,
  onDone,
}: {
  seatId: string;
  scopes?: { keep_sync?: boolean; settle?: boolean; upload?: boolean; auto_submit?: boolean } | null;
  hasLicense?: boolean;
  automationLevel?: string;
  copy: Pick<
    Copy,
    | "keepSync"
    | "keepSyncHint"
    | "grantSettle"
    | "grantSettleHint"
    | "grantUpload"
    | "grantUploadHint"
    | "grantAutoSubmit"
    | "grantAutoSubmitHint"
    | "revokeScopes"
    | "revokeScopesHint"
    | "needLicense"
    | "connSaveFail"
    | "weappH5Copied"
    | "revokeUploadHint"
    | "revokeAutoSubmitHint"
    | "metricsOnlyScopeHint"
    | "confirmGo"
    | "back"
  >;
  onDone?: () => void;
}) {
  async function patch(key: "keep_sync" | "settle" | "upload" | "auto_submit", value: boolean) {
    if (process.env.TARO_ENV === "weapp") {
      await copyWeappCreatorLink(creatorPage("accounts"));
      return;
    }
    try {
      await vibeApi.updateSeatScopes(seatId, { [key]: value });
      onDone?.();
      Taro.showToast({
        title:
          key === "settle"
            ? copy.grantSettle
            : key === "upload"
              ? copy.grantUpload
              : key === "auto_submit"
                ? copy.grantAutoSubmit
                : copy.keepSync,
        icon: "success",
      });
    } catch {
      Taro.showToast({ title: copy.connSaveFail, icon: "none" });
    }
  }

  function askScope(title: string, content: string, then: () => void) {
    void confirmCreatorAction({
      title,
      content,
      confirmText: copy.confirmGo,
      cancelText: copy.back,
    }).then((ok) => {
      if (ok) then();
    });
  }

  function toggleKeepSync() {
    const next = !scopes?.keep_sync;
    if (!next) {
      void patch("keep_sync", false);
      return;
    }
    askScope(copy.keepSync, copy.keepSyncHint, () => void patch("keep_sync", true));
  }

  function toggleUpload() {
    const next = !scopes?.upload;
    if (!next) {
      void confirmCreatorAction({
        title: copy.grantUpload,
        content: copy.revokeUploadHint,
        confirmText: copy.confirmGo,
        cancelText: copy.back,
      }).then((ok) => {
        if (ok) void patch("upload", false);
      });
      return;
    }
    askScope(copy.grantUpload, copy.grantUploadHint, () => void patch("upload", true));
  }

  function toggleAutoSubmit() {
    const next = !scopes?.auto_submit;
    if (!next) {
      void confirmCreatorAction({
        title: copy.grantAutoSubmit,
        content: copy.revokeAutoSubmitHint,
        confirmText: copy.confirmGo,
        cancelText: copy.back,
      }).then((ok) => {
        if (ok) void patch("auto_submit", false);
      });
      return;
    }
    askScope(copy.grantAutoSubmit, copy.grantAutoSubmitHint, () => void patch("auto_submit", true));
  }

  function toggleSettle() {
    const next = !scopes?.settle;
    if (!next) {
      void patch("settle", false);
      return;
    }
    if (!hasLicense) {
      askScope(copy.grantSettle, copy.needLicense, () => Taro.navigateTo({ url: LEGAL_ROUTES.distributionLicense }));
      return;
    }
    askScope(copy.grantSettle, copy.grantSettleHint, () => void patch("settle", true));
  }

  function revoke() {
    if (process.env.TARO_ENV === "weapp") {
      void copyWeappCreatorLink(creatorPage("accounts"));
      return;
    }
    askScope(copy.revokeScopes, copy.revokeScopesHint, () => {
      void (async () => {
        try {
          await vibeApi.revokeSeatScopes(seatId);
          onDone?.();
          Taro.showToast({ title: copy.revokeScopes, icon: "success" });
        } catch {
          Taro.showToast({ title: copy.connSaveFail, icon: "none" });
        }
      })();
    });
  }

  return (
    <View className="creator-scopes">
      <Button size="sm" variant={scopes?.keep_sync ? "primary" : "ghost"} onClick={toggleKeepSync}>
        {copy.keepSync}
      </Button>
      {automationLevel === "metrics_only" ? null : (
        <Button size="sm" variant={scopes?.upload ? "primary" : "ghost"} onClick={toggleUpload}>
          {copy.grantUpload}
        </Button>
      )}
      {automationLevel === "metrics_only" ? null : (
        <Button size="sm" variant={scopes?.auto_submit ? "primary" : "ghost"} onClick={toggleAutoSubmit}>
          {copy.grantAutoSubmit}
        </Button>
      )}
      <Button size="sm" variant={scopes?.settle ? "primary" : "ghost"} onClick={toggleSettle}>
        {copy.grantSettle}
      </Button>
      <Button size="sm" variant="ghost" onClick={revoke}>
        {copy.revokeScopes}
      </Button>
      {automationLevel === "metrics_only" ? (
        <Text className="typo-meta">{copy.metricsOnlyScopeHint}</Text>
      ) : null}
    </View>
  );
}

function formatSyncWhen(
  iso: string | null | undefined,
  copy: Pick<Copy, "connJustNow" | "connMinutesAgo" | "connHoursAgo">,
) {
  if (!iso) return "";
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return String(iso).replace("T", " ").slice(0, 16);
  const mins = Math.round((Date.now() - at) / 60000);
  if (mins < 2) return copy.connJustNow;
  if (mins < 60) return copy.connMinutesAgo.replace("{n}", String(mins));
  if (mins < 24 * 60) return copy.connHoursAgo.replace("{n}", String(Math.max(1, Math.round(mins / 60))));
  return String(iso).replace("T", " ").slice(0, 10);
}

function primaryKind(row: ConnectionCard): "open_portal" | "sync_metrics" | null {
  if (row.status === "platform") return null;
  if (row.status === "disconnected" || row.status === "needs_login") return "open_portal";
  if (row.status === "metrics" || row.status === "settle") return "sync_metrics";
  return row.suggest_connector ? "open_portal" : null;
}

function primaryLabel(row: ConnectionCard, copy: Copy) {
  if (row.status === "disconnected") return copy.connConnect;
  if (row.status === "needs_login") return copy.connLogin;
  return copy.connSync;
}

export function ConnectionsRow({
  connections,
  copy,
  weapp,
  extensionOn,
  compact = true,
  expandAll,
  showAll,
  onChanged,
}: {
  connections?: ConnectionCard[] | null;
  copy: Copy;
  weapp?: boolean;
  extensionOn?: boolean;
  compact?: boolean;
  expandAll?: boolean;
  showAll?: boolean;
  onChanged?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [more, setMore] = useState<string | null>(null);
  const rows = connections || [];
  const ranked = useMemo(() => {
    return rows
      .filter((row) => showAll || row.suggest_connector || row.status !== "disconnected")
      .slice()
      .sort((a, b) => (RANK[a.status || "disconnected"] ?? 9) - (RANK[b.status || "disconnected"] ?? 9));
  }, [rows, showAll]);
  if (!ranked.length) {
    return (
      <View className="creator-connections creator-connections--empty">
        <Text className="typo-meta">{copy.connInstallHint}</Text>
        {weapp ? <WeappH5Bridge path={creatorPage("accounts")} /> : null}
      </View>
    );
  }
  const limit = compact ? 4 : 6;
  const expanded = Boolean(expandAll || open);
  const visible = expanded ? ranked : ranked.slice(0, limit);
  const rest = Math.max(0, ranked.length - visible.length);

  async function run(row: ConnectionCard, kind: "open_portal" | "sync_metrics") {
    try {
      if (weapp) {
        await copyWeappCreatorLink(creatorPage("accounts"));
        return;
      }
      const seatId = await ensureSeatId(row);
      if (!seatId) {
        Taro.navigateTo({ url: creatorPage("accounts") });
        return;
      }
      await vibeApi.commandSeat(seatId, kind, kind === "open_portal" ? { login_url: row.portal } : {});
      if (extensionOn) {
        if (kind === "open_portal") {
          try {
            const minted = await vibeApi.mintConnectorToken();
            await sendPairToExtension(pairFromMinted(minted));
          } catch {
            /* already paired */
          }
        }
        const sent = await sendCommandToExtension({
          kind,
          seatId,
          channel: row.channel_code,
          payload: { login_url: row.portal },
        });
        if (!sent && kind === "sync_metrics") {
          Taro.showToast({ title: copy.connPairFirst, icon: "none" });
          onChanged?.();
          return;
        }
        Taro.showToast({ title: kind === "open_portal" ? copy.connOpened : copy.connSync, icon: "success" });
        void sendPollToExtension();
        onChanged?.();
        return;
      }
      if (kind === "open_portal") {
        Taro.navigateTo({ url: creatorPage("remoteLogin", { seatId }) });
        return;
      }
      Taro.showToast({ title: copy.connInstallHint, icon: "none" });
      onChanged?.();
    } catch {
      Taro.showToast({ title: copy.connSaveFail, icon: "none" });
    }
  }

  async function disconnect(seatId: string) {
    if (weapp) {
      await copyWeappCreatorLink(creatorPage("accounts"));
      return;
    }
    const ok = await confirmCreatorAction({
      title: copy.disconnectSeat,
      content: copy.disconnectSeatHint,
      confirmText: copy.confirmGo,
      cancelText: copy.back,
    });
    if (!ok) return;
    try {
      await vibeApi.disconnectSeat(seatId);
      Taro.showToast({ title: copy.disconnectSeat, icon: "success" });
      onChanged?.();
    } catch {
      Taro.showToast({ title: copy.connSaveFail, icon: "none" });
    }
  }

  const showHow = ranked.some((row) => row.suggest_connector && (row.status === "disconnected" || row.status === "needs_login"));
  const kind = (row: ConnectionCard) => primaryKind(row);

  return (
    <View className="creator-seats">
      <Text className="creator-mode__title">{copy.myConnections}</Text>
      {showHow && compact ? <Text className="typo-meta">{copy.connInstallHint}</Text> : null}
      {visible.map((row) => {
        const mine = row.ownership === "user" && row.seat_id;
        const action = kind(row);
        const when = formatSyncWhen(row.last_sync_at || row.last_harvest_at, copy);
        const extras = !compact && mine && more === row.channel_code;
        return (
          <View key={row.channel_code} className="creator-seat">
            <StatusLine tone={tone(row.status)}>{label(row, copy)}</StatusLine>
            {row.degraded ? (
              <StatusLine tone="info" density="quiet">
                {copy.connDegraded.replace("{name}", row.name || channelName(row.channel_code))}
              </StatusLine>
            ) : null}
            {row.relogin_due && row.status !== "needs_login" ? (
              <StatusLine tone="info" density="quiet">
                {copy.connReloginDue.replace("{name}", row.name || channelName(row.channel_code))}
              </StatusLine>
            ) : null}
            {row.status === "platform" && !row.suggest_connector ? (
              <Text className="typo-meta">{copy.connLabelSkip}</Text>
            ) : null}
            {when ? <Text className="typo-meta">{copy.connLastSync.replace("{when}", when)}</Text> : null}
            <View className="creator-actions">
              {action ? (
                <Button
                  size="sm"
                  variant={action === "sync_metrics" ? "secondary" : "primary"}
                  onClick={() => void run(row, action)}
                >
                  {primaryLabel(row, copy)}
                </Button>
              ) : null}
              {!compact && action === "sync_metrics" ? (
                <Button size="sm" variant="ghost" onClick={() => void run(row, "open_portal")}>
                  {copy.connOpen}
                </Button>
              ) : null}
              {!compact && mine ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setMore(extras ? null : row.channel_code)}
                >
                  {copy.connMore}
                </Button>
              ) : null}
            </View>
            {extras ? (
              <View className="creator-actions">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => Taro.navigateTo({ url: creatorPage("remoteLogin", { seatId: String(row.seat_id) }) })}
                >
                  {copy.openRemoteLogin}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => void disconnect(String(row.seat_id))}>
                  {copy.disconnectSeat}
                </Button>
              </View>
            ) : null}
            {!compact && mine ? (
              <SeatScopeToggles
                seatId={String(row.seat_id)}
                scopes={row.scopes}
                hasLicense={Boolean(row.has_license)}
                automationLevel={row.automation_level}
                copy={copy}
                onDone={onChanged}
              />
            ) : null}
          </View>
        );
      })}
      {rest > 0 ? (
        <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
          {copy.connShowMore.replace("{n}", String(rest))}
        </Button>
      ) : null}
      {expanded && ranked.length > limit && !expandAll ? (
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          {copy.connShowFewer}
        </Button>
      ) : null}
    </View>
  );
}
