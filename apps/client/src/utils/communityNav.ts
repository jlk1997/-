import Taro from "@tarojs/taro";
import { setItem, removeItem, getItem } from "../platform/storage";
import { vibeApi } from "../services/api";
import { bootstrapAuth, isLoggedIn } from "./auth";

export const FEED_HIGHLIGHT_POST_KEY = "feed:highlightPostId";

export function openCommunityPost(postId: string) {
  setItem(FEED_HIGHLIGHT_POST_KEY, postId);
  Taro.switchTab({ url: "/pages/feed/index" });
}

export function consumeFeedHighlightPostId(): string | null {
  const id = getItem(FEED_HIGHLIGHT_POST_KEY);
  if (id) removeItem(FEED_HIGHLIGHT_POST_KEY);
  return id;
}

export async function openExistingDiscoverPost(workId: string, knownPostId?: string | null): Promise<boolean> {
  if (knownPostId) {
    openCommunityPost(knownPostId);
    return true;
  }
  try {
    const work = (await vibeApi.getWork(workId)) as { community_post_id?: string | null };
    if (work.community_post_id) {
      openCommunityPost(work.community_post_id);
      return true;
    }
  } catch {
    /* fall through to feed lookup */
  }
  const resolved = await resolvePostIdForWork(workId);
  if (resolved) {
    openCommunityPost(resolved);
    return true;
  }
  return false;
}

export async function resolvePostIdForWork(workId: string): Promise<string | null> {
  if (!isLoggedIn()) return null;
  bootstrapAuth();
  try {
    const me = await vibeApi.me();
    const feed = await vibeApi.getFeed("latest");
    const post = feed.find((p) => p.work?.id === workId && p.author_username === me.username);
    return post?.id ?? null;
  } catch {
    return null;
  }
}
