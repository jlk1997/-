(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("soundcloud", {
    hosts: ["soundcloud.com"],
    live: (url) => /soundcloud.com\/.+\/.+/.test(url) && !/upload/.test(url),
    selectors: ["input[name='title']", "input.sc-input"],
    isrcSelectors: ["input[name='isrc']", "input[aria-label*='isrc' i]", "input[placeholder*='ISRC']"],
  });
})();
