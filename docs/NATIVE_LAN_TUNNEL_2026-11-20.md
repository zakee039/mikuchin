# Mikuchin Native：局域网与独立 Cloudflare Tunnel 接入

2026-11-20；开发分支：`refactor/official-polystrata-gateway`。

## 对照正式版的启动器交互

- 保留正式版 `frontend/launcher/src/style.css` 基础设计（440×650）。
- 设置页「启动与守护」恢复原有**三行切换排版**：
  「开机自启」「启动器启动后自动拉起服务」「服务异常自动恢复」。三项都持久化、可操作。
- 开机自启仅写入当前 Windows 用户的
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\MikuchinNativeDev`，
  入口为 **Native 自己的 EXE** 加 `--background`，默认关闭；绝不修改正式版键。
- Native 的持久配置为 `%LOCALAPPDATA%\MikuchinNativeLauncher\preferences.json`；
  只有非敏感布尔值和用户选定的域名。API Key 和 Native Tunnel Token 分别经
  Windows DPAPI 加密，Token 绝不写入 JSON、命令行、日志和服务 URL。
- 关闭窗口依旧隐藏到托盘。启动服务、停止服务、原生状态继续在原位置。

## LAN HTTP

- API 页的「局域网 HTTP 直连」是真正的开关（默认关闭）。
- 开启后下一次 Native **安全停止→启动** 将 Gateway 由
  `127.0.0.1:15249` 改为 `0.0.0.0:15249`。为了不打断活跃的 GPU、付费图像任务、
  KV 会话，仅保存并展示「监听变更已保存，安全重启服务后生效」；**绝不自动强制重启服务**。
- 官方 PolyStrata 继续只监听内部回环 `127.0.0.1:15240`；
  API 的 Bearer 鉴权与 Origin 防护、Image Worker 隔离均不变。
- 监听实际生效后，API 页显示可用网卡的 IPv4 访问链接。
  设备访问仍需 Gateway API Key。Windows 防火墙或校园网 AP 隔离可能阻断其他设备，
  不默认创建宽泛的全局防火墙规则。
- 使用与正式版一样的网卡枚举方式，但不调用正式版服务。

## Cloudflare Tunnel

- API 页复用原版紧凑域名和 Token 设置：保存、安装、测试、重启，以及可用的启用开关。
- `Native runtime\tools\cloudflared.exe` 是一个**独立复制的二进制**，
  不读旧版 CF 配置、Token 或凭据。已验证本机源与 Native 副本 SHA-256 完全相同
  （cloudflared 2026.10.7）。
- 默认关闭。启用前必须由用户**新建独立 Tunnel** 并配置 Cloudflare 公网 hostname
  的源站为 `http://127.0.0.1:15249`；在 Native UI 输入那个独立 Tunnel 的
  `eyJ...` Token，保存并启用。不得把正式版生产 Tunnel Token 直接复制到 Native，
  否则多个 Connector 可能分流同一公网域名，造成访问不稳定或切到旧后端。
- Token 使用环境变量 `TUNNEL_TOKEN` 传给 cloudflared；额外管理端口
  `127.0.0.1:23189`，与正式版的 23188 分离。连接器单独由 Tauri 启停、监控重启。
- Tunnel 连接数来自本地 metrics，不把「进程已运行」误判成「公网连通」。
  「测试」发起 `https://{hostname}/health`，只有收到带有 Native Gateway
  特征消息的 HTTP 401 才视为端到端连通；不发送 API Key 或 Token。
- 有效公网域名及新 Tunnel Token 尚需用户在 Cloudflare 自行创建、填写。
  未完成前**不能宣称公网访问已通过**。

## 验证

- `scripts/smoke-native-lan.py`：真实 Windows 三进程 Mock 冒烟，
  独立随机端口、随机临时目录，验证 Gateway `0.0.0.0` 监听、
  未授权 `/health` 返回 401、授权请求 200、官方 Engine 仍只监听回环。
- Python Gateway 原有 65 项加 LAN 参数验证测试；Rust 测试覆盖持久配置默认、
  域名校验与原生 Tunnel 端口隔离。
- `node --test frontend/launcher/tests/native-shell.test.mjs`：启动器控制项与
  Tauri 命令对应、监听开关、页面轮询保留输入焦点/滚动位置。
- 未修改上游 PolyStrata Git 子模块、正式主分支、正式 15239。
- **不制作安装包/Release，不自动创建 Cloudflare 远程配置，也不修改 Windows 防火墙。**
