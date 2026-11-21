# Mikuchin 原生生图修复：无状态上下文、聊天专属确认、聊天图片预览

日期：2026-11-21｜工作树 `E:\LLM\mikuchin`，正式 Native `main`（产品 v0.4.0）；只修改 Mikuchin 所有的 Gateway/Web 文件，不更改官方 PolyStrata SHA `3e1642161198c50ff1abed4046f4e4f476099dbb`。

## 真实问题与根因（不是推测）

用户在同一个「无状态」会话按顺序提出：
- 「生成一张初音未来的真人图」
- 「再生成一张二次元的」

MeroMero 在第二轮真实思考中报告 `Since I don't have the previous image or topic in the current turn`，并生成无特定主题的通用二次元女孩。生产 `runtime/launcher-user-data/native-chat-turns.sqlite3` 的原始已保存请求经检查，**这两次同会话的模型请求 message roles 均只有 `['user']`**，并没有前轮历史。源代码存在两处直接删除历史的语句：

- `frontend/web/app.js:streamInto` 普通聊天：`stateless ? [history.filter(...).at(-1)] : history`
- `frontend/web/app.js:submitModelToolTurn` 原生工具调用：同样的「只保留最后一条 user」逻辑

因此模型确实**没有收到**「初音未来」的先前主题、工具调用和图像 prompt，而不是收到之后忘记了。修复两处，统一使用完整的**当前会话** `apiMessages()`；无状态只是不注入任何用户身份或角色人格，不跨会话获取内容。无状态聊天仍允许当前会话上下文完整继承，前轮 `assistant.tool_calls + tool` 也保持。原有思考流与折叠／展开行为**不改**。同步更新了设置页面及三语言中旧且错误的「每轮仅最近消息」说明。

## 在线 API：聊天内单次确认，默认关

- 每个 API 服务 `image-api-services.json` 新增 `chat_confirm_each_call: boolean`，历史没有此字段按 `false` 读取，保存时严格验证；在服务设置中勾选「聊天内调用时询问一次确认」即可开启，编辑服务其它字段不影响此值。
- 此字段进入可信的 Gateway API 服务目录，`resolve_image_request` 限定仅在线 API 的聊天工具调用读取。
- 选择在线 API 且该开关为 `true` 时，仍然沿用**一次性、不可伪造、单 Turn 验证**的确认 token 和幂等队列；为 `false` 则直接使用既有 `chat_submit` 任务队列，禁止不确定写入后自动重试。默认关闭不意味着绝不收费：用户主动使用在线 API 仍可能产生费用。
- **独立「生图」页**使用既有 `ImageJobStore.submit({request})`，无论开关如何都**不调用确认流程**。本次没有访问真实付费服务，也未向原正式 API 发起新的付费请求。

## 聊天内只读图片预览

- 不再点击图片即下载；点击聊天生成图或其 Original 链接，打开独立暗色全屏浮层 `chat-image-viewer`，右上角只有「下载」「关闭」两个按钮；Esc 和点击遮罩可关闭。
- 通过已有 `MikuchinSecureImages.load` / `prefetch` 读取带 Bearer 授权的受保护 PNG；页面既不暴露 Key，也不直接使用无鉴权资源 URL；关闭后回收 Blob URL，恢复页面滚动和先前焦点。
- 不提供画廊的删除、编辑、切图、缩放或超分操作。

## 隔离验证

- 生产数据只读分析：相关同会话两个 Turn 的请求角色列表均是 `['user']`；问题根因确定。
- Node 中实际执行 `apiMessages()` 的单元测试，以首轮 `初音未来` 的真实结构化 `assistant.tool_calls` 和第二轮 `再生成一张二次元的` 为例，得到 `['user','assistant','tool','assistant','user']`，保留主题及工具参数。
- 隔离 Chrome 无状态模拟完整两轮：真实浏览器点击设置「无状态」→生图→「再生成一张二次元的」后，测试模型录得第一轮 `['user']`、第二轮 `['user','assistant','tool','assistant','user']`；两次本地生成模拟 PNG 成功。此处使用独立 Mock Worker，不宣称重新验证了真实 Qwen 视觉一致性。
- 隔离 Chrome 图片点开只读预览，测试下载、Esc、右上角关闭，Page Errors/Network Errors 为空。
- 隔离 Chrome 持久化在线服务配置，将 `chat_confirm_each_call` 勾选后触发聊天确认框，手动取消，任务 DB 计数为 **0**；再次取消勾选并提交聊天生图请求，不弹框，**Mock Worker** 本地图像任务 `success`。没有访问外部网络或付费 API。
- Python 新增每服务布尔校验、历史服务默认关、开关持久化、强制确认一次性 token、默认直接幂等提交，以及独立生图不走确认等测试；Node 增加上下文原函数执行、只读预览控制验证。

## 上线、回退与剩余限制

已通过 SQLite Online Backup 备份正式 Turn / Conversations / Image Jobs / Gallery / Characters 数据库及服务配置：`runtime/migration-backups/chat-context-preview-confirm-20261121-174638`，没有读取/输出明文密钥。上线前预检时，真实 Image Worker **12 条历史 success、0 条在途**，Turn **0 条未完成**，Supervisor `running`。

**生产部署核验（安全完成）：** 首次检查曾发现 Tailscale 远端设备 `100.96.95.122` 在生产 Gateway `15239` 有 `Established` 连接，安全闸门阻止了初次重载，未中断连接。随后连接自然消失；二次核实客户端连接数 0、图像任务 0、Turn 未完成 0 后，只重启 Gateway 自有子进程，Supervisor 自动恢复，生产监听 PID `1100 → 37040`，Gateway 重启计数 3；**官方 PolyStrata 进程 `41712`、独立 Image Worker 与 Supervisor 的模型/Worker 子进程均未重启**。生效后 `/web/app.js`、API 设置、预览器 JS/CSS 和 i18n 文件均 HTTP 200；无密钥的 `/health`、`/v1/mikuchin/image-api-services`、新 Turn POST 均 401。正式会话保留 **9 个 Turn**、图库 **12 条 success**，API 服务 1 个（默认 `chat_confirm_each_call=false`）；Worker 心跳正常。官方子模块 SHA 未改变。没有实际执行收费 API 测试。

如需关闭原生 Tool Calling，设置 `MIKUCHIN_NATIVE_TOOL_CALLING=0` 并在空闲时重载 Gateway；不要主动回放原有可能计费的 Turn，也不要删除现有历史图像。在线请求默认免确认后的潜在费用由用户选择的 API 模型产生，请谨慎保管服务密钥。

真实 Qwen 生成美学质量（第二张是否能始终是初音未来）、远端 Tunnel/Android 和多设备同时编辑未在此次独立端到端测试中重新量化；本次针对 **系统是否传入同一会话上下文** 的确定性错误实施并验证修复。
