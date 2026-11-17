const $ = (id) => document.getElementById(id);
const ui = self.VibeUi || {};
const CHANNEL_NAMES = ui.CHANNEL_NAMES || {};

let tabChannel = "";
let seatsCache = [];
let online = null;
let lastCoach = null;

async function load() {
  const saved = await chrome.storage.local.get(["apiBase", "token", "channel", "period", "role"]);
  $("apiBase").value = saved.apiBase || "";
  $("token").value = saved.token || "";
  $("channel").value = saved.channel || "netease";
  $("period").value = saved.period || new Date().toISOString().slice(0, 7);
  renderLane(saved.role);
}

function renderLane(role) {
  $("lane").textContent =
    role === "ops"
      ? "运营号：拉任务和入账在「卡住了」里。用户席位默认同步不入账。"
      : (ui.overlayCopy && ui.overlayCopy().lane) || "连上店，再同步播放。入账另开。";
}

function renderSteps(paired, authorized) {
  $("step1").className = `step ${paired ? "done" : "on"}`;
  $("step2").className = `step ${paired ? (authorized ? "done" : "on") : ""}`;
  $("step3").className = `step ${authorized ? "on" : ""}`;
}

function setStatus(text, ok) {
  const el = $("status");
  el.textContent = text;
  el.className = ok ? "ok" : "err";
}

function friendlyError(err) {
  const raw = String(err || "");
  if (raw.includes("Not authenticated") || raw.includes("Invalid token") || raw.includes("401") || raw.includes("Seat required")) {
    return "还没授权这家店，或令牌无效。先配对，再点「同步到比特音」。";
  }
  if (raw.includes("not a store page")) return "当前页不是商店歌曲页，请打开已发布的链接再回传。";
  if (raw.includes("No matching assist job")) return "当前标签对不上待投递店铺。先开门户或同步任务。";
  return raw;
}

function currentSettings() {
  return {
    apiBase: $("apiBase").value.trim(),
    token: $("token").value.trim(),
    channel: $("channel").value,
    period: $("period").value.trim(),
  };
}

function parsePairText(raw) {
  const text = String(raw || "").trim();
  const sliced = text.startsWith("BITTUNE_PAIR:") ? text.slice("BITTUNE_PAIR:".length) : text;
  try {
    const data = JSON.parse(sliced);
    if (data && data.vibePair && data.token && data.apiBase) return data;
  } catch {
    /* not json */
  }
  if (text.startsWith("vsc_")) {
    return { vibePair: 1, token: text, apiBase: $("apiBase").value.trim() };
  }
  return null;
}

async function applyPair(pair) {
  $("apiBase").value = pair.apiBase;
  $("token").value = pair.token;
  await chrome.storage.local.set({
    apiBase: pair.apiBase,
    token: pair.token,
    channel: pair.channel || $("channel").value,
    period: pair.period || $("period").value,
    role: pair.role || "",
    tokenExpiresAt: pair.expires_at || "",
    minExtensionVersion: pair.minVersion || "",
    pairedUserId: pair.user_id || "",
    webBase: pair.webBase || "",
  });
  if (pair.period) $("period").value = pair.period;
  renderLane(pair.role);
  setStatus("已配对。下一步：打开已登录的店后台。", true);
}

async function pingHeartbeat() {
  const settings = currentSettings();
  const el = $("heartbeat");
  if (!settings.token) {
    el.textContent = (ui.overlayCopy && ui.overlayCopy().notPaired) || "尚未配对";
    el.className = "hint";
    online = null;
    return;
  }
  try {
    const res = await chrome.runtime.sendMessage({ type: "sync-now" });
    const body = (res && res.sync) || {};
    online = Boolean(res?.ok && body.online);
    if (online) {
      if (body.period_key) $("period").value = body.period_key;
      const last = body.last_harvest;
      el.textContent = last
        ? `已与账户对齐 · ${ui.channelName ? ui.channelName(last.channel) : last.channel} ${last.count || 0} 行 · 账期 ${body.period_key || ""}`
        : ((ui.overlayCopy && ui.overlayCopy().aligned) || "已与账户对齐 · 账期 {p}。只有你点同步才会拉数。").replace("{p}", body.period_key || "");
      el.className = "ok";
    } else {
      el.textContent = body.reason === "no_token" ? "token 无效或已过期" : "心跳未在线";
      el.className = "err";
    }
  } catch (err) {
    online = false;
    el.textContent = friendlyError(err);
    el.className = "err";
  }
}

async function detectCurrentStore() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["runner-core.js"] });
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () =>
        (window.VibeRunner &&
          ((window.VibeRunner.detectChannelFromDoc && window.VibeRunner.detectChannelFromDoc(document, location.href)) ||
            window.VibeRunner.detectChannel(location.href))) ||
        "",
    });
    tabChannel = result || "";
    if (result) {
      $("channel").value = result;
      $("channelHint").textContent = `当前店：${ui.channelName ? ui.channelName(result) : result}（已自动识别）`;
    } else {
      $("channelHint").textContent = "当前店：未识别。先打开音乐人后台，或点工作台里的店。";
    }
  } catch {
    tabChannel = "";
    $("channelHint").textContent = "当前店：无法读取此页（扩展页或系统页）";
  }
}

async function renderCoach() {
  const saved = await chrome.storage.local.get([
    "token",
    "lastHarvest",
    "harvestProgress",
    "activityLog",
    "tokenExpiresAt",
    "minExtensionVersion",
  ]);
  const coach = ui.coach
    ? ui.coach({
        token: saved.token || currentSettings().token,
        online,
        seats: seatsCache,
        tabChannel,
        lastHarvest: saved.lastHarvest,
        progress: saved.harvestProgress,
        tokenExpiresAt: saved.tokenExpiresAt,
        minExtensionVersion: saved.minExtensionVersion,
        extensionVersion: chrome.runtime.getManifest().version,
      })
    : { title: "比特音连接器", hint: "", tone: "need", action: "pair" };
  lastCoach = coach;
  $("coach").className = `coach ${coach.tone || "need"}`;
  $("coachTitle").textContent = coach.title;
  $("coachHint").textContent = coach.hint;
  const busy = Boolean(saved.harvestProgress && saved.harvestProgress.busy);
  $("primary").disabled = busy;
  const t = ui.overlayCopy ? ui.overlayCopy() : {};
  $("primary").textContent = busy ? t.syncing || "同步中…" : ui.actionLabel ? ui.actionLabel(coach.action) || t.pair || "从剪贴板配对" : t.pair || "从剪贴板配对";
  $("openPanel").className = coach.action === "open" || coach.action === "authorize" ? "step-card" : "step-card hidden";
  renderSteps(Boolean(saved.token || currentSettings().token), Boolean(seatsCache.length));
  const log = (saved.activityLog || []).slice(0, 5);
  $("activity").innerHTML = log
    .map((row) => `<div class="${row.level === "err" ? "err" : row.level === "ok" ? "ok" : "hint"}">${ui.formatWhen ? ui.formatWhen(row.at) : ""} ${row.text}</div>`)
    .join("");
}

async function renderLastHarvest() {
  const box = $("lastHarvest");
  const result = await chrome.runtime.sendMessage({ type: "last-harvest" }).catch(() => null);
  const last = result && result.lastHarvest;
  if (!last) {
    box.innerHTML = "";
    return;
  }
  const when = ui.formatWhen ? ui.formatWhen(last.at) : String(last.at || "").slice(0, 16);
  const src = ui.reasonLabel ? ui.reasonLabel(last.reason) : last.reason;
  const rows = (last.rows || [])
    .slice(0, 4)
    .map((row) => `<li>${row.title || "未命名"} · ${row.streams || 0} 次 · ${row.revenue_minor || 0}${row.revenue_minor ? "" : ""}</li>`)
    .join("");
    const t = ui.overlayCopy ? ui.overlayCopy() : {};
    box.innerHTML = `<div class="preview ${last.ok ? "" : "err"}"><b>${(t.lastSyncTitle || "上次同步 {name}").replace("{name}", ui.channelName ? ui.channelName(last.channel) : last.channel || "")}</b><span class="hint">${when} · ${last.count || 0} 行 · ${src}${last.matched != null ? ` · 匹配 ${last.matched}` : ""}</span>${rows ? `<ul>${rows}</ul>` : ""}</div>`;
}

async function renderSeats() {
  const box = $("seats");
  box.innerHTML = "";
  const result = await chrome.runtime.sendMessage({ type: "list-seats" }).catch(() => null);
  if (!result?.ok) {
    seatsCache = [];
    box.innerHTML = `<div class="empty">${(ui.overlayCopy && ui.overlayCopy().emptySeats) || "配对后这里会列出已授权的店。"}</div>`;
    return;
  }
  const mine = (result.seats || []).filter((seat) => seat.ownership === "user" || seat.runtime === "extension");
  seatsCache = mine.length ? mine : result.seats || [];
  if (!seatsCache.length) {
    box.innerHTML = `<div class="empty">${(ui.overlayCopy && ui.overlayCopy().emptySeats) || "还没有授权的店。登录官方页后点「同步到比特音」。"}</div>`;
    return;
  }
  seatsCache.slice(0, 8).forEach((seat) => {
    const el = document.createElement("div");
    el.className = "seat";
    const health = (seat.extra && seat.extra.farm_health) || {};
    const last = seat.last_sync_at || seat.last_harvest_at || health.at || "尚未同步";
    const expired = ui.seatExpired ? ui.seatExpired(seat) : false;
    el.innerHTML = `<b>${(seat.playbook && seat.playbook.name) || (ui.channelName && ui.channelName(seat.channel_code)) || seat.channel_code}</b><span class="hint">${expired ? "要重新登录" : `上次 ${last}`}${health.rows != null ? ` · ${health.rows} 行` : ""}</span>`;
    const harvestBtn = document.createElement("button");
    const t = ui.overlayCopy ? ui.overlayCopy() : {};
    harvestBtn.textContent = expired ? t.goLogin || "去登录" : t.syncNow || "同步";
    harvestBtn.onclick = async () => {
      harvestBtn.disabled = true;
      setStatus(expired ? "正在打开对账页…" : "正在同步，请稍等…", true);
      if (expired) {
        const opened = await chrome.runtime.sendMessage({ type: "open-stats", channel: seat.channel_code });
        setStatus(opened?.ok ? "已打开对账页。登录后再点「同步到比特音」。" : friendlyError(opened?.error || "打开失败"), Boolean(opened?.ok));
        harvestBtn.disabled = false;
        return;
      }
      const done = await chrome.runtime.sendMessage({ type: "harvest-seat", channel: seat.channel_code, seatId: seat.id });
      setStatus(
        done?.ok ? `已同步 ${done.rows || 0} 行 · 匹配 ${done.matched || 0}` : friendlyError(done?.error || "同步失败"),
        Boolean(done?.ok),
      );
      harvestBtn.disabled = false;
      await refreshAll();
    };
    el.appendChild(harvestBtn);
    box.appendChild(el);
  });
}

async function renderJobs() {
  const settings = currentSettings();
  const box = $("jobs");
  box.innerHTML = "";
  if (!settings.token) return;
  try {
    const queue = await chrome.runtime.sendMessage({ type: "list-queue" }).catch(() => null);
    const queued = (queue && queue.jobs) || [];
    const t = ui.overlayCopy ? ui.overlayCopy() : {};
    queued.slice(0, 6).forEach((job) => {
      const el = document.createElement("div");
      el.className = "job";
      const kind =
        job.kind === "upload" ? "代交" : job.kind === "harvest" || job.kind === "sync_metrics" ? "同步" : job.kind || "任务";
      el.innerHTML = `<b>${ui.channelName ? ui.channelName(job.channel_code) : job.channel_code} · ${kind}</b><span>${job.title || job.status || ""}${job.automation_level === "metrics_only" ? " · 只收数据" : job.automation_level === "connector_assist" || job.degraded ? " · 只填表" : ""}</span>`;
      box.appendChild(el);
    });
    const res = await fetch(`${settings.apiBase.replace(/\/$/, "")}/distribution/assist/jobs`, {
      headers: {
        "X-Connector-Token": settings.token,
        Authorization: `Bearer ${settings.token}`,
      },
    });
    const body = await res.json();
    const jobs = body.jobs || [];
    if (!queued.length && !jobs.length) return;
    jobs.slice(0, 4).forEach((job) => {
      const el = document.createElement("div");
      el.className = "job";
      el.innerHTML = `<b>${job.channel_code} · ${job.status}</b><span>${job.title || "投递辅助"}</span>`;
      const row = document.createElement("div");
      row.className = "row";
      const open = document.createElement("button");
      open.textContent = t.openPortal || "打开后台";
      open.onclick = () => job.upload_url && chrome.tabs.create({ url: job.upload_url });
      const mark = document.createElement("button");
      mark.textContent = t.markLive || "本页已上架";
      mark.onclick = async () => {
        const done = await chrome.runtime.sendMessage({ type: "assist-complete-tab", deliveryId: job.delivery_id });
        setStatus(done?.ok ? `已标记 ${done.status || "live"}` : friendlyError(done?.error || "Complete failed"), Boolean(done?.ok));
      };
      row.appendChild(open);
      row.appendChild(mark);
      if (job.kit_url) {
        const kitBtn = document.createElement("button");
        kitBtn.textContent = "素材包";
        kitBtn.onclick = () => chrome.runtime.sendMessage({ type: "assist-download-kit", deliveryId: job.delivery_id });
        row.appendChild(kitBtn);
      }
      if (job.originality_zip_url) {
        const origBtn = document.createElement("button");
        origBtn.textContent = "证明包";
        origBtn.onclick = () => chrome.runtime.sendMessage({ type: "assist-download-originality", deliveryId: job.delivery_id });
        row.appendChild(origBtn);
      }
      el.appendChild(row);
      box.appendChild(el);
    });
  } catch (err) {
    setStatus(friendlyError(err), false);
  }
}

async function refreshAll() {
  await pingHeartbeat();
  await renderSeats();
  await renderLastHarvest();
  await renderJobs();
  await renderCoach();
}

async function runPrimary() {
  const action = (lastCoach && lastCoach.action) || "pair";
  if (action === "pair") {
    $("pairClick").click();
    return;
  }
  if (action === "authorize") {
    $("authorize").click();
    return;
  }
  if (action === "harvest") {
    $("capture").click();
    return;
  }
  if (action === "open" && lastCoach.channel) {
    const opened = await chrome.runtime.sendMessage({ type: "open-stats", channel: lastCoach.channel });
    setStatus(opened?.ok ? `已打开 ${ui.channelName(lastCoach.channel)}，登录后再授权` : friendlyError(opened?.error || "打开失败"), Boolean(opened?.ok));
    return;
  }
  $("openPanel").className = "step-card";
}

$("primary").addEventListener("click", () => void runPrimary());
$("desk").addEventListener("click", () => chrome.runtime.sendMessage({ type: "open-desk" }));
$("openApp").addEventListener("click", () => chrome.runtime.sendMessage({ type: "open-app" }));
$("openStores").addEventListener("click", () => {
  $("openPanel").className = "step-card";
});
$("unpair").addEventListener("click", async () => {
  const done = await chrome.runtime.sendMessage({ type: "unpair" });
  setStatus(done?.ok ? "已断开配对。回账户页重新发送。" : friendlyError(done?.error || "断开失败"), Boolean(done?.ok));
  await load();
  await refreshAll();
});

const pairBtn = document.createElement("button");
pairBtn.id = "pairClick";
pairBtn.className = "hidden";
document.body.appendChild(pairBtn);
pairBtn.addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    const pair = parsePairText(text);
    if (!pair) {
      setStatus("剪贴板里没有配对文本。请回创作者中心点「发送到已安装的扩展」。", false);
      return;
    }
    await applyPair(pair);
    await refreshAll();
  } catch (err) {
    setStatus(friendlyError(err), false);
  }
});

$("save").addEventListener("click", async () => {
  await chrome.storage.local.set(currentSettings());
  setStatus("已保存", true);
  await refreshAll();
});

$("poll").addEventListener("click", async () => {
  await chrome.storage.local.set(currentSettings());
  setStatus("正在同步席位任务…", true);
  const res = await chrome.runtime.sendMessage({ type: "assist-poll" });
  const seats = await chrome.runtime.sendMessage({ type: "seat-poll" });
  setStatus(
    res?.ok ? `已同步（待投递 ${res.pending || 0} · 席位任务 ${seats?.ran || 0}）` : friendlyError(res?.error || "Sync failed"),
    Boolean(res?.ok),
  );
  await refreshAll();
});

$("authorize").addEventListener("click", async () => {
  const settings = currentSettings();
  await chrome.storage.local.set(settings);
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  setStatus("正在授权并开始同步…", true);
  $("authorize").disabled = true;
  const res = await chrome.runtime.sendMessage({ type: "authorize-seat", settings, tabUrl: tab?.url });
  $("authorize").disabled = false;
  const synced = (res?.synced && res.synced.matched) || (res?.polled && res.polled.ran);
  setStatus(
    res?.ok
      ? `已连接 ${ui.channelName ? ui.channelName(res.seat?.channel_code) : res.seat?.channel_code}${synced ? ` · 已同步` : " · 打开店后台再点同步"}`
      : friendlyError(res?.error || "Authorize failed"),
    Boolean(res?.ok),
  );
  await refreshAll();
});

$("selfTest").addEventListener("click", async () => {
  $("channel").value = "netease";
  await chrome.storage.local.set({ ...currentSettings(), channel: "netease" });
  const opened = await chrome.runtime.sendMessage({ type: "open-self-test" });
  setStatus(opened?.ok ? "已打开本机夹具。再点「收割当前页」应看到两行。" : friendlyError(opened?.error || "打开失败"), Boolean(opened?.ok));
});

$("importCsv").addEventListener("click", () => $("csvFile").click());
$("csvFile").addEventListener("change", async (event) => {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const settings = currentSettings();
  await chrome.storage.local.set(settings);
  setStatus("正在发送官方 CSV…", true);
  const text = await file.text();
  const parsed = (self.VibeHarvest && self.VibeHarvest.parseOfficialCsv(text, settings.channel)) || [];
  const res = await chrome.runtime.sendMessage({ type: "ingest", settings, rows: parsed });
  setStatus(res?.ok ? `CSV 已发送 ${res.matched || 0} 匹配` : friendlyError(res?.error || "CSV send failed"), Boolean(res?.ok));
  await refreshAll();
});

$("capture").addEventListener("click", async () => {
  const settings = currentSettings();
  await chrome.storage.local.set(settings);
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    setStatus("没有活动标签", false);
    return;
  }
  setStatus("正在读当前页…", true);
  $("capture").disabled = true;
  $("primary").disabled = true;
  const harvested = await chrome.runtime.sendMessage({ type: "harvest-tab" });
  $("capture").disabled = false;
  if (harvested?.ok) {
    setStatus(`已发送 ${harvested.matched || 0} 匹配 / ${harvested.unclaimed || 0} 待认领`, true);
    await refreshAll();
    return;
  }
  setStatus(friendlyError(harvested?.error || "Send failed"), false);
  await renderCoach();
});

document.querySelectorAll("[data-open]").forEach((button) => {
  button.addEventListener("click", async () => {
    const channel = button.getAttribute("data-open");
    $("channel").value = channel;
    await chrome.storage.local.set({ ...currentSettings(), channel });
    setStatus(`正在打开 ${ui.channelName ? ui.channelName(channel) : channel}…`, true);
    const opened = await chrome.runtime.sendMessage({ type: "open-stats", channel });
    setStatus(opened?.ok ? `已打开。登录后点「同步到比特音」。` : friendlyError(opened?.error || "打开失败"), Boolean(opened?.ok));
  });
});

chrome.storage.onChanged.addListener((changes) => {
  if (changes.harvestProgress || changes.activityLog || changes.lastHarvest) {
    void renderCoach();
    if (changes.lastHarvest) void renderLastHarvest();
  }
});

load().then(async () => {
  await detectCurrentStore();
  await refreshAll();
});
