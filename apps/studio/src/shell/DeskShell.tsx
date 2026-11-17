import { clearToken, vibeApi } from "@vibe-sorcery/api-client";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { deskCopy } from "../copy";
import { useDeskPlayer } from "../player";

const LINKS = [
  ["/create", "create"],
  ["/library", "library"],
  ["/mixer", "mixer"],
  ["/release", "release"],
  ["/discover", "discover"],
  ["/account", "account"],
] as const;

export function DeskShell({ username, children }: { username: string; children: ReactNode }) {
  const copy = deskCopy();
  const labels: Record<(typeof LINKS)[number][1], string> = {
    create: copy.create,
    library: copy.library,
    mixer: copy.mixer,
    release: copy.release,
    discover: copy.discover,
    account: copy.account,
  };
  const navigate = useNavigate();
  const player = useDeskPlayer();
  const credits = useQuery({ queryKey: ["credits"], queryFn: () => vibeApi.getCredits() });
  const active = useQuery({ queryKey: ["active-job"], queryFn: () => vibeApi.getActiveJob(), refetchInterval: 4000 });

  function leave() {
    clearToken();
    localStorage.removeItem("token");
    navigate("/login");
  }

  function phone() {
    localStorage.setItem("bittune-view", "mobile");
    window.location.assign("/?view=mobile");
  }

  return (
    <div className="desk">
      <aside className="desk-nav">
        <div className="desk-brand">{copy.brand}</div>
        {LINKS.map(([path, key]) => (
          <NavLink key={path} to={path} className={({ isActive }) => (isActive ? "desk-link is-on" : "desk-link")}>
            {labels[key]}
          </NavLink>
        ))}
        <button type="button" className="desk-link desk-link--quiet" onClick={phone}>{copy.phone}</button>
      </aside>
      <div className="desk-main">
        <header className="desk-top">
          <div className="desk-pill">{copy.credits} {credits.data?.balance ?? "—"}</div>
          {active.data?.id ? <div className="desk-pill is-live">{copy.activeJob} {Math.round((active.data.progress || 0) * 100)}%</div> : <div />}
          <button type="button" className="desk-user" onClick={leave} title={copy.logout}>
            <span className="avatar">{(username || "?").slice(0, 1).toUpperCase()}</span>
            {username}
          </button>
        </header>
        <div className="desk-page">{children}</div>
        <footer className="desk-play">
          <button type="button" onClick={player.toggle} disabled={!player.track}>{player.playing ? "II" : "▶"}</button>
          <span>{player.track?.title || "—"}</span>
        </footer>
      </div>
    </div>
  );
}
