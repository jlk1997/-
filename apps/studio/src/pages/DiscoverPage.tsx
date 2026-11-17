import { vibeApi } from "@vibe-sorcery/api-client";
import { useQuery } from "@tanstack/react-query";
import { deskCopy } from "../copy";
import { useDeskPlayer } from "../player";

export function DiscoverPage() {
  const copy = deskCopy();
  const player = useDeskPlayer();
  const feed = useQuery({ queryKey: ["feed"], queryFn: () => vibeApi.getFeed("new") });
  const posts = Array.isArray(feed.data) ? feed.data : [];
  return (
    <div className="panel">
      <h1>{copy.discover}</h1>
      <p className="muted">{copy.discoverNote}</p>
      {feed.isLoading ? <p>加载中…</p> : null}
      {feed.isError ? <button type="button" onClick={() => void feed.refetch()}>重试</button> : null}
      {!feed.isLoading && posts.every((post) => !post.work?.audio_url) ? <p className="muted">{copy.discoverEmpty}</p> : null}
      <div className="discover-grid">
        {posts.slice(0, 30).map((post) => {
          const work = post.work;
          if (!work?.id || !work.audio_url) return null;
          const current = player.track?.id === work.id && player.playing;
          return (
            <article key={post.id} className={current ? "discover-card is-on" : "discover-card"}>
              {work.cover_url ? <img src={work.cover_url} alt="" /> : <div className="discover-cover" />}
              <strong>{work.title}</strong>
              <span>{post.author_username}</span>
              <button
                type="button"
                className={current ? "is-on" : ""}
                onClick={() => {
                  if (player.track?.id === work.id) player.toggle();
                  else player.play({ id: work.id, title: work.title, url: work.audio_url, cover: work.cover_url });
                }}
              >
                {current ? copy.pause : copy.play}
              </button>
            </article>
          );
        })}
      </div>
    </div>
  );
}
