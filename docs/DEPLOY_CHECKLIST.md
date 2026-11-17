# 比特音双端发布 Checklist（H5 + 微信小程序）

## 后端 `.env`（生产）

- [ ] `DEBUG=false`
- [ ] `DEV_MOCK_GENERATION=false`；`GET /api/v1/config/platform` 的 `mock_ai` / `mock_payment` / `partner_stub` / `debug` 必须都是 false
- [ ] 至少一把 AI 厂商密钥（`MINIMAX_API_KEY` 等），否则生产启动失败
- [ ] `LEGAL_CONTACT_EMAIL` / `LEGAL_CONTACT_PHONE` 必须是真实客服，不能是 `privacy@vibe-sorcery.com` / `400-000-0000`
- [ ] `PARTNER_STUB_ENABLED=false`；不要把 `DISTROKID_API_BASE` 指到 `/dev/partner`
- [ ] 未配微信/Stripe 时不要靠 mock checkout 充值（`DEBUG=false` 已关闭假支付）
- [ ] `GET /billing/methods` 只列出已配置渠道，没有「全开 enabled」的假列表
- [ ] `JWT_SECRET` — 32+ 字符强随机
- [ ] `ADMIN_BOOTSTRAP_EMAIL` — 首次 bootstrap 后留空
- [ ] `MINIMAX_API_KEY`
- [ ] `DATABASE_URL` / `REDIS_URL`
- [ ] `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`（若启用 Stripe）
- [ ] `WECHAT_APP_ID` / `WECHAT_APP_SECRET` / 微信支付商户号
- [ ] `FRONTEND_BASE_URL` — H5 站点 origin（小程序「复制浏览器链接」依赖此项，否则剪贴板只有相对路径）
- [ ] `S3/CDN` 公网可达（音频、封面、头像）
- [ ] 启动前执行 `alembic upgrade head`（含 `0027_radio_play`）
- [ ] Celery：`worker`（`celery,priority`）+ `worker-post`（`post_process`）+ **`worker-dist`（`distribution,analytics,settlement`）** + `beat`
- [ ] 无 `worker-dist` 时，厂牌提交、席位收割排水、周五自动出金会堆在 Redis，自动化是假的
- [ ] Windows 单进程 worker 必须带上 `distribution,analytics,settlement`（`scripts/run-worker.ps1` 已改）
- [ ] `docker compose ps` 可见 `browser-farm`。`VIBE_FARM_NAVIGATE=1` 且镜像用 `INSTALL_PLAYWRIGHT=true` 重建后，`GET /config/platform` 的 `farm_navigate` 才会为 true；否则诚实 banner 继续说农场未导航
- [ ] 域名 HTTP（证书未到）：`deploy/nginx/ip.conf` 的 `server_name` 含 `superformersmusic.com`，**不要** 301 到 HTTPS。生产 `FRONTEND_BASE_URL` / `API_PUBLIC_URL` / `CORS_ORIGINS` 用 `http://superformersmusic.com`
- [ ] 域名 HTTPS（TrustAsia 商用包到位后）：证书放 `/opt/bittune/certs/`，启用 `deploy/nginx/https.superformersmusic.com.conf`，全站 origin 改 `https://superformersmusic.com`。域名 HTTP 301 到 HTTPS；**IP 继续走 HTTP，不要 301**。证书未到不要装这个文件
- [ ] 腾讯云安全组放行 **443**（和 80/22）。证书约 90 天，到期前换成新的 `bundle.pem` + `.key` 再 `nginx -s reload`
- [ ] `python deploy/scripts/install_tls.py` 可单独装证书并改 origin，不必整栈重建
- [ ] Essentia：在服务器跑 `scripts/install-essentia-models.sh`，挂到 `models/`。缺模型时 `/health` 仍 200，`essentia_ready=false`
- [ ] KYC：配 `KYC_API_URL` + `KYC_API_KEY` + `KYC_WEBHOOK_SECRET` 才会走厂商；否则提现实名只走管理后台人工通过
- [ ] 席位保险柜：生产设独立 `SEAT_VAULT_KEY`（或至少换掉默认 `JWT_SECRET`）
- [ ] `GET /health` 的 `checks.seat_runtime` 显示席位队列；积压说明抽水没在跑

## H5（Taro build:h5）

- [ ] `TARO_APP_API_URL=/api/v1`（同域 Nginx 反代）或完整 API 域名
- [ ] `docker compose up frontend` 验证静态资源与 `/api` 代理
- [ ] Stripe / 支付宝回跳 `settings?checkout=success` 可用

## 微信小程序（Taro build:weapp）

- [ ] 微信公众平台配置 **request 合法域名**（API）
- [ ] **uploadFile 合法域名**（MinIO/CDN）
- [ ] **downloadFile 合法域名**（音频 CDN）
- [ ] **WebSocket 合法域名**（若启用 job WS；否则依赖 poll）
- [ ] `project.config.json` 填写正确 `appid`
- [ ] 真机关闭「不校验合法域名」后完整走通：登录 → 创作 → 播放 → JSAPI 支付
- [ ] 主包体积 < 2MB；`packageStudio` / `packageOps` / `packageCopilot` 分包已配置

## 冒烟测试（E2E 手动）

1. 注册 / 登录（H5 邮箱 + 小程序微信）— **须勾选用户协议与隐私政策**；带 `?ref=` 或小程序 scene 的新微信用户应拿到邀请额度
2. H5 首次打开 — **隐私政策弹窗**
3. 首次 AI 生成 — **AI 服务声明确认**
4. Create 无 seed 生成单曲 → 库 → 发布发现 — **发布合规勾选**
5. Feed 播放 → 作品显示 **「AI 生成」** 标识
6. Remix → 溯源页
7. 关注用户 → 公开主页粉丝列表
8. 额度不足 402 → Pricing 充值（**勾选付费协议**）→ 继续创作
9. 设置 → 导出数据 / 注销账号
10. `GET /health` 返回 `database`/`redis`/`essentia_models` 子状态  
   - 快速检查：`npm run smoke:health`（默认 `http://localhost:8000/api/v1`）  
   - 公开 API：`npm run smoke:api`（health + presets + platform config + legal documents）

## L0 一键代发手工走通（无合作方密钥）

在 `https://superformersmusic.com` 连跑（证书未到时用 HTTP）。没有店页回执不得写「已上架」。

1. 写一句出两版 → 曲库能看到原版 / 母带说明 → 美化台打成母带 B
2. 一点「上店发行」→ 出现配送行（默认网易 / Spotify / 视频号），文案是「待交店」，不是空 409
3. 配送页顶部 AuthDesk：装连接器 → 配对 → 打开已登录店后台 → 交一间店
4. 同一首歌自动续发，状态变成「连接器代交」或「平台在发」，不是「已在 Spotify 上架」
5. 粘贴真实店页链接（或连接器回执）后才标 live
6. 带金额收割只进法币钱包；额度与电台完播数字不变
7. 申请提现保持 pending；运营看板能看到待打款 / 待 KYC
8. 自动发行开关无记录时视为未同意

## 合规上线（中国大陆 H5 + 微信小程序）

- [ ] `docs/legal/zh/` 六份协议文档已部署且 `GET /legal/documents` 可访问
- [ ] 注册/微信登录勾选用户协议 + 隐私政策
- [ ] H5 首次启动隐私弹窗
- [ ] 首次 AI 生成前 AI 声明确认
- [ ] 付费前勾选付费服务协议
- [ ] 发布前内容合规确认 + 敏感词过滤
- [ ] 全端 AI 生成标识展示
- [ ] 设置页账号注销与数据导出
- [ ] 微信小程序后台隐私指引配置（见 `docs/WECHAT_PRIVACY_SETUP.md`）
- [ ] ICP 备案号展示（H5 页脚，上线时填写真实备案号）
- [ ] 客服邮箱/电话替换为真实联系方式
- [ ] `alembic upgrade head`（含 `0008_legal_consent`、`0009_commercial` 迁移）
- [ ] Celery beat 已启动（含账号注销、订单过期、订阅到期、**分发对账、月结、电台 tick**）
- [ ] `docker compose ps` 可见 `worker` / `worker-post` / `worker-dist` / `browser-farm` / `beat` 均为 running

## 商业化上线

- [ ] 阅读 `docs/COMMERCIAL_DESIGN.md` 并完成支付渠道配置
- [ ] Stripe Webhook 指向 `POST /billing/webhook` 且验签通过
- [ ] 微信/支付宝异步通知 URL 公网可达（`API_PUBLIC_URL`）
- [ ] Paywall 与定价页付费协议勾选联调（402 → 充值成功）
- [ ] 会员开通 / 取消续费 / Stripe Portal 冒烟
- [ ] `GET /billing/subscription` 与订单历史正常
- [ ] Celery：`expire-stale-payment-orders-hourly`、`renew-mock-subscriptions-daily`
- [ ] Celery 厂牌队列：`reconcile-distribution-every-2m`、`sweep-auto-release-every-10m`、`harvest-seats-every-6h`、`drain-seat-jobs-every-1m` 有 `worker-dist` 消费
- [ ] Celery 结算队列：周五 `auto_payout_task` **不得**自动 `paid_manual`；只提醒/等人申请。财务打款后再人工通过
- [ ] 冒烟：厂牌提交后国内走量包进席位队列（`session_wait` / `assisting`），1 分钟内被 `drain_seat_jobs_task` 租走
- [ ] 冒烟：`npm run pack:connector` 后 Chrome 加载 zip 解压目录；账户页「发送到已安装的扩展」能配对；`vsc_` 令牌 `POST /seats/harvest`（用户席位，有真实金额）成功；农场收割一个平台席位成功
- [ ] 冒烟：只有播放没有金额的收割不进可提现；未授权 connector ingest 不自动确认
- [ ] 提现必须绑定**本人**收款账户；`kyc_status=verified` 才能申请；钱包行锁防并发双花
- [ ] 申请后保持 pending，直到财务打款后人工标 `paid_manual`。周五 Celery **不得**自动标已付
- [ ] 席位 DOM 收割默认不自动入账；置信度 < 0.9 或单笔净额超过自动确认上限保持 draft

## 预发钱路闭环（对外说「钱能回来」之前）

本地 IDE 不能代替预发。至少在预发连跑：

1. 用户连接器配对 → 打开网易或 QQ 已登录后台 → 同步播放（不入账）
2. 勾选结算授权后收割**有金额**的行 → 结算 draft 或高置信自动确认 → 钱包可见
3. 实名 + 本人收款账户 → 提现 pending → 财务打款 → 后台标 `paid_manual`
4. 运营日清：管理后台结算页的待打款、待实名、未匹配挂曲、`selector_broke`、`ops_queue`、席位登录墙

短视频店只承诺协助上传。未验证店不要标已上架结算。

## 安全与性能

- [ ] 生产 `.env` 设置 `RATE_LIMIT_FAIL_CLOSED=true`
- [ ] 登录 / 支付 / Webhook 限流联调（429 响应）
- [ ] 微信/支付宝回调金额篡改测试（应拒绝履约）
- [ ] `alembic upgrade head`（含 `0010_payment_indexes`）
- [ ] Redis 可用（缓存 + 限流共用）

## CI 必须通过

- `pytest backend/tests`
- `npm run build:h5` + `npm run build:weapp`
- `npm run smoke:api`（API 启动后）
- `npm run test:e2e`（可选，H5 静态冒烟）
