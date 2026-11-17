importScripts("harvest-core.js", "runner-core.js", "upload-core.js", "ui-shared.js");

const PRIORITY = [
  "netease",
  "qq_music",
  "qishui",
  "kugou",
  "kuwo",
  "bilibili",
  "douyin_musician",
  "wechat_channels",
  "spotify",
  "youtube_music",
];

function headers(settings) {
  const out = { "Content-Type": "application/json" };
  if (settings.token) {
    out["X-Connector-Token"] = settings.token;
    out.Authorization = `Bearer ${settings.token}`;
  }
  return out;
}

function apiUrl(settings, path) {
  return `${String(settings.apiBase || "").replace(/\/$/, "")}${path}`;
}

async function loadSettings() {
  return chrome.storage.local.get(["apiBase", "token", "channel", "period"]);
}

async function apiJson(settings, path, options = {}) {
  const res = await fetch(apiUrl(settings, path), {
    method: options.method || "GET",
    headers: headers(settings),
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText || "HTTP error");
  return body;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function notify(title, message) {
  if (!chrome.notifications) return;
  try {
    await chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title: title || "比特音连接器",
      message: String(message || ""),
    });
  } catch {
    /* icons missing in older unpacked copies */
  }
}

async function setBadge(text, color) {
  try {
    await chrome.action.setBadgeBackgroundColor({ color: color || "#b42318" });
    await chrome.action.setBadgeText({ text: text || "" });
  } catch {
    /* older chrome */
  }
}

function storeName(code) {
  return (self.VibeUi && self.VibeUi.channelName(code)) || code || "这家店";
}

const LIVE_H5_HOSTS = [
  "139.199.90.218",
  "superformersmusic.com",
  "www.superformersmusic.com",
  "localhost",
  "127.0.0.1",
];
const pendingReceipts = new Map();
const notedSubmits = new Set();

async function saveOpenSeatSession(settings, seat, tab) {
  if (!seat?.id || !tab?.url) return false;
  const cookies = await chrome.cookies.getAll({ url: tab.url }).catch(() => []);
  if (!cookies.length && !tab.id) return false;
  const storageState = await captureStorageState(tab.id, cookies);
  await apiJson(settings, `/seats/${seat.id}/session`, {
    method: "POST",
    body: { cookies, storage_state: storageState },
  }).catch(() => null);
  return true;
}

function versionLess(left, right) {
  const a = String(left || "")
    .split(".")
    .map((part) => parseInt(part, 10) || 0);
  const b = String(right || "")
    .split(".")
    .map((part) => parseInt(part, 10) || 0);
  for (let i = 0; i < 3; i += 1) {
    if ((a[i] || 0) < (b[i] || 0)) return true;
    if ((a[i] || 0) > (b[i] || 0)) return false;
  }
  return false;
}

function uploadUrlFor(job, playbook, channel) {
  const payload = (job && job.payload) || {};
  const guide = self.VibeUpload && self.VibeUpload.CHANNEL_UPLOAD_GUIDES && self.VibeUpload.CHANNEL_UPLOAD_GUIDES[channel];
  return payload.upload_url || (job && job.upload_url) || (guide && guide.url) || (playbook && playbook.upload_url) || "";
}

async function noteUserSubmitted(settings, deliveryId, channel, tabId) {
  if (!deliveryId || notedSubmits.has(deliveryId)) return false;
  notedSubmits.add(deliveryId);
  await apiJson(settings, `/distribution/assist/jobs/${deliveryId}/progress`, {
    method: "POST",
    body: { event: "submitted", message: "用户确认提交" },
  }).catch(() => null);
  watchStoreReceipt(settings, deliveryId, channel, tabId);
  await finishProgress(true, `${storeName(channel)}已提交`, "提交后我们记下歌曲页。", channel);
  await broadcastAppEvent("BITTUNE_DELIVERY", { deliveryId, channel, event: "submitted" });
  return true;
}

function originPattern(webBase) {
  try {
    const url = new URL(String(webBase || "").trim());
    if (!url.protocol || !url.host) return "";
    return `${url.protocol}//${url.host}/*`;
  } catch {
    return "";
  }
}

function isBittuneAppTab(url) {
  const raw = String(url || "");
  if (!raw) return false;
  if (LIVE_H5_HOSTS.some((host) => raw.includes(host))) return true;
  return /superformersmusic\.com|loveaibaby\.cn|bityin|bittune|packageCreator|pages\/creator/i.test(raw);
}

async function registerWebBaseBridge(webBase) {
  const matches = new Set([
    "http://139.199.90.218/*",
    "http://superformersmusic.com/*",
    "http://www.superformersmusic.com/*",
    "https://superformersmusic.com/*",
    "https://www.superformersmusic.com/*",
  ]);
  const extra = originPattern(webBase);
  if (extra) matches.add(extra);
  try {
    await chrome.scripting.unregisterContentScripts({ ids: ["bittune-h5-bridge"] }).catch(() => {});
    await chrome.scripting.registerContentScripts([
      {
        id: "bittune-h5-bridge",
        js: ["bridge.js"],
        matches: Array.from(matches),
        runAt: "document_idle",
        persistAcrossSessions: true,
      },
    ]);
  } catch {
    /* host not permitted yet */
  }
}

function kickAssistSoon() {
  chrome.alarms.create("vibe-assist-soon", { when: Date.now() + 5000 });
}

function looksLikeLiveStore(url, channel) {
  return Boolean(self.VibeUpload && self.VibeUpload.looksLikeStorePage(url, channel));
}

const STORE_OPTIONAL_ORIGINS = {
  netease: ["https://music.163.com/*"],
  qq_music: ["https://y.qq.com/*", "https://*.y.qq.com/*", "https://music.qq.com/*"],
  kugou: ["https://www.kugou.com/*", "https://*.kugou.com/*"],
  kuwo: ["https://www.kuwo.cn/*", "https://*.kuwo.cn/*"],
  qishui: ["https://music.douyin.com/*", "https://musician.douyin.com/*", "https://*.douyin.com/*"],
  bilibili: ["https://www.bilibili.com/*", "https://*.bilibili.com/*", "https://member.bilibili.com/*"],
  douyin_musician: ["https://creator.douyin.com/*", "https://*.douyin.com/*", "https://www.douyin.com/*"],
  kuaishou_musician: ["https://cp.kuaishou.com/*", "https://*.kuaishou.com/*"],
  wechat_channels: ["https://channels.weixin.qq.com/*"],
  spotify: ["https://artists.spotify.com/*", "https://open.spotify.com/*"],
  apple_music: ["https://artists.apple.com/*", "https://music.apple.com/*"],
  youtube_music: ["https://studio.youtube.com/*", "https://www.youtube.com/*", "https://music.youtube.com/*"],
  tiktok_music: ["https://www.tiktok.com/*", "https://*.tiktok.com/*"],
  amazon_music: ["https://artists.amazon.com/*", "https://music.amazon.com/*"],
  deezer: ["https://www.deezer.com/*", "https://*.deezer.com/*"],
  soundcloud: ["https://soundcloud.com/*", "https://*.soundcloud.com/*"],
  bandcamp: ["https://bandcamp.com/*", "https://*.bandcamp.com/*"],
};

async function requestStorePermission(channel) {
  const origins = STORE_OPTIONAL_ORIGINS[channel];
  if (!origins || !chrome.permissions || !chrome.permissions.request) {
    return { ok: true, newlyGranted: false };
  }
  try {
    const already = await chrome.permissions.contains({ origins }).catch(() => false);
    if (already) return { ok: true, newlyGranted: false };
    const granted = await chrome.permissions.request({ origins });
    return { ok: Boolean(granted), newlyGranted: Boolean(granted) };
  } catch {
    return { ok: false, newlyGranted: false };
  }
}

async function injectStoreRuntime(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["runner-core.js"] }).catch(() => null);
  await chrome.scripting.executeScript({ target: { tabId }, files: ["upload-core.js"] }).catch(() => null);
  await chrome.scripting.executeScript({ target: { tabId }, files: ["overlay.js"] }).catch(() => null);
}

async function tabHasOverlay(tabId) {
  const probed = await chrome.scripting
    .executeScript({
      target: { tabId },
      func: () => document.documentElement.dataset.bittuneOverlay === "1" || Boolean(window.__bittuneOverlay),
    })
    .catch(() => null);
  return Boolean(probed && probed[0] && probed[0].result);
}

async function ensureReadyStoreTab(url, channel, steal = true) {
  const perm = await requestStorePermission(channel);
  if (!perm.ok) return { tab: null, granted: false, newlyGranted: false };
  const tab = await ensureTab(url, steal, channel);
  if (!tab?.id) return { tab: null, granted: true, newlyGranted: perm.newlyGranted };
  if (perm.newlyGranted) {
    await chrome.tabs.reload(tab.id).catch(() => null);
  }
  await waitTabComplete(tab.id);
  await injectStoreRuntime(tab.id);
  if (!(await tabHasOverlay(tab.id))) {
    await chrome.tabs.reload(tab.id).catch(() => null);
    await waitTabComplete(tab.id);
    await injectStoreRuntime(tab.id);
  }
  return { tab, granted: true, newlyGranted: perm.newlyGranted };
}

async function noteAssistProgress(settings, deliveryId, event, message) {
  if (!deliveryId) return;
  await apiJson(settings, `/distribution/assist/jobs/${deliveryId}/progress`, {
    method: "POST",
    body: { event, message },
  }).catch(() => null);
  await broadcastAppEvent("BITTUNE_DELIVERY", { deliveryId, event, message });
}

async function captureStorageState(tabId, cookies) {
  let web = { origin: "", localStorage: [] };
  if (tabId) {
    const injected = await chrome.scripting
      .executeScript({
        target: { tabId },
        func: () => {
          const dump = (store) => {
            const out = [];
            try {
              for (let i = 0; i < store.length; i += 1) {
                const name = store.key(i);
                out.push({ name, value: store.getItem(name) });
              }
            } catch {
              /* ignore */
            }
            return out;
          };
          return {
            origin: location.origin,
            localStorage: dump(localStorage),
            sessionStorage: dump(sessionStorage),
          };
        },
      })
      .catch(() => null);
    web = (injected && injected[0] && injected[0].result) || web;
  }
  return {
    cookies: cookies || [],
    origins: web.origin
      ? [
          {
            origin: web.origin,
            localStorage: web.localStorage || [],
            sessionStorage: web.sessionStorage || [],
          },
        ]
      : [],
  };
}

async function fetchAssistAsset(settings, path, fallbackName, fallbackType) {
  try {
    const res = await fetch(apiUrl(settings, path), { headers: headers(settings) });
    if (!res.ok) return null;
    const buf = await res.arrayBuffer();
    const fromHeader = String(res.headers.get("content-disposition") || "").match(/filename="?([^"]+)/);
    return {
      bytes: new Uint8Array(buf),
      name: (fromHeader && fromHeader[1]) || fallbackName,
      type: res.headers.get("content-type") || fallbackType,
    };
  } catch {
    return null;
  }
}

async function plantFileOnTab(tabId, key, asset) {
  if (!asset || !asset.bytes || !asset.bytes.length) return false;
  const primed = await chrome.scripting
    .executeScript({
      target: { tabId },
      func: (k) => {
        globalThis.__bittuneFiles = globalThis.__bittuneFiles || {};
        globalThis.__bittuneFiles[k] = [];
      },
      args: [key],
    })
    .catch(() => null);
  if (!primed) return false;
  const chunk = 384 * 1024;
  for (let i = 0; i < asset.bytes.length; i += chunk) {
    const part = Array.from(asset.bytes.subarray(i, Math.min(i + chunk, asset.bytes.length)));
    const wrote = await chrome.scripting
      .executeScript({
        target: { tabId },
        func: (k, bytes) => {
          (globalThis.__bittuneFiles[k] || []).push(Uint8Array.from(bytes));
        },
        args: [key, part],
      })
      .catch(() => null);
    if (!wrote) return false;
  }
  await chrome.scripting.executeScript({
    target: { tabId },
    func: (k, name, type) => {
      const parts = globalThis.__bittuneFiles[k] || [];
      globalThis.__bittuneFiles[k] = new File(parts, name, { type });
    },
    args: [key, asset.name, asset.type],
  });
  return true;
}

async function fillAndAttachOnTab(tabId, settings, job, channel) {
  const deliveryId = job.payload && job.payload.delivery_id;
  const autoSubmit = Boolean(job.seat && job.seat.scopes && job.seat.scopes.auto_submit);
  const level = String((job.payload && job.payload.automation_level) || "");
  const canPlant = level === "connector_full";
  await chrome.scripting.executeScript({ target: { tabId }, files: ["runner-core.js"] }).catch(() => null);
  await chrome.scripting.executeScript({ target: { tabId }, files: ["upload-core.js"] }).catch(() => null);
  const wall = await chrome.scripting
    .executeScript({
      target: { tabId },
      func: (code) => (window.VibeRunner && window.VibeRunner.readyState(document, code)) || { ready: true },
      args: [channel],
    })
    .catch(() => null);
  const ready = (wall && wall[0] && wall[0].result) || {};
  if (ready.reason === "needs_challenge") {
    return { ok: false, attached: false, submitted: false, filled: [], needs_challenge: true, reason: "needs_challenge" };
  }
  let plantedMaster = false;
  if (deliveryId && canPlant) {
    const master = await fetchAssistAsset(settings, `/distribution/assist/jobs/${deliveryId}/master`, "master.wav", "audio/wav");
    plantedMaster = await plantFileOnTab(tabId, "master", master);
    const evidence = await fetchAssistAsset(
      settings,
      `/distribution/assist/jobs/${deliveryId}/originality-file`,
      "originality.zip",
      "application/zip",
    );
    await plantFileOnTab(tabId, "evidence", evidence);
    if (plantedMaster) {
      await noteAssistProgress(settings, deliveryId, "planted", "母带已写入店页，开始填表。");
    }
  } else if (deliveryId && !canPlant) {
    await noteAssistProgress(settings, deliveryId, "assist_skip_attach", "这家店只填表，母带请你自己挂。");
  }
  const injected = await chrome.scripting
    .executeScript({
      target: { tabId },
      func: (cfg) => {
        const files = globalThis.__bittuneFiles || {};
        const masterFile = files.master instanceof File ? files.master : null;
        const evidenceFile = files.evidence instanceof File ? files.evidence : null;
        const payload = {
          ...(cfg.payload || {}),
          channel: cfg.channel,
          masterFile,
          evidenceFile,
          auto_submit: cfg.autoSubmit,
        };
        const filled =
          (window.VibeUpload && window.VibeUpload.fillAuthorizedForm(document, payload)) || { ok: false, filled: [] };
        if (!cfg.canPlant && !document.getElementById("bittune-assist-hint")) {
          const note = document.createElement("div");
          note.id = "bittune-assist-hint";
          note.textContent = "比特音只填了表。请你自己把母带拖进上传框。";
          note.style.cssText =
            "position:fixed;right:16px;bottom:72px;z-index:2147483646;max-width:280px;padding:10px 12px;border-radius:8px;background:#1b1b1b;color:#f7f4ee;font:13px sans-serif;";
          document.body.appendChild(note);
        }
        if (!cfg.autoSubmit && (filled.attached || (filled.filled && filled.filled.length)) && !document.getElementById("bittune-confirm-submit")) {
          const btn = document.createElement("button");
          btn.id = "bittune-confirm-submit";
          btn.textContent = "确认提交到这家店";
          btn.setAttribute("type", "button");
          btn.style.cssText =
            "position:fixed;right:16px;bottom:16px;z-index:2147483647;padding:10px 14px;border:0;border-radius:8px;background:#5b3cc4;color:#fff;font:14px sans-serif;";
          btn.onclick = () => {
            const once = window.VibeUpload && window.VibeUpload.clickSubmitOnce(document, { channel: cfg.channel });
            btn.disabled = true;
            btn.dataset.clicked = once && once.clicked ? "1" : "0";
            document.dispatchEvent(
              new CustomEvent("bittune-page-event", {
                detail: {
                  kind: "submitted",
                  channel: cfg.channel,
                  deliveryId: cfg.deliveryId,
                  clicked: Boolean(once && once.clicked),
                },
              }),
            );
          };
          document.body.appendChild(btn);
        }
        return { ...filled, planted: Boolean(cfg.plantedMaster && masterFile) };
      },
      args: [
        {
          payload: job.payload || {},
          channel,
          autoSubmit,
          deliveryId,
          plantedMaster,
          canPlant,
        },
      ],
    })
    .catch(() => null);
  const result = (injected && injected[0] && injected[0].result) || { ok: false, filled: [] };
  if (!autoSubmit && deliveryId && (result.attached || (result.filled && result.filled.length))) {
    watchConfirmSubmit(tabId, settings, deliveryId, channel);
  }
  return result;
}

function watchConfirmSubmit(tabId, settings, deliveryId, channel) {
  const tick = async () => {
    const probed = await chrome.scripting
      .executeScript({
        target: { tabId },
        func: () => {
          const btn = document.getElementById("bittune-confirm-submit");
          return Boolean(btn && btn.dataset.clicked === "1");
        },
      })
      .catch(() => null);
    if (!(probed && probed[0] && probed[0].result)) return;
    await noteUserSubmitted(settings, deliveryId, channel, tabId);
  };
  [4000, 12000, 30000, 60000].forEach((ms) => setTimeout(() => void tick(), ms));
}

async function reportStoreReceipt(settings, deliveryId, url, channel) {
  if (!deliveryId || !url) return false;
  await apiJson(settings, `/distribution/assist/jobs/${deliveryId}/complete`, {
    method: "POST",
    body: { store_url: url },
  });
  pendingReceipts.delete(deliveryId);
  await finishProgress(true, `${storeName(channel)}已记下歌曲页`, "回创作者中心看配送。不用回贴。", channel);
  await broadcastAppEvent("BITTUNE_DELIVERY", { deliveryId, channel, event: "receipt" });
  return true;
}

function watchStoreReceipt(settings, deliveryId, channel, tabId) {
  if (!deliveryId) return;
  pendingReceipts.set(deliveryId, { channel, tabId, settings });
  const tryUrl = async (url) => {
    if (!looksLikeLiveStore(url, channel)) return false;
    try {
      return await reportStoreReceipt(settings, deliveryId, url, channel);
    } catch {
      return false;
    }
  };
  const tick = async () => {
    const rec = pendingReceipts.get(deliveryId);
    if (!rec) return;
    let tab = null;
    if (rec.tabId) tab = await chrome.tabs.get(rec.tabId).catch(() => null);
    if (!tab && channel) {
      const tabs = await chrome.tabs.query({}).catch(() => []);
      tab = (tabs || []).find((row) => looksLikeLiveStore(row.url, channel)) || null;
    }
    if (tab && (await tryUrl(tab.url))) return;
  };
  [8000, 20000, 45000, 90000].forEach((ms) => setTimeout(() => void tick(), ms));
}

async function setProgress(partial) {
  const progress = {
    busy: false,
    title: "",
    hint: "",
    channel: "",
    ok: null,
    at: new Date().toISOString(),
    ...partial,
  };
  await chrome.storage.local.set({ harvestProgress: progress });
  try {
    await chrome.action.setTitle({ title: progress.busy ? progress.title || "比特音连接器 · 同步中" : "比特音连接器" });
  } catch {
    /* optional */
  }
  if (progress.busy) {
    await setBadge("…", "#5b3cc4");
    try {
      chrome.alarms.create("vibe-keepalive", { when: Date.now() + 20000 });
    } catch {
      /* optional */
    }
  }
}

async function pushLog(level, text) {
  const saved = await chrome.storage.local.get(["activityLog"]);
  const item = { at: new Date().toISOString(), level: level || "info", text: String(text || "") };
  await chrome.storage.local.set({ activityLog: [item, ...(saved.activityLog || [])].slice(0, 40) });
}

async function finishProgress(ok, title, hint, channel) {
  await setProgress({ busy: false, title, hint, channel, ok });
  await pushLog(ok ? "ok" : "err", hint ? `${title} · ${hint}` : title);
  await notify(title, hint);
  if (ok) {
    await setBadge("OK", "#0a7a32");
    setTimeout(() => refreshBadge().catch(() => {}), 5000);
  }
}

async function refreshBadge() {
  const settings = await loadSettings();
  if (!settings.token) {
    await setBadge("", "#888888");
    return;
  }
  try {
    const body = await apiJson(settings, "/seats");
    const sick = (body.seats || []).filter((seat) => {
      const health = seat.farm_health || (seat.extra && seat.extra.farm_health) || {};
      return seat.status === "needs_challenge" || health.needs_challenge || health.session_expired;
    });
    if (sick.length) {
      await setBadge(String(Math.min(sick.length, 9)), "#b42318");
      return;
    }
    const queue = await apiJson(settings, "/seats/queue").catch(() => null);
    const uploading = ((queue && queue.jobs) || []).filter((job) => job.kind === "upload");
    if (uploading.length) {
      await setBadge(String(Math.min(uploading.length, 9)), "#1d4ed8");
      return;
    }
    await setBadge("", "#0a7a32");
  } catch {
    await setBadge("?", "#b42318");
  }
}

async function rememberHarvest(entry) {
  const rows = entry.rows || [];
  const lastHarvest = {
    at: new Date().toISOString(),
    channel: entry.channel,
    reason: entry.reason,
    ok: Boolean(rows.length),
    count: rows.length,
    matched: entry.matched,
    unclaimed: entry.unclaimed,
    rows: rows.slice(0, 8).map((row) => ({
      title: row.title,
      streams: row.streams,
      revenue_minor: row.revenue_minor,
      channel_code: row.channel_code || entry.channel,
    })),
  };
  await chrome.storage.local.set({ lastHarvest });
  await broadcastAppEvent("BITTUNE_SYNC", { lastHarvest });
  if (rows.length) {
    const src = (self.VibeUi && self.VibeUi.reasonLabel(entry.reason)) || entry.reason || "";
    await finishProgress(
      true,
      `${storeName(entry.channel)}已收割 ${rows.length} 行`,
      `${src}${entry.matched != null ? ` · 匹配 ${entry.matched}` : ""}${entry.unclaimed ? ` · 待认领 ${entry.unclaimed}` : ""}。Chrome 开着会自动再跑。`,
      entry.channel,
    );
  }
}

function extensionVersion() {
  try {
    return chrome.runtime.getManifest().version;
  } catch {
    return "0.8.1";
  }
}

function mergeLastHarvest(server, local) {
  if (!server) return local || null;
  const rows = (local && local.channel === server.channel && local.rows) || [];
  return {
    at: server.at || (local && local.at),
    channel: server.channel || (local && local.channel),
    reason: server.reason || server.source || (local && local.reason),
    ok: server.ok !== false,
    count: server.count != null ? server.count : (local && local.count) || 0,
    matched: server.matched != null ? server.matched : local && local.matched,
    unclaimed: server.unclaimed != null ? server.unclaimed : local && local.unclaimed,
    period_key: server.period_key || (local && local.period_key),
    source: "server",
    rows,
  };
}

async function applyServerSync(sync, announce) {
  if (!sync || typeof sync !== "object") return sync;
  const saved = await chrome.storage.local.get(["lastHarvest"]);
  const patch = {
    lastSyncAt: sync.at || new Date().toISOString(),
    syncOk: Boolean(sync.ok !== false && sync.online !== false),
  };
  if (sync.period_key) patch.period = sync.period_key;
  if (sync.token_expires_at) patch.tokenExpiresAt = sync.token_expires_at;
  if (sync.min_extension_version) patch.minExtensionVersion = sync.min_extension_version;
  if (sync.role) patch.role = sync.role;
  if (Array.isArray(sync.seats)) patch.serverSeats = sync.seats;
  if (typeof sync.has_distribution_license === "boolean") patch.hasDistributionLicense = sync.has_distribution_license;
  if (sync.last_harvest) patch.lastHarvest = mergeLastHarvest(sync.last_harvest, saved.lastHarvest);
  if (sync.last_delivery) patch.lastDelivery = sync.last_delivery;
  if (typeof sync.queue_count === "number") patch.queueCount = sync.queue_count;
  if (sync.reason === "stale_extension") patch.upgradeRequired = true;
  else if (sync.ok !== false) patch.upgradeRequired = false;
  if (sync.reason === "no_token") patch.syncOk = false;
  await chrome.storage.local.set(patch);
  if (announce) {
    await broadcastAppEvent("BITTUNE_SYNC", { lastHarvest: patch.lastHarvest || sync.last_harvest, sync });
  }
  return sync;
}

async function heartbeat(settings) {
  if (!settings.token) return { ok: false, online: false, reason: "no_token" };
  const saved = await chrome.storage.local.get(["lastHarvest", "channel", "period", "harvestProgress"]);
  const progress = saved.harvestProgress || {};
  const sync = await apiJson(settings, "/distribution/assist/heartbeat", {
    method: "POST",
    body: {
      extension_version: extensionVersion(),
      channel: saved.channel || settings.channel,
      period_key: saved.period || settings.period,
      last_harvest: saved.lastHarvest
        ? {
            channel: saved.lastHarvest.channel,
            at: saved.lastHarvest.at,
            count: saved.lastHarvest.count,
            matched: saved.lastHarvest.matched,
          }
        : undefined,
      last_progress: progress.title || progress.channel
        ? {
            title: progress.title,
            hint: progress.hint,
            channel: progress.channel,
            busy: Boolean(progress.busy),
            at: progress.at,
          }
        : undefined,
    },
  });
  await applyServerSync(sync);
  await refreshConnectorConfig(settings);
  return sync;
}

async function refreshConnectorConfig(settings) {
  try {
    const cfg = await apiJson(settings, "/seats/connector-config");
    if (!cfg || typeof cfg !== "object") return;
    await chrome.storage.local.set({
      connectorPortals: cfg.portals || {},
      connectorHosts: cfg.hosts || {},
      connectorWebBase: cfg.web_base || "",
    });
  } catch {
    /* keep last cached portals */
  }
}

async function injectJob(tabId, job) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["playbooks.js"],
  });
  if (job?.channel_code) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: [`playbooks/${job.channel_code}.js`],
      });
    } catch {
      /* bundled playbooks.js already has a fallback */
    }
  }
  await chrome.scripting.executeScript({
    target: { tabId },
    func: (payload) => {
      window.__vibeAssistJob = payload;
    },
    args: [job],
  });
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    files: ["assist.js"],
  });
  return result || {};
}

async function completeJob(settings, job, url) {
  return apiJson(settings, `/distribution/assist/jobs/${job.delivery_id}/complete`, {
    method: "POST",
    body: { store_url: url },
  });
}

function hostnameOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

function hostMatches(tabHost, listed) {
  if (!tabHost) return false;
  return (listed || []).some((raw) => {
    const host = String(raw || "")
      .replace(/^www\./, "")
      .toLowerCase();
    return host && (tabHost === host || tabHost.endsWith(`.${host}`) || host.endsWith(`.${tabHost}`));
  });
}

function jobMatchesTab(job, tabUrl) {
  const tabHost = hostnameOf(tabUrl);
  if (hostMatches(tabHost, job.hosts || [])) return true;
  const uploadHost = hostnameOf(job.upload_url);
  return Boolean(uploadHost && (tabHost === uploadHost || tabHost.endsWith(`.${uploadHost}`)));
}

async function pollJobs() {
  const settings = await loadSettings();
  if (!settings.token || !settings.apiBase) return { ok: false, reason: "no_settings" };
  await heartbeat(settings);
  const saved = await chrome.storage.local.get(["serverSeats", "role"]);
  const { jobs } = await apiJson(settings, "/distribution/assist/jobs");
  const pending = (jobs || [])
    .filter((job) => !job.store_url && ["session_wait", "session_running", "ops_queue", "awaiting_manual"].includes(job.status))
    .filter((job) => seatAllowsUpload(job.channel_code, saved.serverSeats, saved.role))
    .sort((a, b) => {
      const score = (Number(b.priority_score) || 0) - (Number(a.priority_score) || 0);
      if (score) return score;
      const rank = (code) => {
        const idx = PRIORITY.indexOf(code);
        return idx === -1 ? 99 : idx;
      };
      return rank(a.channel_code) - rank(b.channel_code);
    });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id && tab.url) {
    const match = pending.find((job) => jobMatchesTab(job, tab.url));
    if (match && looksLikeLiveStore(tab.url, match.channel_code)) {
      await completeJob(settings, match, tab.url);
      return { ok: true, completed: match.delivery_id, url: tab.url, readonly: true };
    }
  }
  return { ok: true, pending: pending.length, readonly: true };
}

function seatAllowsUpload(channel, seats, role) {
  if (role === "ops") return true;
  const list = Array.isArray(seats) ? seats : [];
  const mine = list.find((row) => row.channel_code === channel && row.ownership === "user");
  return Boolean(mine && mine.scopes && mine.scopes.upload);
}

async function injectHarvestRuntime(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["harvest-core.js"] });
  await chrome.scripting.executeScript({ target: { tabId }, files: ["runner-core.js"] });
  await chrome.scripting
    .executeScript({
      target: { tabId },
      func: () => {
        if (window.VibeRunner && window.VibeRunner.installCsvTrap) window.VibeRunner.installCsvTrap(document);
      },
    })
    .catch(() => null);
}

async function detectTabChannel(tabId, fallback) {
  const injected = await chrome.scripting
    .executeScript({
      target: { tabId },
      func: () =>
        (window.VibeRunner &&
          ((window.VibeRunner.detectChannelFromDoc && window.VibeRunner.detectChannelFromDoc(document, location.href)) ||
            window.VibeRunner.detectChannel(location.href))) ||
        "",
    })
    .catch(() => null);
  return (injected && injected[0] && injected[0].result) || fallback || "";
}

async function waitTabComplete(tabId, timeoutMs = 20000) {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (tab?.status === "complete") return tab;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUp);
      resolve(null);
    }, timeoutMs);
    function onUp(id, info, updated) {
      if (id !== tabId || info.status !== "complete") return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUp);
      resolve(updated || null);
    }
    chrome.tabs.onUpdated.addListener(onUp);
  });
}

async function waitForTabReady(tabId, channel, timeoutMs = 15000) {
  await injectHarvestRuntime(tabId);
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const injected = await chrome.scripting
      .executeScript({
        target: { tabId },
        func: (code) => {
          const runner = window.VibeRunner;
          if (!runner) return { ready: false, reason: "no_runner" };
          return runner.readyState(document, code);
        },
        args: [channel],
      })
      .catch(() => null);
    const result = (injected && injected[0] && injected[0].result) || {};
    if (result.reason === "needs_challenge") return result;
    if (result.ready) return result;
    await sleep(400);
  }
  return { ready: false, reason: "timeout" };
}

async function fetchCsvInPage(tabId, channel) {
  const injected = await chrome.scripting
    .executeScript({
      target: { tabId },
      func: async (code) => {
        const runner = window.VibeRunner;
        const harvest = window.VibeHarvest;
        if (!runner || !harvest) return { rows: [], clicked: "" };
        const hrefs = runner.findExportHrefs(document, code) || [];
        for (const href of hrefs) {
          try {
            const text = await fetch(href, { credentials: "include" }).then((res) => res.text());
            const rows = harvest.parseOfficialCsv(text, code) || [];
            if (rows.length) return { rows, source: "csv_href", href };
          } catch {
            /* keep looking */
          }
        }
        const clicked = runner.clickExport(document, code);
        const trapped = (runner.drainCsvTrap && runner.drainCsvTrap(document, code)) || [];
        if (trapped.length) return { rows: trapped, source: "csv_blob", clicked, hrefs };
        return { rows: [], clicked, hrefs };
      },
      args: [channel],
    })
    .catch(() => null);
  return (injected && injected[0] && injected[0].result) || { rows: [], clicked: "" };
}

async function waitForCsvDownload(timeoutMs = 8000) {
  if (!chrome.downloads) return null;
  const before = await chrome.downloads.search({ orderBy: ["-startTime"], limit: 8 }).catch(() => []);
  const beforeIds = new Set((before || []).map((item) => item.id));
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const items = await chrome.downloads.search({ orderBy: ["-startTime"], limit: 12 }).catch(() => []);
    const hit = (items || []).find((item) => {
      if (beforeIds.has(item.id)) return false;
      return /csv|spreadsheet|excel/i.test(`${item.filename || ""} ${item.mime || ""} ${item.url || ""}`);
    });
    if (hit) {
      if (hit.state === "in_progress") {
        await sleep(400);
        continue;
      }
      return hit;
    }
    await sleep(400);
  }
  return null;
}

async function rowsFromDownload(download, channel) {
  const url = download && download.url;
  if (!url || !/^https?:/i.test(url)) return [];
  try {
    const text = await fetch(url, { credentials: "include" }).then((res) => res.text());
    return (self.VibeHarvest && self.VibeHarvest.parseOfficialCsv(text, channel)) || [];
  } catch {
    return [];
  }
}

function mergeHarvest(existing, incoming) {
  if (self.VibeRunner && self.VibeRunner.mergeRows) return self.VibeRunner.mergeRows(existing, incoming);
  return (existing || []).concat(incoming || []);
}

async function harvestVisible(tabId, channel) {
  const injected = await chrome.scripting
    .executeScript({
      target: { tabId },
      func: (code) => {
        const runner = window.VibeRunner;
        if (!runner) return { ok: false, reason: "no_runner", rows: [] };
        runner.scrollBottom(document);
        return runner.run(document, code);
      },
      args: [channel],
    })
    .catch(() => null);
  return (injected && injected[0] && injected[0].result) || { ok: false, rows: [] };
}

async function paginateHarvest(tabId, channel, seed) {
  let rows = seed || [];
  for (let i = 0; i < 8; i += 1) {
    const injected = await chrome.scripting
      .executeScript({
        target: { tabId },
        func: (code) => {
          const runner = window.VibeRunner;
          if (!runner) return { rows: [], clicked: "" };
          const clicked = runner.clickFirst(document, (runner.stepsFor(code) || {}).nextPageSelectors || []);
          runner.scrollBottom(document);
          const result = runner.run(document, code);
          return { ...result, clicked };
        },
        args: [channel],
      })
      .catch(() => null);
    const page = (injected && injected[0] && injected[0].result) || { rows: [] };
    if (page.reason === "needs_challenge") return { ...page, rows };
    const next = mergeHarvest(rows, page.rows || []);
    const grew = next.length > rows.length;
    rows = next;
    if (!page.clicked || !grew) break;
    await sleep(700);
  }
  return { ok: Boolean(rows.length), reason: rows.length ? "dom" : "selector_broke", rows };
}

async function runTabHarvest(tabId, channel) {
  await setProgress({ busy: true, channel, title: `正在同步${storeName(channel)}`, hint: "等对账表出现，优先读官方导出" });
  await pushLog("info", `开始同步 ${storeName(channel)}`);
  await injectHarvestRuntime(tabId);
  const ready = await waitForTabReady(tabId, channel, 15000);
  if (ready.reason === "needs_challenge") {
    return { ok: false, reason: "needs_challenge", rows: [] };
  }
  await setProgress({
    busy: true,
    channel,
    title: `正在读${storeName(channel)}`,
    hint: ready.ready ? "已看到对账表，先找官方导出" : "页面还在加载，继续等表格",
  });
  const csvFirst = await fetchCsvInPage(tabId, channel);
  if ((csvFirst.rows || []).length) {
    return { ok: true, reason: csvFirst.source || "csv", rows: csvFirst.rows };
  }
  if (csvFirst.clicked) {
    await sleep(900);
    const downloaded = await waitForCsvDownload(8000);
    const fromDl = await rowsFromDownload(downloaded, channel);
    if (fromDl.length) return { ok: true, reason: "csv_download", rows: fromDl };
  }
  const visible = await harvestVisible(tabId, channel);
  if (visible.reason === "needs_challenge") return visible;
  const paged = await paginateHarvest(tabId, channel, visible.rows || []);
  if ((paged.rows || []).length) return paged;
  const extracted = await chrome.scripting
    .executeScript({
      target: { tabId },
      files: ["extract.js"],
    })
    .catch(() => null);
  const rows = extracted && extracted[0] && Array.isArray(extracted[0].result) ? extracted[0].result : [];
  return { ok: Boolean(rows.length), reason: rows.length ? "dom" : "selector_broke", rows };
}

async function extractTabRows(tabId) {
  const settings = await loadSettings();
  const result = await runTabHarvest(tabId, settings.channel || "netease");
  return result.rows || [];
}

function normalizeRows(settings, rows) {
  return (rows || []).map((row) => ({
    channel_code: row.channel_code || settings.channel,
    period_key: row.period_key || settings.period,
    external_track_id: row.external_track_id,
    work_id: row.work_id,
    title: row.title,
    isrc: row.isrc,
    streams: Number(row.streams || 0),
    revenue_minor: Number(row.revenue_minor || 0),
    currency: row.currency || "CNY",
    confidence: Number(row.confidence || 0.4),
    raw: row.raw || row,
  }));
}

async function resolveSeatId(settings, channel) {
  const body = await apiJson(settings, "/seats").catch(() => ({ seats: [] }));
  const seats = body.seats || [];
  const mine = seats.filter(
    (seat) =>
      seat.channel_code === channel &&
      (seat.ownership === "user" || seat.runtime === "extension" || Boolean(seat.user_id)),
  );
  const hit = mine.find((seat) => seat.status === "live") || mine[0];
  return (hit && hit.id) || "";
}

async function postSync(settings, rows, seatId) {
  const channel = settings.channel;
  const resolved = seatId || (await resolveSeatId(settings, channel));
  const payload = {
    seat_id: resolved || undefined,
    channel_code: channel,
    period_key: settings.period,
    extension_version: extensionVersion(),
    rows: normalizeRows(settings, rows),
  };
  const body = await apiJson(settings, "/seats/sync", { method: "POST", body: payload });
  if (body && body.sync) await applyServerSync(body.sync, true);
  else await broadcastAppEvent("BITTUNE_SYNC", { lastHarvest: body && body.last_harvest, sync: body });
  return body;
}

async function patchScopes(settings, seatId, scopes) {
  if (!seatId) return null;
  return apiJson(settings, `/seats/${seatId}/scopes`, { method: "PATCH", body: scopes });
}

async function postHarvest(settings, rows, seatId) {
  const channel = settings.channel;
  const resolved = seatId || (await resolveSeatId(settings, channel));
  const payload = {
    seat_id: resolved || undefined,
    channel_code: channel,
    period_key: settings.period,
    extension_version: extensionVersion(),
    rows: normalizeRows(settings, rows),
  };
  const body = await apiJson(settings, "/seats/harvest", { method: "POST", body: payload });
  if (body && body.sync) await applyServerSync(body.sync, true);
  else await broadcastAppEvent("BITTUNE_SYNC", { lastHarvest: body && body.last_harvest, sync: body });
  return body;
}

async function authorizeSeat(settings, tabUrl) {
  let channel = settings.channel;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) {
    await injectHarvestRuntime(tab.id).catch(() => null);
    channel = (await detectTabChannel(tab.id, channel)) || channel;
  }
  await setProgress({ busy: true, channel, title: `正在连接${storeName(channel)}`, hint: "保存已登录会话。同步需你再点一次。" });
  await pushLog("info", `连接 ${storeName(channel)}`);
  await requestStorePermission(channel);
  const connected = await apiJson(settings, "/seats/connect", {
    method: "POST",
    body: { channel_code: channel },
  });
  const cookies = tabUrl ? await chrome.cookies.getAll({ url: tabUrl }) : [];
  const storageState = await captureStorageState(tab && tab.id, cookies);
  const seat = await apiJson(settings, `/seats/${connected.id}/session`, {
    method: "POST",
    body: { cookies, storage_state: storageState },
  });
  try {
    chrome.alarms.create("vibe-assist-soon", { when: Date.now() + 400 });
  } catch {
    /* alarm optional */
  }
  return { ok: true, seat };
}

async function ensureTab(url, steal = true, channel) {
  const code = channel || (self.VibeRunner && self.VibeRunner.detectChannel(url)) || "";
  if (code) await requestStorePermission(code);
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!url) return active;
  const tabs = await chrome.tabs.query({});
  const hit = tabs.find((tab) => tab.url && (tab.url === url || tab.url.startsWith(url.split("?")[0])));
  if (hit) {
    if (steal) await chrome.tabs.update(hit.id, { active: true });
    return hit;
  }
  return chrome.tabs.create({ url, active: Boolean(steal) });
}

function statsUrlsFor(channel) {
  const spec = self.VibeRunner && self.VibeRunner.stepsFor(channel);
  return (spec && spec.statsUrls) || [];
}

async function preferredPortal(channel) {
  const saved = await chrome.storage.local.get(["connectorPortals"]);
  const fromServer = saved.connectorPortals && saved.connectorPortals[channel];
  if (fromServer) return fromServer;
  return statsUrlsFor(channel)[0] || "";
}

async function openStatsTab(channel) {
  const perm = await requestStorePermission(channel);
  const url = await preferredPortal(channel);
  if (!url) throw new Error("没有对账页地址");
  const tab = await ensureTab(url, true, channel);
  if (tab?.id) {
    if (perm.newlyGranted) await chrome.tabs.reload(tab.id).catch(() => null);
    await waitTabComplete(tab.id);
    await injectHarvestRuntime(tab.id).catch(() => null);
  }
  return tab;
}

async function ensureHarvestTab(channel, preferredUrl, steal = true) {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active?.id) {
    await injectHarvestRuntime(active.id).catch(() => null);
    const detected = await detectTabChannel(active.id, "");
    if (detected === channel) return active;
  }
  const url = preferredUrl || (await preferredPortal(channel));
  const tab = await ensureTab(url, steal);
  if (tab?.id) await waitTabComplete(tab.id);
  return tab;
}

function isPortalUrl(url, job) {
  const portal = job.upload_url || job.harvest_url || (job.playbook && (job.playbook.upload_url || job.playbook.portal)) || "";
  if (!url || !portal) return false;
  try {
    return new URL(url).hostname === new URL(portal).hostname && url.replace(/\/$/, "") === String(portal).replace(/\/$/, "");
  } catch {
    return url === portal;
  }
}

async function completeSeatJob(settings, job, body) {
  return apiJson(settings, `/seats/jobs/${job.id}/complete`, { method: "POST", body }).catch(() => null);
}

function watchChallengeResume(settings, seatId, url, channel) {
  if (!url) return;
  const tryOnce = async () => {
    let id = seatId;
    if (!id) {
      const saved = await chrome.storage.local.get(["serverSeats"]).catch(() => ({}));
      const seats = saved.serverSeats || [];
      const mine =
        seats.find((seat) => seat.channel_code === channel && seat.ownership === "user")
        || seats.find((seat) => seat.channel_code === channel);
      id = mine && mine.id;
    }
    if (!id) return false;
    const cookies = await chrome.cookies.getAll({ url }).catch(() => []);
    if (!cookies.length) return false;
    const tabs = await chrome.tabs.query({}).catch(() => []);
    const tab = (tabs || []).find((row) => row.url && (row.url === url || row.url.startsWith(String(url).split("?")[0])));
    const storageState = await captureStorageState(tab && tab.id, cookies);
    await apiJson(settings, `/seats/${id}/session`, {
      method: "POST",
      body: { cookies, storage_state: storageState },
    }).catch(() => null);
    pollSeatJobs().catch(() => null);
    kickAssistSoon();
    return true;
  };
  setTimeout(() => void tryOnce(), 15000);
  setTimeout(() => void tryOnce(), 45000);
}

async function reportHarvestFailure(channel, reason) {
  const name = storeName(channel);
  if (reason === "needs_challenge") {
    await finishProgress(false, `${name}像登录墙`, "在官方页过完验证，我们会自动接着跑。不填密码。", channel);
    await setBadge("!", "#b42318");
    return;
  }
  if (reason === "selector_broke" || reason === "timeout") {
    await finishProgress(false, `${name}对账表没读到`, "打开收益页，或导入官方 CSV。店改版了就靠夹具修剧本。", channel);
    return;
  }
  await finishProgress(false, `${name}这次没抄到数`, String(reason || "没有可见行"), channel);
}

let seatJobsBusy = false;

async function pollSeatJobs() {
  if (seatJobsBusy) return { ok: true, skipped: true };
  seatJobsBusy = true;
  try {
    return await runSeatJobs();
  } finally {
    seatJobsBusy = false;
  }
}

async function runSeatJobs() {
  const settings = await loadSettings();
  if (!settings.token || !settings.apiBase) return { ok: false, reason: "no_settings" };
  const saved = await chrome.storage.local.get(["minExtensionVersion", "upgradeRequired"]);
  if (saved.upgradeRequired || (saved.minExtensionVersion && versionLess(extensionVersion(), saved.minExtensionVersion))) {
    await setProgress({
      busy: false,
      title: "连接器太旧了",
      hint: `请重新加载 unpacked，至少 ${saved.minExtensionVersion || ""}。`,
    });
    return { ok: false, reason: "stale_extension" };
  }
  const body = await apiJson(settings, "/seats/jobs").catch(() => ({ jobs: [] }));
  const jobs = body.jobs || [];
  let ran = 0;
  for (const job of jobs) {
    const playbook = job.playbook || {};
    if (job.kind === "open_portal") {
      const channel = (job.seat && job.seat.channel_code) || settings.channel;
      const url = (job.payload && job.payload.login_url) || playbook.portal || playbook.harvest_url || (await preferredPortal(channel));
      await ensureTab(url, true, channel);
      await completeSeatJob(settings, job, { ok: true, result: { opened: true } });
      ran += 1;
      continue;
    }
    if (job.kind === "harvest" || job.kind === "sync_metrics") {
      const channel = (job.seat && job.seat.channel_code) || settings.channel;
      const scopes = (job.seat && job.seat.scopes) || {};
      const userSeat = job.seat && job.seat.ownership === "user";
      if (userSeat && job.kind === "sync_metrics" && !scopes.metrics) {
        await completeSeatJob(settings, job, { ok: false, result: { error: "scope_revoked" } });
        continue;
      }
      if (userSeat && job.kind === "harvest" && !scopes.settle && !scopes.keep_sync) {
        await completeSeatJob(settings, job, { ok: false, result: { error: "scope_revoked" } });
        continue;
      }
      const statsUrl = playbook.stats_url || (playbook.stats_urls && playbook.stats_urls[0]) || job.harvest_url || playbook.harvest_url;
      const tab = await ensureHarvestTab(channel, statsUrl, false);
      if (!tab?.id) {
        await completeSeatJob(settings, job, { ok: false, result: { error: "no_tab", needs_runtime: true } });
        continue;
      }
      const harvested = await runTabHarvest(tab.id, channel);
      if (harvested.reason === "needs_challenge") {
        await completeSeatJob(settings, job, { ok: false, result: { error: "needs_challenge", needs_challenge: true } });
        await reportHarvestFailure(channel, "needs_challenge");
        watchChallengeResume(settings, job.seat && job.seat.id, tab.url || statsUrl);
        continue;
      }
      const rows = harvested.rows || [];
      if (!rows.length) {
        await completeSeatJob(settings, job, {
          ok: false,
          result: { error: harvested.reason || "selector_broke", selector_broke: harvested.reason === "selector_broke" },
        });
        await reportHarvestFailure(channel, harvested.reason || "selector_broke");
        await rememberHarvest({ channel, rows: [], reason: harvested.reason || "selector_broke" });
        continue;
      }
      const license = Boolean((await chrome.storage.local.get(["hasDistributionLicense"])).hasDistributionLicense);
      const postedSettle = job.kind === "harvest" && (!userSeat || (scopes.settle && license));
      const posted = postedSettle
        ? await postHarvest({ ...settings, channel }, rows, job.seat && job.seat.id)
        : await postSync({ ...settings, channel }, rows, job.seat && job.seat.id);
      await rememberHarvest({
        channel,
        rows,
        reason: harvested.reason,
        matched: posted.matched,
        unclaimed: posted.unclaimed || posted.unmatched_count,
      });
      await completeSeatJob(settings, job, { ok: true, result: { rows: rows.length, reason: harvested.reason, settled: Boolean(postedSettle) } });
      ran += 1;
    }
    if (job.kind === "upload") {
      const scopes = (job.seat && job.seat.scopes) || {};
      if (job.seat && job.seat.ownership === "user" && !scopes.upload) {
        await completeSeatJob(settings, job, { ok: false, result: { error: "scope_revoked" } });
        continue;
      }
      const channel = (job.seat && job.seat.channel_code) || settings.channel;
      const deliveryId = job.payload && job.payload.delivery_id;
      const level = String((job.payload && job.payload.automation_level) || "");
      if (level === "metrics_only") {
        await completeSeatJob(settings, job, { ok: false, result: { error: "metrics_only" } });
        await finishProgress(false, `${storeName(channel)}不能直传`, "这家店不接受个人直传。连接器只收播放与收益。", channel);
        continue;
      }
      await setProgress({
        busy: true,
        channel,
        title: `正在代交${storeName(channel)}`,
        hint: level === "connector_full" ? "只填已打开的官方页。提交后我们记下歌曲页。" : "只填字段。母带请你自己拖进上传框。",
      });
      const ready = await ensureReadyStoreTab(uploadUrlFor(job, playbook, channel), channel);
      const tab = ready.tab;
      if (deliveryId) {
        await noteAssistProgress(settings, deliveryId, "opening", ready.granted ? "店页已打开，准备填表。" : "还没拿到这家店的页面权限。");
      }
      let fill = { ok: false, filled: [] };
      if (tab?.id) {
        fill = await fillAndAttachOnTab(tab.id, settings, job, channel);
        if (!fill.ok && !fill.needs_challenge && fill.reason !== "needs_challenge") {
          await sleep(1600);
          await waitTabComplete(tab.id);
          await injectStoreRuntime(tab.id);
          fill = await fillAndAttachOnTab(tab.id, settings, job, channel);
        }
      }
      if (fill.needs_challenge || fill.reason === "needs_challenge") {
        if (deliveryId) await noteAssistProgress(settings, deliveryId, "needs_challenge", "遇到验证，需你在官方页过一下。不填密码。");
        await completeSeatJob(settings, job, { ok: false, result: { error: "needs_challenge", needs_challenge: true } });
        await finishProgress(false, `${storeName(channel)}像登录墙`, "在官方页过完验证，我们会自动接着跑。不填密码。", channel);
        watchChallengeResume(settings, job.seat && job.seat.id, tab && tab.url, channel);
        continue;
      }
      const liveUrl = looksLikeLiveStore(tab && tab.url, channel) ? tab.url : "";
      const events = [];
      if (fill.ok) events.push("fields_filled");
      if (fill.attached) events.push("master_attached");
      if (fill.submitted) events.push("submitted");
      if (liveUrl) {
        await completeSeatJob(settings, job, {
          ok: true,
          result: {
            filled: Boolean(fill.ok),
            attached: Boolean(fill.attached),
            submitted: Boolean(fill.submitted),
            events,
            store_url: liveUrl,
            title_with_code: (job.payload || {}).title_with_code,
          },
        });
        await saveOpenSeatSession(settings, job.seat, tab);
        await reportStoreReceipt(settings, deliveryId, liveUrl, channel).catch(() => null);
      } else if (fill.attached || fill.ok) {
        const event = fill.submitted ? "submitted" : fill.attached ? "master_attached" : "fields_filled";
        if (deliveryId) {
          await noteAssistProgress(
            settings,
            deliveryId,
            event,
            fill.submitted ? "已在店页提交。" : fill.attached ? "母带已挂上上传框。" : "表单已填。",
          );
        }
        await completeSeatJob(settings, job, {
          ok: true,
          result: {
            filled: Boolean(fill.ok),
            attached: Boolean(fill.attached),
            submitted: Boolean(fill.submitted),
            events,
            title_with_code: (job.payload || {}).title_with_code,
          },
        });
        await saveOpenSeatSession(settings, job.seat, tab);
        watchStoreReceipt(settings, deliveryId, channel, tab && tab.id);
        await finishProgress(
          true,
          fill.submitted ? `${storeName(channel)}已提交` : `${storeName(channel)}表单已填`,
          fill.attached ? "母带已放进上传框。提交后我们记下歌曲页。" : "在官方页提交后，我们会自动记下歌曲页。",
          channel,
        );
        await broadcastAppEvent("BITTUNE_DELIVERY", {
          deliveryId,
          channel,
          event,
        });
      } else {
        await completeSeatJob(settings, job, { ok: false, result: { error: "fill_incomplete" } });
        if (deliveryId) {
          await noteAssistProgress(settings, deliveryId, "fill_incomplete", "店页还没填完。不会立刻重排队，等你补全或回执。");
        }
        watchChallengeResume(settings, job.seat && job.seat.id, tab && tab.url, channel);
        watchStoreReceipt(settings, deliveryId, channel, tab && tab.id);
      }
      if (deliveryId) await pollJobs().catch(() => null);
      ran += 1;
    }
    if (job.kind === "remote_login" && job.seat && job.seat.id) {
      const tab = await ensureTab(
        (job.payload && job.payload.login_url) || playbook.portal || playbook.harvest_url,
        true,
        job.seat && job.seat.channel_code,
      );
      const cookies = tab?.url ? await chrome.cookies.getAll({ url: tab.url }).catch(() => []) : [];
      if (cookies.length) {
        const storageState = await captureStorageState(tab && tab.id, cookies);
        await apiJson(settings, `/seats/${job.seat.id}/session`, {
          method: "POST",
          body: { cookies, storage_state: storageState },
        }).catch(() => null);
        await completeSeatJob(settings, job, { ok: true, result: { captured: true } });
      } else {
        await completeSeatJob(settings, job, { ok: false, result: { error: "no_session" } });
      }
      ran += 1;
    }
  }
  await refreshBadge();
  return { ok: true, seats: jobs.length, ran };
}

function applyPairPayload(message) {
  const webBase = message.webBase || message.web_base || "";
  return chrome.storage.local
    .set({
      apiBase: message.apiBase,
      token: message.token,
      channel: message.channel || "netease",
      period: message.period || new Date().toISOString().slice(0, 7),
      role: message.role || "",
      tokenExpiresAt: message.expires_at || message.expiresAt || "",
      minExtensionVersion: message.minVersion || message.min_extension_version || "",
      pairedUserId: message.user_id || message.userId || "",
      webBase,
    })
    .then(() => registerWebBaseBridge(webBase));
}

function ensureAssistAlarm() {
  chrome.alarms.create("vibe-assist", { periodInMinutes: 1 });
}

chrome.runtime.onInstalled.addListener((details) => {
  ensureAssistAlarm();
  chrome.storage.local.get(["webBase"]).then((saved) => registerWebBaseBridge(saved.webBase));
  if (details.reason === "install" || details.reason === "update") {
    notify("比特音连接器已就绪", "回创作者中心点「发给连接器」。打开已登录的店，我们会代交并记下歌曲页。");
  }
});
chrome.runtime.onStartup.addListener(() => {
  ensureAssistAlarm();
  chrome.storage.local.get(["webBase"]).then((saved) => registerWebBaseBridge(saved.webBase));
});
ensureAssistAlarm();
chrome.storage.local.get(["webBase"]).then((saved) => registerWebBaseBridge(saved.webBase));

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  const url = change.url || tab.url;
  if (!url || !pendingReceipts.size) return;
  pendingReceipts.forEach((rec, deliveryId) => {
    if (rec.tabId && rec.tabId !== tabId && !looksLikeLiveStore(url, rec.channel)) return;
    if (!looksLikeLiveStore(url, rec.channel)) return;
    void reportStoreReceipt(rec.settings, deliveryId, url, rec.channel).catch(() => null);
  });
});

async function broadcastCoach() {
  const tabs = await chrome.tabs.query({}).catch(() => []);
  for (const tab of tabs || []) {
    if (tab.id) chrome.tabs.sendMessage(tab.id, { type: "coach-refresh" }).catch(() => {});
  }
}

async function broadcastAppEvent(event, extra) {
  const tabs = await chrome.tabs.query({}).catch(() => []);
  for (const tab of tabs || []) {
    if (!tab.id || !tab.url) continue;
    if (!isBittuneAppTab(tab.url)) continue;
    chrome.tabs.sendMessage(tab.id, { type: "BITTUNE_APP_EVENT", event, ...(extra || {}) }).catch(() => {});
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "vibe-assist" || alarm.name === "vibe-assist-soon") {
    loadSettings()
      .then((settings) => heartbeat(settings))
      .catch(() => {});
    pollJobs().catch(() => {});
    pollSeatJobs().catch(() => {});
    refreshBadge().catch(() => {});
    broadcastCoach().catch(() => {});
  }
  if (alarm.name === "vibe-keepalive") {
    chrome.storage.local.get(["harvestProgress"]).then((saved) => {
      if (saved.harvestProgress && saved.harvestProgress.busy) {
        chrome.alarms.create("vibe-keepalive", { when: Date.now() + 20000 });
      }
    });
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "pair-settings") {
    applyPairPayload(message)
      .then(async () => {
        const settings = await loadSettings();
        const sync = await heartbeat(settings).catch(() => null);
        if (sync) await broadcastAppEvent("BITTUNE_SYNC", { sync, lastHarvest: sync.last_harvest });
        await pushLog("ok", "已从创作者中心配对，账期与席位已对齐");
        await finishProgress(true, "已配对比特音", "下一步：打开已登录的店后台。发行会自动代交。", "");
        await pollSeatJobs().catch(() => null);
        kickAssistSoon();
        await refreshBadge();
        sendResponse({ ok: true, sync });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "list-queue") {
    loadSettings()
      .then((settings) => apiJson(settings, "/seats/queue"))
      .then((body) => sendResponse({ ok: true, jobs: body.jobs || [] }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "page-event") {
    loadSettings()
      .then(async (settings) => {
        const deliveryId = message.deliveryId;
        if (message.kind === "submitted" && deliveryId) {
          await noteUserSubmitted(
            settings,
            deliveryId,
            message.channel,
            _sender && _sender.tab && _sender.tab.id,
          );
        }
        if (message.kind === "needs_challenge" && deliveryId) {
          await apiJson(settings, `/distribution/assist/jobs/${deliveryId}/progress`, {
            method: "POST",
            body: { event: "needs_challenge", message: "登录墙" },
          }).catch(() => null);
        }
        sendResponse({ ok: true });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "list-seats") {
    loadSettings()
      .then((settings) => apiJson(settings, "/seats"))
      .then((body) => sendResponse({ ok: true, seats: body.seats || [], playbooks: body.playbooks || [] }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "last-harvest") {
    chrome.storage.local
      .get(["lastHarvest"])
      .then((saved) => sendResponse({ ok: true, lastHarvest: saved.lastHarvest || null }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "open-stats") {
    openStatsTab(message.channel || "netease")
      .then((tab) => sendResponse({ ok: true, tabId: tab && tab.id, url: tab && tab.url }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "harvest-tab") {
    loadSettings()
      .then(async (settings) => {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.id) throw new Error("没有活动标签");
        await injectHarvestRuntime(tab.id);
        const channel = (await detectTabChannel(tab.id, settings.channel)) || settings.channel;
        const harvested = await runTabHarvest(tab.id, channel);
        if (harvested.reason === "needs_challenge") {
          await reportHarvestFailure(channel, "needs_challenge");
          watchChallengeResume(settings, null, tab.url, channel);
          throw new Error("当前页像登录墙，请先登录店后台");
        }
        if (!(harvested.rows || []).length) {
          await reportHarvestFailure(channel, "selector_broke");
          throw new Error(harvested.reason === "selector_broke" ? "对账表没读到。打开收益页或导入官方 CSV。" : "没有可见行");
        }
        const body = await postSync({ ...settings, channel }, harvested.rows);
        await rememberHarvest({
          channel,
          rows: harvested.rows,
          reason: harvested.reason,
          matched: body.matched,
          unclaimed: body.unclaimed || body.unmatched_count,
        });
        await refreshBadge();
        sendResponse({ ok: true, matched: body.matched, unclaimed: body.unclaimed || body.unmatched_count, rows: harvested.rows.length });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "ingest") {
    const { settings, rows } = message;
    postHarvest(settings, rows)
      .then(async (body) => {
        await rememberHarvest({
          channel: settings.channel,
          rows,
          reason: "official_csv",
          matched: body.matched,
          unclaimed: body.unclaimed || body.unmatched_count,
        });
        sendResponse({ ok: true, matched: body.matched, unclaimed: body.unclaimed || body.unmatched_count });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "authorize-seat") {
    authorizeSeat(message.settings, message.tabUrl)
      .then(async (result) => {
        const settings = message.settings || (await loadSettings());
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        let synced = null;
        if (tab?.id) {
          const channel = (result.seat && result.seat.channel_code) || settings.channel;
          const harvested = await runTabHarvest(tab.id, channel).catch(() => ({ rows: [] }));
          if (harvested.reason === "needs_challenge") {
            watchChallengeResume(settings, result.seat && result.seat.id, tab.url, channel);
          } else if ((harvested.rows || []).length) {
            synced = await postSync({ ...settings, channel }, harvested.rows, result.seat && result.seat.id);
            await rememberHarvest({
              channel,
              rows: harvested.rows,
              reason: harvested.reason,
              matched: synced.matched,
              unclaimed: synced.unclaimed || synced.unmatched_count,
            });
          }
        }
        const polled = await pollSeatJobs().catch(() => null);
        await refreshBadge();
        sendResponse({ ...result, synced, polled });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "harvest-seat") {
    loadSettings()
      .then(async (settings) => {
        const channel = message.channel || settings.channel;
        const tab = await ensureHarvestTab(channel, message.statsUrl);
        if (!tab?.id) throw new Error("没有可收割的标签");
        const harvested = await runTabHarvest(tab.id, channel);
        if (harvested.reason === "needs_challenge") {
          await reportHarvestFailure(channel, "needs_challenge");
          watchChallengeResume(settings, message.seatId, tab.url, channel);
          throw new Error("当前页像登录墙，请先登录店后台");
        }
        if (!(harvested.rows || []).length) {
          await reportHarvestFailure(channel, harvested.reason || "selector_broke");
          throw new Error("对账表没读到。打开收益页或导入官方 CSV。");
        }
        const saved = await chrome.storage.local.get(["serverSeats", "hasDistributionLicense"]);
        const seats = saved.serverSeats || [];
        const mine = seats.find((seat) => seat.id === message.seatId || (seat.channel_code === channel && seat.ownership === "user"));
        const canSettle = Boolean(mine && mine.scopes && mine.scopes.settle && saved.hasDistributionLicense);
        const body = canSettle
          ? await postHarvest({ ...settings, channel }, harvested.rows, message.seatId)
          : await postSync({ ...settings, channel }, harvested.rows, message.seatId);
        await rememberHarvest({
          channel,
          rows: harvested.rows,
          reason: harvested.reason,
          matched: body.matched,
          unclaimed: body.unclaimed || body.unmatched_count,
        });
        await refreshBadge();
        sendResponse({ ok: true, matched: body.matched, unclaimed: body.unclaimed || body.unmatched_count, rows: harvested.rows.length });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "open-self-test") {
    const url = chrome.runtime.getURL("fixtures/self-test.html");
    chrome.tabs
      .create({ url, active: true })
      .then((tab) => sendResponse({ ok: true, tabId: tab.id, url }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "open-app") {
    chrome.storage.local
      .get(["webBase"])
      .then(async (saved) => {
        const base = String(saved.webBase || "").replace(/\/$/, "");
        if (!base) throw new Error("还没有配对地址。先回创作者中心发送到扩展。");
        const local = /localhost|127\.0\.0\.1/.test(base);
        const url = local
          ? `${base}/#/packageCreator/pages/accounts/index`
          : `${base}/packageCreator/pages/accounts/index`;
        const tab = await chrome.tabs.create({ url, active: true });
        sendResponse({ ok: true, tabId: tab.id, url });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "unpair") {
    loadSettings()
      .then(async (settings) => {
        if (settings.token) {
          await fetch(apiUrl(settings, "/distribution/connector/token"), {
            method: "DELETE",
            headers: headers(settings),
          }).catch(() => null);
        }
        await chrome.storage.local.remove([
          "token",
          "tokenExpiresAt",
          "pairedUserId",
          "lastHarvest",
          "serverSeats",
          "syncOk",
          "lastSyncAt",
          "minExtensionVersion",
          "role",
        ]);
        await setBadge("", "#888888");
        await pushLog("ok", "已断开配对，旧令牌作废");
        await broadcastAppEvent("BITTUNE_UNPAIRED", {});
        sendResponse({ ok: true });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "open-desk") {
    const url = chrome.runtime.getURL("desk.html");
    chrome.tabs.query({ url })
      .then(async (tabs) => {
        if (tabs[0]) {
          await chrome.tabs.update(tabs[0].id, { active: true });
          sendResponse({ ok: true, tabId: tabs[0].id });
          return;
        }
        const tab = await chrome.tabs.create({ url, active: true });
        sendResponse({ ok: true, tabId: tab.id });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "sync-now") {
    loadSettings()
      .then(async (settings) => {
        const sync = await heartbeat(settings);
        await refreshBadge();
        sendResponse({ ok: true, sync });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "ui-state") {
    chrome.storage.local
      .get([
        "apiBase",
        "token",
        "channel",
        "period",
        "role",
        "lastHarvest",
        "lastDelivery",
        "queueCount",
        "harvestProgress",
        "activityLog",
        "tokenExpiresAt",
        "minExtensionVersion",
        "lastSyncAt",
        "syncOk",
        "serverSeats",
      ])
      .then((saved) => sendResponse({ ok: true, extensionVersion: extensionVersion(), ...saved }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "page-coach" || message?.type === "overlay-state") {
    const channel =
      (self.VibeRunner && self.VibeRunner.detectChannel(message.url || "")) || "";
    if (!channel) {
      sendResponse({ show: false });
      return false;
    }
    chrome.storage.local
      .get(["token", "harvestProgress", "lastHarvest", "lastDelivery", "serverSeats", "hasDistributionLicense"])
      .then((saved) => {
        const progress = saved.harvestProgress || {};
        const last = saved.lastHarvest || {};
        const delivery = saved.lastDelivery || {};
        const seats = saved.serverSeats || [];
        const mine = seats.find((seat) => seat.channel_code === channel && seat.ownership === "user");
        const scopes = (mine && mine.scopes) || { metrics: true, export_csv: true, settle: false };
        const coach = self.VibeUi && self.VibeUi.coach
          ? self.VibeUi.coach({
              token: saved.token,
              tabChannel: channel,
              progress,
              lastHarvest: last,
              seats,
              online: true,
            })
          : {};
        const t = self.VibeUi && self.VibeUi.overlayCopy ? self.VibeUi.overlayCopy() : {};
        sendResponse({
          show: true,
          paired: Boolean(saved.token),
          channel,
          name: storeName(channel),
          scopes,
          hasLicense: Boolean(saved.hasDistributionLicense),
          title: storeName(channel),
          hint: progress.busy && progress.channel === channel ? (progress.hint || progress.title || t.syncing) : saved.token ? t.loggedIn : t.needPair,
          busy: Boolean(progress.busy && progress.channel === channel),
          last:
            delivery.channel_code === channel && delivery.event
              ? `${delivery.event}${delivery.message ? ` · ${delivery.message}` : ""}`
              : last.ok && last.channel === channel
                ? (t.last || "上次同步 {n} 行").replace("{n}", String(last.count || 0))
                : "",
          error: progress.ok === false && progress.channel === channel ? (progress.hint || progress.title || "") : "",
          action: coach.action === "pair" ? "open-popup" : "open-app",
          actionLabel: saved.token ? t.sync || "同步到比特音" : t.needPair || t.openConnector || "去配对",
        });
      })
      .catch(() => sendResponse({ show: false }));
    return true;
  }
  if (message?.type === "overlay-sync") {
    loadSettings()
      .then(async (settings) => {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        const channel = message.channel || settings.channel;
        await setProgress({ busy: true, channel, title: `正在同步${storeName(channel)}`, hint: "只读取你勾选的可见数据" });
        if (tab?.id) chrome.tabs.sendMessage(tab.id, { type: "overlay-refresh" }).catch(() => {});
        if (message.settle) {
          const saved = await chrome.storage.local.get(["hasDistributionLicense"]);
          if (!saved.hasDistributionLicense) throw new Error("还没签署发行协议，不能用于结算");
        }
        const authorized = await authorizeSeat({ ...settings, channel }, tab && tab.url);
        const seatId = authorized && authorized.seat && authorized.seat.id;
        if (message.settle) {
          await patchScopes(settings, seatId, { settle: true });
        }
        if (!tab?.id) throw new Error("没有当前页");
        const harvested = await runTabHarvest(tab.id, channel);
        if (harvested.reason === "needs_challenge") {
          watchChallengeResume(settings, seatId, tab.url, channel);
          throw new Error("需要你在官方页登录");
        }
        if (!(harvested.rows || []).length) throw new Error(harvested.reason === "selector_broke" ? "对账表没读到" : "没有可见行");
        const rows =
          self.VibeUi && self.VibeUi.filterHarvestRows
            ? self.VibeUi.filterHarvestRows(harvested.rows, message.fields)
            : harvested.rows;
        const posted = message.settle
          ? await postHarvest({ ...settings, channel }, rows, seatId)
          : await postSync({ ...settings, channel }, rows, seatId);
        await rememberHarvest({
          channel,
          rows,
          reason: harvested.reason,
          matched: posted.matched,
          unclaimed: posted.unclaimed || posted.unmatched_count,
        });
        await finishProgress(true, `${storeName(channel)}已同步 ${rows.length} 行`, "回创作者中心看播放与预计收入。", channel);
        chrome.tabs.sendMessage(tab.id, { type: "overlay-refresh" }).catch(() => {});
        sendResponse({ ok: true, matched: posted.matched, rows: rows.length });
      })
      .catch(async (err) => {
        await finishProgress(false, "同步失败", String(err && err.message ? err.message : err), message.channel);
        try {
          const [failTab] = await chrome.tabs.query({ active: true, currentWindow: true });
          if (failTab?.id) chrome.tabs.sendMessage(failTab.id, { type: "overlay-refresh" }).catch(() => {});
        } catch {
          /* optional */
        }
        sendResponse({ ok: false, error: String(err && err.message ? err.message : err) });
      });
    return true;
  }
  if (message?.type === "open-popup") {
    if (chrome.action && chrome.action.openPopup) chrome.action.openPopup().catch(() => {});
    sendResponse({ ok: true });
    return false;
  }
  if (message?.type === "seat-poll") {
    pollSeatJobs()
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "assist-poll") {
    pollJobs()
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "assist-complete-tab") {
    loadSettings()
      .then(async (settings) => {
        const body = await apiJson(settings, "/distribution/assist/jobs");
        const jobs = body.jobs || [];
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.url) throw new Error("No active tab URL");
        const job =
          jobs.find((row) => row.delivery_id === message.deliveryId) ||
          jobs.find((row) => jobMatchesTab(row, tab.url));
        if (!job) throw new Error("No matching assist job for this tab");
        const saved = await completeJob(settings, job, tab.url);
        sendResponse({ ok: true, status: saved.status, store_url: saved.store_url });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "assist-download-kit") {
    loadSettings()
      .then(async (settings) => {
        const body = await apiJson(settings, `/distribution/assist/jobs/${message.deliveryId}/kit`);
        if (!body.kit_url) throw new Error("No kit url");
        await chrome.tabs.create({ url: body.kit_url, active: true });
        sendResponse({ ok: true, kit_url: body.kit_url, title: body.title });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "assist-download-originality") {
    loadSettings()
      .then(async (settings) => {
        const body = await apiJson(settings, `/distribution/assist/jobs/${message.deliveryId}/originality`);
        if (!body.originality_zip_url) throw new Error("No originality pack");
        await chrome.tabs.create({ url: body.originality_zip_url, active: true });
        sendResponse({ ok: true, originality_zip_url: body.originality_zip_url });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "assist-download-clips") {
    loadSettings()
      .then(async (settings) => {
        const body = await apiJson(settings, `/distribution/assist/jobs/${message.deliveryId}/clip-pack`);
        if (!body.clip_pack_url) throw new Error("No clip pack");
        await chrome.tabs.create({ url: body.clip_pack_url, active: true });
        sendResponse({ ok: true, clip_pack_url: body.clip_pack_url });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  if (message?.type === "seat-command") {
    loadSettings()
      .then(async (settings) => {
        const seatId = message.seatId;
        if (!seatId) throw new Error("seat required");
        const kind = message.kind || "sync_metrics";
        if (kind === "open_portal" && message.payload && message.payload.login_url) {
          await ensureTab(message.payload.login_url);
        }
        const body = await apiJson(settings, `/seats/${seatId}/command`, {
          method: "POST",
          body: { kind, payload: message.payload || {} },
        });
        try {
          chrome.alarms.create("vibe-assist-soon", { when: Date.now() + 400 });
        } catch {
          /* optional */
        }
        sendResponse({ ok: true, ...body });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  return false;
});

chrome.runtime.onMessageExternal.addListener((message, _sender, sendResponse) => {
  if (message?.type === "pair-settings" || message?.type === "BITTUNE_PAIR") {
    applyPairPayload({
      apiBase: message.apiBase || (message.pair && message.pair.apiBase),
      token: message.token || (message.pair && message.pair.token),
      channel: message.channel || (message.pair && message.pair.channel),
      period: message.period || (message.pair && message.pair.period),
      role: message.role || (message.pair && message.pair.role),
      expires_at: message.expires_at || (message.pair && message.pair.expires_at),
      minVersion: message.minVersion || (message.pair && message.pair.minVersion),
      user_id: message.user_id || (message.pair && message.pair.user_id),
      webBase: message.webBase || (message.pair && message.pair.webBase),
    })
      .then(async () => {
        const settings = await loadSettings();
        await heartbeat(settings).catch(() => null);
        await pushLog("ok", "已从网页配对");
        await finishProgress(true, "已配对比特音", "下一步：打开已登录的店后台，点「同步到比特音」。", "");
        sendResponse({ ok: true });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
  return false;
});

chrome.notifications.onClicked.addListener(() => {
  const url = chrome.runtime.getURL("desk.html");
  chrome.tabs.query({ url }).then(async (tabs) => {
    if (tabs[0]) {
      await chrome.tabs.update(tabs[0].id, { active: true });
      return;
    }
    await chrome.tabs.create({ url, active: true });
  });
});
