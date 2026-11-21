# Native Tool Calling 图像任务：自然开始回复与失败解释

日期：2026-11-21
工程：E:\LLM\mikuchin
边界：**只修改 Mikuchin Native Gateway/Web**；官方 PolyStrata（含子模块 SHA）、独立 Image Worker 和线上收费图像接口均不改动。

## 用户需求与行为

1. 全局设置「聊天生图模型」选中 `family=api` 时，彻底隐藏本地 GPU「运行方式」字段，模型选择器占满此行宽度；仍提示 API 在服务端独立生成，不需要卸载 LLM。本地 `qwen_turbo/sdxl` 继续显示运行方式并保留持久化值。
2. API / 本地同时运行模式在**任务成功提交后**，由相同对话的 LLM 生成一条轻量的开始回应，结合用户当轮指令与角色语气，避免“已经开始为你生成图片了”这一固定文案；`tool_choice=none`、`reasoning_effort=none`、`reasoning_budget_tokens=0`、`max_tokens=160`。用户可以在排队或后台生图时继续对话，模型不能声称图片已完成。
3. 图片成功后仍沿用 Native 的真实图片视觉理解尾部回复；模型参考发起生图时的上下文和新发生的同会话消息，禁用工具与思考，把图片与自然回复作为单独 assistant 消息放在当前正在进行的聊天回复**之后**。
4. 图片供应商返回失败后，任务卡片保留原始（脱敏、截断）错误与执行耗时，Gateway 单次将工具事件和供应商错误发回 LLM，让它结合上下文解释可能原因、给出安全的调整建议，并询问用户是否自愿重新调用（再次调用可能产生费用）。**不自动重试、不自动提交新任务**。
5. 只有响应里出现明确审核标记（如 `content_policy_violation`、`nudity`、`moderation_block`）才将 `error_category` 识别为 `moderation_block`。普通 `HTTP 400` 归未知，超时/网络/鉴权/额度/参考图错误分别归类，LLM 不得凭服饰修改内容推断供应商审核。错误文本只作为不可信引用，不得指导模型执行操作。用户还可以选择别的图像模型，或调整提示词后**显式**重新提交。

## 新的有界事件链

- `image_job_started`：只有图片 Job 已被独立 Worker 队列确实接纳才触发；后台线程执行一次不含图片工具的 LLM follow-up。新增 Turn SQLite 字段 `start_state`、`start_text`，用 CAS 抢占一次；刷新与会话切换只 GET，不重发 image job。
- `image_job_succeeded`：现有 `image_done → vision_running → vision_done/vision_failed` 流程不变（实际 PNG + 用户历史），成功图像通过单独消息承载，任务卡片保留。
- `image_job_failed`：`queued/running → failure_running → image_failed`，只读取得 `ImageJobStore` 中的 `error` 字段，按原有状态、Job ID、原指令及同会话消息运行**一次**无工具/无思考 LLM 解释；成功后存入 Turn 的 `text`，失败时保守降级为错误提示。模型服务或 Gateway 重启中断这段解释时，SQLite 启动迁移将该 Turn 终止为 `image_failed`，**永不重复向供应商发起请求**。
- 前端 `native-tool-client.js` 保留错误卡片（失败 state），使用 `native_completion_type='failed'` 将 LLM 的解释追加成普通 assistant 消息；不能生成图时不附带图片工具。前端 `deliverNativeBackgroundCompletions()` 使用 Turn ID 去重，并在其他 LLM 回复进行时延迟插入。始发提示稳定保存在原 assistant 消息中，刷新后继续同步 `start_state/start_text`。

## 安全与兼容性

- Native 旧 SQLite 只做增量添加字段；保留所有既有 Session、Turn、Gallery 与任务结果。
- 用户自选开启的在线 API **聊天内单次确认**仍独立有效；未确认不排队、不发开始回应。此次没有删除/绕过收费确认。
- 对本地独占模式，原 GPU 卸载/恢复期间**不主动开启并行开始回应**，避免因模型卸载造成冲突；失败尾部在模型可用后仍会尝试输出自然解释。
- 图像服务的 `error` 字段由原独立 Worker 脱敏并截断，新模块在发给 LLM 前进一步去掉网址/凭证路径。错误信息仍被视为外部不可信文本。
- 服务端 LLM follow-up 与普通聊天共享同会话推理锁，不会与自己重叠；异步进程永不调用图像生成接口。
- 不能从未知错误推断“色情/裸露内容”；建议不得为了规避平台限制而进行隐蔽绕过。
- 版本号、安装包、Release、Tag 均不变，官方 PolyStrata 不改。

## 验证

- Python 回归 **150/150**；Node 回归 **88/88**。
- 新 Python 测试覆盖：一次性 started follow-up、真实审核码、未知 HTTP400 不误判、超时分类、错误脱敏、同会话新历史、无工具/无思考、LLM 失败降级、重启中断不重发。
- 新 Node 测试覆盖：API 隐藏运行方式、本地保留、started 回复不会被后台轮询覆盖、失败卡片 + 后续独立回复、聊天并发完成后才追加、Turn ID 去重。
- 隔离 Chrome + 假图像供应商：在线模型 API 设置界面没有「运行方式」；任务开始有一条由假 LLM 输出的自然确认；慢图像期间发送普通聊天成功，图片在普通聊天回答后独立出现；模拟 `ImageProviderError: image API HTTP 400: content_policy_violation (nudity)` 时失败卡片记录具体错误，随后独立 LLM 说明；浏览器 reload 后没有重复消息。Page errors 为空。全部用 Mock，**没有访问真实第三方付费图片服务**。

## 生产部署记录（已完成）

- 本机生产 SQLite Online Backup、图像服务配置、活跃 LLM JSON 已保存在
  `runtime/migration-backups/native-image-event-followup-20261121-192602`。原有数据没有覆盖、丢弃或人工重放。备份包含 Native Turn、Conversations、Characters、Gallery、Image Jobs 五个 SQLite。
- 重载前 `ImageJobStore` 共 **22 success、1 failed、1 draft**；`draft` 是用户已保存但尚未执行的草稿，不是正在运行的图像任务；进行中的图像任务 **0**、Native Turn **0**，官方 LLM upstream 没有活动推理连接。
- 在上面状态复查后，只停止并让 Supervisor 自动恢复 **Mikuchin Gateway** 监听进程（PID `50360 → 9264`；Supervisor Gateway restart `5 → 6`）。有两条空闲客户端连接需要重连；官方 PolyStrata 子进程 `37936`、独立 Image Worker 子进程 `9612` 均未重启。官方子模块 SHA 仍 `3e1642161198c50ff1abed4046f4e4f476099dbb`。
- 正式页面根路由、`/web/app.js`、`/web/characters.js`、`/web/native-tool-client.js`、`/web/app.css` 全部 HTTP **200**；未提供 Key 的 `/health`、`/v1/mikuchin/chat/turns`、`/v1/mikuchin/image-models` 均 HTTP **401**。旧 Turn 三种已有终止状态和图像数据库计数未变化，新增 `start_state/start_text` SQLite 字段检查通过，Image Worker 心跳正常。
- 功能提交 `13c1f18cfeb4aba1955d4a97311aa01b253b608e` 已推送 `origin/main`。GitHub Actions **Version consistency**、**Native PolyStrata Gateway contracts**、**pages build and deployment** 三项均为 success。
- **未发起生产真实付费生图试验**，因此生产中每个不同提供商的错误文案是否可解析仍需用户以后实际失败时检验；隔离 Mock 已覆盖审核失败、未知失败和并发对话，不冒充真实模型输出一致性。
