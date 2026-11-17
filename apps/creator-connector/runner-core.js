(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.VibeRunner = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const HOSTS = {
    netease: ["music.163.com"],
    qq_music: ["y.qq.com"],
    kugou: ["kugou.com"],
    kuwo: ["kuwo.cn"],
    qishui: ["music.douyin.com"],
    bilibili: ["bilibili.com", "member.bilibili.com"],
    spotify: ["artists.spotify.com", "open.spotify.com"],
    apple_music: ["artists.apple.com", "music.apple.com"],
    youtube_music: ["studio.youtube.com", "youtube.com"],
    tiktok_music: ["tiktok.com"],
    amazon_music: ["artists.amazon.com", "artists.amazonmusic.com", "music.amazon.com"],
    deezer: ["deezer.com"],
    wechat_channels: ["channels.weixin.qq.com"],
    douyin_musician: ["creator.douyin.com", "douyin.com"],
    kuaishou_musician: ["cp.kuaishou.com", "kuaishou.com"],
    soundcloud: ["soundcloud.com"],
    bandcamp: ["bandcamp.com"],
  };

  function flattenSelectors(selectorSets) {
    const out = [];
    for (const item of selectorSets || []) {
      if (Array.isArray(item)) out.push(...item);
      else if (item) out.push(item);
    }
    return out;
  }

  function trySelectors(doc, selectorSets) {
    for (const selectors of selectorSets) {
      const sels = Array.isArray(selectors) ? selectors : [selectors];
      for (const sel of sels) {
        try {
          const el = doc.querySelector(sel);
          if (el) return { el, selector: sel };
        } catch { /* invalid selector */ }
      }
    }
    return null;
  }

  const STEPS = {
    netease: {
      version: 2,
      statsUrls: ["https://music.163.com/st/musician"],
      waitSelectors: [
        ["[data-vibe-row]", ".m-table tbody tr", "table.song-list tr"],
        ["table", ".song-item", ".m-table"],
      ],
      exportSelectors: [
        ["a[href*='.csv']", "a[download*='csv' i]", "button[data-action='export-csv']"],
        ["a[href*='.csv']", "button[data-export]", "[data-action='export']"],
      ],
      exportTexts: ["导出CSV", "导出报表", "导出"],
      nextPageSelectors: [
        [".znxt", ".nxt", "a.next", ".pagination-next", "button[aria-label='next']"],
      ],
      loginHints: ["登录", "二维码", "手机号"],
    },
    qq_music: {
      statsUrls: ["https://y.qq.com/portal/", "https://y.qq.com/nportal/"],
      waitSelectors: ["table", ".song_item", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']", "a[download*='csv' i]", "button[data-export]"],
      exportTexts: ["导出CSV", "导出", "下载报表"],
      nextPageSelectors: [".page_next", "a.next", ".pagination-next"],
      loginHints: ["登录", "QQ登录", "微信登录"],
    },
    qishui: {
      statsUrls: ["https://music.douyin.com/"],
      waitSelectors: ["table", ".track-card", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']", "a[download*='csv' i]"],
      exportTexts: ["导出", "下载"],
      nextPageSelectors: [".pagination-next", "button.next"],
      loginHints: ["登录", "抖音登录"],
    },
    kugou: {
      statsUrls: ["https://www.kugou.com/musician/"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']", "a[download*='csv' i]"],
      exportTexts: ["导出", "下载"],
      nextPageSelectors: [".pagination-next", "a.next"],
      loginHints: ["登录"],
    },
    kuwo: {
      statsUrls: ["https://www.kuwo.cn/musician"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']", "a[download*='csv' i]"],
      exportTexts: ["导出", "下载"],
      nextPageSelectors: [".pagination-next", "a.next"],
      loginHints: ["登录"],
    },
    douyin_musician: {
      statsUrls: ["https://creator.douyin.com/", "https://creator.douyin.com/creator-micro/home"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']", "a[download*='csv' i]"],
      exportTexts: ["导出", "下载数据"],
      nextPageSelectors: [".pagination-next", "button.next"],
      loginHints: ["登录", "扫码"],
    },
    spotify: {
      statsUrls: ["https://artists.spotify.com/c/music", "https://artists.spotify.com/c/music/songs", "https://artists.spotify.com/"],
      waitSelectors: ["table", "[data-testid='row']", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']", "button[data-testid='export']", "[data-testid='download-csv']"],
      exportTexts: ["Download CSV", "Export CSV", "Export"],
      nextPageSelectors: ["button[aria-label='Next']", "[data-testid='pagination-next']"],
      loginHints: ["Log in", "Sign in", "登录"],
    },
    apple_music: {
      statsUrls: ["https://artists.apple.com/"],
      waitSelectors: ["table", ".song-row", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']", "button[data-export]"],
      exportTexts: ["Download CSV", "Export", "导出"],
      nextPageSelectors: ["button[aria-label='Next']", "a.next"],
      loginHints: ["Sign in", "Log in", "登录"],
    },
    youtube_music: {
      statsUrls: ["https://studio.youtube.com/", "https://studio.youtube.com/channel/analytics/tab-overview/period-default"],
      waitSelectors: ["table", "[data-views]", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']", "button[aria-label*='Download']"],
      exportTexts: ["Download CSV", "Download", "导出"],
      nextPageSelectors: ["#next-page-button", "button[aria-label='Next']"],
      loginHints: ["Sign in", "登录"],
    },
    bilibili: {
      statsUrls: ["https://member.bilibili.com/", "https://member.bilibili.com/platform/home"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']"],
      exportTexts: ["导出", "下载"],
      nextPageSelectors: [".pagination-next", "a.next"],
      loginHints: ["登录"],
    },
    wechat_channels: {
      statsUrls: ["https://channels.weixin.qq.com/", "https://channels.weixin.qq.com/platform"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']"],
      exportTexts: ["导出", "下载"],
      nextPageSelectors: [".pagination-next", "a.next"],
      loginHints: ["登录", "扫码"],
    },
    kuaishou_musician: {
      statsUrls: ["https://cp.kuaishou.com/"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']"],
      exportTexts: ["导出", "下载"],
      nextPageSelectors: [".pagination-next", "a.next"],
      loginHints: ["登录"],
    },
    tiktok_music: {
      statsUrls: ["https://www.tiktok.com/studio"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']"],
      exportTexts: ["Download", "Export"],
      nextPageSelectors: ["button[aria-label='Next']", "a.next"],
      loginHints: ["Log in", "Sign in"],
    },
    amazon_music: {
      statsUrls: ["https://artists.amazon.com/", "https://artists.amazonmusic.com/analytics"],
      waitSelectors: [".analytics-table", "[data-testid='streams-table']", "table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']"],
      exportTexts: ["Download CSV", "Export"],
      nextPageSelectors: ["button[aria-label='Next']", "a.next"],
      loginHints: ["Sign in", "Log in"],
    },
    deezer: {
      statsUrls: ["https://artists.deezer.com/analytics", "https://www.deezer.com/"],
      waitSelectors: [".analytics-table", ".streams-list", "table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']"],
      exportTexts: ["Export", "Download"],
      nextPageSelectors: ["button[aria-label='Next']", "a.next"],
      loginHints: ["Log in", "Sign in"],
    },
    soundcloud: {
      statsUrls: ["https://soundcloud.com/you/insights"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']"],
      exportTexts: ["Export", "Download"],
      nextPageSelectors: ["button[aria-label='Next']", "a.next"],
      loginHints: ["Sign in", "Log in"],
    },
    bandcamp: {
      statsUrls: ["https://bandcamp.com/"],
      waitSelectors: ["table", "[data-vibe-row]"],
      exportSelectors: ["a[href*='.csv']"],
      exportTexts: ["Export", "Download"],
      nextPageSelectors: ["button[aria-label='Next']", "a.next"],
      loginHints: ["Log in", "Sign in"],
    },
  };

  const DEFAULT_STEPS = {
    statsUrls: [],
    waitSelectors: ["table", "[data-vibe-row]"],
    exportSelectors: ["a[href*='.csv']", "a[download]", "button[data-export]"],
    exportTexts: ["导出CSV", "Download CSV", "Export CSV", "导出", "Export"],
    nextPageSelectors: [".pagination-next", "a.next", "button[aria-label='Next']"],
    loginHints: ["登录", "Sign in", "Log in", "Sign-in"],
  };

  function stepsFor(code) {
    return { ...DEFAULT_STEPS, ...(STEPS[code] || {}) };
  }

  function detectChannel(url) {
    let host = "";
    try {
      host = new URL(url).hostname.replace(/^www\./, "").toLowerCase();
    } catch {
      return "";
    }
    for (const [code, listed] of Object.entries(HOSTS)) {
      if (listed.some((raw) => host === raw || host.endsWith(`.${raw}`))) return code;
    }
    return "";
  }

  function detectChannelFromDoc(doc, url) {
    try {
      const root = doc && doc.documentElement;
      const marked = root && root.getAttribute && root.getAttribute("data-vibe-channel");
      if (marked) return String(marked);
    } catch {
      /* ignore */
    }
    return detectChannel(url || (doc && doc.location && doc.location.href) || "");
  }

  function pageText(doc) {
    return String((doc && doc.body && doc.body.innerText) || "").slice(0, 6000);
  }

  function detectLoginWall(doc, code) {
    const spec = stepsFor(code);
    const text = pageText(doc);
    const url = (doc && doc.location && doc.location.href) || "";
    const hasWait = (spec.waitSelectors || []).some((sel) => {
      try {
        return Boolean(doc.querySelector(sel));
      } catch {
        return false;
      }
    });
    const loginish = (spec.loginHints || []).some((hint) => text.includes(hint) || url.toLowerCase().includes(String(hint).toLowerCase()));
    if (loginish && !hasWait) return true;
    if (/\/login|\/signin|passport\.|accounts\.google|accounts\.spotify/i.test(url) && !hasWait) return true;
    return false;
  }

  function isReady(doc, code) {
    const spec = stepsFor(code);
    return flattenSelectors(spec.waitSelectors).some((sel) => {
      try {
        return Boolean(doc.querySelector(sel));
      } catch {
        return false;
      }
    });
  }

  function findExportHrefs(doc, code) {
    const spec = stepsFor(code);
    const hrefs = [];
    const seen = new Set();
    const push = (href) => {
      const raw = String(href || "").trim();
      if (!raw || seen.has(raw)) return;
      if (!/\.csv(\?|#|$)/i.test(raw) && !/[?&](export|format)=csv/i.test(raw)) return;
      seen.add(raw);
      hrefs.push(raw);
    };
    for (const sel of flattenSelectors(spec.exportSelectors)) {
      try {
        Array.from(doc.querySelectorAll(sel) || []).forEach((el) => {
          push(el.href || (el.getAttribute && el.getAttribute("href")) || "");
        });
      } catch {
        /* invalid selector */
      }
    }
    return hrefs;
  }

  function readyState(doc, code) {
    if (detectLoginWall(doc, code)) {
      return { ready: false, reason: "needs_challenge", hrefs: [] };
    }
    const ready = isReady(doc, code);
    return { ready, reason: ready ? "ready" : "waiting", hrefs: findExportHrefs(doc, code) };
  }

  function clickFirst(doc, selectors) {
    for (const sel of flattenSelectors(selectors)) {
      try {
        const el = doc.querySelector(sel);
        if (el && typeof el.click === "function") {
          el.click();
          return sel;
        }
      } catch {
        /* invalid selector */
      }
    }
    return "";
  }

  function clickByText(doc, texts) {
    const needles = (texts || []).map((item) => String(item).toLowerCase());
    if (!needles.length || !doc || !doc.querySelectorAll) return "";
    const nodes = doc.querySelectorAll("a, button, [role='button']");
    let fallback = null;
    for (const el of Array.from(nodes || [])) {
      const text = String(el.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (!text || text.length > 32) continue;
      if (needles.some((needle) => text === needle)) {
        if (typeof el.click === "function") {
          el.click();
          return text;
        }
      }
      if (!fallback && needles.some((needle) => text.includes(needle))) fallback = el;
    }
    if (fallback && typeof fallback.click === "function") {
      fallback.click();
      return String(fallback.textContent || "").replace(/\s+/g, " ").trim();
    }
    return "";
  }

  function clickExport(doc, code) {
    const spec = stepsFor(code);
    return clickFirst(doc, spec.exportSelectors || []) || clickByText(doc, spec.exportTexts || []);
  }

  function scrollBottom(doc) {
    const win = doc.defaultView;
    if (win && typeof win.scrollTo === "function") {
      win.scrollTo(0, (doc.documentElement && doc.documentElement.scrollHeight) || 0);
    }
  }

  function rowKey(row) {
    return `${row && row.track_code ? row.track_code : ""}|${row && row.title ? row.title : ""}|${row && row.streams ? row.streams : 0}|${row && row.revenue_minor ? row.revenue_minor : 0}`;
  }

  function mergeRows(existing, incoming) {
    const out = Array.isArray(existing) ? existing.slice() : [];
    const seen = new Set(out.map(rowKey));
    (incoming || []).forEach((row) => {
      const key = rowKey(row);
      if (seen.has(key)) return;
      seen.add(key);
      out.push(row);
    });
    return out;
  }

  function harvestApi() {
    if (typeof globalThis !== "undefined" && globalThis.VibeHarvest) return globalThis.VibeHarvest;
    if (typeof window !== "undefined" && window.VibeHarvest) return window.VibeHarvest;
    return {};
  }

  function looksLikeCsv(text) {
    const raw = String(text || "");
    return raw.includes(",") && /title|曲名|track|streams|播放|revenue|收益/i.test((raw.split("\n")[0] || ""));
  }

  function installCsvTrap(doc) {
    const win = doc && doc.defaultView;
    if (!win || win.__vibeCsvTrap) return;
    win.__vibeCsvTrap = { texts: [] };
    const pushText = (text) => {
      if (looksLikeCsv(text)) win.__vibeCsvTrap.texts.push(String(text));
    };
    const orig = win.URL && win.URL.createObjectURL;
    if (typeof orig === "function") {
      win.URL.createObjectURL = function (blob) {
        try {
          if (blob && typeof blob.text === "function") {
            const type = String(blob.type || "");
            if (!type || /csv|text|spreadsheet|excel/i.test(type) || (blob.size && blob.size < 2e6)) {
              Promise.resolve(blob.text()).then(pushText).catch(() => {});
            }
          }
        } catch {
          /* keep original download */
        }
        return orig.apply(this, arguments);
      };
    }
    win.addEventListener(
      "click",
      (event) => {
        const target = event.target && event.target.closest ? event.target.closest("a[download], a[href*='.csv']") : null;
        if (!target) return;
        const href = target.href || "";
        if (/^(blob:|data:)/i.test(href)) {
          fetch(href)
            .then((res) => res.text())
            .then(pushText)
            .catch(() => {});
        }
      },
      true,
    );
  }

  function drainCsvTrap(doc, code) {
    const harvest = harvestApi();
    const parse = harvest.parseOfficialCsv;
    const win = doc && doc.defaultView;
    const texts = (win && win.__vibeCsvTrap && win.__vibeCsvTrap.texts) || [];
    if (!parse) return [];
    for (const text of texts) {
      const rows = parse(text, code) || [];
      if (rows.length) return rows;
    }
    return [];
  }

  function harvestCsvBlobs(doc, code) {
    const harvest = harvestApi();
    const parse = harvest.parseOfficialCsv;
    if (!parse) return [];
    const trapped = drainCsvTrap(doc, code);
    if (trapped.length) return trapped;
    const blobs = [];
    (doc.querySelectorAll("textarea, pre, [data-vibe-csv]") || []).forEach((el) => {
      const text = el.value || el.textContent || "";
      if (looksLikeCsv(text)) blobs.push(text);
    });
    for (const text of blobs) {
      const rows = parse(text, code) || [];
      if (rows.length) return rows;
    }
    return [];
  }

  function extractRows(doc, code) {
    const harvest = harvestApi();
    const csv = harvestCsvBlobs(doc, code);
    if (csv.length) return { source: "csv", rows: csv };
    const fn = harvest.harvestChannel || harvest.harvestVisibleTables;
    const rows = fn ? fn(doc, code) || [] : [];
    return { source: rows.length ? "dom" : "empty", rows };
  }

  function healCandidates(code) {
    const spec = stepsFor(code) || {};
    const sets = spec.waitSelectors || [];
    const primary = flattenSelectors(sets.slice(0, 1));
    const alternate = flattenSelectors(sets.slice(1));
    return {
      primary,
      alternateSelectors: alternate,
      statsUrls: spec.statsUrls || [],
      exportSelectors: flattenSelectors(spec.exportSelectors || []),
    };
  }

  function run(doc, code) {
    const spec = stepsFor(code);
    if (detectLoginWall(doc, code)) {
      return { ok: false, reason: "needs_challenge", rows: [], steps: spec };
    }
    const extracted = extractRows(doc, code);
    if (extracted.rows.length) {
      return { ok: true, reason: extracted.source, rows: extracted.rows, steps: spec };
    }
    const hit = trySelectors(doc, spec.waitSelectors || []);
    return {
      ok: false,
      reason: "selector_broke",
      rows: [],
      steps: spec,
      heal: {
        matchedSelector: hit ? hit.selector : null,
        ...healCandidates(code),
      },
    };
  }

  return {
    HOSTS,
    STEPS,
    stepsFor,
    trySelectors,
    healCandidates,
    detectChannel,
    detectChannelFromDoc,
    detectLoginWall,
    installCsvTrap,
    drainCsvTrap,
    isReady,
    readyState,
    findExportHrefs,
    clickFirst,
    clickByText,
    clickExport,
    scrollBottom,
    rowKey,
    mergeRows,
    extractRows,
    run,
  };
});
