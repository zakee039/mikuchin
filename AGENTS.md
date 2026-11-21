# Mikuchin 版本与发布规则（仓库级指令）

## 2026-11-21 顶栏状态、聊天工具计时与本地生图导入

- 顶栏状态**只能**通过 `native-header-status.js` 的单一状态仲裁与 `paintHeaderStatus()` 渲染；禁止 Metrics 与 Native Health 各自调用 `setPill()` 抢占标签。后台可并行生图用单独 `生图 N` 副标签。
- 聊天生图 Tool Calling 计时来自 Worker `started_at` 和 `finished_at`，从实际推理开始（排队和卸载 LLM 不计），只更新计时文本，不每秒重渲染会话；旧任务没有时间时不虚构耗时。
- 「生图服务」提供本地模型列表及「导入本地模型」。这是本机 localhost + Bearer 允许的**Qwen-Image 文件注册**，只接收 Diffusion/VAE/LLM/可选视觉编码器现有路径，复用受信的已注册 sd-cli exe/args。绝不能变成远端客户端设置任意 EXE/脚本/命令行参数的功能，不能自动上传或下载大模型，不修改 LLM 模型配置文件。详见 `docs/UNIFIED_HEADER_TIMER_LOCAL_IMPORT_2026-11-21.md`。

## 2026-11-21 聊天生图运行模式与异步交付（最新用户决定）

- **运行方式在「全局设置 → 聊天生图模型」右侧**，作为 `chat_image_settings.runtime_mode` 自动保存于 Mikuchin 自身角色选项；**禁止写入 LLM 模型 JSON**。默认 `exclusive` 及旧配置兼容：沿用 GPU 独占、LLM 卸载→生图→恢复 KV 的工作流。显式 `concurrent` 仅在本地资源允许时跳过卸载、保持共享 GPU 锁；内存不足不得自动重复提交。在线 API 后台独立运行，不需要此本地模式控件。
- 在线/并行聊天图像任务先自然报备开始、允许继续聊天；完成时依据实际生成图 + 原请求 + **同会话新上下文**，关闭思考生成单独回复。已有普通回答尚在生成时，等回复结束再插入完成消息，不得覆盖当前回答或重复生成图片。
- API 可接多图时，编辑使用同会话上一张成功图片及本次用户参考图；仅单图支持则以上一张为准；不支持图片参考时用上一张真实提示词 + 本轮指令重绘，禁止跨会话引用。
- 聊天图片真正全屏预览无横向顶栏，下载/关闭按钮浮在右上方；画廊右上也有下载。详细说明见 `docs/CHAT_IMAGE_RUNTIME_ASYNC_2026-11-21.md`。

## 2026-11-21 聊天上下文、API 确认、图片预览（最新用户决定）

- **无状态并非抹除当前对话历史**：无状态不注入用户身份、角色卡、跨会话记忆；但在同一会话内，普通聊天及 Native Tool Calling 必须携带此前对话、工具调用与结果，使“再生成一张二次元的”仍能指向上轮“初音未来”。不能在组装模型请求时只留下最后一个 user。
- 仅在**聊天里**模型选择在线图像服务时读取该服务独立保存的 `chat_confirm_each_call`：默认 `false`，不弹窗、直接走现有幂等 Worker 流程；用户主动勾选后才在本次调用前弹确认。**独立「生图」页面始终不弹这个确认框**。不额外触发收费测试，不重试不确定的付费请求。
- 聊天里生成的图片点击进入私有 Blob 鉴权的**只读预览**，右上角仅「下载／关闭」，不直接下载、不带画廊删除/编辑功能。保留已有思考流与展开/收起行为，不过滤模型真实思考内容。
- 本次实现记录见 `docs/NATIVE_TOOL_CONTEXT_CONFIRM_PREVIEW_2026-11-21.md`；这组决定优先于下文 2026-11-21 较早的“每次在线生图都需确认”规则。

## 2026-11-21 聊天自动生图与 MeroMero 运行配置（最新决策）

- 正式 Native main 在 `E:\LLM\mikuchin`，旧版 `E:\LLM\mikuchin-old` 仅供回退；产品 v0.4.0 与官方 PolyStrata `v0.1.45-poly.10` 子模块版本不变。
- 正式模型选择 `runtime/config/G4-MeroMero-26B-Q4_K_M.json`：MeroMero 26B-A4B Q4_K_M GGUF、**131072 上下文、14 CPU 线程、INT8 KV、15 分钟空闲卸载**，官方 CPU 视觉编码器由固定上游版本独立构建；模型权重仍在 `E:\LLM\models`。旧 `official-sm86-model-test.json` 保留作本机回滚。
- 聊天内用户明确提出生图/修改请求时，前端使用经过用户授权且带唯一 `request_id` 的 Native `chat_submit` 图像任务，不经原版 `strata_image_tool`，避免把 `dalle.text2im` JSON 当作回复。纯文本讨论、教程、否定句不能触发生图；有收费可能的在线模型，每次调用都必须再次确认。完成后用本地视觉一次短回复，**禁用思考、最多 256 总 Token，不再发起新生图任务**。
- 本地图像 GPU 交接使用 Gateway 全局互斥及官方引擎私有接口。单活动槽位 KV 使用 `slot_save_path` + `/slots/0?action=save|restore` 临时文件进行尽力保存恢复，**它不是按会话独立持久化的完整 KV 系统**；失败时只能重新 prefill，不得假称命中。图片生成任务先完成再交付，不因 KV 恢复异常重试可能收费的生图。
- Native 当前不支持独立正文 Token 上限；采样设置仅显示独占一行的思考预算，旧会话残留 `max` 不转换成 `max_tokens`。
- 相关源码：`frontend/web/chat-image-router.js`、`frontend/web/app.js`、`frontend/web/characters.js`、`backend/gateway/local_images.py`；验证与限制见 `docs/NATIVE_AUTO_CHAT_IMAGE_2026-11-21.md`。

## 2026-11-21 最终本机目录（最高优先级）

用户将最终部署路径统一为：
- 当前 Native main 及源代码：`E:\LLM\mikuchin`
- Native 的唯一私有运行环境（.venv、build-cuda86、launcher-user-data、图像引擎、Tauri 构建目录等）：`E:\LLM\mikuchin\runtime`（Git 忽略）
- 旧版 old-mixed 主工作树：`E:\LLM\mikuchin-old`
- 旧版 PolyStrata 未提交资料、研究配置/报告恢复包：`E:\LLM\mikuchin-old\_migration-recovery\20261121`
- 旧同级 `E:\LLM\deploy` 已决定清理；下面历史记录中以此为前缀的路径仅为历史证据，**不得作为未来执行路径**。

新 Native Gateway 15239、官方 PolyStrata 回环 15240、旧版预留端口 25239，PolyStrata 固定 `v0.1.45-poly.10`。模型权重仍归属于 `E:\LLM\models`；保留迁移后的凭据、SQLite 会话/画廊，不重播图像任务。启动器计划任务应使用 `E:\LLM\mikuchin\runtime\tauri-target\debug\mikuchin.exe`。需要改变目录时先检查私有配置 JSON 的绝对路径和 Git linked worktree/submodule 路径，严禁删除旧版 Git 主仓库。

## 2026-11-21 Native main 正式迁移（当前最高优先级）

用户明确选择**源码主分支切换**：原始 main 的最后提交 `5dde9ac` 与旧版端口改动 `79f9332` 均保存在 `old-mixed`（原始工作树 `E:\LLM\deploy\mikuchin`），新 Native 工作树 `E:\LLM\deploy\mikuchin-native` 作为 **main**。下面历史文档里“Native 不能使用 main/15239、独立 Key/CF Token 不能迁移”只针对切换前开发隔离，现被用户新决定覆盖。

- **新版 main**：Native Gateway 外部端口 **15239**，官方 PolyStrata 始终只在 **127.0.0.1:15240**；原版 **old-mixed** 默认端口 **25239**，其 Cloudflare 连接器和开机自启已禁用。
- 原 `key.zakee.fun` 命名 Cloudflare Token 的 **DPAPI 加密字节**与原旧版 API Key 的**加密字节**按用户正式迁移目标复制到 Native 的独立状态目录，并保留切换前备份。只允许新版 Cloudflare Connector 服务该域名，防止两条连接器重叠；凭据永远不进入 Git 或日志。
- `main`、Launcher、Android 版本统一 **v0.4.0**（Android versionCode 400）；**官方 PolyStrata 仍固定 `v0.1.45-poly.10`、子模块 SHA `3e1642161198c50ff1abed4046f4e4f476099dbb`，不得改动其源码或指针**。
- 已迁移角色卡 2、11 会话、87 旧画廊 PNG + Native 原5 => 总92、旧 miku 世界书4文件；源数据库/文件只读，独立 SQLite 与加密设置备份：`E:\LLM\deploy\mikuchin-native-runtime\migration-backups\old-mixed-20261121`。不自动重播付费任务或旧 KV 快照。
- 复刻旧版精心设计的 440×650 Tauri 布局：总览选择/查看配置、API Key 明文复制与更换、CFTunnel 域名/Token/安装/测试/重启、设置三卡（启动与守护/全局语言/空闲卸载分钟），原生状态第四标签单独展示新增监控。不要在设置页重新放“模型 JSON 路径”或解释性长段。
- **本机真实**公网 `https://key.zakee.fun/v1/strata/sessions` 使用旧 Key 可返回迁移后的11会话；但 Android 真机安装升级及跨机器完整运行时还需单独验证。
- Windows NSIS 当前**仅包含 Launcher**，不内置 Python/CUDA/模型/服务端，不能宣称完整可搬迁正式安装包；Android v0.4.0 同包名升级候选已经用原证书签名核验，但没有真机验证。在用户明确允许正式发布前**不创建/覆盖 GitHub Tag 或 Release**。
- 详细实测与回滚步骤见 `docs/NATIVE_V040_MAIN_MIGRATION_2026-11-21.md`。今后代码修改按新版 main 的安全停机/任务/显存门槛执行，不重启 old-mixed 回到15239。

---


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

- Native 显式聊天生图（2026-11-20）：在 Chat 输入纯文本后点击新增「生图」并于**页面内确认框**确认方会创建任务；普通聊天依旧不加 `strata_image_tool=true`，`health.chat_image_tool=false`。显式能力 `health.chat_image_jobs` 仅代表可使用独立 Worker。持久化 `chat_image_requests(session_id,request_id)` 唯一键保证重复点击、刷新或请求超时后不自动重复付费；只能取消未认领任务。成功后安全 Blob 图片显示并在 `health.images=true` 时用**一次** `reasoning_effort=none,max_tokens=256` 本地视觉摘要，不重复触发生图。Chat 作品画廊来源为 `chat` 并保存会话归属。旧版 LLM 自主调用的工具功能**仍未移植**，不要宣称自动识别任意生图意图。完整约束与 Mock 浏览器验收见 `docs/NATIVE_CHAT_IMAGE_ORCHESTRATION_2026-11-20.md`；实际收费 API 不得仅为测试而调用。
- Native P1 智能生图意图（2026-11-20）：Chat「自动：关／开」默认关闭（浏览器本地偏好），开时使用**本地官方 LLM**短请求分类 `text/generate/edit`；异常回退正常聊天，仅 `generate/edit` 且人工确认后通过原 `chat_submit` 幂等单次提交。修改上一张时从**同会话**最近成功生成图提取私有参考图、保留 `source_id` 和 `edited_previous`，不允许跨会话任意引用；不支持参考图时明确失败而非降级为新图。旧版 `strata_image_tool=true` 仍未移植；独立 `answer_budget_tokens` 仍未得到精确等价官方接口，不能把 `max_tokens` 冒充正文限额。详见 `docs/NATIVE_P1_IMAGE_INTENT_2026-11-20.md`。

- Native P0–P3 补齐进展（2026-11-20）：启动器已有模型 JSON 注册/切换（独立 runtime/config 文件名白名单、仅手动卸载/重新加载后生效）、可选 `idle_unload_s` 0/300/900/1800/3600，运行时生成 isolated active-model-config.json 且绝不更改原 JSON；API Key 可在完全停止 Native 三进程且用户确认后轮换 DPAPI，测试期间不主动轮换真实用户 Key。Gallery 显式 4× 使用独立 Image Worker 的 `kind=upscale`，只读已有原 PNG 并调用 Real-ESRGAN；重复任务不重新调用生图提供商、成功则封面+原图同组。新增 Native 会话全局语言 `GET/POST /v1/mikuchin/ui-language` 经 Bearer/Origin 授权，zh-CN/en-US/ja-JP 持久 SQLite。剩余精确正文 Token 限额、内容型完整监控/WDDM GPU预算、真实 Uncensored 图生图、公网 Tunnel/Android/正式打包仍未全部验收，详见 `docs/NATIVE_P0_P3_CLOSEOUT_2026-11-20.md`。**不得宣称 P0–P3 全完成；生产 main/15239 不动。**

- Native 聊天输入区与任务计时（2026-11-21）：根据用户明确要求，**删除聊天输入框的「生图」「自动：关」两个按钮及其自动路由/提交逻辑**；不再加载 `chat-image-intent.js`，普通 Chat 始终走文字聊天路径。独立「生图」页、画廊和已存在聊天生图的历史展示/状态轮询仍保留，后台历史任务数据不删除。图像任务 `started_at` 改为由 Worker **真正开始调用 API/模型**时写入；排队、等待 GPU 锁、卸载 LLM 不计入运行耗时，`started_at=NULL` 的进行中任务应显示「排队中」，不再把客户端点击时间当执行起点。此规则同时修复正式 main 的 `backend/polystrata/serve/image_jobs.py` 与 `frontend/web/image-studio.js`，但**main 服务无须为此强制启动**；后续不应擅自恢复两个聊天按钮。

- Native P2 实机验收（2026-11-21）：已在 Native 独立真实 Worker 上验证 Uncensored 384×384/4steps 生成成功（166.4s），同一图片执行画廊手动 Real-ESRGAN 4× 成功（1536×1536，7.2s），画廊原图/封面成对、重复提交幂等，测试图片/任务全部删除。又发现 Official 匹配的 `mmproj-Qwen3VL-8B-Instruct-F16.gguf`，只在 Native Official 的 `llm_vision` 注册并保留配置备份，真实 GPU 参考 128×128 PNG 生成 256×256 成功（170.6s），私有图片引用/CLI参数/输出及画廊索引均核验，测试产物/引用已清理。Uncensored 采用不同LLM，当前 `reference_mode=none`，不得强行复用 Official mmproj。不得将参考图生成功能运行成功夸大为视觉一致性或美学质量已验证。详细结果 `docs/NATIVE_P2_UNCENSORED_4X_VALIDATION_2026-11-21.md`；不影响正式 main/15239，无在线收费生图调用。

- Native P3 跨设备与预览打包（2026-11-21）：用户将独立正文 Token 上限降为非优先项，专注 P3。已确认 Native Gateway 监听 0.0.0.0:15249，Official 仍仅 127.0.0.1:15240；本机 WLAN/Tailscale/loopback IPv4 访问：401 无 Key、200 正确 Key 与 Sessions、403 非法 Origin，**尚不是远端设备发起的测试**。使用随机端口与临时隔离 Mock Native，通过真实 Cloudflare Quick Tunnel 验证公网 HTTPS /health=401、/=200，临时 Tunnel 已退出；真实命名 Tunnel 仍须用户新建专用 hostname/Token，不能复用正式版。Android 修复 401 Native 健康预检，先不发送 Key、再按保存入口 Key 读取 Sessions；新增 `nativePreview` 应用 ID `com.mikuchin.client.nativepreview`、独立 Keystore 与 `mikuchin-native-android` tsnet 身份，2 项 Kotlin 单测与本机 Preview APK 构建及 v2 签名校验通过，但**没有 Android 真机访问验收**。Tauri Debug NSIS 独立开发启动器已构建；发布构建不再静默回退编译机源码路径，支持显式 Runtime 路径。但 Windows 安装包目前仅启动器，**缺 Python/官方运行时/模型，不能视为可直接在其他电脑安装的完整发行包**。版本未变，未打正式 Tag/Release；详细状态 `docs/NATIVE_P3_ACCESS_PACKAGING_2026-11-21.md`，保持 main/15239 不变。

- Native P1 请求监控增量（2026-11-21）：受认证的 `GET /v1/mikuchin/request-monitor` 记录每次经 Gateway 转发的推理 POST 的固定类别、HTTP 状态、完成耗时、响应字节及失败状态；仅在内存中保存最近30条，重启清空，**不保存请求正文/消息/Token/用户IP/Key/路径**。真实 SSE 和非流式均按整个转发周期计时，GPU 锁拒绝记为 `gpu_busy`。Tauri `get_status` 与「原生状态」只读汇总已接通；如接口失效不得显示假数据。旧版 `answer_budget_tokens` 仍没有官方精确等价接口（官方 max_tokens 包含思考+正文），继续 health=false/501，不以字符数估算。动态 GPU 配额和单次精确 token 仍不支持，不应显示假配置。详情 `docs/NATIVE_P1_REQUEST_MONITOR_2026-11-21.md`。

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
