(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.VibeUpload = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const TITLE_SELECTORS = [
    "input[name*='title' i]",
    "input[id*='title' i]",
    "input[name='name']",
    "input[placeholder*='歌名']",
    "input[placeholder*='曲名']",
    "input[placeholder*='标题']",
    "input[placeholder*='Title' i]",
    "textarea[name*='title' i]",
  ];
  const ARTIST_SELECTORS = [
    "input[name*='artist' i]",
    "input[id*='artist' i]",
    "input[placeholder*='艺人']",
    "input[placeholder*='Artist' i]",
  ];
  const ISRC_SELECTORS = [
    "input[name*='isrc' i]",
    "input[id*='isrc' i]",
    "input[placeholder*='ISRC' i]",
    "input[placeholder*='曲目码']",
  ];
  const EVIDENCE_RE = /原创|版权证明|分轨|工程|stems?|originality|proof|evidence|instrumental|伴奏|zip|rar/;
  const AUDIO_RE = /audio|song|track|music|mp3|wav|flac|歌曲|音频|正片|master/;

  function setValue(el, value) {
    if (!el || value == null || !("value" in el)) return false;
    if (typeof el.focus === "function") el.focus();
    try {
      const proto =
        el.tagName === "TEXTAREA"
          ? typeof HTMLTextAreaElement !== "undefined" && HTMLTextAreaElement.prototype
          : typeof HTMLInputElement !== "undefined" && HTMLInputElement.prototype;
      const desc = proto && Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) desc.set.call(el, String(value));
      else el.value = String(value);
    } catch {
      el.value = String(value);
    }
    const fire = (type) => {
      try {
        el.dispatchEvent(typeof Event === "function" ? new Event(type, { bubbles: true }) : { type });
      } catch {
        if (typeof el.dispatchEvent === "function") el.dispatchEvent({ type });
      }
    };
    fire("input");
    fire("change");
    return true;
  }

  function fillFirst(doc, selectors, value) {
    if (!value) return false;
    const root = doc || document;
    for (const sel of selectors) {
      const el = root.querySelector(sel);
      if (el && setValue(el, value)) return true;
    }
    return false;
  }

  function haystack(el) {
    const parent = el.closest ? el.closest("label, .form-item, .upload, .ant-form-item, li") : null;
    return [
      el.name,
      el.id,
      el.accept,
      el.placeholder,
      el.className,
      el.getAttribute && el.getAttribute("aria-label"),
      parent && parent.textContent,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
  }

  function classifyFileInputs(doc) {
    const root = doc || document;
    const inputs = Array.from((root.querySelectorAll && root.querySelectorAll("input[type='file']")) || []);
    const evidence = [];
    const audio = [];
    inputs.forEach((el) => {
      const hay = haystack(el);
      if (EVIDENCE_RE.test(hay) && !AUDIO_RE.test(hay.split("zip")[0])) evidence.push(el);
      else if (EVIDENCE_RE.test(hay)) evidence.push(el);
      else audio.push(el);
    });
    return {
      master: audio[0] || null,
      evidence: evidence[0] || null,
      extraAudio: audio.slice(1),
      listingAsset: "master",
    };
  }

  function fireInput(el) {
    const fire = (type) => {
      try {
        el.dispatchEvent(typeof Event === "function" ? new Event(type, { bubbles: true }) : { type });
      } catch {
        if (typeof el.dispatchEvent === "function") el.dispatchEvent({ type });
      }
    };
    fire("input");
    fire("change");
  }

  function fileListOf(file) {
    if (typeof DataTransfer === "function") {
      const dt = new DataTransfer();
      dt.items.add(file);
      return dt.files;
    }
    return {
      length: 1,
      0: file,
      item() {
        return file;
      },
    };
  }

  function setInputFile(input, file) {
    if (!input || !file) return false;
    try {
      const list = fileListOf(file);
      try {
        input.files = list;
      } catch {
        Object.defineProperty(input, "files", { configurable: true, value: list });
      }
      fireInput(input);
      return Boolean(input.files && input.files.length > 0);
    } catch {
      return false;
    }
  }

  function dropFileOnZone(doc, file) {
    const root = doc || document;
    const zone =
      (root.querySelector &&
        (root.querySelector("[class*='upload-drag']") ||
          root.querySelector("[class*='dropzone']") ||
          root.querySelector("[class*='drop-zone']") ||
          root.querySelector("[data-upload]") ||
          root.querySelector(".ant-upload-drag"))) ||
      null;
    if (!zone || !file) return false;
    try {
      const dt = typeof DataTransfer === "function" ? new DataTransfer() : { files: fileListOf(file), items: { add() {} } };
      if (dt.items && dt.items.add) dt.items.add(file);
      for (const type of ["dragenter", "dragover", "drop"]) {
        const evt =
          typeof DragEvent === "function"
            ? new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt })
            : { type, bubbles: true, dataTransfer: dt };
        if (typeof zone.dispatchEvent === "function") zone.dispatchEvent(evt);
      }
      return true;
    } catch {
      return false;
    }
  }

  function firstMatch(doc, selectors) {
    const root = doc || document;
    for (const sel of selectors || []) {
      const node = root.querySelector && root.querySelector(sel);
      if (node) return node;
    }
    return null;
  }

  function attachReleaseAssets(doc, payload) {
    const roles = classifyFileInputs(doc);
    const data = payload || {};
    const guide = CHANNEL_UPLOAD_GUIDES[data.channel] || {};
    const masterSlot = firstMatch(doc, splitSelectors(guide.audioFileSelector, [])) || roles.master;
    const evidenceSlot = firstMatch(doc, splitSelectors(guide.evidenceFileSelector, [])) || roles.evidence;
    const filled = [];
    const master = data.masterFile || data.master_file;
    const evidence = data.evidenceFile || data.evidence_file;
    if (masterSlot && master && masterSlot !== evidenceSlot && setInputFile(masterSlot, master)) {
      filled.push("master");
    } else if (master && dropFileOnZone(doc, master)) {
      const after = classifyFileInputs(doc).master;
      if (after && after.files && after.files.length > 0) filled.push("master");
    }
    if (evidenceSlot && evidence && evidenceSlot !== masterSlot && setInputFile(evidenceSlot, evidence)) {
      filled.push("evidence");
    }
    return {
      ok: filled.length > 0,
      attached: filled.includes("master"),
      filled,
      listingAsset: "master",
      skippedStemsOnMaster: true,
      hasEvidenceSlot: Boolean(roles.evidence),
    };
  }

  function clickSubmitOnce(doc, payload) {
    const data = payload || {};
    if (data.submitted || data._submitted) return { clicked: false, reason: "already" };
    const guide = CHANNEL_UPLOAD_GUIDES[data.channel] || {};
    const selectors = splitSelectors(guide.submitSelector, ['button[type="submit"]', ".btn-submit", ".publish-btn"]);
    const root = doc || document;
    for (const sel of selectors) {
      const btn = root.querySelector && root.querySelector(sel);
      if (!btn || btn.disabled) continue;
      try {
        if (typeof btn.click === "function") btn.click();
        return { clicked: true, selector: sel };
      } catch {
        continue;
      }
    }
    return { clicked: false, reason: "no_button" };
  }

  function splitSelectors(raw, fallback) {
    if (!raw) return fallback;
    const parts = String(raw)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return parts.length ? parts.concat(fallback) : fallback;
  }

  function fillAuthorizedForm(doc, payload) {
    const data = payload || {};
    const guide = CHANNEL_UPLOAD_GUIDES[data.channel] || {};
    const title = data.title_with_code || data.title;
    const filled = [];
    if (fillFirst(doc, splitSelectors(guide.titleSelector, TITLE_SELECTORS), title)) filled.push("title");
    if (fillFirst(doc, splitSelectors(guide.artistSelector, ARTIST_SELECTORS), data.artist_name)) filled.push("artist");
    if (fillFirst(doc, splitSelectors(guide.isrcSelector, ISRC_SELECTORS), data.isrc || data.track_code)) filled.push("isrc");
    const files = attachReleaseAssets(doc, data);
    const submit = data.auto_submit ? clickSubmitOnce(doc, data) : { clicked: false };
    return {
      ok: filled.length > 0 || files.ok,
      attached: Boolean(files.attached),
      submitted: Boolean(submit.clicked),
      filled: filled.concat(files.filled),
      title: title || "",
      listingAsset: "master",
      hasEvidenceSlot: files.hasEvidenceSlot,
      channel: data.channel || "",
    };
  }

  const CHANNEL_UPLOAD_GUIDES = {
    netease: {
      url: "https://music.163.com/st/musician/upload",
      titleSelector: 'input[name="songName"], input[placeholder*="歌曲名"]',
      artistSelector: 'input[name="singer"], input[placeholder*="歌手"]',
      isrcSelector: 'input[name="isrc"]',
      genreSelector: 'select[name="genre"], .genre-picker',
      submitSelector: 'button[type="submit"], .btn-submit',
      extraFields: { language: 'select[name="language"]' },
      audioFileSelector: 'input[type=file][accept*="audio"], input[type=file][name*="song"], input[type=file]',
      evidenceFileSelector:
        'input[type=file][name*="stem" i], input[type=file][name*="proof" i], input[type=file][accept*="zip"], input[type=file][name*="original"]',
    },
    qq_music: {
      url: "https://y.qq.com/portal/publish.html",
      titleSelector: 'input.song-title, input[placeholder*="歌曲名称"]',
      artistSelector: 'input.artist-name, input[placeholder*="艺人"]',
      isrcSelector: 'input[name="isrc"]',
      submitSelector: ".publish-btn, button.submit",
      evidenceFileSelector: 'input[type=file][accept*="zip"], input[type=file][name*="stem"]',
    },
    kugou: {
      url: "https://www.kugou.com/imusic/static/html/document.html",
      titleSelector: 'input[name="songName"], input[placeholder*="歌名"]',
      artistSelector: 'input[name="artist"]',
      submitSelector: "button.submit",
      evidenceFileSelector: 'input[type=file][accept*="zip"], input[type=file][name*="stem"]',
    },
    kuwo: {
      url: "https://kuwo.cn/musician/upload",
      titleSelector: 'input[name="title"]',
      artistSelector: 'input[name="artist"]',
      submitSelector: "button.submit",
    },
    qishui: {
      url: "https://musician.douyin.com/upload",
      titleSelector: 'input[placeholder*="歌曲名"]',
      artistSelector: 'input[placeholder*="歌手"]',
      submitSelector: 'button[type="submit"]',
      audioFileSelector: 'input[type=file][accept*="audio"], input[type=file]',
    },
    bilibili: {
      url: "https://member.bilibili.com/platform/upload/audio/home",
      titleSelector: 'input[placeholder*="标题"], input[name*="title"]',
      submitSelector: 'button[type="submit"], .submit-btn, button.submit',
    },
    spotify: { url: "https://artists.spotify.com/" },
    apple_music: { url: "https://artists.apple.com/" },
    youtube_music: { url: "https://studio.youtube.com/" },
    tiktok_music: { url: "https://www.tiktok.com/studio" },
    amazon_music: { url: "https://artists.amazon.com/" },
    deezer: { url: "https://www.deezer.com/" },
    soundcloud: { url: "https://soundcloud.com/upload" },
    bandcamp: { url: "https://bandcamp.com/" },
    wechat_channels: {
      url: "https://channels.weixin.qq.com/",
      titleSelector: 'textarea[placeholder*="标题"], input[placeholder*="标题"], textarea[placeholder*="描述"]',
      submitSelector: 'button[type="submit"], .weui-desktop-btn_primary, button.publish',
    },
    douyin_musician: {
      url: "https://creator.douyin.com/",
      titleSelector: 'input[placeholder*="标题"], textarea[placeholder*="标题"], input[placeholder*="作品"]',
      submitSelector: 'button[type="submit"], button.publish, .publish-btn',
    },
    kuaishou_musician: {
      url: "https://cp.kuaishou.com/",
      titleSelector: 'input[placeholder*="标题"], textarea[placeholder*="标题"], input[placeholder*="作品"]',
      submitSelector: 'button[type="submit"], button.publish, .publish-btn',
    },
  };

  const STORE_LIVE = {
    netease: /music\.163\.com\/(?:#\/)?song/i,
    qq_music: /y\.qq\.com\/.*songDetail/i,
    kugou: /kugou\.com\/.+(?:hash=|song)/i,
    kuwo: /kuwo\.cn\/.+(?:play_detail|yinyue|\d{5,})/i,
    qishui: /music\.douyin\.com\/.+/i,
    bilibili: /bilibili\.com\/(?:video|audio)\//i,
    spotify: /open\.spotify\.com\/(?:intl-[a-z]+\/)?(?:track|album)\//i,
    apple_music: /music\.apple\.com\/.+\/(?:album|song)\//i,
    youtube_music: /(?:youtube\.com\/watch|youtu\.be\/|music\.youtube\.com\/watch)/i,
    tiktok_music: /tiktok\.com\/(?:music\/|.+\/sound\/)/i,
    amazon_music: /music\.amazon\.[^/]+\/(?:albums|tracks)\//i,
    deezer: /deezer\.com\/.*\/(?:track|album)\//i,
    wechat_channels: /channels\.weixin\.qq\.com\/.+(?:finder|export|feed|post)/i,
    douyin_musician: /douyin\.com\/(?:.+\/)?(?:video|note|music)/i,
    kuaishou_musician: /kuaishou\.com\/(?:.+\/)?(?:short-video|photo)/i,
    soundcloud: /soundcloud\.com\/[^/?#]+\/[^/?#]+/i,
    bandcamp: /bandcamp\.com\/(?:track|album)\//i,
  };

  function looksLikeStorePage(url, code) {
    const raw = String(url || "");
    if (!raw) return false;
    if (/artists\.(spotify|apple|amazon)|studio\.youtube|creator\.douyin|member\.bilibili|cp\.kuaishou/i.test(raw)) {
      return false;
    }
    if (/\/st\/musician|\/portal\/|\/musician|\/upload\/?$/i.test(raw)) return false;
    const pattern = STORE_LIVE[code];
    return pattern ? pattern.test(raw) : false;
  }

  function planUpload(code, spec, payload) {
    const guide = CHANNEL_UPLOAD_GUIDES[code] || {};
    const data = payload || {};
    return {
      ok: Boolean(spec),
      action: "upload",
      url: guide.url || (spec && spec.uploadUrl) || "",
      listingAsset: "master",
      guide: {
        titleSelector: guide.titleSelector || TITLE_SELECTORS.join(", "),
        artistSelector: guide.artistSelector || ARTIST_SELECTORS.join(", "),
        isrcSelector: guide.isrcSelector || ISRC_SELECTORS.join(", "),
        submitSelector: guide.submitSelector || "",
        extraFields: guide.extraFields || {},
        audioFileSelector: guide.audioFileSelector || "input[type=file]",
        evidenceFileSelector: guide.evidenceFileSelector || "",
      },
      payload: {
        title_with_code: data.title_with_code || "",
        artist_name: data.artist_name || "",
        isrc: data.isrc || data.track_code || "",
        master_audio_url: data.master_audio_url || data.audio_url || "",
        originality_zip_url: data.originality_zip_url || "",
        listing_asset: "master",
      },
    };
  }

  return {
    fillAuthorizedForm,
    planUpload,
    classifyFileInputs,
    attachReleaseAssets,
    setInputFile,
    dropFileOnZone,
    clickSubmitOnce,
    looksLikeStorePage,
    CHANNEL_UPLOAD_GUIDES,
    STORE_LIVE,
  };
});
