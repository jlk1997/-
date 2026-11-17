(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("apple_music", {
    hosts: ["artists.apple.com", "music.apple.com"],
    live: (url) => /music.apple.com\//.test(url),
    selectors: ["input[name='title']", "input[aria-label*='title' i]"],
    isrcSelectors: ["input[name='isrc']", "input[aria-label*='isrc' i]", "input[placeholder*='ISRC']"],
  });
})();
