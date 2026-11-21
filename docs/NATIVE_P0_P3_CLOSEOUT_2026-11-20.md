# Native P0–P3 收尾进度（2026-11-20）

工作分支：`refactor/official-polystrata-gateway`；不修改生产 `main`、15239、正式浏览器 Key 或 Cloudflare 凭据。当前是**局部补齐**，不代表四阶段已全部验收或可以发布。

## 此次真正补齐

### P1：模型配置/卸载策略/Key

- Native 启动器设置中增加**本地 JSON 配置注册**（限 256 KiB，有效官方 `exe/args`），导入至单独的 `mikuchin-native-runtime/config`；只按白名单文件名选择已注册配置，不接受 `../`、绝对路径等绕过数据目录的模型设置。
- 注册与选择不会立即切断正在推理的服务。只有下一次手动「卸载模型→加载模型」才按所选配置启动，保持以前已经明确同意的整栈安全停止语义。
- 新增 `idle_unload_s`：0（禁用）、300、900、1800、3600 秒，Native preferences.json 默认 900 秒。由 Tauri 在真正启动前，从**已注册原 JSON**生成独立 `launcher-user-data/active-model-config.json` 并修改 `idle_unload_s`；不篡改用户导入的原 JSON，也不改官方 PolyStrata 子模块。
- 新增 Native API Key 轮换按钮。**只有 Supervisor、Gateway 和 Worker 全部停止并且不处于自动恢复状态时才允许**，需要用户明确确认。新随机 Key 加密写入 Native 专用 Windows DPAPI；不会修改正式版 Key。旧客户端的 Key 立即失效，手动加载后须重新复制与配置。**验收不主动轮换用户真实 Key**。

### P2：画廊已有作品手动 4×

- Native ImageJobStore 新增单纯 `kind=upscale` 任务；按画廊已有原图的 32 位 hex ID 及实际尺寸验证，在 Worker 持有 GPU 独占锁时调用现成 `local_images.upscale` Real-ESRGAN，再经 `gallery.attach_upscaled` 将封面 4×、原图合成一组。
- 该任务**不重新调用任何 Qwen-Image 或在线生图 API**。对于相同的作品 ID，running/success 则返回原任务 id，防止重复执行；失败时原图仍完好，重新尝试必须是用户主动操作。
- 原生 Gallery 按 `health.native_upscaler_ready` 开启原先被强制隐藏的「生成 4× 图」按钮；进行中禁用，成功显示原图/超分配对，轮询兼容 Native 的 `success` 状态。
- 已补无真实 GPU 的端到端 Python/HTTP、浏览器脚本契约测试。不能把 Mock 图片倍率测试误称真实 GPU 生成已通过；真实 Real-ESRGAN 单次处理在先前 Native GPU 验证中已有成功记录。

### P3：多语言服务设置

- Native 新增持久 `GET/POST /v1/mikuchin/ui-language`，仅支持 `zh-CN/en-US/ja-JP`，存入独立 SQLite global_settings。GET 和 POST 均经 Native Gateway Bearer/Origin 鉴权。
- 原 Web i18n.js 的 GET 改为带当前会话授权头；其他设备可读取同一语言偏好。不修改已有聊天内容或模型返回文本。

## 回归与约束

- Rust Native 配置测试：默认模型配置、路径白名单、配置文件原件不被修改、有效覆盖、禁用空闲卸载、非法时间拒绝、API Key 轮换只允许停止状态。
- Python Gateway：按已有任务真实 HTTP 路由验证语言 401/403/200/无效语言 400，画廊 4× 唯一入队、鉴权、旧生图提供商调用次数不增加。
- Web：Gallery 与 Launcher 的新按钮/模型选择合同；核心聊天 SSE/角色/图像/语言旧测试全部保留。
- 本机安全更新：只有 Image Worker 队列无 running，GPU exclusive 锁空闲、官方 LLM 不在生成时才重启 Native 开发栈；确保正式 15239 不受影响。

## 未完成，不能误报

- **P0** `answer_budget_tokens` 的独立正文精确上限官方 PolyStrata 没有等价接口，暂保留 `health.answer_budget_tokens=false`。普通聊天及模型流内 `strata_image_tool=true` 不是同一种功能；后者仍未迁移。真实第三方 MCP 工具执行尚未配置验证。
- **P1** 旧版完整内容型请求监控及 WDDM GPU budget 动态管理还未移植。现有安全监控仅能展示模型指标/状态，不显示所有聊天正文。
- **P2** Uncensored 与 Official 两套模型的端到端图生图品质评估未全部完成；新手动超分入口需要真实 Native 模型/画廊一轮用户界面验收。
- **P3** Native 独立 Cloudflare Tunnel Token、域名绑定与公网贯通需要用户配置；Android 客户端兼容测试、多 OS 发布构建与灰度主分支未完成。不制作正式安装包/Tag/Release。

## 2026-11-21 用户反馈：任务计时及聊天输入区精简

- **计时口径**：`started_at` 不再在浏览器点击 / HTTP 入队 / Worker 认领时填写。在线生图仅在调用图像 API 前记录；本地 Qwen / Real-ESRGAN 只有拿到 GPU 并准备执行实际模型子进程后才记录。排队、等待 GPU 锁、卸载文本 LLM 不计运行时间；已完成任务以 `finished_at` 冻结。进行中而 `started_at=NULL` 显示「排队中」。**同一修复已同步写入旧版 main 的图像任务和前端代码**，旧版服务仍停机，未主动启动。
- **聊天工具条**：用户明确取消 Native Chat 的「生图」与「自动：关」两项交互；删除按钮、意图识别入口和独立的临时路由脚本。普通 Chat 只走文字对话路径。独立生图页面、Gallery、既有聊天生图记录的状态、视觉摘要和取消已入队记录的能力仍保留。
- 更新 Native 本机运行实例时确认 Worker 无 running、GPU 锁空闲、LLM 不在生成，才以启动器原生 STOP 方式安全更新；验证 Gateway 15249、引擎 15240 及新 Web 静态资源，新版本未触碰正式 15239。
- Mock/契约回归：Native Gateway 82 项、Web 42 项、Launcher 10 项；旧版 main 的服务单测 19 项、Web 21 项。均已通过；**不等于真实两套图像模型全部验收。**

**不能把当前修复说成 P0–P3 全部完成。**
