(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("qq_music", {
    hosts: ["y.qq.com", "music.qq.com"],
    live: (url) => /songDetail|\/song\?|\/n\/ryqq\/songDetail/.test(url),
    selectors: ["input[name='title']", "input[placeholder*='歌曲']"],
    isrcSelectors: ["input[name='isrc']", "input[placeholder*='ISRC']"],
  });
})();
