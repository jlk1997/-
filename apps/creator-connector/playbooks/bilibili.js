(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("bilibili", {
    hosts: ["bilibili.com", "member.bilibili.com"],
    live: (url) => /bilibili.com\/audio\/|bilibili.com\/video\//.test(url),
    selectors: ["input[placeholder*='标题']", "input.input-val"],
    isrcSelectors: ["input[placeholder*='ISRC']", "input[name='isrc']"],
  });
})();
