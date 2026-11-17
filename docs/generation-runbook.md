# 出歌运行说明

TokenHub MiniMax v3.0 是主引擎。直连 MiniMax 负责翻唱、写词、对话、图片，并在主引擎鉴权、限流或服务失败时接音乐。内容审核和参数错误不换引擎，积分按失败退回。

一次生成会先把 `trace_id` 和音频链接写进任务。链接 12 小时内有效。下载失败由 `recover_provider_audio_task` 退避重试，不会再付一次费。

分轨队列是 `stems`，一次只算一首。当前镜像没有 Demucs 时，结果标成「预览近似」，不能当审核分轨。要真分轨时单独构建：

```
docker compose -f docker-compose.yml -f docker-compose.stems.yml build worker-stems
```

模型放在 `/opt/bittune/models/torch`。四核机器上把这个容器限制在 2 核、4G。

运营后台「生成」页看 24 小时成功率、p50/p95、兜底次数和分轨排队。成功率低于 90%、p95 超过 6 分钟、鉴权失败、分轨排队超过 10 首，会出告警。

离线演练：`python scripts/drill_music_fallback.py`。线上演练：在供应商池里暂时停用 TokenHub 钥匙，生成一首，确认溯源里的引擎变成 minimax，再打开钥匙。不要把钥匙写进仓库。

发行级 wav 默认关着。`python scripts/probe_tokenhub_music.py` 确认引擎接受 wav 之后，才把 `TOKENHUB_WAV_ENABLED=true`。
