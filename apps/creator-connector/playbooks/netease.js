(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("netease", {
    hosts: ["music.163.com"],
    live: (url) => /song\?id=|\/song\/|program\?id=/.test(url),
    selectors: ["input[name='name']", "input[placeholder*='歌名']", "input[placeholder*='歌曲名']"],
    isrcSelectors: ["input[name='isrc']", "input[placeholder*='ISRC']", "input[placeholder*='国际标准']"],
  });
})();
