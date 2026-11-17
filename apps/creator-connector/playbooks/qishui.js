(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("qishui", {
    hosts: ["music.douyin.com"],
    live: (url) => /music|aweme|video/.test(url) && !/creator/.test(url),
    selectors: ["input[placeholder*='作品']", "input[placeholder*='标题']"],
    isrcSelectors: ["input[placeholder*='ISRC']"],
  });
})();
