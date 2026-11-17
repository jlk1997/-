export type Work = {
  id: string;
  title: string;
  audio_url: string;
  hls_url?: string;
  cover_url?: string;
  moods?: string[];
  visibility?: string;
  version?: number;
  c2pa_verified?: boolean;
  post_process_status?: Record<string, unknown>;
  parent_work_id?: string;
  parent_work_title?: string;
  is_ai_generated?: boolean;
  release_status?: string;
  isrc?: string;
  is_owner?: boolean;
  live_stores?: number;
  commercial?: boolean;
  artist_name?: string;
  owner_username?: string;
  community_post_id?: string | null;
  community_caption?: string | null;
};

export type FeedPost = {
  id: string;
  caption?: string;
  like_count: number;
  comment_count?: number;
  liked_by_me?: boolean;
  author_is_following?: boolean;
  collected_by_me?: boolean;
  author_username?: string;
  author_creator_level?: string;
  tags?: string[];
  recommend_reason?: string;
  work?: Work;
};
