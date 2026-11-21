# Native Tool Calling：流式思考、图像任务状态与会话切换修复

日期：2026-11-21｜仓库：`E:\LLM\mikuchin`｜官方 PolyStrata 固定 `3e1642161198c50ff1abed4046f4e4f476099dbb`

## 用户报告

- 图片工具决策期间聊天气泡持续显示“模型正在判断是否需要调用图片工具…”，损害排版；普通文本响应无逐步输出及思考展示。
- Qwen-Image 运行时顶部显示“服务无法连接”，工具卡只有原始英文 `Local Qwen-Image inference`，无法看到模型卸载、生成、加载、KV 恢复阶段。
- 生成中无法切换会话；旧历史侧栏还调用已删除的 `intentRouting`，点击历史时触发 `ReferenceError`。

## 实施内容

1. **保留结构化原生 Tool Calling，同时流式传输**：新增严格的官方 SSE 汇聚器 `backend/gateway/chat_streaming.py`，按 index 组装增量 `tool_calls`，先显示 `reasoning_content` 与正文。只有拿到完整 `finish_reason=tool_calls` 及 `[DONE]` 才能执行工具；半截 JSON、未知工具不可执行。增加已鉴权的 `POST /v1/mikuchin/chat/turns/stream`。网络断开时服务端仍完成单次已接受请求、客户端只读查原 `turn_id`，不会重播生图。
2. **UI 按实际 token 逐步出现**：`native-turn-stream.js`、`app.js` 切换到 SSE 流读取，取消决策气泡中的固定大段占位文字。状态由工具卡承担；模型推理时仍使用已有折叠式思考 UI，进入正文后按原行为收起。
3. **持久化思考内容**：Turn SQLite 新增可向后兼容的 `reasoning_text` 字段，在首次 Gateway 启动时原位添加；既有 Turn、聊天会话、图片 Job 不变。新 Turn 的文本/图片工具决策保存模型已输出思考，刷新后只读查询可恢复。
4. **逐阶段状态**：任务卡将 `Waiting for official model unload`、`Local Qwen-Image inference`、`Real-ESRGAN 4x upscale`、`Restoring official text model`、`Restoring active KV snapshot` 显示为中文可读状态，并在展开面板只记录**实际观察到**的阶段，不伪造不存在的进度百分比。`/metrics` 随 LLM 正常卸载不可用时，网页使用 Native Gateway 的鉴权 `/health` 中 `native_gpu` 与 `native_image_jobs` 分辨“卸载 / 生图 / 恢复”，而不是误报整个服务断线。
5. **会话切换解绑 UI、不取消后端**：进行中的 Native Turn 先存档旧会话快照，允许新建或打开历史会话；原进程已接受的任务继续运行，回到旧会话后通过 GET 恢复图片、阶段及思考，不因导航额外 POST。发送/重新生成的旧页面异步回调使用原 session ID 验证，不能改写切换后的新会话。删除旧 `intentRouting`/ `chatImageSubmitting` 历史侧栏残留引用。

## 可核查验证

- 真实隔离 MeroMero：`runtime/p0-tool-probe.py --stream-only` 以无图像工具执行的真实 Stream 得到 **721 个 SSE 事件、1908 字符推理、95 字符正文**，以 `finish_reason=stop` 完成；保存于忽略目录 `runtime/tool-calling-p0-isolated/results-stream-only.json`。
- Python 完整单测：**117/117 passed**，包含 SSE 碎片化工具、不完整工具拒绝、HTTP SSE 认证及同 `turn_id` 幂等行为。
- Node 全量单测：**64/64 passed**，包含前端流解析、阶段映射、健康监测状态、会话切换保护；JS `--check` 和 `git diff --check` 通过。
- Chrome 独立 Mock Gateway 实测：思考中可见 `Thinking…` 及逐步文本、完整后看到正常文字/工具；新建会话、返回历史会话后原有聊天和图像仍在；清除旧 `intentRouting` 后无页面异常；没有使用在线付费图像模型。
- 生产安全重载：先确保 Worker 无运行/排队任务、Turn 无未完成项、Gateway 无活动客户端；独立 SQLite+配置备份 `runtime/migration-backups/native-tool-stream-ui-20261121-170015`。只替换 Gateway 实际服务进程（`12656 → 1100`），Supervisor 自动恢复为 `running`；官方引擎及 Worker 原 PID 未变。生产页面的 `app.js`、`sessions.js` 和两段新工具脚本 HTTP 200；无 Bearer 的 `/health` 和新工具 POST HTTP **401**。
- 生产数据：`native-chat-turns.sqlite3` 保留 **2 个原 Turn**、新列存在；原图像任务 **7 条 success**；官方子模块 SHA 不变。

## 明确未声称的验证

没有为了 UI 修复额外生成一张真实 Qwen 图（之前真实链路已完成），因此复杂 GPU 阶段 UI 是由真实 Worker 状态字段映射 + 单测验证，并非本次独立真实生图过程重新截图验收。无额外在线付费 API 测试。远端 CF Tunnel、安卓真机、多设备同时操作下的完整会话切换未单独回归。工具调用细粒度“构造 JSON 参数”的流式进度被安全隐藏，只有思考和正文公开；完整 JSON 经过服务端结构验证才执行。

## 回滚

将 `MIKUCHIN_NATIVE_TOOL_CALLING=0` 设置到 Gateway 的进程环境并在无活动 Worker 任务后重载，可暂停新的原生工具调用。备份数据库在上述目录；**禁止为了回滚而删除已有图像任务、覆盖正式存储或修改官方 PolyStrata**。旧版基线可使用 Git 提交回退代码。
