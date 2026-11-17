(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("deezer", {
    hosts: ["deezer.com"],
    live: (url) => /deezer.com\/(track|album)\//.test(url),
    selectors: ["input[name='title']"],
    isrcSelectors: ["input[name='isrc']", "input[aria-label*='isrc' i]", "input[placeholder*='ISRC']"],
  });
})();
