import { vibeApi } from "@vibe-sorcery/api-client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { deskCopy } from "../copy";

export function AccountPage() {
  const copy = deskCopy();
  const me = useQuery({ queryKey: ["me"], queryFn: () => vibeApi.me() });
  const credits = useQuery({ queryKey: ["credits"], queryFn: () => vibeApi.getCredits() });
  const packs = useQuery({ queryKey: ["packs"], queryFn: () => vibeApi.getCreditPacks() });
  const [payNote, setPayNote] = useState("");

  async function buy(packId: string) {
    setPayNote("");
    try {
      const meta = await vibeApi.getLegalMeta();
      const version = meta.required_versions?.["payment-terms"];
      if (version) await vibeApi.recordConsents([{ consent_type: "payment-terms", version }]);
      const res = await vibeApi.createPayment(packId, "alipay", "h5", version);
      const url = res.pay_url || res.url;
      if (res.mode === "mock") {
        setPayNote(`测试记账已加上 ${res.credits_granted ?? ""} 次。`);
        return;
      }
      if (url) {
        window.location.href = url;
        return;
      }
      setPayNote("支付页没有打开。可以改用手机版充值。");
    } catch (err) {
      setPayNote(err instanceof Error ? err.message : "没能发起支付");
    }
  }

  return (
    <div className="panel">
      <h1>{copy.account}</h1>
      <p>{me.data?.email}</p>
      <p>{copy.balance}：{credits.data?.balance ?? "—"}</p>
      <h2>{copy.packs}</h2>
      {packs.isLoading ? <p>加载中…</p> : null}
      {packs.isError ? <button type="button" onClick={() => void packs.refetch()}>次数包加载失败，重试</button> : null}
      <ul className="stack">
        {(packs.data || []).map((pack) => (
          <li key={pack.id} className="row">
            <span>{pack.label} · {pack.credits} {copy.credits}</span>
            <button type="button" onClick={() => void buy(pack.id)}>去支付</button>
          </li>
        ))}
      </ul>
      {payNote ? <p>{payNote}</p> : null}
    </div>
  );
}
