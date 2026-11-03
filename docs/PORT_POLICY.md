# Mikuchin API 端口

- 唯一默认 API 端口：**15239**。
- Windows Manager 独占负责启动和守护后端；不再保留 18081 端口转发、旧管理器或旧部署兼容监听。
- 是否允许局域网访问由 Manager 设置决定；启用时监听 `0.0.0.0`，否则只监听 `127.0.0.1`。
- Cloudflare Tunnel 的唯一源站应为 `http://127.0.0.1:15239`。远程托管的路由必须在 Cloudflare 控制台同步更新，不允许回退至旧端口。
- 需同时验证本机 `http://127.0.0.1:15239/health` 和公网 `https://key.zakee.fun/health` 均返回 HTTP 200。
- 除模型文件外，部署相关路径都位于 Mikuchin 项目目录下，新配置必须通过 `scripts/audit-local-paths.py` 检查。
