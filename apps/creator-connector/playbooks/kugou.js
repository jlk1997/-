(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("kugou", {
    hosts: ["kugou.com"],
    live: (url) => /song|hash|album/.test(url),
    selectors: ["input[name='songName']", "input[placeholder*='歌名']"],
    isrcSelectors: ["input[name='isrc']", "input[placeholder*='ISRC']"],
  });
})();
