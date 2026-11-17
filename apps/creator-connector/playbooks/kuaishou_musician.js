(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("kuaishou_musician", {
    hosts: ["kuaishou.com"],
    live: (url) => /short-video|photo/.test(url),
    selectors: ["input[placeholder*='标题']", "textarea[placeholder*='描述']"],
    isrcSelectors: ["input[name='isrc']", "input[placeholder*='ISRC']"],
  });
})();
