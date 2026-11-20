# Native 聊天内生图（显式提交版）· 2026-11-20

分支：`refactor/official-polystrata-gateway`。本功能**不是**旧版 `strata_image_tool` LLM 自动工具调用，且不会修改官方 PolyStrata 子模块。

## 用户路径与语义

- 在 Chat 文本框输入**纯文本**提示词，点击旁边的「生图」，显示**页面内**确认框，列出全局设置选定的生图模型、分辨率、在线/本地类型和在线收费提醒。只有点击「确认提交」后才写入任务；取消确认不创建任何请求。
- 复用全局设置 `chat_image_profile`、`chat_image_settings`（长宽、步数、LoRA、4×）与独立 Image Worker。用户的全新配置若仍为 `default`，仅在确认框里**预选首款可用本地 Qwen-Image（通常 Official）**并标明「首次使用默认本地模型」；不会写入偏好，更不会自动选收费 API。已保存的其他模型若不可用，则提示前往设置修复。
- 独立 Worker 在后台生成；Chat 通过 `GET /v1/mikuchin/image-jobs?session_id=...` 跟踪队列状态。浏览器刷新、切换会话、关闭窗口均不重发图像生成请求。失败需用户再次明确操作。
- 生图成功后自动显示在本条消息里，图片通过带授权的 Blob 加载，**API Key 不进入 img URL、查询参数或缓存**；画廊记录按 `source=chat` 且关联 `session_id`。
- 若官方 LLM 支持视觉，自动执行**一次**本地视觉摘要：先在会话中保存 `vision_state=requested`，带图片 JPEG 缩放至最长边 768，`reasoning_effort=none`、`reasoning_budget_tokens=0`、`max_tokens=256`、`strata_image_tool=false`、`strata_mcp=false`。结果更新该条消息文本；失败不重复调用生图或支付请求。浏览器中途关闭可能导致视觉摘要中断，不会重复触发，用户可继续追问。
- 「取消排队任务」仅在 Worker **尚未认领**且 `phase='排队等待执行'` 时允许；已开始处理/在线请求可能已经计费，绝不强制取消或声称可退款。

## 幂等与隔离

- `ImageJobStore` 新增 SQLite `chat_image_requests(session_id,request_id,job_id,created)`，唯一约束 `(session_id,request_id)`。每次明确提交都先将关联 ID 保存在会话消息中。
- Gateway 通过已有 Bearer/Origin 边界只接受 `action=chat_submit/chat_cancel`；提交会在一次 SQLite 事务中写任务与关联。收到重复 ID 时返回原任务，甚至在任务失败或已清理时也不会重新扣费。Worker 进程重启对不确定在途付费调用仍标记失败，不自动重播。
- 单会话任务列表通过独立关联表过滤；一般 Image Studio 任务不混入。任务 id、图片 id 使用白名单验证，图片文件仍处于原 Native 私有目录。
- 生成阶段只能由已有 Image Worker 执行，Gateway 和 LLM SSE 线程都不发图像提供商请求。
- 本阶段不实现自然语言 LLM 自动决定何时生图；旧 `health.chat_image_tool` **必须保持 false**。新的 `health.chat_image_jobs=true` 仅表示显式用户提交的能力。不要把 `chat_image_jobs` 冒充旧版自动工具能力。

## 测试与已验证范围

- Python `test_image_jobs`：重复 request ID 幂等、SQLite 重启保留、Worker 重启不重发、未认领可取消、被认领不可撤回、图片成功索引到 chat 会话。
- Gateway HTTP 测试：未授权 401、非法 Origin 403、有效提交 200、重复 ID 返回同一任务、session 过滤、取消队列。
- 真实 Chromium + **一次性纯模拟** Image Worker：独立 `scripts/smoke-native-chat-browser.py` 只写临时 PNG、不访问实际生图 API；Chat 显示模型确认框，明确批准后发起一笔任务，等待成功显示图片，后续一次模拟视觉理解回复，刷新后保持，未触发第二次提交。私有图片无 Key 时返回 401。
- 本机真实 Native 运行时：已核对两个本地模型 `local-qwen-official` 与 `local-qwen-uncensored` 均显示 available；全局保存项仍为 `default`，因此启用上述明确展示本地默认模型的预选，而不触发任何真实 GPU 图像推理；Gateway/Worker 模块重启后 `health.chat_image_jobs=true`、`chat_image_tool=false`、`image_worker_ready=true`。
- 仍需与真实本地 Qwen-Image Official、Uncensored 及单独在线收费提供商逐一进行受控实机验证，本轮**不主动产生付费图像 API 请求**。旧主分支 `main` 和端口 15239 不触碰。

## 已知限制

- 不支持旧版那种 LLM 在普通聊天中自主选择生图的 `strata_image_tool=true`；这是为防止不受控收费而刻意保留的独立工作项。
- 尚未在生图任务中自动加入上一张图片作为编辑参考；此能力依赖所选模型真正支持 reference_mode。图片视觉摘要为下一轮文本对话提供辅助描述，但不能替代真正的图生图。
- 如果浏览器在视觉分析进行时关闭，可能保存为 `vision_state=requested` 而不自动重试；避免重复调用。
- 异步任务当前不可中断已经认领的 GPU/提供商调用；停止服务会按原有安全收尾策略完成任务。
