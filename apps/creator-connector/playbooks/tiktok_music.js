(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("tiktok_music", {
    hosts: ["tiktok.com"],
    live: (url) => /tiktok.com\/music\/|\/sound\//.test(url),
    selectors: ["input[placeholder*='title' i]", "input[placeholder*='标题']"],
    isrcSelectors: ["input[name='isrc']", "input[aria-label*='isrc' i]", "input[placeholder*='ISRC']"],
  });
})();
