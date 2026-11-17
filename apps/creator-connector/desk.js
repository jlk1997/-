const ui = self.VibeUi || {};
const $ = (id) => document.getElementById(id);

const P0 = [
  ["netease", "网易云"],
  ["qq_music", "QQ 音乐"],
  ["qishui", "汽水"],
  ["kugou", "酷狗"],
  ["kuwo", "酷我"],
  ["douyin_musician", "抖音"],
  ["spotify", "Spotify"],
  ["apple_music", "Apple"],
  ["youtube_music", "YouTube"],
];

function paintStores() {
  const box = $("stores");
  box.innerHTML = "";
  P0.forEach(([code, label]) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.onclick = async () => {
      await chrome.storage.local.set({ channel: code });
      await chrome.runtime.sendMessage({ type: "open-stats", channel: code });
    };
    box.appendChild(btn);
  });
}

async function render() {
  const state = await chrome.runtime.sendMessage({ type: "ui-state" }).catch(() => ({}));
  const seatsRes = state.token ? await chrome.runtime.sendMessage({ type: "list-seats" }).catch(() => null) : null;
  const seats = ((seatsRes && seatsRes.seats) || []).filter((seat) => seat.ownership === "user" || seat.runtime === "extension");
  const coach = ui.coach
    ? ui.coach({
        token: state.token,
        online: state.syncOk !== false && Boolean(state.token),
        seats,
        lastHarvest: state.lastHarvest,
        progress: state.harvestProgress,
        tokenExpiresAt: state.tokenExpiresAt,
        minExtensionVersion: state.minExtensionVersion,
        extensionVersion: state.extensionVersion || chrome.runtime.getManifest().version,
      })
    : { title: "比特音", hint: "", tone: "need" };
  $("coach").className = `coach ${coach.tone || "need"}`;
  $("coachTitle").textContent = coach.title;
  $("coachHint").textContent = coach.hint;

  const queueBox = $("queue");
  if (queueBox) {
    const queued = state.token ? await chrome.runtime.sendMessage({ type: "list-queue" }).catch(() => null) : null;
    const jobs = (queued && queued.jobs) || [];
    queueBox.innerHTML = jobs.length
      ? jobs
          .slice(0, 8)
          .map((job) => {
            const kind = job.kind === "upload" ? "代交" : job.kind === "harvest" || job.kind === "sync_metrics" ? "同步" : job.kind || "任务";
            const name = ui.channelName ? ui.channelName(job.channel_code) : job.channel_code;
            const extra = job.automation_level === "metrics_only" ? " · 只收数据" : job.automation_level === "connector_assist" || job.degraded ? " · 只填表" : "";
            return `<div class="seat"><div><b>${name} · ${kind}</b><div class="hint">${job.title || job.status || ""}${job.leased ? " · 执行中" : " · 排队"}${extra}</div></div></div>`;
          })
          .join("")
      : `<p class="hint">现在没有排队任务。发行台按下一键后会出现在这里。</p>`;
  }

  const last = state.lastHarvest;
  const live = state.lastDelivery;
  $("lastHarvest").innerHTML = live && live.event
    ? `${ui.formatWhen ? ui.formatWhen(live.at) : live.at || ""} · ${ui.channelName ? ui.channelName(live.channel_code) : live.channel_code} · ${live.event}${live.message ? ` · ${live.message}` : ""}${state.queueCount ? ` · 队列 ${state.queueCount}` : ""}`
    : last
    ? `${ui.formatWhen ? ui.formatWhen(last.at) : last.at} · ${ui.channelName ? ui.channelName(last.channel) : last.channel} · ${last.count || 0} 行 · ${ui.reasonLabel ? ui.reasonLabel(last.reason) : last.reason}${last.matched != null ? ` · 匹配 ${last.matched}` : ""}`
    : "还没有";

  const log = state.activityLog || [];
  $("log").innerHTML = log.length
    ? log
        .slice(0, 20)
        .map((row) => `<div class="${row.level === "err" ? "err" : row.level === "ok" ? "ok" : ""}">${ui.formatWhen ? ui.formatWhen(row.at) : ""} ${row.text}</div>`)
        .join("")
    : "还没有记录";

  const box = $("seats");
  box.innerHTML = "";
  if (!seats.length) {
    box.innerHTML = `<p class="hint">还没有授权席位。打开已登录的店后台，点扩展「交给比特音」。</p>`;
    return;
  }
  seats.forEach((seat) => {
    const el = document.createElement("div");
    el.className = "seat";
    const expired = ui.seatExpired ? ui.seatExpired(seat) : false;
    const health = (seat.extra && seat.extra.farm_health) || {};
    el.innerHTML = `<div><b>${(seat.playbook && seat.playbook.name) || (ui.channelName && ui.channelName(seat.channel_code))}</b><div class="hint">${expired ? "要重新登录" : seat.last_harvest_at || "尚未收割"}${health.rows != null ? ` · ${health.rows} 行` : ""}</div></div>`;
    const btn = document.createElement("button");
    btn.textContent = expired ? "去登录" : "同步";
    btn.onclick = async () => {
      btn.disabled = true;
      if (expired) {
        await chrome.runtime.sendMessage({ type: "open-stats", channel: seat.channel_code });
      } else {
        await chrome.runtime.sendMessage({ type: "harvest-seat", channel: seat.channel_code, seatId: seat.id });
      }
      btn.disabled = false;
      await render();
    };
    el.appendChild(btn);
    box.appendChild(el);
  });
}

$("poll").onclick = async () => {
  $("poll").disabled = true;
  await chrome.runtime.sendMessage({ type: "assist-poll" });
  await chrome.runtime.sendMessage({ type: "seat-poll" });
  $("poll").disabled = false;
  await render();
};

$("pair").onclick = async () => {
  try {
    const text = await navigator.clipboard.readText();
    const sliced = text.startsWith("BITTUNE_PAIR:") ? text.slice("BITTUNE_PAIR:".length) : text;
    const pair = JSON.parse(sliced);
    if (!pair.token || !pair.apiBase) throw new Error("剪贴板不是配对文本");
    await chrome.runtime.sendMessage({ type: "pair-settings", ...pair });
    await render();
  } catch (err) {
    $("coachHint").textContent = String(err.message || err);
  }
};

$("selfTest").onclick = () => chrome.runtime.sendMessage({ type: "open-self-test" });
$("openApp").onclick = () => chrome.runtime.sendMessage({ type: "open-app" });
$("unpair").onclick = async () => {
  await chrome.runtime.sendMessage({ type: "unpair" });
  await render();
};

chrome.storage.onChanged.addListener(() => void render());
paintStores();
void chrome.runtime.sendMessage({ type: "sync-now" }).finally(() => void render());
