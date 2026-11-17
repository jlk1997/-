import { useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow, usePullDownRefresh } from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../../../components/PageShell";
import { AsyncPanel, Badge, Button, Collapsible, EmptyState, Input, SectionLabel, StatusLine } from "../../../components/ui";
import { useAsyncQuery } from "../../../hooks/useAsyncQuery";
import { vibeApi } from "../../../services/api";
import { requireAuth } from "../../../utils/auth";
import { creatorPage } from "../../../constants/routes";
import { goShipBand } from "../../nextActionNav";
import { copyWeappCreatorLink, WeappH5Bridge } from "../../WeappH5Bridge";
import { channelName, statusLabel, statusTone } from "../../lib";
import "../../creator.scss";

type Member = {
  username?: string;
  role?: string;
  mine?: boolean;
  unpublished?: number;
  publishing?: number;
  live_stores?: number;
};

type QueueRow = {
  delivery_id: string;
  work_id?: string;
  title?: string;
  channel_code?: string;
  status?: string;
  owner_username?: string;
  mine?: boolean;
  priority_score?: number;
};

type Unpublished = { work_id: string; title?: string; qc_ready?: boolean };

type CommunePayload = {
  commune?: {
    name?: string;
    invite_code?: string;
    member_count?: number;
    max_members?: number;
    is_owner?: boolean;
  } | null;
  members?: Member[];
  queue?: QueueRow[];
  note?: string;
  wallet_shared?: boolean;
  unpublished?: Unpublished[];
};

export default function CreatorCommunePage() {
  const { copy } = useLocale();
  const c = copy.creatorUi;
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [busy, setBusy] = useState("");
  const weapp = process.env.TARO_ENV === "weapp";

  const { data, loading, error, reload } = useAsyncQuery<CommunePayload | null>(async () => {
    if (!requireAuth(creatorPage("commune"))) return null;
    const [board, hub] = await Promise.all([
      vibeApi.getCreatorCommune() as Promise<CommunePayload>,
      vibeApi.getCreatorHub().catch(() => null),
    ]);
    return {
      ...board,
      unpublished: ((hub?.unpublished_works || []) as Unpublished[]),
    };
  }, []);

  useDidShow(() => {
    void reload();
  });
  usePullDownRefresh(async () => {
    await reload();
    Taro.stopPullDownRefresh();
  });

  async function run(key: string, fn: () => Promise<unknown>, ok: string) {
    if (weapp) {
      await copyWeappCreatorLink(creatorPage("commune"));
      Taro.showToast({ title: c.weappDeskHint, icon: "none" });
      return;
    }
    setBusy(key);
    try {
      await fn();
      Taro.showToast({ title: ok, icon: "success" });
      await reload();
    } catch (err) {
      Taro.showToast({ title: String((err as Error)?.message || copy.adminUi.actionFail), icon: "none" });
    } finally {
      setBusy("");
    }
  }

  const commune = data?.commune;

  return (
    <PageShell title={c.communeTitle} subtitle={c.communeHint} ambient>
      <View className="creator">
        <WeappH5Bridge path={creatorPage("commune")} />
        <AsyncPanel
          loading={loading}
          error={error}
          errorTitle={copy.worksUi.loadFail}
          errorActionLabel={copy.discoverUi.retry}
          onRetry={() => void reload()}
        >
          <StatusLine tone="info">{data?.note || c.communeHint}</StatusLine>
          {!commune && (
            <>
              <EmptyState iconName="profile" title={c.communeEmpty} description={c.communeHint} />
              <Input label={c.communeTitle} value={name} onInput={(e) => setName(e.detail.value)} />
              <Button
                variant="primary"
                block
                loading={busy === "create"}
                onClick={() => void run("create", () => vibeApi.createCreatorCommune(name), c.communeCreate)}
              >
                {c.communeCreate}
              </Button>
              <Collapsible label={c.communeJoinDoor} defaultOpen={false}>
                <Input label={c.communeCode} value={inviteCode} onInput={(e) => setInviteCode(e.detail.value)} />
                <Button
                  variant="secondary"
                  block
                  loading={busy === "join"}
                  onClick={() => void run("join", () => vibeApi.inviteCreatorCommune({ invite_code: inviteCode }), c.communeJoin)}
                >
                  {c.communeJoin}
                </Button>
              </Collapsible>
            </>
          )}

          {commune && (
            <>
              <View className="creator-hero">
                <Text className="creator-hero__kicker">{c.communeTitle}</Text>
                <Text className="creator-hero__title">{commune.name}</Text>
                <Text className="creator-hero__sub">
                  {commune.member_count || 0}/{commune.max_members || 10}
                  {commune.invite_code ? ` · ${c.communeCode} ${commune.invite_code}` : ""}
                </Text>
              </View>
              {commune.invite_code && (
                <Button
                  variant="secondary"
                  block
                  onClick={() => {
                    void Taro.setClipboardData({ data: commune.invite_code || "" });
                    Taro.showToast({ title: c.communeCopied, icon: "success" });
                  }}
                >
                  {c.communeCode}
                </Button>
              )}
              {commune.is_owner && (
                <>
                  <Input label={c.splitUsername} value={username} onInput={(e) => setUsername(e.detail.value)} />
                  <Button
                    variant="primary"
                    block
                    loading={busy === "invite"}
                    onClick={() => void run("invite", () => vibeApi.inviteCreatorCommune({ username }), c.communeInvite)}
                  >
                    {c.communeInvite}
                  </Button>
                </>
              )}
              <Button
                variant="ghost"
                block
                loading={busy === "leave"}
                onClick={() => void run("leave", () => vibeApi.leaveCreatorCommune(), c.communeLeave)}
              >
                {c.communeLeave}
              </Button>

              <SectionLabel>{c.communeTitle}</SectionLabel>
              {(data?.members || []).map((member) => (
                <View key={member.username || member.role} className="creator-channel">
                  <View>
                    <Text className="creator-channel__name">
                      {member.username || "—"}
                      {member.mine ? " · me" : ""}
                    </Text>
                    <Text className="creator-channel__meta">
                      {c.unpublishedWorks} {member.unpublished || 0}
                      {` · ${c.publishing} ${member.publishing || 0}`}
                      {` · ${c.liveStores.replace("{n}", String(member.live_stores || 0))}`}
                    </Text>
                  </View>
                  <Badge tone={member.role === "owner" ? "accent" : "info"}>{member.role || "member"}</Badge>
                  {member.mine && (member.unpublished || 0) > 0 && (
                    <Button size="sm" variant="ghost" onClick={() => goShipBand()}>
                      {c.communeSubmit}
                    </Button>
                  )}
                </View>
              ))}

              {(data?.unpublished || []).length > 0 && (
                <>
                  <SectionLabel>{c.unpublishedWorks}</SectionLabel>
                  {(data?.unpublished || []).map((work) => (
                    <View key={work.work_id} className="creator-channel">
                      <View>
                        <Text className="creator-channel__name">{work.title || c.releaseUntitled}</Text>
                      </View>
                      <Button
                        size="sm"
                        variant="primary"
                        loading={busy === work.work_id}
                        onClick={() =>
                          goShipBand(work.work_id)
                        }
                      >
                        {c.communeSubmit}
                      </Button>
                    </View>
                  ))}
                </>
              )}

              <SectionLabel>{c.communeQueue}</SectionLabel>
              {(data?.queue || []).length === 0 && (
                <EmptyState
                  iconName="feed"
                  title={c.noDeliveries}
                  actionLabel={c.goDeliveries}
                  onAction={() => Taro.navigateTo({ url: creatorPage("deliveries") })}
                />
              )}
              {(data?.queue || []).map((row) => (
                <View
                  key={row.delivery_id}
                  className="creator-channel"
                  onClick={() => {
                    if (!row.mine || !row.work_id) return;
                    Taro.navigateTo({ url: creatorPage("deliveries", { workId: row.work_id }) });
                  }}
                >
                  <View>
                    <Text className="creator-channel__name">{row.title || c.releaseUntitled}</Text>
                    <Text className="creator-channel__meta">
                      {channelName(row.channel_code || "", c.channels)}
                      {row.owner_username ? ` · @${row.owner_username}` : ""}
                      {row.priority_score ? ` · ${row.priority_score}` : ""}
                    </Text>
                  </View>
                  <Badge tone={statusTone(row.status)}>{statusLabel(row.status || "ops_queue", c.status)}</Badge>
                </View>
              ))}
            </>
          )}
        </AsyncPanel>
      </View>
    </PageShell>
  );
}
