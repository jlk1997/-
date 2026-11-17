(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("douyin_musician", {
    hosts: ["douyin.com", "creator.douyin.com"],
    live: (url) => /music|aweme|video/.test(url),
    selectors: ["input[placeholder*='作品']", "textarea[placeholder*='作品']"],
    isrcSelectors: ["input[name='isrc']", "input[placeholder*='ISRC']"],
  });
})();
