(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("youtube_music", {
    hosts: ["studio.youtube.com", "youtube.com", "music.youtube.com"],
    live: (url) => /youtube.com\/watch|youtu.be\/|music.youtube.com\/watch/.test(url),
    selectors: ["#textbox", "div[aria-label*='title' i]", "input[name='title']"],
    isrcSelectors: ["input[name='isrc']", "input[aria-label*='isrc' i]", "input[placeholder*='ISRC']"],
  });
})();
