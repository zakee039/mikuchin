# Native P0：网页聊天能力协商与接口兼容（2026-11-20）

开发分支：refactor/official-polystrata-gateway。此文档为当前实现状态，正式 main 保持不变。

## 背景与实测问题

原 Gateway 在独立 Image Worker 提供生图模型时，GET /health 返回 image_generation=true。共享 Web UI 错把这个能力当成「聊天内可调用图像工具」，对每条聊天请求附加 strata_image_tool=true；Native 对该尚未迁移的字段返回 HTTP 501，使默认聊天可能完全失败。图像工作室在「解析提示词」时发送 strata_image_tool=false，也被原来「字段一出现就 501」的检查拒绝。

answer_budget_tokens 是 Mikuchin main 的**仅正文 Token 上限**，与官方 PolyStrata 的 max_tokens / max_completion_tokens（思考与正文合计）不等价。禁止静默转换。

## 已接入的协议

- GET /health 保留 image_generation：独立 Image Studio 中至少一款图像模型可用。
- 新增显式能力：chat_image_tool=false、answer_budget_tokens=false、chat_mcp=false。绝不使用 image_generation 代替 chat_image_tool。
- 共享 Web UI 新增 web/chat-capabilities.js，Native 不再附加未实现的 strata_image_tool=true 或 strata_mcp=true。对于没有这些新字段的旧服务，保留原版请求兼容行为。
- 当当前或已保存会话设置了独立正文上限时，Native 在调用前明确提示需要清空，既不会忽略上限，也不会替换成不同语义的 max_tokens。采样上限输入框无值时禁用，有旧值时允许清空；思考预算保持正常。
- Gateway 接受 strata_image_tool=false 并从上游请求中剔除。图像工作室的 LLM Prompt 解析不再因此返回 501；true 和 answer_budget_tokens 的未实现请求依旧严格返回 501，防止静默降级。
- Gateway 继续 Bearer 与 Origin 鉴权；独立 Image Worker 和 Image Studio 不受影响。

## 验证

- Python Gateway 的 FakeOfficial 真实 HTTP 测试验证 SSE、角色/工作流、HTTP 501、图像模型可用但聊天工具不可用、图像工作室 false 参数可转发。
- node --test frontend/web/tests/*.test.mjs：独立纯函数测试覆盖 Native/旧版能力、MCP 禁用、stateless、思考预算不变、正文上限报错、脚本顺序。
- Native 开发端口：Gateway 15249、官方引擎 15240；正式生产 15239 不接管。官方 PolyStrata 子模块零源码修改。

### 真实 Native/CUDA + 浏览器端到端验证

- 重启前确认 Native 图像任务没有 queued/working/running、GPU 独占锁空闲、官方引擎 metrics.live.state=unloaded，之后仅重启 Native 试用启动器与独立三进程栈；没有重启 main 15239。
- 重启后在开发 Gateway 15249 查询鉴权 /health：image_generation=true, chat_image_tool=false, answer_budget_tokens=false, chat_mcp=false, image_worker_ready=true。新静态资源 /web/chat-capabilities.js 返回 HTTP 200。
- 使用当前官方 Gemma 4 26B SM86 CUDA 模型执行真实 Chat Completions：非流式、含 mikuchin_stateless=true、strata_image_tool=false、strata_mcp=false、max_tokens=24 的请求返回 HTTP 200，正文 P0_OK（5 completion tokens）；SSE 带临时 session_id 及 32-token 上限返回 HTTP 200、8 个数据事件、正文 P0_SSE_OK、finish=stop 和 [DONE]。
- 真实思考预算 + SSE：reasoning_effort=low、reasoning_budget_tokens=48、max_tokens=120 的请求返回 HTTP 200、66 个事件、218 个 reasoning_content 字符、正文「4」及 [DONE]，没有流式 JSON 错误。这验证思考和正文的分离输出路径，但不代表支持仅正文 Token 上限。
- 脚本 scripts/smoke-native-chat-browser.py 启动**临时随机端口**的 Mock Official Engine + Gateway，使用临时假 Key 和临时数据目录，模拟 image_generation=true 但 chat_image_tool=false；在真实 Chromium 浏览器加载完整 Web UI、发送消息，最终显示 P0_BROWSER_OK。Fake Official 的接收记录只有 messages,model,reasoning_budget_tokens,reasoning_effort,stream，证明没有转发 strata_image_tool、strata_mcp、answer_budget_tokens。采样抽屉显示原生正文上限不可用说明。脚本在 STOP 文件出现后自行清理，相关临时浏览器和服务均已关闭。

## 未完成、不得误报

1. 仅正文 Token 上限没有真正等价的官方内核控制，不能标称完整 P0。
2. 聊天内生图、生成后视觉回喂与 MCP 工具编排，不能用独立 Image Studio 代替。
3. 主版本的完整模型管理/监控和全局语言接口在后续 P1。
4. 旧版手动 KV 快照管理是 Native 明确的设计取舍，不原样回迁。
