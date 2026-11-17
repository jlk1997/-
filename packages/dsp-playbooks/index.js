const harvestApi = require("./harvest");
const uploadApi = require("./upload");
const runnerApi = require("./runner");

const PLAYBOOKS = {
  netease: { name: "网易云音乐", harvestUrl: "https://music.163.com/st/musician", uploadUrl: "https://music.163.com/st/musician", region: "cn" },
  qq_music: { name: "QQ 音乐", harvestUrl: "https://y.qq.com/portal/", uploadUrl: "https://y.qq.com/portal/", region: "cn" },
  kugou: { name: "酷狗音乐", harvestUrl: "https://www.kugou.com/musician/", uploadUrl: "https://www.kugou.com/musician/", region: "cn" },
  kuwo: { name: "酷我音乐", harvestUrl: "https://www.kuwo.cn/musician", uploadUrl: "https://www.kuwo.cn/musician", region: "cn" },
  qishui: { name: "汽水音乐", harvestUrl: "https://music.douyin.com/", uploadUrl: "https://music.douyin.com/", region: "cn" },
  bilibili: { name: "B 站音频", harvestUrl: "https://member.bilibili.com/", uploadUrl: "https://member.bilibili.com/", region: "cn" },
  spotify: { name: "Spotify", harvestUrl: "https://artists.spotify.com/", uploadUrl: "https://artists.spotify.com/", region: "global" },
  apple_music: { name: "Apple Music", harvestUrl: "https://artists.apple.com/", uploadUrl: "https://artists.apple.com/", region: "global" },
  youtube_music: { name: "YouTube Music", harvestUrl: "https://studio.youtube.com/", uploadUrl: "https://studio.youtube.com/", region: "global" },
  tiktok_music: { name: "TikTok Music", harvestUrl: "https://www.tiktok.com/studio", uploadUrl: "https://www.tiktok.com/studio", region: "global" },
  amazon_music: { name: "Amazon Music", harvestUrl: "https://artists.amazon.com/", uploadUrl: "https://artists.amazon.com/", region: "global" },
  deezer: { name: "Deezer", harvestUrl: "https://www.deezer.com/", uploadUrl: "https://www.deezer.com/", region: "global" },
  wechat_channels: { name: "微信视频号", harvestUrl: "https://channels.weixin.qq.com/", uploadUrl: "https://channels.weixin.qq.com/", region: "cn" },
  douyin_musician: { name: "抖音音乐人", harvestUrl: "https://creator.douyin.com/", uploadUrl: "https://creator.douyin.com/", region: "cn" },
  kuaishou_musician: { name: "快手音乐人", harvestUrl: "https://cp.kuaishou.com/", uploadUrl: "https://cp.kuaishou.com/", region: "cn" },
  soundcloud: { name: "SoundCloud", harvestUrl: "https://soundcloud.com/", uploadUrl: "https://soundcloud.com/upload", region: "global" },
  bandcamp: { name: "Bandcamp", harvestUrl: "https://bandcamp.com/", uploadUrl: "https://bandcamp.com/", region: "global" },
};

function listPlaybooks() {
  return Object.entries(PLAYBOOKS).map(([code, spec]) => ({ code, ...spec }));
}

function playbook(code) {
  return PLAYBOOKS[code] || null;
}

function health(code) {
  const spec = playbook(code);
  if (!spec) return { ok: false, code, issues: ["unknown_playbook"] };
  const steps = runnerApi.stepsFor(code) || {};
  const statsUrls = steps.statsUrls || (spec.harvestUrl ? [spec.harvestUrl] : []);
  const waitSelectors = runnerApi.healCandidates(code);
  const issues = [];
  if (!statsUrls.length) issues.push("missing_stats_url");
  if (!(waitSelectors.primary || []).length && !(waitSelectors.alternateSelectors || []).length) {
    issues.push("missing_wait_selectors");
  }
  return {
    ok: issues.length === 0,
    code,
    ...spec,
    statsUrls,
    issues,
    healCandidates: waitSelectors,
  };
}

function upload(code, payload) {
  const spec = playbook(code);
  return {
    ...uploadApi.planUpload(code, spec, payload),
    fillAuthorizedForm: uploadApi.fillAuthorizedForm,
  };
}

function harvest(doc, code) {
  return (harvestApi.harvestChannel || harvestApi.harvestVisibleTables)(doc, code);
}

function confirmLive(url, code) {
  const spec = playbook(code);
  return { ok: Boolean(url), store_ref: url || "", channel: code, harvest_url: spec && spec.harvestUrl };
}

module.exports = {
  PLAYBOOKS,
  listPlaybooks,
  playbook,
  health,
  upload,
  harvest,
  confirmLive,
  harvestVisibleTables: harvestApi.harvestVisibleTables,
  harvestChannel: harvestApi.harvestChannel || harvestApi.harvestVisibleTables,
  parseOfficialCsv: harvestApi.parseOfficialCsv,
  EXTRACTOR_VERSION: harvestApi.EXTRACTOR_VERSION,
  fillAuthorizedForm: uploadApi.fillAuthorizedForm,
  attachReleaseAssets: uploadApi.attachReleaseAssets,
  setInputFile: uploadApi.setInputFile,
  classifyFileInputs: uploadApi.classifyFileInputs,
  looksLikeStorePage: uploadApi.looksLikeStorePage,
  CHANNEL_UPLOAD_GUIDES: uploadApi.CHANNEL_UPLOAD_GUIDES,
  trySelectors: runnerApi.trySelectors,
  healCandidates: runnerApi.healCandidates,
  detectChannel: runnerApi.detectChannel,
  detectChannelFromDoc: runnerApi.detectChannelFromDoc,
  installCsvTrap: runnerApi.installCsvTrap,
  drainCsvTrap: runnerApi.drainCsvTrap,
  detectLoginWall: runnerApi.detectLoginWall,
  mergeRows: runnerApi.mergeRows,
  readyState: runnerApi.readyState,
  findExportHrefs: runnerApi.findExportHrefs,
  runHarvest: runnerApi.run,
  harvestSteps: runnerApi.stepsFor,
};
