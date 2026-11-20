# Mikuchin 版本与发布规则（仓库级指令）

## Native PolyStrata 重构分支（优先级高于下方旧版发布规则）

当前目录 `E:\LLM\deploy\mikuchin-native` 对应 `refactor/official-polystrata-gateway`，是从正式 `v0.3.0` 基线创建的独立 Git Worktree。原始 `E:\LLM\deploy\mikuchin` 和其正在运行的 15239 后端**绝对不得被本分支的开发脚本、重启或清理操作影响**。

- 本分支 `backend/polystrata` 是来自 `simplexai-labs/PolyStrata` 的**未修改官方 Git 子模块**，而非下文描述的旧 vendored Fork。不得修改/提交其 Python/C++ 内部源码；官方更新只能通过 `scripts/native-polystrata.ps1 pin -Tag ...` 更新 Git 子模块指针，再跑兼容性测试。
- 新业务代码全部写入 `backend/gateway` 等 Mikuchin 自有目录；官方服务只允许绑定内部 loopback，预定内部端口 `15240`。当前 Gateway 开发端口 `15249`；在完成验收前**不得占用正式生产的 15239**。
- 旧版 `scripts/package-main-release.py` 不支持 `.gitmodules`，因此本分支暂时**不得使用旧版主程序发布流程或以 v0.3.0 名义发布新架构**。`versions.json` 的 0.3.0 是开发起点，不是新架构完成版本。
- 必做检查：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/native-polystrata.ps1 verify`、`python -m unittest discover -s backend/gateway -v`、`git submodule status`、`git status`。未来真实模型/显存/KV 测试须独立执行。
- 如改动 Gateway 协议，可执行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke-native-transport.ps1`，它将官方 Mock Engine、Gateway 以及独立 Image Worker 临时运行在 15240/15249（或指定替代端口），结束时自动退出；使用临时随机密钥和新会话测试目录，不会影响 15239。不要把 Mock 测试误报为真实 GPU/KV 推理验证。
- 独立在线生图 Worker：`scripts/start-native-image-worker.ps1`；Gateway 只写任务/草稿，不得自动在 HTTP 进程执行收费请求。独立 Worker 必须持有单例锁，持续心跳；任务进程重启后绝不能自动重复付费请求。受保护图片使用 `frontend/web/auth-images.js` 通过 Bearer `fetch`+Blob URL，绝不将 API Key 加到图片 URL。
- 官方 SM86 CUDA 编译产物和测试 GGUF 配置放在 `E:\LLM\deploy\mikuchin-native-runtime`，绝不提交模型、密钥、缓存或编译产物。真实模型验证记录见 `docs/NATIVE_OFFICIAL_CUDA_VALIDATION_2026-11-20.md`；测试结束时关闭 15240/15249 的开发服务，不能误杀或更改正式 15239。
- 新增 `scripts/start-native-stack.ps1` 与 `backend/gateway/supervisor.py`，统一启动官方引擎→独立 Worker→Gateway；默认使用 15240/15249、独立 Native 数据目录和私有 Gateway Key，禁止占用 15239。Tauri Native 开发版已经通过 `frontend/launcher/src-tauri/src/native.rs` 接入 Supervisor（不使用旧 15239 启动逻辑）；独立 App ID `fun.zakee.mikuchin.native-dev`、独立 DPAPI Key 和数据目录，真实窗口/托盘生命周期及 Mock/CUDA 已验证。未制作正式安装包或 Release。守护器允许在父进程显式使用 `--control-stdin` 时收取私有 `STOP` 指令；普通交互式 PowerShell 使用 Ctrl+C。发生付费生图时须等待 Worker 完成，不得强杀或重复付费请求。
- 新的 Gateway GET `/` 与 `/web/*.js|css|svg` 是不含秘密的浏览器静态资源，`/health`、聊天、画廊及图片 API 仍需 Bearer Key，`/config` 等危险上游接口继续禁用。真实三进程的 CUDA 验证及自动缓存结果见上述日志文档，避免与 Mock 冒烟测试混淆。
- Native 独立本地生图架构（2026-11-20）：`backend/gateway/local_images.py` + `gpu_gate.py` 在官方源码之外接入本地 Qwen-Image 官方/无审查模型、三款 LoRA 与 Real-ESRGAN 4×；`image_jobs.py` 仍是唯一任务数据库，在线付费请求的重启不自动重试规则保持不变。浏览器仅传本地模型及 LoRA ID，执行程序与权重路径由独立 Native 数据目录下的 `images/config/native-local-images.json` 决定，使用 `scripts/configure-native-local-images.ps1` 独立配置。程序和超分资源复制到 `E:\LLM\deploy\mikuchin-native-runtime\image-engines`，绝不提交到 Git 或引用正式版的运行进程。本地生图期间 Gateway 聊天持共享 GPU 文件锁，独立 Worker 获取独占锁，私有认证上游接口完成官方 LLM 的卸载与重新加载；真实测试脚本 `scripts/smoke-native-local-real.py`，详细记录 `docs/NATIVE_LOCAL_IMAGE_GPU_2026-11-20.md`。真实 GPU 检验结果以实际日志为准，不得将模拟子进程测试当成 GPU 生成成功。
- Native GPU 协调后续优化（2026-11-20）：本地 Qwen 生成和 Real-ESRGAN 4× 现在共用 **一次** 独占 GPU 文件锁及官方 LLM 卸载/加载周期，不再在两阶段之间重新加载 LLM；在线 API 的后处理仍单独请求本地 GPU。Native Gateway 授权 `/health` 提供 `native_gpu`、`native_image_jobs`、`native_upscaler_ready`，Tauri `get_status` 面板显示任务阶段/Worker/超分/子进程重启次数；官方引擎异常退出时守护器在 GPU 仍独占期间延后模型重启。真实模型含 LoRA + 4× 测试已确认 384×384→1536×1536、`gpu_handoffs=1`，但单次总耗时不构成性能提升证据；详细结果与局限见 `docs/NATIVE_LOCAL_IMAGE_GPU_2026-11-20.md`。分支未发布任何新安装包或 Release。
- Native Tauri 试用界面（2026-11-20）：已按用户反馈复刻稳定版 440×650 紧凑启动器外观（直接复用主版本的 CSS），保留总览/API/设置并新增「原生状态」标签，删除工作流；总览读取真实 NVIDIA 显存及官方 `/metrics`，密钥不进入浏览器地址或日志。尚未移植 LAN、CF Tunnel、注册/切换模型及配置修改，不得宣称可用。Windows GUI 子系统适用于 Debug/Release，不再弹黑色控制台；**必须运行 `npx tauri build --debug --no-bundle` 以把前端资源嵌入 Debug EXE**，直接 `cargo build --bin mikuchin` 后打开会因 Vite 1420 未启动而出现连接拒绝。Native 独立 EXE 路径 `E:\LLM\deploy\mikuchin-native-runtime\tauri-target\debug\mikuchin.exe`，当前用无触发器的临时交互任务 `Mikuchin-Native-Dev-Launch` 保持当前用户会话的启动器运行（不是开机启动）。已修复 2 秒状态轮询导致滚动回顶；150% DPI 使用 WebView 原生缩放，**禁止全局设置 `document.documentElement.style.zoom`**，否则 UI 只占窗口上方且下方留白。已用 DPI aware 的真实窗口抓图验证。本机试用/安全重启说明和测试详见 `docs/NATIVE_LAUNCHER_UI_PARITY_2026-11-20.md`。操作前查看队列和 GPU 锁；不要中断运行中的任务。
- Native LAN / Tunnel 新接入（2026-11-20）：在 `backend/gateway/managed_child.py` 与 `supervisor.py` 添加 Native 显式 `--lan-access`，仅 Gateway 改为 0.0.0.0:15249，官方 PolyStrata 始终回环 15240；新偏好设置 `native_prefs.rs` 的 HKCU Run 键 `MikuchinNativeDev` 与独立 preferences.json 支持开机自启、自动启动、守护及 LAN/Tunnel 开关。LAN 监听改动保留待重启状态，绝不静默重启活跃会话。新 `native_network.rs` 管理独立 cloudflared.exe（runtime tools）、独立 metrics 23189、DPAPI token `native-cf-tunnel-token`、HTTPS /health 401 端到端测试；**不许复制正式版 Tunnel Token、远程 Tunnel 配置或云端路由**，用户必须新建并输入 Native 独立 Tunnel Token，公网尚未完成配置时只可宣称本地接入。已真实测试临时三进程 `scripts/smoke-native-lan.py`：Gateway 0.0.0.0 监听/401 鉴权/官方引擎回环；详见 `docs/NATIVE_LAN_TUNNEL_2026-11-20.md`。UI 沿用原版紧凑 API、设置卡片，三项启动配置已真实持久化；严禁再添加无法操作的假开关。
- Native LAN 列表与空闲卸载状态（2026-11-20）：开启 LAN 后须列出所有真实 IPv4 网卡地址（Tailscale/WLAN/以太网）；即使更改仍待重启，也应显示为不可点击的预览而不是隐藏，`lan_effective` 仅决定是否生成可点击链接。Native Gateway 的鉴权 `/health` 增加 `official_model_loaded: true|false|null`，由官方 PolyStrata 的 `loaded` 透传，Tauri 根据 Gateway 在线且 model_loaded=false 且 GPU 未被图像独占时显示「空闲卸载」徽标，区别于服务停止；下一次请求重新加载后恢复「运行正常」。参考 `docs/NATIVE_LAN_TUNNEL_2026-11-20.md` 末节及 Gateway/Rust/前端回归测试。
- 迁移文档 `docs/NATIVE_POLYSTRATA_DEVELOPMENT.md`，总体计划 `docs/PLAN_OFFICIAL_POLYSTRATA_GATEWAY_v0.3.0.md`。
- Native P0 聊天兼容性（2026-11-20）：Native Gateway 的授权 `/health` 必须区分 `image_generation`（独立图像任务）与 `chat_image_tool=false`（聊天内图像工具尚未迁移）；还明确声明 `answer_budget_tokens=false`，`chat_mcp` 在官方引擎可用时为 true（但工具列表可能为空）。共享 Web UI 使用 `web/chat-capabilities.js` 协商，不能自动将有独立图像模型误判为聊天工具能力，且必须保留旧版无能力字段时的行为。Image Studio 的提示词解析携带 `strata_image_tool:false` 属于显式禁用，Gateway 必须剔除该字段后转发；`true` 继续 501。**官方 `max_tokens` 包含思考+正文，不等价于 main 的独立正文上限；在没有真正适配前 UI 显示不支持、已有非空限制先提示清空，不静默忽略/转化。** 完整测试和剩余 P0 事项见 `docs/NATIVE_P0_CHAT_2026-11-20.md`；正式 15239 与原版业务保持隔离。
- Native MCP 后续接入（2026-11-20）：官方引擎的 `GET /mcp` 已通过 Native Gateway 独立 Bearer/Origin 安全门，仅加入精确 allowlist；`strata_mcp:true` 及官方 SSE `strata_mcp` call/result 直接代理，由**官方** run_with_mcp 执行工具。授权 health 的 `chat_mcp` 随官方引擎健康状态启用，但网页仍严格要求从 `/mcp` 读取到工具数 >0 并且用户允许 MCP 时才将工具传入；零工具不会启用。不要导入旧版的第三方服务密钥，也不要在 Gateway 自动执行本地程序。FakeOfficial Mock 已测完整 SSE，真实工具仍需单独配置与实测。详情见 `docs/NATIVE_P0_CHAT_2026-11-20.md`。
- Native 手动卸载（2026-11-20）：用户允许复用原有**安全停止整个 Native 服务栈**的实现，但启动器按钮必须显示「卸载模型／加载模型」，不得显示「停止服务」。手动卸载时 Supervisor 的 `desired=false`，写入 Native `preferences.json.manual_unloaded=true`，阻止看门狗自动重启以及启动器重新打开时的自动拉起。手动加载清除持久标志，再启动 Native 三进程。**空闲 900 秒卸载是官方模型权重卸载，可由下次请求自动加载；手动卸载则 Gateway/API/Chat 也暂时不可用，直至用户再次点击加载。**普通托盘退出不写手动标志。代码和约束见 `docs/NATIVE_MANUAL_MODEL_UNLOAD_2026-11-20.md`；不更改 `main` 或 `15239`。

本仓库从 v0.2.8 起使用 **根目录 `versions.json` 作为唯一产品版本来源**。

每次开始版本相关工作（包括新对话、移植上游、Release、安装包构建），先执行：
```powershell
python scripts/versioning.py status
python scripts/versioning.py check
git status --short --branch
gh release list --repo zakee039/mikuchin --limit 5
```

- `versions.json` 的 release 指当前正在准备/发布的 Git tag，`previous_release` 只是历史标识。
- 产品版本三轴：`components.main.version`、`components.launcher.version`、`components.android.version` 与 `versionCode`，可以独立升版；**本次 v0.2.8 特别统一三者为 0.2.8**。
- 改动版本号时，修改 manifest，然后运行 `python scripts/versioning.py sync` 与 `check`。不得只改 README 或某个代码内的数字。
- 版本历史和实际发布资产见 `docs/VERSION_HISTORY.md`，GitHub Releases 则是**是否真正发布**的最终依据；仓库提交不等于发布。
- Android 必须签名有效且升级证书与旧版一致；版本号变更后必须重新构建 APK。Windows Launcher 必须重新构建 EXE/NSIS；绝不将旧二进制重命名成新版。
- 主程序 Release ZIP 使用 `scripts/package-main-release.py` 打包，必须通过版本校验和干净工作区检查；资源文件、模型、用户对话、密钥及临时构建目录禁止提交或打包。
- PolyStrata 是 vendored 后端源代码（`backend/polystrata`），它自带的旧 `manager` 示例版本 0.1.12 **不是 Mikuchin Launcher 产品版本**，勿全局替换它。
- 提交/打 Tag/上传 Release 之后核验版本、远程 Tag 指向、所有上传资产名称及 SHA256。若任何构建缺失不得宣称所有端均更新完毕。
- 历史实验：`docs/UPSTREAM_PORTS_2026-11-13.md`、`docs/NATIVE_AB_VALIDATION_2026-11-13.md`、`docs/LIVE_CPU14_ROLLOUT_2026-11-13.md`。

## 修复后的本机生效约定

- 用户明确要求：以后每次完成并验证 Mikuchin 修复，**默认在本机直接重启需要重启的服务，并核实新代码已生效**，不要只留下未加载的源代码让用户自行重启。纯网页资源修改可通过缓存版本更新直接生效，不要无故中断后端。
- 重启前先检查任务数据库中没有 `queued` / `working` / `running` 任务，并检查 `/health`、模型加载状态；正在生成或存在活跃会话、状态不明时**不要强杀**，应说明阻碍。避免中断付费 API、生图、用户 KV 会话。
- Windows 托盘启动器在 `frontend/launcher/portable/Mikuchin.exe`，由它管理 `15239` 后端服务。安全空闲时可借助独立启动流程重启启动器和子服务，之后核验新进程 PID、`/health`、已鉴权 API 是否暴露新字段，以及网页资源。临时重启任务完成后必须清理。
- 源码生效、启动器重启、版本号更新、GitHub 提交和 Release 是不同的事；如实汇报，不擅自发布。
