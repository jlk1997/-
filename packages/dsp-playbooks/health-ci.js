const fs = require("fs");
const path = require("path");
const {
  health,
  listPlaybooks,
  harvestVisibleTables,
  harvestChannel,
  parseOfficialCsv,
  fillAuthorizedForm,
  classifyFileInputs,
  attachReleaseAssets,
  setInputFile,
  looksLikeStorePage,
  CHANNEL_UPLOAD_GUIDES,
  upload,
  detectChannel,
  detectChannelFromDoc,
  detectLoginWall,
  mergeRows,
  readyState,
  findExportHrefs,
  harvestSteps,
  runHarvest,
  healCandidates,
} = require("./index");

const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "health-rows.json"), "utf8"));
const rows = fixture.rows || [];
if (rows.length < 2) {
  console.error("health fixture needs at least 2 rows");
  process.exit(1);
}
for (const row of rows) {
  if (!row.channel_code || !row.title) {
    console.error("fixture row missing channel_code/title", row);
    process.exit(1);
  }
  if (!health(row.channel_code).ok) {
    console.error("unknown playbook", row.channel_code);
    process.exit(1);
  }
}
const books = listPlaybooks();
if (books.length < 17) {
  console.error("expected 17 store playbooks, got", books.length);
  process.exit(1);
}

const { JSDOM } = (() => {
  try {
    return { JSDOM: null };
  } catch {
    return { JSDOM: null };
  }
})();
function fixtureDoc(html) {
  const tables = [];
  const tableRe = /<table[^>]*>([\s\S]*?)<\/table>/gi;
  let tableMatch;
  while ((tableMatch = tableRe.exec(html))) {
    const rows = [];
    const trRe = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
    let trMatch;
    while ((trMatch = trRe.exec(tableMatch[1]))) {
      const cells = [];
      const cellRe = /<(td|th)[^>]*>([\s\S]*?)<\/\1>/gi;
      let cellMatch;
      while ((cellMatch = cellRe.exec(trMatch[1]))) {
        cells.push({ tag: cellMatch[1].toLowerCase(), text: cellMatch[2].replace(/<[^>]+>/g, "").trim() });
      }
      rows.push(cells);
    }
    tables.push(rows);
  }
  const cards = [];
  const cardRe = /<(?:div|li)([^>]*data-vibe-row[^>]*)>/gi;
  let cardMatch;
  while ((cardMatch = cardRe.exec(html))) {
    const attrs = {};
    const attrRe = /(data-[\w-]+)=["']([^"']*)["']/g;
    let attrMatch;
    while ((attrMatch = attrRe.exec(cardMatch[1]))) {
      attrs[attrMatch[1]] = attrMatch[2];
    }
    cards.push({
      getAttribute(name) {
        return attrs[name] || "";
      },
      querySelector() {
        return null;
      },
    });
  }
  return {
    querySelectorAll(sel) {
      if (sel === "table") {
        return tables.map((rows) => ({
          querySelectorAll(inner) {
            if (String(inner).includes("thead th") || String(inner).includes("tr:first-child")) {
              return (rows[0] || []).map((cell) => ({ textContent: cell.text }));
            }
            if (inner === "tr") {
              return rows.map((row) => ({
                querySelectorAll() {
                  return row.filter((cell) => cell.tag === "td").map((cell) => ({ textContent: cell.text }));
                },
              }));
            }
            return [];
          },
        }));
      }
      if (
        String(sel).includes("data-vibe-row") ||
        String(sel).includes("song-item") ||
        String(sel).includes("song_item") ||
        String(sel).includes("track-card") ||
        String(sel).includes("data-testid") ||
        String(sel).includes("song-row") ||
        String(sel).includes("data-views")
      ) {
        return cards;
      }
      return [];
    },
  };
}

if (!JSDOM) {
  const fakeDoc = {
    querySelectorAll() {
      return [];
    },
  };
  const extracted = harvestVisibleTables(fakeDoc, "netease");
  if (!Array.isArray(extracted)) {
    console.error("harvestVisibleTables must return an array");
    process.exit(1);
  }
}

const harvestFixtures = [
  { code: "netease", file: "netease.html", currency: "CNY", minRevenue: 3600 },
  { code: "spotify", file: "spotify.html", currency: "USD", minRevenue: 1200 },
  { code: "netease", file: "netease-cards.html", currency: "CNY", minRevenue: 3600 },
  { code: "apple_music", file: "apple.html", currency: "USD", minRevenue: 1800 },
  { code: "qishui", file: "qishui.html", currency: "CNY", minRevenue: 2800 },
  { code: "qq_music", file: "qq.html", currency: "CNY", minRevenue: 4200 },
  { code: "kugou", file: "kugou.html", currency: "CNY", minRevenue: 3100 },
  { code: "youtube_music", file: "youtube.html", currency: "USD", minRevenue: 1900 },
  { code: "douyin_musician", file: "douyin.html", currency: "CNY", minRevenue: 2750 },
];
for (const spec of harvestFixtures) {
  const html = fs.readFileSync(path.join(__dirname, "fixtures", "harvest", spec.file), "utf8");
  const rows = harvestChannel(fixtureDoc(html), spec.code);
  if (rows.length !== 1) {
    console.error("fixture extractor missed rows", spec.code, rows);
    process.exit(1);
  }
  const row = rows[0];
  if (row.title.indexOf("Night Drive") < 0 || row.track_code !== "VSAAAAAAAABBBB") {
    console.error("fixture title/code mismatch", spec.code, row);
    process.exit(1);
  }
  if (row.currency !== spec.currency || row.revenue_minor < spec.minRevenue) {
    console.error("fixture revenue mismatch", spec.code, row);
    process.exit(1);
  }
  if (!row.extractor_version || row.confidence < 0.8) {
    console.error("extractor must stamp version and confidence", spec.code, row);
    process.exit(1);
  }
}

const planned = upload("netease", { title_with_code: "Night Drive [VSAAAAAAAABBBB]", isrc: "VSAAAAAAAABBBB" });
if (!planned.ok || planned.action !== "upload") {
  console.error("upload playbook missing");
  process.exit(1);
}
const filled = fillAuthorizedForm(
  {
    querySelector(sel) {
      if (String(sel).includes("title")) return { value: "", focus() {}, dispatchEvent() {} };
      return null;
    },
  },
  { title_with_code: "Night Drive [VSAAAAAAAABBBB]" },
);
if (!filled.ok || !filled.filled.includes("title")) {
  console.error("fillAuthorizedForm should write title_with_code", filled);
  process.exit(1);
}
if (planned.listingAsset !== "master" || planned.payload.listing_asset !== "master") {
  console.error("upload plan must list the stereo master, not stems", planned);
  process.exit(1);
}
const classified = classifyFileInputs({
  querySelectorAll() {
    return [
      { name: "audio", accept: "audio/wav", getAttribute: () => "", closest: () => ({ textContent: "歌曲文件" }) },
      { name: "stems", accept: ".zip", getAttribute: () => "", closest: () => ({ textContent: "原创证明" }) },
    ];
  },
});
if (!classified.master || !classified.evidence || classified.listingAsset !== "master") {
  console.error("file inputs must split master vs originality evidence", classified);
  process.exit(1);
}

function fakeFile(name, type) {
  return { name, type, size: 16 };
}
function uploadFixtureDoc() {
  const master = {
    name: "song",
    accept: "audio/wav",
    files: { length: 0 },
    getAttribute: () => "",
    closest: () => ({ textContent: "歌曲文件" }),
    focus() {},
    dispatchEvent() {},
  };
  const evidence = {
    name: "proof",
    accept: ".zip",
    files: { length: 0 },
    getAttribute: () => "",
    closest: () => ({ textContent: "原创证明" }),
    focus() {},
    dispatchEvent() {},
  };
  const title = { value: "", focus() {}, dispatchEvent() {} };
  return {
    querySelector(sel) {
      if (String(sel).includes("title") || String(sel).includes("songName") || String(sel).includes("歌曲")) return title;
      if (String(sel).includes("submit") || String(sel).includes("publish")) return { click() {}, disabled: false };
      return null;
    },
    querySelectorAll(sel) {
      if (String(sel).includes("file")) return [master, evidence];
      return [];
    },
    _master: master,
    _evidence: evidence,
  };
}
const CONNECTOR_FULL = [
  "netease",
  "qq_music",
  "kugou",
  "kuwo",
  "qishui",
  "bilibili",
  "douyin_musician",
  "kuaishou_musician",
  "wechat_channels",
  "soundcloud",
  "bandcamp",
];
for (const code of CONNECTOR_FULL) {
  const doc = uploadFixtureDoc();
  const attached = attachReleaseAssets(doc, {
    channel: code,
    masterFile: fakeFile("master.wav", "audio/wav"),
    evidenceFile: fakeFile("originality.zip", "application/zip"),
  });
  if (!attached.attached || !attached.filled.includes("master") || !(doc._master.files && doc._master.files.length)) {
    console.error("connector_full attach must set input.files", code, attached, doc._master.files);
    process.exit(1);
  }
  if (attached.filled.includes("master") && !doc._master.files.length) {
    console.error("attach claimed success without files.length", code);
    process.exit(1);
  }
}
const uploadJs = fs.readFileSync(path.join(__dirname, "upload.js"), "utf8");
if (!uploadJs.includes("audioFileSelector") || !uploadJs.includes("function firstMatch")) {
  console.error("attachReleaseAssets should honor playbook file selectors");
  process.exit(1);
}
const pathOnly = attachReleaseAssets(uploadFixtureDoc(), { master_path: "/tmp/master.wav" });
if (pathOnly.attached || pathOnly.ok) {
  console.error("payload path must not count as attach success", pathOnly);
  process.exit(1);
}
if (typeof setInputFile !== "function") {
  console.error("setInputFile must be exported");
  process.exit(1);
}
const uploadHtml = fs.readFileSync(path.join(__dirname, "fixtures", "upload-netease.html"), "utf8");
if (uploadHtml.indexOf('input type="file"') < 0 && uploadHtml.indexOf("type=\"file\"") < 0) {
  console.error("upload fixture missing file input");
  process.exit(1);
}
const CN_UPLOAD_FIXTURES = {
  netease: "upload-netease.html",
  qq_music: "upload-qq.html",
  kugou: "upload-kugou.html",
  kuwo: "upload-kuwo.html",
  qishui: "upload-qishui.html",
  bilibili: "upload-bilibili.html",
  wechat_channels: "upload-wechat.html",
  douyin_musician: "upload-douyin.html",
  kuaishou_musician: "upload-kuaishou.html",
};
for (const [code, file] of Object.entries(CN_UPLOAD_FIXTURES)) {
  const guide = CHANNEL_UPLOAD_GUIDES[code] || {};
  if (!guide.titleSelector || !guide.submitSelector) {
    console.error("upload guide must fill title and submit", code, guide);
    process.exit(1);
  }
  const html = fs.readFileSync(path.join(__dirname, "fixtures", file), "utf8");
  if (html.indexOf("标题") < 0 && html.indexOf("歌曲") < 0 && html.indexOf("歌名") < 0) {
    console.error("upload fixture missing title field copy", code);
    process.exit(1);
  }
  if (html.indexOf("submit") < 0 && html.indexOf("发布") < 0 && html.indexOf("发表") < 0) {
    console.error("upload fixture missing submit", code);
    process.exit(1);
  }
}
const LIVE_SAMPLES = {
  netease: "https://music.163.com/song?id=88",
  qq_music: "https://y.qq.com/n/ryqq/songDetail/001",
  kugou: "https://www.kugou.com/song/#hash=abc",
  kuwo: "https://www.kuwo.cn/play_detail/12345",
  qishui: "https://music.douyin.com/qishui/track/1",
  bilibili: "https://www.bilibili.com/audio/au1",
  wechat_channels: "https://channels.weixin.qq.com/export/post/abc",
  douyin_musician: "https://www.douyin.com/video/123",
  kuaishou_musician: "https://www.kuaishou.com/short-video/123",
};
for (const [code, url] of Object.entries(LIVE_SAMPLES)) {
  if (!looksLikeStorePage(url, code)) {
    console.error("readonly receipt must recognize store page", code, url);
    process.exit(1);
  }
}

function assertSame(left, right, label) {
  const a = fs.readFileSync(left, "utf8").replace(/\r\n/g, "\n");
  const b = fs.readFileSync(right, "utf8").replace(/\r\n/g, "\n");
  if (a !== b) {
    console.error(label + " drifted from packages/dsp-playbooks");
    process.exit(1);
  }
}
const repoRoot = path.join(__dirname, "..", "..");
assertSame(path.join(__dirname, "harvest.js"), path.join(repoRoot, "apps", "creator-connector", "harvest-core.js"), "harvest-core.js");
assertSame(path.join(__dirname, "upload.js"), path.join(repoRoot, "apps", "creator-connector", "upload-core.js"), "upload-core.js");
assertSame(path.join(__dirname, "runner.js"), path.join(repoRoot, "apps", "creator-connector", "runner-core.js"), "runner-core.js");

const csvRows = parseOfficialCsv(
  "Title,Streams,Revenue\nNight Drive [VSAAAAAAAABBBB],8400,$12.00\n",
  "spotify",
);
if (!csvRows.length || csvRows[0].track_code !== "VSAAAAAAAABBBB" || csvRows[0].confidence < 0.9) {
  console.error("parseOfficialCsv failed", csvRows);
  process.exit(1);
}

if (detectChannel("https://artists.spotify.com/c/music") !== "spotify") {
  console.error("detectChannel failed for spotify");
  process.exit(1);
}
if (detectChannel("https://music.163.com/st/musician") !== "netease") {
  console.error("detectChannel failed for netease");
  process.exit(1);
}

const P0 = ["netease", "qq_music", "qishui", "kugou", "kuwo", "douyin_musician", "spotify", "apple_music", "youtube_music"];
for (const code of P0) {
  const steps = harvestSteps(code);
  if (!steps.statsUrls || !steps.statsUrls.length || !steps.waitSelectors.length) {
    console.error("P0 playbook missing executable steps", code, steps);
    process.exit(1);
  }
  const report = health(code);
  if (!report.ok || !(report.healCandidates && report.healCandidates.statsUrls || []).length) {
    console.error("playbook health must expose heal candidates", code, report);
    process.exit(1);
  }
  const heal = healCandidates(code);
  if (!heal || !Array.isArray(heal.alternateSelectors)) {
    console.error("healCandidates missing alternateSelectors", code, heal);
    process.exit(1);
  }
}

const quotedCsv = parseOfficialCsv(
  'Title,Streams,Revenue\n"Night Drive [VSAAAAAAAABBBB], remix",8400,"$12.00"\n',
  "spotify",
);
if (!quotedCsv.length || quotedCsv[0].title.indexOf("remix") < 0 || quotedCsv[0].revenue_minor < 1200) {
  console.error("quoted CSV parse failed", quotedCsv);
  process.exit(1);
}

const loginDoc = {
  body: { innerText: "请登录后继续 二维码" },
  location: { href: "https://music.163.com/login" },
  querySelector() {
    return null;
  },
  querySelectorAll() {
    return [];
  },
};
if (!detectLoginWall(loginDoc, "netease")) {
  console.error("detectLoginWall missed login page");
  process.exit(1);
}
const readyDoc = {
  body: { innerText: "曲名 播放 收益" },
  location: { href: "https://music.163.com/st/musician" },
  querySelector(sel) {
    return sel === "table" ? {} : null;
  },
  querySelectorAll() {
    return [];
  },
};
if (!readyState(readyDoc, "netease").ready) {
  console.error("readyState should see table");
  process.exit(1);
}

const merged = mergeRows(
  [{ title: "A", streams: 1, revenue_minor: 100, track_code: "VSAAAAAAAABBBB" }],
  [
    { title: "A", streams: 1, revenue_minor: 100, track_code: "VSAAAAAAAABBBB" },
    { title: "B", streams: 2, revenue_minor: 200, track_code: "VSCCCCCCCCDDDD" },
  ],
);
if (merged.length !== 2) {
  console.error("mergeRows should drop duplicates", merged);
  process.exit(1);
}

const csvDoc = {
  body: { innerText: "" },
  location: { href: "https://music.163.com/st/musician" },
  querySelector() {
    return null;
  },
  querySelectorAll(sel) {
    if (String(sel).includes(".csv")) return [{ href: "https://music.163.com/export.csv" }];
    return [];
  },
};
if (!findExportHrefs(csvDoc, "netease").length) {
  console.error("findExportHrefs missed csv link");
  process.exit(1);
}

const csvHtml = fs.readFileSync(path.join(__dirname, "fixtures", "harvest", "csv-link.html"), "utf8");
if (csvHtml.indexOf("export.csv") < 0) {
  console.error("csv-link fixture missing");
  process.exit(1);
}
const loginRun = runHarvest(loginDoc, "netease");
if (loginRun.reason !== "needs_challenge") {
  console.error("runHarvest should mark login wall", loginRun);
  process.exit(1);
}

const markedDoc = {
  documentElement: {
    getAttribute(name) {
      return name === "data-vibe-channel" ? "netease" : "";
    },
  },
  location: { href: "chrome-extension://local/fixtures/self-test.html" },
  querySelector() {
    return null;
  },
};
if (detectChannelFromDoc(markedDoc) !== "netease") {
  console.error("detectChannelFromDoc missed fixture channel");
  process.exit(1);
}

const selfTest = fs.readFileSync(path.join(repoRoot, "apps", "creator-connector", "fixtures", "self-test.html"), "utf8");
const selfRows = harvestChannel(fixtureDoc(selfTest), "netease");
if (selfRows.length < 2 || selfRows[0].track_code !== "VSAAAAAAAABBBB") {
  console.error("self-test fixture should harvest two coded rows", selfRows);
  process.exit(1);
}

const ui = require(path.join(repoRoot, "apps", "creator-connector", "ui-shared.js"));
if (ui.coach({ token: "" }).action !== "pair") {
  console.error("coach should ask to pair");
  process.exit(1);
}
if (ui.coach({ token: "x", online: false }).tone !== "err") {
  console.error("coach should flag dead token");
  process.exit(1);
}
if (ui.coach({ token: "x", online: true, tabChannel: "netease", seats: [] }).action !== "authorize") {
  console.error("coach should authorize recognized store tab");
  process.exit(1);
}
if (ui.coach({ token: "x", progress: { busy: true, title: "正在收割网易云音乐" } }).tone !== "busy") {
  console.error("coach should show harvest progress");
  process.exit(1);
}
if (ui.reasonLabel("selector_broke") !== "对账表没读到") {
  console.error("selector_broke label drifted");
  process.exit(1);
}
if (
  ui.coach({
    token: "x",
    online: true,
    seats: [{ ownership: "user", channel_code: "netease" }],
    lastHarvest: { ok: false, reason: "selector_broke", channel: "netease", count: 0 },
  }).tone !== "err"
) {
  console.error("coach should surface selector_broke");
  process.exit(1);
}
if (ui.coach({ token: "x", online: true, tokenExpiresAt: "2010-01-01T00:00:00Z" }).action !== "pair") {
  console.error("coach should re-pair expired token");
  process.exit(1);
}
if (ui.coach({ token: "x", online: true, extensionVersion: "0.6.0", minExtensionVersion: "0.8.0" }).tone !== "err") {
  console.error("coach should block stale extension");
  process.exit(1);
}
if (ui.versionLess("0.7.0", "0.8.0") !== true || ui.versionLess("0.8.0", "0.8.0") !== false) {
  console.error("version compare drifted");
  process.exit(1);
}

const copy = ui.overlayCopy();
if (!copy.sync || !copy.needField || !copy.syncFail || !copy.openPortal || !copy.changeFields || !copy.needPair) {
  console.error("overlay copy missing sync labels");
  process.exit(1);
}
const redacted = ui.filterHarvestRows(
  [{ title: "Night Drive", isrc: "US-1", streams: 9, work_id: "w1", raw: { geo: "CN", audience: 3 } }],
  { streams: true, tracks: false, geo: false, audience: false },
)[0];
if (redacted.title !== "redacted" || redacted.isrc || redacted.work_id || redacted.raw.geo || redacted.streams !== 9) {
  console.error("filterHarvestRows did not honor field checks", redacted);
  process.exit(1);
}

const { execFileSync } = require("child_process");
const connectorDir = path.join(repoRoot, "apps", "creator-connector");
const backgroundSrc = fs.readFileSync(path.join(connectorDir, "background.js"), "utf8");
if (!backgroundSrc.includes("/seats/connector-config")) {
  console.error("background should fetch /seats/connector-config");
  process.exit(1);
}
if (backgroundSrc.includes("settle: false, upload: false")) {
  console.error("connect must not reset optional scopes");
  process.exit(1);
}
if (!backgroundSrc.includes("registerWebBaseBridge") || !backgroundSrc.includes("watchStoreReceipt")) {
  console.error("background should register the live H5 bridge and watch store receipts");
  process.exit(1);
}
if (!backgroundSrc.includes("fillAndAttachOnTab") || !backgroundSrc.includes("/distribution/assist/jobs/")) {
  console.error("background should fetch master bytes and attach files");
  process.exit(1);
}
if (!backgroundSrc.includes("plantFileOnTab") || !backgroundSrc.includes("fetchAssistAsset")) {
  console.error("background should fetch master in the worker and plant File chunks");
  process.exit(1);
}
if (!backgroundSrc.includes("ensureReadyStoreTab") || !backgroundSrc.includes("injectStoreRuntime")) {
  console.error("background should wait for the store tab and inject after optional permission");
  process.exit(1);
}
if (!backgroundSrc.includes("saveOpenSeatSession") || !backgroundSrc.includes("uploadUrlFor") || !backgroundSrc.includes("seatJobsBusy")) {
  console.error("background should save session after fill, open the upload form, and mutex the seat queue");
  process.exit(1);
}
if (!backgroundSrc.includes("musician.douyin.com") || !backgroundSrc.includes("stale_extension")) {
  console.error("background should request qishui upload host and refuse stale clients");
  process.exit(1);
}
if (!backgroundSrc.includes("noteAssistProgress") || !backgroundSrc.includes("last_progress")) {
  console.error("background should report live delivery progress on heartbeat");
  process.exit(1);
}
if (backgroundSrc.includes('error: "fill_incomplete", needs_runtime: true')) {
  console.error("fill_incomplete must not busy-loop via needs_runtime");
  process.exit(1);
}
if (!backgroundSrc.includes("/seats/queue") || !backgroundSrc.includes("page-event")) {
  console.error("background should read the seat queue and accept page submit events");
  process.exit(1);
}
if (!backgroundSrc.includes("watchConfirmSubmit") || !backgroundSrc.includes("noteUserSubmitted")) {
  console.error("background should notice the in-page confirm submit");
  process.exit(1);
}
if (!backgroundSrc.includes("sessionStorage") || !backgroundSrc.includes("readonly: true")) {
  console.error("background should snapshot sessionStorage and keep assist poll read-only");
  process.exit(1);
}
const bridgeSrc = fs.readFileSync(path.join(connectorDir, "bridge.js"), "utf8");
if (!bridgeSrc.includes("BITTUNE_POLL") || !bridgeSrc.includes("BITTUNE_DELIVERY")) {
  console.error("H5 bridge should wake the seat queue and forward delivery events");
  process.exit(1);
}
const manifest = JSON.parse(fs.readFileSync(path.join(connectorDir, "manifest.json"), "utf8"));
if (!JSON.stringify(manifest).includes("139.199.90.218")) {
  console.error("connector must talk to the live H5 origin");
  process.exit(1);
}
if (!JSON.stringify(manifest).includes("superformersmusic.com")) {
  console.error("connector must also trust superformersmusic.com");
  process.exit(1);
}
if (manifest.version !== "0.14.0") {
  console.error("connector version should be 0.14.0 for assist-skip-attach + metrics_only");
  process.exit(1);
}
if (!backgroundSrc.includes("const canPlant = level === \"connector_full\"") || !backgroundSrc.includes("assist_skip_attach")) {
  console.error("connector must skip planting the master unless automation_level is connector_full");
  process.exit(1);
}
if (!Array.isArray(manifest.optional_host_permissions) || !manifest.optional_host_permissions.some((item) => String(item).includes("music.163.com"))) {
  console.error("store hosts should be optional_host_permissions");
  process.exit(1);
}
if (!looksLikeStorePage("https://music.163.com/#/song?id=1", "netease")) {
  console.error("looksLikeStorePage should accept a NetEase song page");
  process.exit(1);
}
if (looksLikeStorePage("https://music.163.com/st/musician", "netease")) {
  console.error("looksLikeStorePage must reject the musician portal");
  process.exit(1);
}
if (!CHANNEL_UPLOAD_GUIDES.spotify || !CHANNEL_UPLOAD_GUIDES.soundcloud) {
  console.error("upload guides should cover global volume stores");
  process.exit(1);
}
const overlaySrc = fs.readFileSync(path.join(connectorDir, "overlay.js"), "utf8");
if (!overlaySrc.includes("dataset.bittuneOverlay")) {
  console.error("overlay should mark the page so the worker can detect injection");
  process.exit(1);
}
for (const file of ["overlay.js", "ui-shared.js", "background.js", "popup.js"]) {
  execFileSync(process.execPath, ["--check", path.join(connectorDir, file)], { stdio: "pipe" });
}

console.log("dsp-playbooks health ok", books.length, "stores", rows.length, "fixture rows");
