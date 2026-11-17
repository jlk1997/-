# Chrome / Edge 商店上架备忘

连接器现在是 unpacked / zip。上商店才能让普通人安装和自动更新。

## 要交的材料

- 名称：比特音创作者连接器
- 版本：与 `manifest.json` 一致（现 0.14.0）
- 隐私政策：沿用比特音法律页，写明只存连接器令牌和加密 cookie，不存密码
- 权限说明：
  - `storage` / `alarms`：配对与每分钟拉任务
  - `cookies` / `tabs` / `scripting`：在用户已登录的店后台填表、传母带、抄可见表
  - `optional_host_permissions`：用户连接某店时才申请该店域名
  - API 域名留在 `host_permissions`（比特音自己的站）

## 审核口径

对外一律叫「连接器代发」，不叫官方 API 分发。只在用户自己的账号、自己的作品、逐店勾选的范围内操作。验证码不代过。

## 上架后

Chrome 应用商店 + Edge Add-ons 各交一份 zip（`npm run pack:connector`）。商店审核通过前，安装路径仍是开发者模式加载。
