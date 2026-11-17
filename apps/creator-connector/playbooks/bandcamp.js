(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("bandcamp", {
    hosts: ["bandcamp.com"],
    live: (url) => /bandcamp.com\/(track|album)\//.test(url),
    selectors: ["input[name='title']", "#track_title"],
    isrcSelectors: ["input[name='isrc']", "input[aria-label*='isrc' i]", "input[placeholder*='ISRC']"],
  });
})();
