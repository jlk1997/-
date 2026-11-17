(() => {
  const api = window.__vibePlaybooks;
  if (!api) return;
  api.register("wechat_channels", {
    hosts: ["channels.weixin.qq.com"],
    live: (url) => /channels.weixin.qq.com/.test(url) && /finder|export|feed|post/.test(url),
    selectors: ["input[placeholder*='标题']", "textarea[placeholder*='描述']"],
    isrcSelectors: ["input[name='isrc']", "input[placeholder*='ISRC']"],
  });
})();
