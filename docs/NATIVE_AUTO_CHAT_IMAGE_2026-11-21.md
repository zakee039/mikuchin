# Native 聊天自动生图、KV 交接与 MeroMero 正式配置（2026-11-21）

## 目标与行为

- 用户明确说「生成一张初音未来的图片」等指令时，`frontend/web/chat-image-router.js` 识别明确生图意图。普通知识问答、对生图原理的讨论、否定式指令继续普通对话。编辑意图只有当前会话确有成功图片时才采用 `edit_previous`，且必须有兼容参考图的本地图像配置。
- 在用户可见聊天中不再暴露模型自行输出的 `dalle.text2im` JSON。**从未执行未知模型生成代码**，仅解析允许的图像工具名称，并以用户原始明确图像请求作为授权条件。
- 生图前默认保留用户原始图像指令，不额外运行可能覆盖当前活动 Slot 的 LLM 提示词改写；需要更强上下文扩写时应先隔离该次推理的 KV。图像请求发往经过授权的 `POST /v1/mikuchin/image-jobs`，`action=chat_submit`，使用 32 位十六进制的 `session_id`、唯一 `request_id`，先持久化 ID 再提交，遇到网络故障 **不自动重复提交**。本地模型不要求二次点击确认；在线服务可能收费，提交前显式确认。
- 后端图像 Worker 在独立 GPU 互斥下保存模型活动 KV 槽位（若启用），卸载官方 LLM，载入本地 Qwen-Image 或调用指定图像后端，完成本地生成/超分，卸载图像模型，恢复 LLM 并尝试恢复 KV；图库与聊天任务索引均按会话和原有幂等契约存储。Worker 进程结束或异常不允许重播带收费风险的任务。
- 客户端根据 `request_id` 轮询，仅在已完成时绘制图片和回复。若正式 MeroMero 已启用 `vision`，把**刚生成的**图片做一次受认证的本地视觉短回复（`reasoning_effort=none`、`reasoning_budget_tokens=0`、`max_tokens=256`，不调用生图工具）；视觉异常时保留图片，显示可说明的失败信息。离开页面不会取消已提交的图像任务。

## KV 实际支持边界

- 官方 PolyStrata 目前是唯一可用的推理引擎，不修改其子模块。原生内存会话复用依赖 `--conversation-cache-mib auto --conversation-cache-slots 4`。显式 `/slots/0?action=save|restore` 仅保存**当前单活动槽**，不等价于逐会话/逐模型的磁盘 KV 快照管理。
- 仅在正式模型配置提供 `slot_save_path`、目录存在且引擎响应成功时，`backend/gateway/local_images.py` 在独占 GPU 锁中调用官方私有 API 保存临时快照。重载后尽力恢复并删除临时文件，不能承诺每一轮都完整复用。
- 任一步快照失败或缓存失效，原文聊天记录仍在 SQLite，会在随后请求用完整上下文正常 prefill。任务成功不因 KV 保存/恢复错误而重试生图。
- 原引擎的会话磁盘接口只支持单槽，不能将「按会话保存 KV」宣传为已完成的能力。未来扩展需要明确的多会话缓存版本隔离、时序和失效机制。

## 正式模型与资源隔离

- `E:\LLM\mikuchin\runtime\config\G4-MeroMero-26B-Q4_K_M.json` 保存实际新配置，`runtime\config\official-sm86-model-test.json` 留作回退。
- 使用 `E:\LLM\models\G4-MeroMero-26B-A4B-it-uncensored-heretic-Q4_K_M.gguf`，**128K 上下文、14 CPU 线程、INT8 KV、900 秒空闲卸载**，延续旧版 MeroMero 专家 Profile。
- 视觉投影文件 `E:\LLM\models\G4-MeroMero-26B-A4B-it-uncensored-heretic-mmproj-BF16.gguf`，`runtime\build-vision\bin\strata-vision.exe` 由官方固定 `69f201a2051ea9b9e9b50c3cc56afd9e2ae64414` 源码单独构建 CPU 版；4 个官方 CUDA DLL 依赖独立放在 `runtime\cuda\bin`，不依赖旧版仓库。
- 先前的模型/数据库/图像配置已备份到 `runtime\migration-backups\chat-auto-image-20261121`，原始聊天和画廊保留，未改动用户凭据。模型选择属于本地 Launcher 偏好，不写入 Git。
- 旧版图像 profile 名称 `qwen-image-2.1-turbo-official/uncensored` 在 Native 中映射到 `local-qwen-official/uncensored`，严禁未知 Profile 自动切换为收费云 API。

## UI 与部署验收

- 采样抽屉移除独立正文 Token 预算输入框和提示，思考预算独占一行；旧会话的 `max` 字段在 Native 中不再阻止对话，也绝不冒充 `max_tokens`。
- 无附加按钮：用户在聊天输入框直接提出生成需求，即可提交；独立「生图」和「画廊」页面保留。
- 执行的测试：Native 网页 Node 测试、Gateway Python 单元测试、正式模型健康检查、无收费的合成图片视觉识别、只用本地 Qwen Worker 的 GPU/单槽 KV 交接验证。
- **无法从自动化测试推断实际画质**；原图成功和显存/缓存恢复为独立可验证指标。若浏览器 UI 的边缘路径不确定，应明确记录，不能宣称全设备兼容性已验证。
- 修改后保留 `v0.4.0` 版本和已存在的 Tag，不发布 APK/Release；官方 PolyStrata 子模块 SHA 维持 `3e1642161198c50ff1abed4046f4e4f476099dbb`。

## 正式配置异常回滚

1. 核查用户当前无推理和 Worker 任务，保存私有配置与 SQLite 备份。
2. 停止 `Mikuchin-Native-Dev-Launch`，确认 Native 15239/15240 已释放。残留的专属 Cloudflare Tunnel 进程需先明确进程路径再清理，不要停止 AgentDock Tunnel。
3. 将 Launcher `%LOCALAPPDATA%\MikuchinNativeLauncher\preferences.json` 中 `model_config` 恢复为 `official-sm86-model-test.json`，不要改动其他密钥或偏好。
4. 重新启动计划任务，验证本机健康、会话数和公网 401 鉴权。旧模型的 8K 测试配置并不意味着正式 128K 的性能结论。

## 真实 GPU、KV 快照与回喂补充验收

- 真实本地 Qwen-Image Worker 成功生成 384×384 PNG：任务 `success`、`provider=local`、`gpu_handoffs=1`，没有调用在线付费生成服务。
- 官方推理日志记录 `strata-poly: session saved: 124 tokens, 320 MiB in 299 ms`，生图后模型重新加载，接着 `strata-poly: session restored: 124 tokens, 320 MiB in 12269 ms`。
- GPU 状态从 `generating` 经 `restoring` 回到 `idle`；临时 Slot 文件被删除，任务只执行一次。此验证是**活动 Slot 恢复**，并非证明所有缓存会话均恢复。
- 当前 Chat 视觉尾部发送历史上下文和生成图像，带原会话 `strata_session_id`，禁用思考及生图工具，限制 256 总 Token；改动对应网页结构检查已经通过，但完整真实浏览器交互仍需单独验收。
- Gateway Python 全套 88 项、Native 网页相关 Node 15 项测试通过；官方 PolyStrata 子模块 commit 保持 `3e164216` 不变。
