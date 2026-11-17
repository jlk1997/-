const PORTAL_HOSTS = new Set([
  "artists.spotify.com",
  "studio.youtube.com",
  "artists.apple.com",
  "artists.amazon.com",
  "creator.douyin.com",
  "member.bilibili.com",
  "cp.kuaishou.com",
]);

const STORE_HINTS = [
  /open\.spotify\.com\/(?:intl-[a-z]+\/)?(?:track|album)\//i,
  /music\.163\.com\/(?:#\/)?song/i,
  /y\.qq\.com\/.*songDetail/i,
  /bilibili\.com\/(?:video|audio)\//i,
  /(?:youtube\.com\/watch|youtu\.be\/|music\.youtube\.com\/watch)/i,
  /music\.apple\.com\/.+(?:album|song)\//i,
  /tiktok\.com\/(?:music\/|.+\/sound\/)/i,
  /deezer\.com\/.+\/(?:track|album)\//i,
  /soundcloud\.com\/[^/?#]+\/[^/?#]+/i,
  /bandcamp\.com\/(?:track|album)\//i,
  /channels\.weixin\.qq\.com\/.+(?:finder|export|feed|post)/i,
  /douyin\.com\/.+(?:video|note|music)/i,
  /kuaishou\.com\/.+(?:short-video|photo)/i,
  /kugou\.com\/.+(?:hash=|song)/i,
  /kuwo\.cn\/.+(?:play_detail|yinyue|\d{5,})/i,
  /music\.douyin\.com\/.+/i,
  /music\.amazon\.[^/]+\/(?:albums|tracks)\//i,
];

function hostnameOf(url: string): { host: string; path: string } | null {
  try {
    const parsed = new URL(url);
    return { host: parsed.hostname.replace(/^www\./, ""), path: parsed.pathname.toLowerCase() };
  } catch {
    return null;
  }
}

export function isUploadPortalUrl(url: string): boolean {
  const parsed = hostnameOf(url.trim());
  if (!parsed) return false;
  if (PORTAL_HOSTS.has(parsed.host)) return true;
  return (
    parsed.path.includes("/st/musician") ||
    parsed.path.includes("/portal/") ||
    parsed.path.includes("/musician") ||
    parsed.path.endsWith("/upload")
  );
}

export function looksLikeStorePage(url: string): boolean {
  const raw = url.trim();
  if (!/^https?:\/\//i.test(raw)) return false;
  if (isUploadPortalUrl(raw)) return false;
  return STORE_HINTS.some((pattern) => pattern.test(raw));
}
