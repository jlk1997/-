(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("amazon_music", {
    hosts: ["music.amazon.com", "artists.amazon.com"],
    live: (url) => /music.amazon.com/.test(url),
    selectors: ["input[name='title']"],
    isrcSelectors: ["input[name='isrc']", "input[aria-label*='isrc' i]", "input[placeholder*='ISRC']"],
  });
})();
