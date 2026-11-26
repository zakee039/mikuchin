# PolyStrata v0.2.20-poly.5 升级验收（2026-11-26）

直接在 Mikuchin `main` 开发，不创建产品分支；回退基线 `v0.5.2` (`d62c655ff8efbbcce3018a85b690268974449f05`)。升级前正式子模块为 `v0.1.45-poly.10`（`3e1642161198c50ff1abed4046f4e4f476099dbb`），目标官方 release `v0.2.20-poly.5` (`d62dfacbe185dfbb447e79c5fb1091ae189afc64`) 已 fetch，隔离源码快照与预编译包位于 ignored runtime。官方源码未改动。

## 兼容改造

- 解析 `terminal/serve/server.py` 新布局，保留旧布局回退能力；Launcher root 检测、CI requirements、transport smoke、版本同步及缓存版本一并适配。Pin 脚本拒绝在正式端口监听时修改 checkout，支持校验已获取 tag 的完整预期 SHA。
- Windows 官方 CUDA13 SM75/80/86/89/120 预编译 ZIP SHA256 `e019563d6945737b75228b6e04d5cde5a33730c7ebfbd791a0d8f368688f5724`，包含独立 strata-poly 和 strata-vision。新 Launcher 0.5.2 Debug EXE 已重新构建。
- MeroMero 保留 131072 context、14 CPU threads、INT8 KV、1024 MiB reserve、4 conversation slots、现有 GGUF/mmproj。Tokenizer 从原路径原样复制到 Native runtime，专家 profile、日志、slot 快照独立用于测试。生产候选 JSON 已准备，未覆盖活动配置。

## 本机真实 A/B（RTX 3070 Ti 8GB，单轮）

| 测试 | poly.10 | poly.5 |
|---|---:|---:|
| 35-token prompt / 96 output decode t/s | 63.8 | 59.6 |
| 3516-token prompt prefill t/s | 1405.1 | 1456.2 |
| 3516-token prompt / 96 output decode t/s | 74.4 | 78.1 |

新引擎真实 SSE 完成、CPU vision 对红色测试图答 Red；Native `generate_image` auto tool_choice 返回合法 tool_calls 并经严格 parser 解析，未执行工具。强制 function choice 在旧、新两版均有 XML 落入普通文本的情况，不放宽现有安全校验。slot 0 save→实际 unload→load→restore 成功（103 tokens、319 MiB、505 ms restore）。两套隔离引擎均正常 STOP 退出，无真实收费请求。未进行 131K 满上下文压力测试，也未接入 strata_pin（单独评估静态 prefix 与跨角色隔离）。

## 切换前验收与备份

- 目标版源码快照上的 Gateway 全回归 191/191，真实官方 Mock transport smoke 通过；模型与视觉使用真实 GPU/CPU 运行而非 mock。
- 已对生产五份 SQLite 做 Online Backup + quick_check；备份旧模型配置及旧 Launcher。正式 UI 安全退出操作未完成，Windows WTS session 已确认 locked，不能强杀或绕过锁屏；当前正式服务不变。当前版本显示仍保持旧 pin，以免误报。
- 解锁后通过 Launcher 托盘「安全退出」，确认旧进程与 15239/15240 均关闭，再运行私有 `runtime/polystrata-v0.2.20-poly.5/activate_after_safe_quit.py`（使用 Native venv Python）。脚本校验 tag、ZIP、预编译文件、验收记录，切换 submodule + 显示版本 + 配置 + Launcher，出错回退原 pin/配置/Launcher。之后正常启动，核验正式健康、管理接口和实际引擎。产品版本未提升，未 push/tag/release。原有 v0.5.2 tag 只保护 Git 源码，运行时与用户数据库备份必须单独保留。

## 正式切换结果（2026-11-26）

- Windows 解锁后重新确认零活跃请求/图像任务/GPU 空闲，重新备份五份 SQLite，全部 quick_check=ok。通过现有 Launcher 托盘「安全退出」正常停止整个服务栈。
- 官方子模块已切换至 `v0.2.20-poly.5` / `d62dfacbe185dfbb447e79c5fb1091ae189afc64`，源码 clean 且 index 指针一致。正式 Launcher 已替换为重新构建的 0.5.2 EXE；模型配置指向经 SHA256 核验的官方新版 strata-poly 与 strata-vision。
- Supervisor PID 22416，正式 strata-poly PID 8604 由新版预编译路径启动，日志确认 131072 context、14 threads、INT8 KV、8192 MiB/4 slots RAM conversation cache，模型 ready。Gateway 15239 LAN、官方 15240 回环、独立管理 10407 回环均监听，Worker 心跳正常。
- 正式管理 CLI eligibility 返回 allowed=true，专用鉴权与 Windows SQLite 路径修复均生效。本轮未额外执行管理 reload 或发起收费请求。
- 所有用户 SQLite quick_check=ok 且各表行数与停机前备份一致：25 个会话、106 条 turn、2 张角色卡、138 张画廊索引、49 个生图任务、26 条聊天生图请求。
- 实际生产启动与模型加载已验证；本机真实推理、SSE、视觉、自动工具、KV 交接在切换前隔离环境验证，未额外做生产聊天或生图测试。未接入 strata_pin，未更改产品版本或既有 tag/release。
