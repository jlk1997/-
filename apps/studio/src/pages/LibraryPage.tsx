import { vibeApi } from "@vibe-sorcery/api-client";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deskCopy } from "../copy";
import { useDeskPlayer } from "../player";

export function LibraryPage() {
  const copy = deskCopy();
  const navigate = useNavigate();
  const player = useDeskPlayer();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "beauty" | "raw">("all");
  const works = useQuery({ queryKey: ["works"], queryFn: () => vibeApi.listWorks("newest", undefined, 80) });

  const rows = useMemo(() => {
    const list = works.data || [];
    return list.filter((work) => {
      if (q && !work.title.toLowerCase().includes(q.toLowerCase())) return false;
      if (filter === "beauty" && !work.from_workbench) return false;
      if (filter === "raw" && work.from_workbench) return false;
      return true;
    });
  }, [filter, q, works.data]);

  function onKey(event: React.KeyboardEvent) {
    if (event.key === "/" && document.activeElement?.tagName !== "INPUT") {
      event.preventDefault();
      document.getElementById("library-search")?.focus();
    }
  }

  return (
    <div className="panel" onKeyDown={onKey}>
      <div className="row">
        <h1>{copy.library}</h1>
        <input id="library-search" placeholder={copy.search} value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
          <option value="all">全部</option>
          <option value="raw">成曲</option>
          <option value="beauty">美化</option>
        </select>
      </div>
      {works.isLoading ? <p>加载中…</p> : null}
      {works.isError ? <button type="button" onClick={() => void works.refetch()}>加载失败，重试</button> : null}
      {!works.isLoading && rows.length === 0 ? <p className="muted">{copy.emptyLibrary}</p> : null}
      <table className="grid">
        <thead>
          <tr><th>标题</th><th>来源</th><th>状态</th><th /></tr>
        </thead>
        <tbody>
          {rows.map((work) => (
            <tr key={work.id} className={player.track?.id === work.id && player.playing ? "is-on" : ""}>
              <td>{work.title}</td>
              <td>{work.from_workbench ? "调音台" : "生成"}</td>
              <td>{work.visibility || "private"}</td>
              <td className="row">
                <button
                  type="button"
                  onClick={() => {
                    if (player.track?.id === work.id) player.toggle();
                    else player.play({ id: work.id, title: work.title, url: work.audio_url, cover: work.cover_url });
                  }}
                >
                  {player.track?.id === work.id && player.playing ? copy.pause : copy.play}
                </button>
                <button type="button" onClick={() => navigate(`/mixer?work=${work.id}`)}>{copy.openMixer}</button>
                <button type="button" onClick={() => navigate(`/release?work=${work.id}`)}>{copy.ship}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
