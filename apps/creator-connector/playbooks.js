(() => {
  const PLAYBOOKS = [
    {
      id: "netease",
      hosts: ["music.163.com"],
      live: (url) => /song\?id=|\/song\/|program\?id=/.test(url),
    },
    {
      id: "qq_music",
      hosts: ["y.qq.com", "music.qq.com"],
      live: (url) => /songDetail|\/song\?|y.qq.com\/n\/ryqq\/songDetail/.test(url),
    },
    {
      id: "qishui",
      hosts: ["music.douyin.com"],
      live: (url) => /music|aweme|video/.test(url),
    },
    {
      id: "kugou",
      hosts: ["kugou.com"],
      live: (url) => /song|hash|album/.test(url),
    },
    {
      id: "kuwo",
      hosts: ["kuwo.cn"],
      live: (url) => /play_detail|yinyue/.test(url),
    },
    {
      id: "bilibili",
      hosts: ["bilibili.com", "member.bilibili.com"],
      live: (url) => /bilibili.com\/audio\/|bilibili.com\/video\//.test(url),
    },
    {
      id: "douyin_musician",
      hosts: ["douyin.com", "creator.douyin.com"],
      live: (url) => /music|aweme|video/.test(url),
    },
    {
      id: "wechat_channels",
      hosts: ["channels.weixin.qq.com"],
      live: (url) => /channels.weixin.qq.com/.test(url) && /finder|export|feed|post/.test(url),
    },
    {
      id: "spotify",
      hosts: ["artists.spotify.com", "open.spotify.com"],
      live: (url) => /open.spotify.com\/(track|album)\//.test(url),
    },
    {
      id: "youtube_music",
      hosts: ["studio.youtube.com", "youtube.com", "music.youtube.com"],
      live: (url) => /youtube.com\/watch|youtu.be\/|music.youtube.com\/watch/.test(url),
    },
    {
      id: "kuaishou_musician",
      hosts: ["kuaishou.com"],
      live: (url) => /kuaishou.com\/short-video|photo/.test(url),
    },
    {
      id: "apple_music",
      hosts: ["artists.apple.com", "music.apple.com"],
      live: (url) => /music.apple.com\//.test(url),
    },
    {
      id: "tiktok_music",
      hosts: ["tiktok.com"],
      live: (url) => /tiktok.com\/music\/|\/sound\//.test(url),
    },
    {
      id: "amazon_music",
      hosts: ["music.amazon.com", "artists.amazon.com"],
      live: (url) => /music.amazon.com/.test(url),
    },
    {
      id: "soundcloud",
      hosts: ["soundcloud.com"],
      live: (url) => /soundcloud.com\/.+\/.+/.test(url) && !/upload/.test(url),
    },
    {
      id: "bandcamp",
      hosts: ["bandcamp.com"],
      live: (url) => /bandcamp.com\/(track|album)\//.test(url),
    },
    {
      id: "deezer",
      hosts: ["deezer.com"],
      live: (url) => /deezer.com\/(track|album)\//.test(url),
    },
  ];

  const SELECTORS = [
    "input[name='name']",
    "input[name='title']",
    "input[placeholder*='歌名']",
    "input[placeholder*='标题']",
    "input[placeholder*='Title']",
    "input[aria-label*='title' i]",
    "textarea[name='description']",
  ];
  const ISRC_SELECTORS = [
    "input[name*='isrc' i]",
    "input[placeholder*='ISRC']",
    "input[aria-label*='isrc' i]",
  ];
  const ARTIST_SELECTORS = [
    "input[name='artist']",
    "input[placeholder*='艺人']",
    "input[placeholder*='Artist']",
    "input[aria-label*='artist' i]",
  ];

  function setValue(el, value) {
    if (!el || value == null) return false;
    el.focus();
    el.value = String(value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function register(id, book) {
    const next = { id, ...book };
    const idx = PLAYBOOKS.findIndex((item) => item.id === id);
    if (idx >= 0) PLAYBOOKS[idx] = { ...PLAYBOOKS[idx], ...next };
    else PLAYBOOKS.push(next);
  }

  function fillJob(job) {
    const book = PLAYBOOKS.find((item) => item.id === job.channel_code) || {};
    const filled = { title: 0, artist: 0, isrc: 0 };
    const title = job.title_with_code || job.title;
    for (const sel of [...(book.selectors || []), ...SELECTORS]) {
      const el = document.querySelector(sel);
      if (el && title && setValue(el, title)) filled.title += 1;
    }
    for (const sel of ARTIST_SELECTORS) {
      const el = document.querySelector(sel);
      if (el && job.artist_name && setValue(el, job.artist_name)) filled.artist += 1;
    }
    for (const sel of [...(book.isrcSelectors || []), ...ISRC_SELECTORS]) {
      const el = document.querySelector(sel);
      if (el && job.isrc && setValue(el, job.isrc)) filled.isrc += 1;
    }
    return { filled: filled.title + filled.artist + filled.isrc, fields: filled, title: job.title_with_code || job.title || "" };
  }

  function matchPlaybook(url, channel) {
    const host = (() => {
      try {
        return new URL(url).hostname.replace(/^www\./, "");
      } catch {
        return "";
      }
    })();
    const byChannel = PLAYBOOKS.find((item) => item.id === channel);
    if (byChannel && byChannel.hosts.some((h) => host.endsWith(h.replace(/^www\./, "")))) return byChannel;
    return PLAYBOOKS.find((item) => item.hosts.some((h) => host.endsWith(h.replace(/^www\./, "")))) || byChannel || null;
  }

  function looksLive(url, channel) {
    const book = matchPlaybook(url, channel);
    return Boolean(book && book.live(url));
  }

  function banner(job) {
    const id = "vibe-assist-banner";
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      el.style.cssText =
        "position:fixed;z-index:2147483646;left:12px;right:12px;bottom:12px;padding:10px 12px;border-radius:10px;background:#111;color:#fff;font:13px/1.4 sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.25)";
      document.documentElement.appendChild(el);
    }
    const clips = (job.clip_windows || [])
      .map((clip) => {
        if (clip.start != null && clip.end != null) return `${clip.length}s ${clip.start}–${clip.end}`;
        return `${clip.length}s`;
      })
      .join(" / ");
    const bits = [
      `比特音一键代发：${job.title || ""}`,
      job.isrc || "无 ISRC",
      clips ? `切片 ${clips}` : "",
      job.kit_url ? "弹窗可下载素材包" : "",
      job.originality_zip_url ? "证明包另下，不要当正片音频上传" : "",
      "发布后回传商店页链接，不要回传后台首页",
    ].filter(Boolean);
    el.textContent = bits.join(" · ");
  }

  window.__vibePlaybooks = { PLAYBOOKS, register, fillJob, matchPlaybook, looksLive, banner };
})();
