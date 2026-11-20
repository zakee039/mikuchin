# Native P1：本地 LLM 自动识别聊天生图意图（2026-11-20）

分支 `refactor/official-polystrata-gateway`，官方 PolyStrata 子模块保持原样；正式 main / 15239 不改。

## 模式和边界

- Chat 输入框新增 **「自动：关／开」** 开关，默认关，保存在**当前浏览器**的 `strata.auto-image-route`，不在各设备间自动开启。
- 开启后，每次发送纯文本消息先向 **当前 Native 官方本地模型**的授权 `POST /v1/chat/completions` 请求一次短的路由判断。输入只有当前用户文字、同会话此前是否已有成功生成图的布尔值，没有上传历史、图片或账户凭据到第三方。
- 分类只能是严格 JSON `{"action":"text|generate|edit"}`。无法解析、超时（35 s）、用户点击「跳过识别」、官方模型不可用、附带文件或当前开关关闭时都按**普通文字聊天**处理。普通文字不触发生图任务。路由请求禁用推理思考、MCP 与现有 `strata_image_tool`，最大输出 80 token。
- `generate` 建议生成新图；`edit` 仅当当前会话至少保存一张聊天生成图时建议修改上一张。**两种建议均显示与 P0 一样的页面内模型／尺寸／可能收费确认框**：取消不提交任何请求；确认后才走现有 `chat_submit` 单次收费动作。系统不会自行接受确认。
- 选择的模型和 LoRA/4×/尺寸仍来自全局生图设置，只有初次 `default` 可以在确认框中预选明确显示的**本地**模型，绝不会悄悄改成在线 API。浏览器正在路由或提交时不允许新会话/切换，以避免消息与任务跑到错误会话。
- 手动「生图」按钮始终可用，不需要开启自动模式。聊天意图分类是额外一次本地模型推理，可能增加首 token 延迟；不是模型内部原生工具调用。

## 图生图参考素材

- `chat_submit` 可附加布尔 `edit_previous=true`（默认 false），但客户端**不能提供任意 reference ID**给此路径。
- Gateway 在同一 SQLite 事务里检索**该会话**的最近成功图像任务，优先引用 4× 的原图（避免超大），再从私有生成图片目录读出 PNG、保存成 ImageJobStore reference，并以常规 `strata_reference_assets` 交给已有 Worker。`source_id` 保留源任务关联，`result.edited_previous=true` 让聊天前端显示编辑标记。
- 未生成过图片、图片已删除/过大、当前本地模型/在线服务不支持参考图时返回明确错误；**绝不因为无法编辑而静默降级为新图并收费**。同一 `session_id + request_id` 重复调用仍返回原结果，不产生二次付费。
- 仍不支持原版 LLM 在每条对话流内部自主调用 `strata_image_tool=true`；`/health.chat_image_tool` 保持 false，`chat_image_jobs` 仅指**人工最终确认的路由**。

## 独立正文 Token 上限研究结论

- 官方 PolyStrata 当前 `max_tokens`、`max_completion_tokens` **共同限制思考+正文**，`reasoning_budget_tokens` 是独立的思考上限，但**不是仅正文上限**。
- Native Gateway 只能拿到官方解码返回的字符串/SSE 块，无法获得每个生成 token 的可靠正文边界与模型精确 tokenizer 同步信息。使用 `max_tokens=正文上限+思考上限` 或把文字长度换算成 token 均不严格等价。
- 因用户要求保留旧版 `answer_budget_tokens` 的准确语义，此 P1 **不伪装实现**；`/health.answer_budget_tokens=false`、旧非空值需先清空的提醒保持。要达成精确控制，下一步应通过官方可维护的扩展接口、上游提出功能或正式适配官方引擎 token 事件协议，而不是改其子模块源代码或未经测量的 SSE 截断。

## 验证

- Node 测试覆盖 JSON 解析安全、开关默认关闭、路由不会提交付费任务、保持人工确认和同会话保护。
- Python 测试覆盖 session 隔离、上一张图片参考、编辑错误不扣费、重启/幂等原有契约。
- 临时 Mock Official 和 Image Worker 的真实 Chromium 场景：自动模式下普通文字仅回复文本；画图请求显示确认；取消不入队；确定后生成图片；编辑上张图再次确认，第二条任务 `source_id` 指向第一条且引用一个私有 reference；刷新后仍可见，模拟仅执行各确认一次。此测试**不调用真实付费 API**。
- 实机 GPU 模型分类验证和 GitHub CI 结果另以实际记录为准。真实 Qwen-Image 的完整图生图质量仍需人工验收。

### 本机真实官方模型测试

- 在 Native 开发栈的 ImageJobStore 运行数为 0、GPU 锁空闲、`/metrics.live.state=unloaded` 后，对 `15249/v1/chat/completions` 发送三条**仅分类**的授权请求。均使用 `reasoning_effort=none,reasoning_budget_tokens=0,max_tokens=80`、不启用 MCP/图片工具，未发生任何真实生图或付费调用。
- 官方 Gemma 4 运行实例分别返回 `{"action":"generate"}`（画薄荷绿小猫，冷模型载入约 17 秒）、`{"action":"text"}`（解释扩散模型，约 1 秒）、`{"action":"edit"}`（修改上一张图的眼睛，约 1 秒）。这是三条定向样例，不代表分类准确率统计。
- 冷启动耗时接近最初的 20 秒客户端超时，因此最终改为 **35 秒自动回退文字**，并增加「跳过识别」立即取消分类且继续普通文字对话，避免用户被锁住。
- 真实 Native 开发启动器已在 GPU/队列空闲条件下安全重启，只更新独立 15249/15240 三进程。重启后授权 `/health` 显示 `chat_image_jobs=true, chat_image_tool=false, answer_budget_tokens=false, image_worker_ready=true`；新 JS 静态资源授权前可公开读取（不含秘密），图片/会话接口仍需要 Bearer。
