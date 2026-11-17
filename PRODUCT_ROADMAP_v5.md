# Vibe Sorcery 产品路线图 v5.0

> **定位**：比特音是开放的创作者操作系统 —— 情绪出歌、轻工作室精编、多店发行、授权收获、按店按歌一本账。对照汽水「妙响」：不抢抖音流量，用全球收获 + 非独家权利赢。  
> **前提**：v4.0 已完成 Generation Control Stack（航点 + BPM/调性/种子/Remix/Cover + Studio UI）。  
> **原则**：不扩 MiniMax 未文档化字段；分发与能出片的精编进入内核；收获只走授权会话。社交仍做，但不压过精编/分发。

---

## 1. 现状与下一层目标

### 1.1 已具备（v4.0）

| 层 | 能力 |
|----|------|
| **创作** | Playlist / Single / Vocals / Text Journey；航点 AV；music_params；Cover/Remix |
| **管线** | Essentia 分析 → M3 prompt → music-2.6 → MinIO → HLS/C2PA 后处理 |
| **社区** | Feed、点赞、评论、Remix、举报 |
| **信任** | Provenance 谱系、SHA256 校验、.vibe 导出 |
| **运营** | Admin 统计/用量/Flags/举报；挑战活动后端 |

### 1.2 诚实对照：已闭环 / 停住 / 等密钥

> 不要再对外卖已关掉的缺口。关注 / 评论 / 挑战 / 榜单 / 搜索 / 同款墙 / `prompt_journey` 无 seed 出歌，今天都能走完。缺的是密钥、证书和人审，不是再开入口。

```mermaid
flowchart TB
  subgraph closed [今天能走完]
    A[出歌扣积分]
    B[发到发现]
    C[电台打卡 display_only]
    D[搜索 / 榜单 / 挑战]
  end
  subgraph parked [必须停住]
    E[无店页回执不得 live]
    F[结算草稿等人审]
    G[KYC 人工]
    H[提现后财务回单]
  end
  subgraph keys [等密钥或证书]
    I[DistroKid / TuneCore]
    J[Playwright 农场导航]
    K[微信虚拟支付道具]
    L[二进制 C2PA / 真链上]
  end
```

| 状态 | 事实 | 不许假装 |
|------|------|----------|
| **已闭环** | 生成、曲库、发到发现、搜索、榜单、挑战、同款墙、`prompt_journey` 无 seed | 不要再写「Playlist 必须 seed / 搜索未做」 |
| **停住** | 质检 → 完成带勾许可/店 → 连接器填表 → 店页回执 → CSV/收割 → 运营确认 → 申请提现 → `paid_manual` | 无回执不得 live；未签许可不得 settle；周五不是自动打款日；Spotify 默认只听数据 |
| **等密钥** | DistroKid、农场导航、KYC 厂商、虚拟支付道具、Demucs 镜像、HTTPS 证书、真 C2PA | 徽章不得写已认证 / 已上链 |
| **规格里有、不是上线闭环** | 嵌入播放器、原生连续包月、多租户 | 文档不要当已上线卖 |

---

## 2. 目标架构：五层产品栈

```mermaid
flowchart TB
  subgraph L5 [L5 平台与商业]
    SaaS[多租户 / API Key]
    Credits[额度与计费]
    Embed[嵌入播放器 / Open API]
  end
  subgraph L4 [L4 信任与权利]
    Prov[Provenance 2.0]
    License[Remix 许可 / 署名]
    C2PA[二进制 C2PA + 可选链上]
  end
  subgraph L3 [L3 生态与发现]
    Social[关注 / 主页 / 私信预留]
    Feed[个性化 + 话题 + 挑战榜]
    Collab[Remix 树 / 合集 / 共创]
  end
  subgraph L2 [L2 创作工作流]
    Studio[Studio 2.0 模板 + 高级]
    Presets[风格包 / 编曲模板]
    Batch[变体批量 / A-B 对比]
  end
  subgraph L1 [L1 生成内核]
    AV[情绪 AV + 航点]
    Music[music-2.6 + cover + lyrics]
    Post[HLS / 封面 / 波形]
  end
  L1 --> L2 --> L3 --> L4 --> L5
```

---

## 3. L2 — 音乐定制化（深度设计）

在 v4.0 的 L1–L4 控制栈之上，增加 **「模板 + 参考 + 编排」** 三层，降低专业参数门槛、提高可控上限。

### 3.1 定制能力矩阵

| 定制维度 | 用户入口 | 后端落点 | MiniMax 映射 |
|----------|----------|----------|--------------|
| **情绪曲线** | 曲线预设 / 航点编辑器 | `journey_math` + orchestrator | M3 prompt 中 step AV |
| **风格包** | Genre+Mood 卡片（一键） | `StylePreset` → moods/genres/BPM 默认 | prompt JSON |
| **编曲模板** | Intro→Build→Peak→Outro 结构 | 航点自动生成 + duration 分配 | 每步 duration + AV |
| **参考音频** | 上传 / 选作品「像这首」 | 分析参考轨 AV+moods，插值到 journey | seed + emotion 约束 |
| **人声** | 歌词编辑器 + 语言 | `lyrics` + `lyrics_optimizer` | music-2.6 官方字段 |
| **翻唱** | CoverStudio two-step | `cover_feature_id` + modified_lyrics | music-cover API |
| **Remix 意图** | 自然语言 + 原谱系 prompt | `remix_prompt()` 合并 provenance | M3 + music-2.6 |
| **复现** | Seed 输入 / Regenerate | job hash 或 user seed | `seed` 参数 |
| **导出** | WAV/MP3/HLS/`.vibe` | storage + provenance export | — |

### 3.2 Style Preset 系统（P0）

**问题**：BPM/调性/航点对普通用户仍抽象。  
**方案**：平台维护可版本化的 **Style Preset**（类似 DAW 模板）。

```yaml
# 示例 preset: lo-fi-night
id: lo-fi-night
label: Lo-Fi 深夜
moods: [melancholic, calm, nostalgic]
genres: [lo-fi, chillhop]
bpm_range: [70, 90]
key: Am
duration_preference: medium
default_curve: calm_to_energy
waypoint_template:   # 按 steps 缩放
  - { t: 0.0, arousal: 2, valence: 4 }
  - { t: 0.5, arousal: 4, valence: 5 }
  - { t: 1.0, arousal: 3, valence: 6 }
instrumental_default: true
```

**API**：
- `GET /config/presets` — 列表 + 分类（场景/流派/挑战官方包）
- `POST /studio/apply-preset` — 返回完整 `journey` + `music_params` + 可选 waypoints

**UI**：Create 页顶部「风格包」横向卡片；选中后预填 MusicParamsPanel + 可选航点。

**数据**：新表 `style_presets`（或 JSON 文件 + admin 编辑），挑战可绑定 `preset_id`。

### 3.3 编曲结构模板（P1）

将 journey **steps** 与 **段落语义** 绑定：

| 模板 | steps | 段落映射 |
|------|-------|----------|
| `classic_arc` | 6 | Intro×1 → Verse×2 → Chorus×2 → Outro×1 |
| `dj_set` | 8 | Warmup → Build×3 → Peak×2 → Cooldown×2 |
| `meditation` | 4 | Settle → Deepen → Hold → Release |

实现：`structure_template.py` 根据 steps 数量缩放航点时间与 AV 曲线，写入 `journey_config.structure`。

### 3.4 参考轨模式 Reference Track（P1）

**场景**：「我想要一首**像**《Track X》但走向更欢快」。

流程：
1. 选 `reference_work_id`（或上传）
2. Essentia 分析 → 基准 AV + moods/genres
3. 用户选偏移：`brighter` / `darker` / `more_energy` / 自定义 ΔAV
4. orchestrator 以参考 AV 为 step 0，按 curve 或 waypoints 偏移

**Schema 扩展**：
```json
{
  "reference": {
    "work_id": "uuid",
    "av_offset": { "arousal": +2, "valence": +1 }
  }
}
```

### 3.5 变体实验室 Variation Lab（P1）

**Studio 子模式**：同一 config 生成 N 个 seed 变体（N=3/5），网格试听 + 选主版本发布。

- API：`POST /works/generate/variations` → 单 job 多 work 或 fan-out 子 job
- UI：GenerationProgress 多列预览；「设为正式版」写入 parent 关系

### 3.6 人声与语言扩展（P2）

| 能力 | 说明 |
|------|------|
| 多语言歌词 | `lyrics_language` 贯通 generate + cover preprocess |
| 人声风格 hint | M3 prompt 层描述（非 API 未文档字段）：「气声」「说唱」「合唱」 |
| Speech-2.8 旁白 | 片头/片尾口播 → 与 music 分轨存储（未来） |

### 3.7 定制数据流（统一）

```mermaid
sequenceDiagram
  participant U as User
  participant S as Studio UI
  participant P as Preset/Structure
  participant O as Orchestrator
  participant M as MiniMax

  U->>S: 选风格包 + 微调 BPM/航点
  S->>P: apply-preset + overrides
  P->>S: journey + music_params
  S->>O: PlaylistGenerateRequest
  O->>M: build_music_prompt(target_av, bpm, key...)
  M->>O: audio bytes
  O->>O: provenance + post_process
```

---

## 4. L3 — 生态与发现

### 4.1 创作者身份（P0）

**路由**：`/u/[username]`

| 区块 | 数据 |
|------|------|
| 头部 | avatar, bio, 统计（作品/粉丝/获赞） |
| 作品 | 公开 works + playlists |
| 动态 | 发布的 posts |
| Remix 树 | 以某 work 为根的衍生链（只读图） |

**API 新增**：
- `GET /users/{username}/profile`
- `GET /users/{username}/works?visibility=public`
- `GET /users/{username}/posts`

**Follow 闭环**：
- Discover 卡片关注按钮 → `POST /community/follow/{username}`
- Feed 排序已有 follow 权重（`recommendation.py`），补 UI 即可

### 4.2 收藏与合集（P0）

**路由**：`/collections`

- 展示 `GET /collections` 返回的 bookmark
- 支持「公开合集」→ 类似 Spotify playlist sharing（`Collection.visibility` 字段扩展）

### 4.3 Discover 2.0（P1）

| 功能 | 实现 |
|------|------|
| 排序切换 | latest / popular / personalized（API 已有） |
| 话题 Tag | Post.tags 筛选 `GET /community/feed?tag=` |
| Remix 入口 | 卡片 → Studio（`?seed=` 已有）+ Remix drawer |
| 嵌入播放 | `/packageOps/pages/embed/index?workId=` 轻量播放器 |

### 4.4 挑战运营（P1）

**Challenges 页升级**：
- 挑战详情页内 **一键参赛**（选作品 / 跳转 Studio 用官方 preset）
- 排行榜：按 like_count + entry 时间
- Admin 创建挑战 UI（绑定 `target_curve` + `style_preset_id`）

**增长闭环**：
```
官方 Preset → 挑战 → 用户生成 → 发布 → Feed → Remix 链 → 回流 Studio
```

### 4.5 Remix 生态图谱（P1）

**路由**：`/remix/[workId]` 或 provenance 页增强

- 树状/时间线展示 `parent_work_id` 链
- 节点：封面、作者、AV、moods、「基于此 Remix」按钮
- 统计：衍生深度、总播放量（若后续加 analytics）

### 4.6 通知系统（P2）

| 事件 | 通道 |
|------|------|
| 生成完成 | 站内 + Web Push |
| 被点赞/评论 | 站内 |
| 挑战截止提醒 | 邮件/Web Push |
| Remix 被衍生 | 站内（「你的作品被 Remix 了」） |

**模型**：`notifications(user_id, type, payload, read_at)`

---

## 5. L4 — 信任、权利与溯源 2.0

### 5.1 Provenance 2.0（P1）

| 项 | v4 | v5 |
|----|----|----|
| 参数展示 | prompt/BPM/seed/AV | + waypoints JSON、preset_id、reference |
| 导出 | .vibe bundle | + 可读 PDF 谱系摘要 |
| C2PA | JSON sidecar | **二进制嵌入**（`c2pa-python`） |
| 链上 | mock tx | 可配置 Polygon/蚂蚁链 |

### 5.2 Remix 许可（P2）

Work 发布时选择：
- `allow_remix: bool`
- `attribution_required: bool`
- `commercial_use: enum`（personal / NC / commercial）

Remix API 校验许可；provenance 记录 `license_snapshot`。

### 5.3 内容安全（P1）

- Admin：用户封禁、作品下架、批量处理举报
- 生成前/发布前：敏感词 + 音频时长限制（已有 max_lyrics_length）
- 可选：MiniMax 内容审核回调

---

## 6. L5 — 平台、SaaS 与商业化

### 6.1 多租户（P2）

`tenant_id` 已在 User/Work/Post/Challenge：

1. 所有 list/query 加 `tenant_id` 过滤
2. JWT 含 `tenant_id`；注册时分配或邀请码
3. Admin 按租户看 stats/usage
4. 参考 [deploy/SAAS.md](deploy/SAAS.md) K8s 按租户限流

### 6.2 额度与计费（P2）

| 资源 | 计量 |
|------|------|
| music-2.6 调用 | 次/秒 |
| M3 tokens | ApiUsageLog 已有 |
| 存储 | MinIO 用量 |

**模型**：`user_credits` / `subscription_tier`  
**Gate**：生成前检查余额；Admin 手动充值；Stripe 预留 webhook。

### 6.3 Open API（P2）

- `POST /api/v1/keys` 创建 API Key（scoped: generate/read/feed）
- 文档站：基于 OpenAPI `/docs` 导出
- Webhook：`job.completed` → 第三方 DAW/视频工具

### 6.4 嵌入与分发（P3）

- iframe 播放器 + 「Made with Vibe Sorcery」
- 导出到：下载链接、HLS CDN URL、`.vibe` 文件
- 多店发行已进内核：完成带按填表 / 只听数据 / 运营队列分流；默认只勾能填表的店，未配对 Spotify 不自动勾
- DistroKid / TuneCore / 国内厂牌 webhook 为合作方主路；DOM 收获只做无 API 的店
- 北极星：**每创作者每月结算到的店数 × 账本可信度**（不对标抖音 DAU）

---

## 7. 客户端矩阵

| 能力 | Web | Mobile (Expo) | 小程序 (Taro) |
|------|-----|---------------|---------------|
| Studio 全参数 | ✅ v4 | Phase A: preset+playlist | Phase B: 单曲+预设 |
| HLS 播放 | ✅ | Phase A | 原生 audio 组件 |
| 社区完整 | ✅ v4 | Phase A: feed+follow | Phase B: feed |
| 挑战 | 部分 | Phase B | — |
| Provenance | ✅ | Phase B | — |
| 离线草稿 | — | Phase C | — |

**策略**：`packages/api-client` 为唯一 SDK；Taro H5 + 微信小程序共用 `apps/client`。

---

## 8. 实施分期（建议 12 周）

```mermaid
gantt
  title Vibe Sorcery v5 建议排期
  dateFormat YYYY-MM-DD
  section P0 生态基础
  创作者主页+Follow UI     :a1, 2026-07-07, 2w
  收藏页+公开合集         :a2, after a1, 1w
  Style Preset 系统       :a3, 2026-07-07, 2w
  section P1 定制深化
  编曲结构模板            :b1, after a3, 1w
  Reference Track 模式    :b2, after b1, 2w
  Variation Lab           :b3, after b2, 1w
  挑战UX+Remix图谱        :b4, after a2, 2w
  Discover排序+Tag        :b5, after a1, 1w
  section P1 信任
  Provenance2+C2PA嵌入    :c1, after b4, 2w
  Admin moderation增强    :c2, after c1, 1w
  section P2 平台
  多租户生效              :d1, after c2, 3w
  额度计费                :d2, after d1, 2w
  Mobile Phase A          :d3, after a3, 4w
  section P3 扩展
  Open API+Webhook        :e1, after d2, 2w
  通知系统                :e2, after d1, 2w
  Speech旁白/嵌入播放     :e3, after e1, 3w
```

### Phase 5（Week 1–3）— 生态基座 + 风格包
- [x] 创作者主页 + Follow UI（`pages/user` + FollowButton；不是独立 `/u/` 路由）
- [ ] `/collections` 收藏浏览
- [x] `StylePreset` 后端 + Create 风格包 UI
- [x] Discover 排序切换

### Phase 6（Week 4–6）— 定制深化
- [ ] 编曲结构模板 → 自动航点
- [x] Reference Track 选择器（权利检查后 embedding 仍未做）
- [x] Variation Lab 组件（多 seed 网格深度仍可加，不要标「未做」）
- [x] Challenges 页内参赛 + Admin 创建挑战

### Phase 7（Week 7–9）— 生态闭环
- [ ] Remix 衍生树可视化
- [ ] Provenance 2.0 + C2PA 二进制嵌入
- [ ] Admin 用户/作品 moderation
- [ ] Mobile Phase A（Feed + Preset Playlist + HLS）

### Phase 8（Week 10–12）— 平台化
- [ ] 多租户 query 隔离 + 租户 Admin
- [ ] 用户额度与生成 Gate
- [ ] Open API Key + job webhook
- [ ] 通知（生成完成 / 互动）

### Phase H0（约 8 周）— 手感像成品
- [x] 两版并排听 → 选主版本 → 切片 / 电台 / 确认一次发行
- [x] 发行向导 QC 通过走 `quickRelease`
- [x] 钱一览按店 / 按歌 / 按切片；席位失败文案「打开已登录的店后台」
- [x] 小程序远程登录 ack 后必 `runtime-kick`；连接器只在 H5/桌面

### Phase H1（约一季度）— 精编不输妙响
- [x] 可插拔分轨（审核级 Demucs；ffmpeg 频段 = preview ≠ review）+ 变速变调 + 一键母带
- [x] 锁词翻唱、续写 15–30 秒写入谱系、轻工作室撤销
- [x] MixGraph 美化台 / 调音台：会话内续写、换桥、同款写进节点，打成新立体声 Work；额度账不法币
- [x] 工作台接进发行主电路：Work B 带 `work_ids` / 切片窗 / 护照精编；待发行优先母带；市场套包进会话
- [x] 工作台接进通知 / 助手 / 轻编续写：完成通知回会话；`open_beautify` ≠ 风格包；失败不改 last_result
- [x] 发行闸优先 Work B：向导 / 一键代发 / 本周建议不拿被取代的原曲上架；曲库标美化母带
- [x] 本周掉落 / 电台试投 / 听感曲库优先或标明 Work B；个人中心任务回美化台；调音台旋钮覆盖官方包节点；Sync / 切片回执改投未上架母带
- [x] 参考轨 embedding 仅在权利检查后写入（不做「像某首热歌」）
- [x] 完成带：选版 / 工作台 / 创作者台共用一张卡；默认只勾能填表的店；无店页回执不得 live；用户席位收获须已签分发许可
- [x] 一键上店入口统一进创作者台完成带；向导只留给 QC / 元数据；小程序复制创作者台链接
- [x] 听感距离再炼：第一版偏移跨过「太近」；仍太近时质检露出再炼，工作台用更大偏移

### Phase H4 — 双控制台 2.0（MixGraph v2）
- [x] MixGraph v2：clips / regions / origin；渲染补 pan / solo / fade / trim；套包不踩用户剪辑
- [x] 电脑专业台：波形时间线 + 片段精编 + 三步教练 + 发布包预检（不含 clips）
- [x] 手机简易台：需求横滑 / 切头尾 / 四推子；出歌完成页建议美化 + 3 秒预听
- [x] 效果包飞轮：need_tags、分轨包、PackDemand 定制、创作者 OS 包收入 / 已发行数
- [x] 时间线选区再生成落成 take clip；同区多 take 选用后 bounce；失败不改 last_result_work_id
- [x] 会话露出 `waveform_url`；官方包可预烘焙 6 秒预听；Work B 回写 `applied_pack_id`
- [x] 上架包禁止外部 IR/采样；创作页商店只进配方货架；轻编变速变调映射进美化台；时间线内再生成 / H5 波形尺 / 未准备不甩空轨

### Phase H2（约两季度）— 收获护城河
- [x] 每店版本化抽取器 + HTML 夹具 CI
- [x] 合作方 webhook 字段规范化；官方 CSV 优先于 DOM
- [x] 农场 drain 指标 + `farm_health`；低置信度禁止自动确认
- [x] 用户侧自动化：回到创作者台叫醒扩展继续填表；未发完会再问一次；农场导航关着时钱一览只叫醒扩展抄账，不写成已到账
- [x] 连接器在线且店在等登录时，完成带自动打开该店一次；有店页回执后可在卡上叫醒扩展抄账
- [x] 填表中断且扩展在线时只叫醒一次接着填，不重新确认；已有结算草稿时钱一览去看草稿，不再叫醒抄账
- [x] 店页回执刚记下、且席位已授权抄账时马上排队去抄，不用再等变旧；扩展在这台浏览器上时完成带立刻叫醒一次
- [x] 网易云 / QQ → Spotify / YouTube → 短视频会话 → Apple 的覆盖顺序（目录 sort + Suggested Ship）

### Phase H3（第二年）— 妙响复制不了的生态
- [x] 电台试投作为揭晓默认下一步，发行成功后自动开试投
- [x] 护照权利证书（非独家）+ 谱系互链
- [x] Sync Desk / 嵌入按租户隔离
- [x] 厂牌席位池 warmup 接线（connecting 诚实 stamp，不发明金额）
- [x] 发现升级为情绪相似 + 热度：登录按气质相近再叠完播；未登录按完播热度，芯片不假装口味重叠

---

## 9. 数据模型扩展摘要

| 新表/字段 | 用途 |
|-----------|------|
| `style_presets` | 风格包定义 |
| `Collection.visibility` | 公开/私密合集 |
| `Work.allow_remix`, `license` | Remix 许可 |
| `Work.preset_id`, `reference_work_id` | 定制溯源 |
| `Notification` | 站内通知 |
| `ApiKey` | Open API |
| `UserCredits` | 额度 |
| `Post.tags[]` GIN 索引 | 话题筛选 |

---

## 10. 成功指标（KPI）

| 指标 | v5 目标 |
|------|---------|
| 注册 → 首次生成转化率 | > 40% |
| 生成 → 发布转化率 | > 25% |
| Remix 衍生率（公开作品） | > 15% |
| 7 日留存 | > 20% |
| 平均 Studio 参数使用率（非默认 preset） | > 50% |
| API P95 生成 job 完成时间 | < 3min（6 step playlist） |
| 确认发行 → 至少 1 家店 live 中位时间 | 持续下降；`ops_queue` 占比下降 |
| 授权席位 7 日活跃 / 收获行匹配率 | 可运营，而非 demo |
| 每创作者每月结算到的店数 × 账本可信度 | **北极星（不对标抖音 DAU）** |

---

## 11. 风险与约束

1. **MiniMax 配额**：Variation Lab / 批量生成需严格 credits Gate  
2. **Essentia 模型**：Reference Track 依赖分析质量；无模型时降级为 tag 相似度  
3. **C2PA 二进制**：FFmpeg 重封装链路增加 worker 时间  
4. **多租户**：迁移需 backfill `tenant_id` 默认值  
5. **小程序**：音频播放与文件上传受平台政策限制，功能子集需产品妥协  

---

## 12. 与现有文档关系

| 文档 | 关系 |
|------|------|
| [MINIMAX_MODELS.md](MINIMAX_MODELS.md) | v4 Studio 参数表；v5 增加 preset/reference 映射说明 |
| [PHASE3.md](PHASE3.md) | HLS/C2PA/挑战基础；v5 在其上扩展 UX 与嵌入 |
| [deploy/SAAS.md](deploy/SAAS.md) | 多租户/计费/小程序的技术落地参考 |
| v4 Music Generation Freedom Plan | 已完成；v5 本文件为其生态与定制延伸 |

---

**下一步建议（若继续开发）**：创作者 OS 的下一杠杆是合作方真密钥覆盖，不是再开主页/第五 Tab/多轨上架。席位 warmup 已诚实 stamp；参考轨 embedding 已过权利闸；Sync Desk 买方可见非独家权利证。

---

## 0. Intent-First 原则（必读）

**默认用户路径不包含上传种子音乐。** 见 [PRODUCT_INTENT_FIRST_ARCHITECTURE.md](PRODUCT_INTENT_FIRST_ARCHITECTURE.md)。

| 旧默认 | 新默认 |
|--------|--------|
| 上传 seed → 分析 → 生成 | Preset + 一句话 → 生成 |
| SeedPicker 首屏 | Advanced「音频锚定（可选）」 |
| Playlist 400 无 file | `prompt_journey` 无 seed 可生成 |

---

---

## 13. 完整规格书（Master Spec）

v5 路线图侧重战略与排期；**每个功能的详细 UX、API、数据模型与验收标准** 见：

👉 **[PRODUCT_SPEC_COMPLETE.md](PRODUCT_SPEC_COMPLETE.md)**

该文档包含：

- **全功能矩阵**（80+ 项：✅ / ◐ / ⬜）
- **4 条端到端用户旅程**（新手 / Remix / 挑战 / 创作者）
- **Studio / 生态 / 媒体管线 / 推荐 / 安全** 分模块规格
- **完整 API 缺口清单** 与 **Web 路由目标表**
- **数据模型演进** 与 **Phase 5–9 验收总表**

### 13.1 全系统完成度快照（目标 v5 结束）

| 域 | 当前约 | v5 目标 |
|----|--------|---------|
| 创作 Studio | 85% | 95%（+Preset/Structure/Reference/Variation） |
| 生态社区 | 55% | 85%（+主页/Follow/收藏/挑战闭环） |
| 溯源信任 | 70% | 90%（+C2PA 嵌入/许可） |
| 平台 SaaS | 25% | 60%（+租户/额度/API） |
| Mobile/小程序 | 20% | 45% / 25% |

### 13.2 与 v4 / Phase3 文档关系

| 版本 | 文档 | 状态 |
|------|------|------|
| v4.0 | Music Generation Freedom Plan | ✅ 已实现 |
| v3.0 | PHASE3.md | ✅ 基础设施 |
| v5.0 | PRODUCT_ROADMAP_v5.md | 📋 战略 |
| v5.0 | PRODUCT_SPEC_COMPLETE.md | 📋 全量规格 |
| v5.0 | [PRODUCT_IMPLEMENTATION_BLUEPRINT.md](PRODUCT_IMPLEMENTATION_BLUEPRINT.md) | 📋 权限/状态机/81项清单/迁移 |
| v5.0 | [PRODUCT_UX_DESIGN_SYSTEM.md](PRODUCT_UX_DESIGN_SYSTEM.md) | 📋 完整 UX：IA、Studio 线框、组件、状态、a11y |
| v5.0 | [PRODUCT_INTENT_FIRST_ARCHITECTURE.md](PRODUCT_INTENT_FIRST_ARCHITECTURE.md) | 📋 **意图优先**：去 seed 核心化、prompt_journey、Studio 重组 |

## 14. 运营落地（2026-10）

自动化继续做，但是加速器。上线时效先靠人工。前提、字段清单和角色见 [docs/landing/PHASE0.md](docs/landing/PHASE0.md)。运营网页在 `apps/ops-console`。发行资料按渠道必填项在 `backend/app/services/distribution/channel_fields.py`，核对完成前不拦住提交。用户自己账号上的 10% 记在许可上，不从店铺账户扣款。提现仍然只由财务标已付。
