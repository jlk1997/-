(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.VibeUi = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const CHANNEL_NAMES = {
    netease: "网易云音乐",
    qq_music: "QQ 音乐",
    kugou: "酷狗",
    kuwo: "酷我",
    qishui: "汽水",
    bilibili: "B 站",
    wechat_channels: "视频号",
    douyin_musician: "抖音音乐人",
    kuaishou_musician: "快手音乐人",
    spotify: "Spotify",
    apple_music: "Apple Music",
    youtube_music: "YouTube Music",
    tiktok_music: "TikTok",
    amazon_music: "Amazon Music",
    deezer: "Deezer",
    soundcloud: "SoundCloud",
    bandcamp: "Bandcamp",
  };

  function channelName(code) {
    return CHANNEL_NAMES[code] || code || "这家店";
  }

  function reasonLabel(reason) {
    const map = {
      csv: "官方 CSV",
      csv_href: "官方导出链接",
      csv_blob: "页面导出文件",
      csv_download: "下载的 CSV",
      official_csv: "导入的 CSV",
      dom: "页面表格",
      needs_challenge: "登录墙",
      selector_broke: "对账表没读到",
      timeout: "页面加载超时",
    };
    return map[reason] || reason || "";
  }

  function formatWhen(iso) {
    return String(iso || "").replace("T", " ").slice(0, 16);
  }

  function seatExpired(seat) {
    const health = (seat && (seat.farm_health || (seat.extra && seat.extra.farm_health))) || {};
    return Boolean(seat && (seat.status === "needs_challenge" || health.needs_challenge || health.session_expired));
  }

  function versionLess(a, b) {
    const pa = String(a || "")
      .split(".")
      .map((part) => Number(part) || 0);
    const pb = String(b || "")
      .split(".")
      .map((part) => Number(part) || 0);
    for (let i = 0; i < 3; i += 1) {
      if ((pa[i] || 0) < (pb[i] || 0)) return true;
      if ((pa[i] || 0) > (pb[i] || 0)) return false;
    }
    return false;
  }

  function tokenExpired(iso) {
    if (!iso) return false;
    const at = Date.parse(iso);
    return Number.isFinite(at) && at < Date.now();
  }

  function coach(state) {
    const seats = state.seats || [];
    const mine = seats.filter((seat) => seat.ownership === "user" || seat.runtime === "extension" || seat.user_id);
    const rows = mine.length ? mine : seats;
    const tabChannel = state.tabChannel || "";
    const progress = state.progress || {};
    const last = state.lastHarvest;
    if (progress.busy) {
      return {
        title: progress.title || "正在同步",
        hint: progress.hint || "请保持这个后台开着。",
        tone: "busy",
        action: null,
        channel: progress.channel || tabChannel,
      };
    }
    if (!state.token) {
      return {
        title: "先配对",
        hint: "回账户页点「发送到连接器」。",
        tone: "need",
        action: "pair",
      };
    }
    if (state.minExtensionVersion && versionLess(state.extensionVersion, state.minExtensionVersion)) {
      return {
        title: "连接器太旧了",
        hint: `加载 ${state.minExtensionVersion} 以上再配对。`,
        tone: "err",
        action: "pair",
      };
    }
    if (tokenExpired(state.tokenExpiresAt) || state.online === false) {
      return {
        title: "配对失效了",
        hint: "回创作者中心重新发送。",
        tone: "err",
        action: "pair",
      };
    }
    const expired = rows.filter(seatExpired);
    if (expired.length) {
      return {
        title: `${channelName(expired[0].channel_code)}要登录`,
        hint: "打开官方后台登录，再点同步。",
        tone: "need",
        action: "open",
        channel: expired[0].channel_code,
      };
    }
    if (!rows.length) {
      if (tabChannel) {
        return {
          title: `这是 ${channelName(tabChannel)}`,
          hint: "点同步。不填密码。",
          tone: "need",
          action: "authorize",
          channel: tabChannel,
        };
      }
      return {
        title: "打开已登录的店",
        hint: "先在官方页登录，再回来同步。",
        tone: "need",
        action: "open",
      };
    }
    if (last && (last.reason === "selector_broke" || last.ok === false) && !last.count) {
      return {
        title: `${channelName(last.channel)}对账表没读到`,
        hint: "打开收益页，或到「卡住了」导入官方 CSV。不会当成同步成功。",
        tone: "err",
        action: "open",
        channel: last.channel,
      };
    }
    if (last && last.ok && last.count) {
      return {
        title: `${channelName(last.channel)}已同步 ${last.count} 行`,
        hint: "播放用来估钱。入账另开。",
        tone: "ok",
        action: "sync",
        channel: last.channel,
      };
    }
    return {
      title: "已连上",
      hint: "要点同步才拉数。",
      tone: "ok",
      action: "sync",
    };
  }

  function actionLabel(action) {
    return overlayCopy()[action] || (
      {
        pair: "从剪贴板配对",
        authorize: "同步到比特音",
        open: "打开官方后台",
        harvest: "同步当前页",
        sync: "同步到比特音",
      }[action] || ""
    );
  }

  function isEnglish() {
    try {
      const lang = String((navigator && navigator.language) || "").toLowerCase();
      return lang.startsWith("en");
    } catch {
      return false;
    }
  }

  function overlayCopy() {
    if (isEnglish()) {
      return {
        brand: "BitTune",
        loggedIn: "Official dashboard. No password.",
        needPair: "Pair from the creator desk first.",
        streams: "Plays",
        tracks: "Tracks",
        geo: "Regions",
        audience: "Listeners",
        settleBox: "Book to wallet (needs agreement)",
        sync: "Sync to BitTune",
        syncSettle: "Sync and book",
        openHub: "See the ledger",
        openConnector: "Open connector",
        syncing: "Syncing…",
        needLicense: "Sign the agreement first.",
        last: "Synced {n} rows",
        needField: "Keep plays or tracks on.",
        syncFail: "Didn't sync. Stay on this page.",
        pair: "Pair from clipboard",
        authorize: "Sync to BitTune",
        open: "Open store",
        harvest: "Sync this page",
        aligned: "Linked · {p}. Sync when you tap.",
        notPaired: "Not paired",
        emptySeats: "No store yet. Log in, then tap Sync.",
        syncNow: "Sync",
        goLogin: "Log in",
        lastSyncTitle: "{name}",
        openPortal: "Open store",
        markLive: "This page is live",
        changeFields: "Choose what to sync",
        hideFields: "Hide range",
        lane: "Connect a store, then sync plays. Wallet stays off.",
      };
    }
    return {
      brand: "比特音",
      loggedIn: "官方后台。不同步密码。",
      needPair: "先回创作者中心配对。",
      streams: "播放",
      tracks: "歌曲",
      geo: "地区",
      audience: "听众",
      settleBox: "记进钱包（要先签协议）",
      sync: "同步到比特音",
      syncSettle: "同步并入账",
      openHub: "去看账",
      openConnector: "打开连接器",
      syncing: "同步中…",
      needLicense: "先签发行协议。",
      last: "同步了 {n} 行",
      needField: "至少留着播放或歌曲。",
      syncFail: "没同步上，留在这页再试。",
      pair: "从剪贴板配对",
      authorize: "同步到比特音",
      open: "打开店",
      harvest: "同步当前页",
      aligned: "已对齐 · {p}。要点同步才拉数。",
      notPaired: "还没配对",
      emptySeats: "还没连店。登录后台再点同步。",
      syncNow: "同步",
      goLogin: "去登录",
      lastSyncTitle: "{name}",
      openPortal: "打开店",
      markLive: "本页已上架",
      changeFields: "改范围",
      hideFields: "收起范围",
      lane: "连上店，再同步播放。入账另开。",
    };
  }

  function filterHarvestRows(rows, fields) {
    const list = Array.isArray(rows) ? rows : [];
    const f = fields || {};
    return list.map((row) => {
      const next = { ...row };
      if (f.streams === false) next.streams = 0;
      if (f.geo === false) {
        const raw = { ...(next.raw || {}) };
        delete raw.geo;
        delete raw.country;
        delete raw.region;
        next.raw = raw;
      }
      if (f.audience === false) {
        const raw = { ...(next.raw || {}) };
        delete raw.audience;
        delete raw.listeners;
        next.raw = raw;
      }
      if (f.tracks === false) {
        next.title = "redacted";
        next.isrc = "";
        next.external_track_id = "";
        next.work_id = "";
      }
      return next;
    });
  }

  return {
    CHANNEL_NAMES,
    channelName,
    reasonLabel,
    formatWhen,
    seatExpired,
    versionLess,
    tokenExpired,
    coach,
    actionLabel,
    overlayCopy,
    filterHarvestRows,
    isEnglish,
  };
});
