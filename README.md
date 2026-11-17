# 比特音 / BitTune

情绪出歌，授权把歌唱到各店，再把**有金额的对账**收回来。

小程序只做听 / 做 / 签到 / 看钱。连接器只在电脑 Chrome。额度是创作燃料，法币是商店版税，两本账永不混。

运维入口：[PLATFORM.md](PLATFORM.md) · 上线闸：[docs/DEPLOY_CHECKLIST.md](docs/DEPLOY_CHECKLIST.md) · 规格：[PRODUCT_SPEC_COMPLETE.md](PRODUCT_SPEC_COMPLETE.md)

## 产品闭环

1. **出歌** — 写一句意图或点风格包，MiniMax 出歌。上传参考音频是可选项，不是门槛。
2. **发行** — 自己发抽 10%，厂牌抽 20%。没合作方密钥就进运营队列，不是故障。
3. **收获** — 用户连接器或平台农场抄有金额的对账。只有播放、没有金额的不同步进可提现。
4. **提现** — 本人收款账户 + 实名通过。财务打款后再标已付。周五任务不会自动汇出。

创作者中心不承诺「点一下全球上架并自动到账」。短视频店只协助上传。电台完播是发现，不是商店版税。

## 本地怎么跑

完整 Windows 步骤见 [START-WINDOWS.md](START-WINDOWS.md) 与 [PLATFORM.md](PLATFORM.md)。

```bash
cp .env.example .env
# 填 MINIMAX_API_KEY；对外必须 DEBUG=false，并关掉 mock_ai / mock_payment / partner_stub

docker compose up -d postgres redis minio
docker compose up api worker worker-post worker-dist beat browser-farm frontend
```

- H5：http://localhost:3000（Docker）或 `npm run dev:web` → http://localhost:10086
- API：http://localhost:8000/docs
- 连接器：Chrome 加载 `apps/creator-connector/`（或 `npm run pack:connector`）

生产必须跑齐 `worker`、`worker-post`、`worker-dist`、`beat`、`browser-farm`。缺 `worker-dist` 或农场时，自动化是假的。

## 仓库结构

| 路径 | 用途 |
|------|------|
| `apps/client` | Taro H5 + 微信小程序（唯一用户端） |
| `apps/creator-connector` | 电脑 Chrome 连接器 |
| `apps/browser-farm` | 平台席位农场 |
| `backend` | FastAPI + Celery |
| `packages/dsp-playbooks` | 各店对账剧本 |

## 论文来源

情绪歌单的研究原型仍可从 CLI 复现（`python main.py`）。产品名是比特音，不是论文仓库。

Urrego-Gómez, I., Colton, S., & Roman, I. R. (2025). *Vibe Sorcery: Integrating Emotion Recognition with Generative Music for Playlist Curation*. LLM4MA Workshop.
