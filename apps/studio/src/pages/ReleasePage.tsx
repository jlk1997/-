import { vibeApi } from "@vibe-sorcery/api-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { deskCopy } from "../copy";

export function ReleasePage() {
  const copy = deskCopy();
  const client = useQueryClient();
  const [params] = useSearchParams();
  const workId = params.get("work") || "";
  const releases = useQuery({ queryKey: ["releases"], queryFn: () => vibeApi.listReleases() });
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function start() {
    if (!workId) return;
    setBusy(true);
    setMessage("");
    try {
      await vibeApi.createRelease(workId);
      await client.invalidateQueries({ queryKey: ["releases"] });
      setMessage("已建立发行单。质检和授权通过后才会去交店，不会自动上架。");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "没能建立发行单");
    } finally {
      setBusy(false);
    }
  }

  async function step(id: string, kind: "qc" | "license" | "submit") {
    setBusy(true);
    setMessage("");
    try {
      if (kind === "qc") await vibeApi.qcRelease(id);
      if (kind === "license") await vibeApi.signReleaseLicense(id);
      if (kind === "submit") await vibeApi.submitRelease(id);
      await client.invalidateQueries({ queryKey: ["releases"] });
      setMessage(kind === "submit" ? "已交去填表。没有店面回执之前，这首歌还不算在售。" : "发行单已更新。");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "这一步没完成");
    } finally {
      setBusy(false);
    }
  }

  const rows = releases.data?.releases || [];
  return (
    <div className="panel">
      <h1>{copy.release}</h1>
      <p className="muted">{copy.notLive}</p>
      {workId ? <button type="button" className="primary" disabled={busy} onClick={() => void start()}>为这首歌建立发行单</button> : null}
      {message ? <p>{message}</p> : null}
      {releases.isLoading ? <p>加载中…</p> : null}
      {releases.isError ? <button type="button" onClick={() => void releases.refetch()}>重试</button> : null}
      {!rows.length && !releases.isLoading ? <p>{copy.releaseEmpty}</p> : null}
      <table className="grid">
        <thead><tr><th>作品</th><th>{copy.qc}</th><th>{copy.license}</th><th>{copy.receipt}</th></tr></thead>
        <tbody>
          {rows.map((row) => {
            const item = row as { id?: string; title?: string; work_title?: string; qc_status?: string; license_status?: string; status?: string };
            const id = String(item.id || "");
            return (
              <tr key={id}>
                <td>{item.work_title || item.title || id}</td>
                <td>
                  {item.qc_status || "—"}
                  {id ? <button type="button" disabled={busy} onClick={() => void step(id, "qc")}>质检</button> : null}
                </td>
                <td>
                  {item.license_status || "—"}
                  {id ? <button type="button" disabled={busy} onClick={() => void step(id, "license")}>签授权</button> : null}
                </td>
                <td>
                  {item.status || "—"}
                  {id ? <button type="button" disabled={busy} onClick={() => void step(id, "submit")}>交去填表</button> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
