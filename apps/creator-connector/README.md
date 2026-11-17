# 比特音创作者连接器

席位运行时之一：在已经登录的官方页授权，按共享剧本进对账页，优先读官方 CSV，再抄可见表。授权席位的收割行可以结算。

## 闭环

1. Chrome 打开 `chrome://extensions`，开发者模式，加载本目录（或 `npm run pack:connector` 解压后加载）。
2. 创作者中心 → 账户点「发送到已安装的扩展」。扩展未装时复制 `BITTUNE_PAIR`，再在弹层点「从剪贴板配对」。
3. 打开已登录的音乐人后台，点「把当前后台交给比特音」。扩展按当前标签识别店。
4. Chrome 开着时，闹钟拉 `GET /seats/jobs`：打开对账页 → 等表格 → 优先 fetch/下载官方 CSV → 翻页合并 → `POST /seats/harvest`。
5. 登录墙标 `needs_challenge` 并通知；空表标 `selector_broke`，不会当成成功。
6. 弹层只强调「现在该做什么」。每分钟心跳会把账期、席位、上次收割与创作者中心对齐，不以扩展本地月历为准。
7. 店后台页底部会出提示条。点通知或「打开工作台」可盯着收割，关掉弹层也不丢进度。
8. 弹层「本机夹具」收在「卡住了」里，用扩展内 HTML 验收读表。授权后立刻拉席位任务，不必等一分钟闹钟。
9. 弹层不要手填 localhost；API 地址由配对文本写入。运营拉任务也在「卡住了」。空表标 `selector_broke`，教练条会标红。

厂牌用户不用装。运营用平台席位 + 农场（默认导航）。个人代发用户装这个，抽 10%。

微信小程序不装扩展。小程序用户复制 H5 链接到电脑完成一次连接。

站点改版只改 `packages/dsp-playbooks`（含 `runner.js`）与夹具。改完后同步 `harvest-core.js` / `upload-core.js` / `runner-core.js`（`node packages/dsp-playbooks/health-ci.js` 会锁一致性）。
