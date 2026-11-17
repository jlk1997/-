(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("spotify", {
    hosts: ["artists.spotify.com", "open.spotify.com"],
    live: (url) => /open.spotify.com\/(track|album)\//.test(url),
    selectors: ["input[name='title']", "input[aria-label*='title' i]"],
    isrcSelectors: ["input[name='isrc']", "input[aria-label*='isrc' i]", "input[placeholder*='ISRC']"],
  });
})();
