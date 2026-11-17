(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("kuwo", {
    hosts: ["kuwo.cn"],
    live: (url) => /play_detail|yinyue/.test(url),
    selectors: ["input[placeholder*='歌名']", "input[name='name']"],
    isrcSelectors: ["input[name='isrc']", "input[placeholder*='ISRC']"],
  });
})();
