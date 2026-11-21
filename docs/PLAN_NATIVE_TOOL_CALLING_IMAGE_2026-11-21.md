# Mikuchin Native Tool Calling 重构实施计划书

> 版本：计划 v1.0｜编写日期：2026-11-21｜**状态：待下一对话实施，本文件不是功能完成报告**
>
> 主仓库：`E:\LLM\mikuchin`（`main`，起始审计 HEAD `77bf25b`）；旧版只读回退工作树：`E:\LLM\mikuchin-old`。项目版本暂为 `v0.4.0`。
>
> **不可修改**官方 PolyStrata 子模块（`backend/polystrata`）的源码、依赖、Git 指针；固定 SHA `3e1642161198c50ff1abed4046f4e4f476099dbb`（`v0.1.45-poly.10`）。

## 一、决策与目标

**核心决策：废弃“前端关键词/正则识别决定生图”的主架构，改成 MeroMero 通过官方 `tools` / `tool_choice` 决策，Mikuchin Gateway 独立编排工具执行。**

用户目标：像真正具备工具能力的聊天助手那样，根据完整对话、用户身份、角色卡、世界书、上传图片和上下文，自主选择普通回复、`generate_image` 或 `edit_image`。不要求用户输入特定关键词，不允许再由前端把“生成一张初音未来”之类的文字硬编码为直接生图。

预期典型交互：

1. 用户说“明天是她的生日，给她做张暖色系贺图”，带工具声明的 MeroMero 首先完成一次**本地文本推理**，返回结构化 `tool_calls`。
2. Gateway 验证工具名、JSON 参数、用户会话及权限，解析出生成/编辑操作；选择图片引擎和尺寸等仍以**用户已有的全局图像设置**为准。
3. **本地** Qwen-Image 可自动提交；**在线可能收费**的模型进入一次性确认，确认前绝不入队，也不因模型主动建议而自动付款。
4. 任务创建成功后显示明确的“已排队/正在生成/完成/失败”，不得在 Running 状态错误渲染“Error: Local Qwen-Image inference”或永远显示“(being written)”。
5. GPU 独占生图走现有 `Image Worker → 活动 Slot KV 尽力保存 → 卸载 LLM → 生图 → 重新加载 LLM → 尝试恢复 KV`。
6. 生成图片显示于**发起请求的原会话**。Gateway 组织工具结果，禁用工具，给 MeroMero 刚生成的图片做最多 256 总 Token 的短视觉尾部回复；失败时依然保留成功图片。

**不是本轮研究目标**：重新训练/LoRA 微调 MeroMero、修改 PolyStrata 推理内核、跨模型 KV 复用、多会话 KV 全量持久化、全新图像引擎、收费服务自动重试、全端正式安装包。

## 二、已经实证的基线与缺口（不能误报成完成）

| 事项 | 截至写本计划时的实际状态 | 代码/证据 |
| --- | --- | --- |
| MeroMero | Native 正式配置已准备：128K、14 线程、INT8 KV，视觉支持已配置；运行时状态需每次开工复查 | `runtime/config/G4-MeroMero-26B-Q4_K_M.json`（私有） |
| 官方 Tool Calling | 官方代码接收 OpenAI `tools`、`tool_choice`，提供非流式 `message.tool_calls` 和 SSE `delta.tool_calls`；**尚未证明当前 MeroMero 在复杂真实对话下稳定调用它** | `backend/polystrata/serve/server.py` `_openai`、`openai_chunks`、`openai_collect` |
| 当前前端 | `app.js:send()` 先调用 `MikuchinChatImageRouter.intent`；命中则绕过 LLM，直接 `submitAutoChatImage`；不是模型做决策 | `frontend/web/app.js`、`chat-image-router.js` |
| 当前 Gateway | 对聊天请求做鉴权、参数验证、`gpu_turn` 共享锁，然后直接流式代理；**未注册、消费或执行模型原生 `tool_calls`** | `backend/gateway/app.py` `do_POST`、`_proxy`、`_proxy_unguarded` |
| 官方内置 MCP | 只有显式 `strata_mcp=true` 时才进入官方 `run_with_mcp`；可能在本轮推理尚未结束时执行外部工具，**不适合直接承担需要卸载 LLM 的 GPU 生图** | 官方 `server.py` `_openai` 中 `use_mcp` 分支 |
| 已有图片任务 | `ImageJobStore.chat_submit(session_id,request_id,request,edit_previous)` 同一 SQLite 事务写入关联表与任务，重试同一 ID 不重复扣费 | `backend/gateway/image_jobs.py` |
| 已有 GPU/KV | 本地 Qwen-Image 已实测一次活动 Slot `save/unload/generate/load/restore` 成功；**只能证明当时活动 Slot，非所有会话 KV** | `backend/gateway/local_images.py`、`docs/NATIVE_AUTO_CHAT_IMAGE_2026-11-21.md` |
| 视觉尾部 | 当前浏览器可以发带图片的第二次聊天请求；仍需把它转为可靠的工具结果续写闭环，不能依赖单个浏览器页面一直打开 | `frontend/web/app.js` `describeNativeChatImage` |
| 真实用户问题 | 关键词方案曾出现漏判；后续截图出现任务卡 Running/参数写入中、页面右上“服务无法连接”，需分开排查**前端状态、后端联通、任务生命周期**，不能把截图认定为模型或 GPU 的唯一故障 | 用户反馈，待下一轮带时间戳日志核实 |

**重要判断**：官方引擎“有 Tool Calling 接口”和“MeroMero 当前 GGUF 一定能稳定调用”是两回事。**第一阶段必须做无生图的模型真实 Tool Calling PoC**；若失败，不绕过事实宣称完成。

## 三、架构边界（明确责任，不魔改 PolyStrata）

```text
用户/角色/世界书/历史/图片
     │
     ▼
Mikuchin Web（只发送完整聊天，显示状态/确认，不做正则工具决策）
     │ Bearer + Origin
     ▼
Mikuchin Gateway（模型 tools 注入 + 推理结果消费 + 参数安全校验）
     ├─ 普通回复 ───────────────► 原会话展示文本
     └─ tool_calls: generate_image / edit_image
          │ 结束模型响应/释放共享GPU锁后，才允许执行
          ▼
    Gateway Tool Dispatcher / 持久 Turn 状态
          │ 用户本地Profile / 在线付费确认 / 唯一request_id
          ▼
    ImageJobStore.chat_submit ─► 独立 Image Worker
          │                  （同一次幂等任务）
          ▼
    GPU独占 → 官方活动Slot KV尽力保存 → LLM卸载
          → Qwen-Image / 图生图 / 超分 → LLM重载 → KV尽力恢复
          │
          ▼
    工具结果 / 生成图像 / 非递归视觉尾部调用（tool_choice=none）
          ▼
    原会话：成功图片 + 简短自然回复（失败仍保留图片）
```

不得将官方 PolyStrata 内部 `strata_mcp` 直接绑定本地图像 GPU 工具。可保留现有普通 MCP 功能，但在 Native 生图决策请求中应显式隔离 `strata_mcp=false`，避免双执行者/命名冲突。其他 MCP 工具恢复方案另行评估，不能为了生图破坏已有正常 MCP 会话。

## 四、协议设计（优先小型纵向切片，再完善）

### 4.1 模型侧暴露的 Tool Schema

第一阶段**只开放 `generate_image`**，第二阶段再开放 `edit_image`，单条用户消息最多自动执行**一个**图像工具。JSON Schema（建议）：

```json
{
  "type": "function",
  "function": {
    "name": "generate_image",
    "description": "Generate a new image for the user using the currently configured Mikuchin image service. Call only when the user actually requests an image; ordinary discussion must remain text.",
    "parameters": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "prompt": {
          "type": "string",
          "description": "A complete visual prompt grounded in the current chat and character context."
        }
      },
      "required": ["prompt"]
    }
  }
}
```

```json
{
  "type": "function",
  "function": {
    "name": "edit_image",
    "description": "Edit the latest successful generated image in this conversation, preserving unspecified features. Do not create an unrelated image.",
    "parameters": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "instruction": {"type": "string"}
      },
      "required": ["instruction"]
    }
  }
}
```

不把 `provider_id`、`file_path`、`api_key`、本地命令或任意 `image_id` 的最终选择权交给模型。模型给出的仅是**不可信参数**；服务端验证长度、UTF-8/JSON、工具白名单和内容类型。分辨率、LoRA、参考模式、超分、是否调用在线服务由用户已有的全局设置 + 服务端可信配置决定。编辑只采用**当前会话**最近成功的服务端图片（已有 `edit_previous` 语义）。

初次注入使用 `tool_choice:"auto"`，尾部视觉恢复及内部状态检查用 `tool_choice:"none"`、`strata_mcp:false`。仅检查支持，不要求前端自己拼出动作关键词。

### 4.2 Gateway 编排 API（设计目标，**当前不存在**）

优先新建**受 Bearer/Origin 鉴权保护**的 Native 编排接口，避免直接破坏现有 `/v1/chat/completions` 兼容代理：

- `POST /v1/mikuchin/chat/turns`：接收 `session_id`、稳定 `turn_id`、消息/角色上下文和采样参数；创建/查询幂等推理 Turn，调用官方 `/v1/chat/completions` 注入 `tools`。
- `GET /v1/mikuchin/chat/turns/<turn_id>`：只返回该会话的状态、可见文本、已脱敏工具参数、任务 ID、图片结果与错误；过滤其他会话；支持刷新后恢复。
- `POST /v1/mikuchin/chat/turns/<turn_id>/approve`：**仅在线收费服务**使用，一次性短期确认，服务端绑定 `session_id / turn_id / profile / 请求摘要`；拒绝客户端任意 `approved:true` 冒充授权。
- 现有 `POST /v1/mikuchin/image-jobs` / `chat_submit` 继续作为**内部下游执行机制**，通过同一个事务和原有唯一 ID 去重；不复制第二套收费生图队列。

实现方案优先为**非流式模型决策 PoC**，便于稳定读取完整 `message.tool_calls` 和 `finish_reason`。验证通过后再把模型普通文字/思考增量展示升级为 SSE；SSE `delta.tool_calls` 必须按 `index` 合并 `id/name/arguments`，**只在 `finish_reason="tool_calls"` 且 JSON 完整时认可调用**。绝不能一边读取半截 JSON 一边创建收费任务。非流式 PoC 的首字延迟作为性能验收指标之一。

状态机（建议）：

```text
created → deciding
    ├─ text_done
    ├─ decision_error / cancelled_before_dispatch
    └─ awaiting_approval（只针对在线收费）
         ├─ cancelled
         └─ approved → queued → running → image_done
                                  ├─ vision_done
                                  └─ vision_failed（图片仍然成功）
    失败：tool_rejected / unavailable / image_failed
```

必须把 `turn_id`、最终 `tool_call_id`、`request_id`、`job_id` 与已授权决策持久化。收到相同 `(session_id, turn_id)`、断网重连、刷新、第二设备重复轮询，只能返回原 Turn/Job；不产生第二笔收费或 GPU 推理。所有状态单向前进；审计日志不得输出 Key、云服务 Token、完整私人聊天或图像数据。

### 4.3 推理与 GPU 时序红线

1. 决策阶段只运行一次 LLM：模型输出普通答案或 `tool_calls`。Web 不得用“正则命中”绕过这次模型决策。
2. 必须等官方模型响应**完成并关闭读取连接、Gateway `gpu_turn` 共享锁释放**后，才把可执行任务交给 Worker；不能在 `_proxy_unguarded` 仍占用锁时请求卸载官方 LLM。
3. Worker 仍通过现有 `local_images.gpu_handoff` 申请独占；当前只能对 `/slots/0` 做**尽力快照**，验证 Slot 所属会话是否可确认；无法确认时允许放弃快照/重新 Prefill，不得恢复错误会话。
4. 用户切换会话或断网不改变任务归属；原会话仍能查询状态。图片生成出错只影响本次工具任务，不吞掉其他正常文本。
5. 使用 **tool_calls → tool 结果** 语义把工具输出回喂模型，并提供受控多模态图片输入；遵守官方 OpenAI 消息转换格式。续写时禁止新的图像工具调用/无限循环，最多一次短视觉回复；工具结果不能泄露私有磁盘路径或 Key。
6. 会话记录必须同时保存原 user turn、assistant 工具决定及其 `tool_call_id`、tool 结果和最终 assistant 文本/图片，避免下一次 Prefill 丢失结构。
7. 恢复失败或 KV 过期，退回历史上下文重新 Prefill，**不能重跑生图**；完成/失败的任务状态由 Worker 数据库决定，而不是页面上显示的 Running 标签。

### 4.4 计费、隐私和失败策略

- 本地 Qwen：用户本次消息已明确授权“能生图”且模型真实选择工具时，允许自动入队；须保留停止后续新任务开关，不暗中提交旧任务。
- 在线服务：展示实际提供商/模型及可能费用；用户二次确认前**不得创建可执行 Worker Job**。无确认则 `cancelled`；付费结果/网络错误/重连时仍不自动重试。
- 无可用模型、Worker 掉线、模型未产出有效工具或本地 GPU 被占用，应给**准确可见**状态；不得变成“我只是语言模型不能画图”的伪正常收尾，也不得无限 Running。
- 图片回喂只用现有带 Bearer 的图片访问/内部受控文件，**不在 URL、浏览器日志或工具参数中暴露密钥/绝对路径**。外部 API 图像发送要尊重用户选择。
- 模型提示词注入和会话历史均为不可信输入；服务端只执行白名单工具，不能通过模型内容触发任意 MCP、命令、文件系统操作。
- 保留原有“仅取消尚未认领队列任务”的语义；可能已发出收费请求不能承诺取消/退款。

## 五、拟修改的文件与边界

| 源码 | 下一轮要做的事 |
| --- | --- |
| `backend/gateway/chat_tool_dispatch.py`（**新建**） | Tool schema、规范化/校验 `tool_calls`、强制单次调用、工具名路由、拒绝未知参数和重复调度 |
| `backend/gateway/chat_turns.py`（**新建或并入持久 Store**） | Turn 状态机、SQLite 唯一约束、原会话归属、收费授权绑定、崩溃恢复与查询 |
| `backend/gateway/app.py` | Gateway 自有编排路由、认证与上游非流式决策调用、模型工具注入、请求监控；保留原 OpenAI 兼容转发与 GPU 锁 |
| `backend/gateway/image_jobs.py` | 尽量复用 `chat_submit`，按需增加 Turn 关联/查询；不改付费/Worker 的原有幂等不变量 |
| `backend/gateway/local_images.py`、`worker.py` | 原则上先不动 GPU 已验证主流程；如需要只补“任务来源/错误状态/活动 Slot 所属”校验 |
| `frontend/web/app.js` | 将 `send()` 的 `parser.intent(...)` 主路径替换为工具编排接口；增加模型返回工具调用的结构化状态展示、刷新恢复、会话切换保护 |
| `frontend/web/chat-capabilities.js` | 新 `chat_tool_calling` 能力协商；与旧 `chat_mcp` 及 `chat_image_tool` 区分，不能仅靠 Image Studio 有模型就声称支持 |
| `frontend/web/chat-image-router.js` | **从主路径移除**；仅作为历史数据识别/明确兼容提示，默认不再根据正则自动提交任何图像任务 |
| `frontend/web/characters.js` | 复用用户选择的图片 Profile、LoRA、尺寸、超分；考虑将选择和私有费用信息由 Gateway 受控解析，避免前端替模型执行 |
| `frontend/web/index.html`、`frontend/web/app.css` | 任务卡准确状态：“决策中/等待确认/排队/生成/完成/失败”；Running 不显示 Error；已解析参数不显示“(being written)” |
| `backend/gateway/test_chat_tool_dispatch.py`、`test_chat_turns.py`（**新建**） | 工具结构、幂等、鉴权、异步状态、错误回退、跨会话、费用确认、KV 时序 |
| `frontend/web/tests/`、`scripts/smoke-native-chat-browser.py` | 无收费的浏览器 E2E，覆盖文字、生成、编辑、取消、刷新、断网、尾部、重复消息 |
| `docs/` | 记录真实模型测试结果、日志位置、架构限制、回滚；同步本计划状态，不得虚报“已完成” |

后端应成为唯一“接受模型工具决策并可创建任务”的执行者；Web 只负责用户意图上下文、UI 和**对收费动作的真人确认**。

## 六、分阶段实施（下一对话直接按顺序执行）

### P0｜基线冻结、备份与原生工具 PoC（必须先通过）

- [ ] `git status` 干净、`main` HEAD/CI 检查、`git submodule status` 校验官方 SHA；确认 `runtime` 私有目录及实际 Port 15239/15240。
- [ ] 检查当前 `/health`、`/metrics`、请求监控、`ImageJobStore.activity`、GPU 状态以及最近用户截图“服务无法连接”的具体时间与日志；**任何正在运行的图像任务都不得重启/杀进程**。
- [ ] 备份 Native SQLite、会话/图库索引和 MeroMero JSON；不导出/记录明文 Key。保留 `mikuchin-old` 完整回滚。
- [ ] 用本地 MeroMero 以 `tools` + `tool_choice=auto` 发送**仅做决策、不执行工具**的三类请求：明确生成、普通解释、基于已有图修改；测试 `stream:false`、`stream:true` 中 `tool_calls` 与 `finish_reason` 兼容性，不调用 Worker/在线付费 API。
- [ ] 观察模型在思考开启/关闭、长上下文和中文指令下是否会返回合法 JSON；如果经常只是生成工具名字的普通文字，先修提示/工具模板兼容，不进入 P1。记录样例数量与解析成功率，不把少数成功案例冒充稳定率。
- **验收门槛**：至少明确生成和普通问答分别得到正确 Tool/Text 决策，非法/半截调用不会执行，官方源码和进程安全不变。PoC 失败则停止并报告阻碍。

### P1｜Mikuchin Gateway 工具注入与调度（关键纵向切片）

- [ ] 新增单工具 `generate_image` Schema 与 `chat_tool_dispatch` 规范校验、结构化错误。
- [ ] 新增可恢复 Turn API/Store，不使现有标准 OpenAI 代理破坏兼容；普通文字原样返回，完整工具决策变成 `awaiting_approval / queued` 等事件/状态。
- [ ] 全面区分“模型决定工具”与“用户授权执行”；初次优先配置本地模型，在线收费必须独立授权。
- [ ] 同 `ImageJobStore.chat_submit` 链接，固定 `session_id` / `request_id`；已发送的不确定任务不自动再次 POST。
- [ ] 加入短超时、用户主动中止决策、无合法工具的安全文本回退；拒绝多工具/未知工具/无效参数。
- **验收门槛**：Mock Official 响应中一个合法 `tool_call` 只导致一次模拟任务；普通话题零次生图；模拟断开重连仍只一个 Job。

### P2｜前端从关键词切换到 Model Tool Calling

- [ ] 删除 `send()` 中正则直接 `submitAutoChatImage` 的主分支；正常文字一律先走 Gateway 带 tools 的模型决策。
- [ ] 工具调用参数由 **Gateway 规范化** 后展示，模型还未完成时显示“正在思考/构造工具请求”，真正入队后才显示“排队/生成”；错误状态单独显示，不再把状态说明塞进“Error”栏。
- [ ] 任务卡可刷新/跨会话恢复，确认对旧会话的误提交竞态已消失。
- [ ] 用户可在已有全局设置中指定本地/在线图像引擎；缺失/不兼容时显示修复入口，**不暗中切换收费模型**。
- [ ] 模型没调用工具时不允许前端再“按关键词补一次自动生图”。旧 `dalle.text2im` 裸文本仅展示温和兼容错误/诊断，不可执行。
- **验收门槛**：真实 Chrome 对隔离 Mock Gateway，从用户发出“生成一张初音未来”→ 模型 tool call → 一次 ImageJob → PNG/短回复；“如何生成图片”和否定句不触发。

### P3｜编辑上一张图和多模态闭环

- [ ] 注入 `edit_image`，只允许修改本会话最近成功的图片，必须调用已有安全的 `edit_previous` 参考素材逻辑。
- [ ] 使用现有 GPU/KV handoff，校验**决策推理已结束、共享锁释放后** Worker 才开始独占；快照失败仍可 Prefill，但绝不额外生图。
- [ ] 图像完成后正确构造 `assistant.tool_calls + tool(tool_call_id)`，回喂用户上下文及刚生成的图片，调用一次 `tool_choice:none` 的短视觉回复；关闭推理思考，最大 256 总 Token。
- [ ] 补后台“视觉尾部待完成”持久状态，浏览器关闭时用户仍能看见成功图片且不会自动重新计费；尾部失败可见且不能递归工具。
- **验收门槛**：本地 Qwen-Image 真实成功一次；同会话基于“把上一张图背景改为夜景”生成关联编辑图；可检查源图关联、状态单调、图片确实传入视觉处理，而非仅文本路径。

### P4｜回归、部署与 GitHub（不能跳过）

- [ ] Python：`runtime/.venv/Scripts/python.exe -m unittest discover -s backend/gateway -q`。
- [ ] Node：`node --test frontend/web/tests/*.mjs`；JS 语法检查。
- [ ] Mock Chrome：分别测试 ①普通话题②直白生图③隐含意图④编辑⑤否定⑥在线收费取消⑦双击/重连幂等⑧刷新⑨长任务/Worker断开⑩尾部失败⑪不同会话并发。
- [ ] 真实本地 MeroMero + 本地 Qwen 测试必须检查 GPU/负载/活动请求，并在适当时间执行；**不得为测试主动触发在线收费 API**。至少一次真实工具决策、图片成功、KV 尝试恢复和视觉尾部验证。
- [ ] 网关未授权返回 401，跨 Origin 403；任意模型参数不能访问本地文件/外部 Key；保留 Cloudflare Tunnel 的既有鉴权。
- [ ] 对照 GUI 任务卡逐项验收：不允许“Running 同时 Error”、卡片永远写参数、图片完成未显示、刷新重复入队。测试 Mobile/Android 是否同样用 Gateway 状态协议（不要求本阶段打 APK）。
- [ ] 所有测试合格才短暂停机部署/必要重启；先确认 Worker 无运行任务，备份状态再执行，最后看 15239/15240/CF Tunnel 和 11+ 会话/画廊记录是否完整。
- [ ] `git diff --check`、`git submodule status`、固定官方 SHA 验证；提交到 `main`，推送 GitHub，检查 Actions。**不要在没有用户新授权时改 v0.4.0 Tag、建立 Release 或构建新版 APK/Launcher。**

## 七、独立验收案例（每个都要给出可核实证据）

| 输入/场景 | 预期 |
| --- | --- |
| `生成一张初音未来` | **MeroMero 发 `generate_image`**，Gateway 一次任务、图片和短回复 |
| `明天她过生日，做张贺图，要和之前的角色服装一致` | 使用上下文/角色信息选图像工具并形成合理 prompt |
| `解释一下 Qwen-Image 的工作原理` | 普通文字，图像任务数不变 |
| `不要生成图片，给我一些构图建议` | 文字回复，不生成 |
| `如果我想生成一张初音未来，需要什么参数？` | 文字解释，不自动生图 |
| `把刚才那张图的眼睛调大，其他不要变` | `edit_image`、引用同会话的成功图片；无参考图时明确失败而非收费重画 |
| `生成一张成绩表/Excel 表格` | 不调用图像工具；文本/数据处理能力独立决定 |
| 用户选择在线付费模型、模型调用生图 | 服务端等待一次性人工确认；取消后任务表不增加 |
| 同一 `turn_id` 重连、刷新、重复 POST | 仍是唯一 Job，图片数量/收费次数不增加 |
| 模型返回未知工具/错误 JSON/半截 SSE | 不执行；显示明确错误或正常文本，日志可诊断 |
| 首轮生图成功，KV restore 失败 | 图片保留成功，继续对话可重新 Prefill，绝不重生图 |
| 任务执行中关闭浏览器/切换会话 | 继续关联原会话，恢复后查询进度；不把图片插进其他会话 |
| Worker 失联/端口不可达/未登录 Key | UI 准确显示原因、状态不会永远 Running |

**报告必须分开说明**：Mock Python/Browser、真实 LLM tool-calling、真实本地 GPU 生图、真实图像回喂、收费模拟/用户确认；不能以其中一项替代全部验收。

## 八、回滚和事故处理

1. P0 先用时间戳记录 `git rev-parse HEAD`、模型 JSON、Gateway/Worker/Launcher 进程与端口、当前 SQLite 数据库备份；不要把任何 Key 写进报告。
2. 以**独立可关闭的 Feature Flag**（建议 `native_tool_calling_enabled`）上线；未验证完成时默认关闭，现有 Chat/手动 Image Studio 继续可用。用户体验通过后可切成默认启用。
3. 任何环节若出现收费重复、跨会话图片泄露、死锁、KV 恢复错位或 Worker 卡死：先禁用新编排入口，停止接受**新**任务；**不得强杀已认领或可能收费的任务**。
4. 禁用新功能后普通文字聊天继续用现有兼容转发；已提交的 Job 只读追踪/原样保留；必要时将新路由提交单独 revert，并使用事务备份恢复持久 Turn 状态。
5. 如需退回模型配置，按 `docs/NATIVE_AUTO_CHAT_IMAGE_2026-11-21.md` 的安全停机步骤操作；`E:\LLM\mikuchin-old` 是旧版 Git 元数据主工作树，禁止随意删除；`runtime` 与所有 Key 不进入 Git。
6. 官方 PolyStrata 接口若无法稳定提供工具调用，选择“停止自动 Tool Calling、保留显式用户操作的生图入口”，**不要悄悄恢复关键词自动收费路径**，也不私改子模块。

## 九、下一对话开工指令（可直接复制）

> 使用 `$desktop` 连接我的台式机。请读取 `E:\LLM\mikuchin\docs\PLAN_NATIVE_TOOL_CALLING_IMAGE_2026-11-21.md`，从 **P0 原生 Tool Calling PoC** 开始按阶段直接实施。仓库是 `E:\LLM\mikuchin`，当前官方 PolyStrata 子模块必须固定 `3e1642161198c50ff1abed4046f4e4f476099dbb`，**不要更改其源码或指针**。先核验 `main` 当前 HEAD/工作区、15239/15240、Worker/GPU 活动和备份；严格禁止在线付费测试。真正使用 MeroMero `tools/tool_choice` 决策，Gateway 负责工具执行，停止前端关键词直接生图；先完成 `generate_image`，验证后再做 `edit_image` 和图片视觉短尾部。复用现有 SQLite 幂等与单活动 Slot KV handoff；必须等官方推理响应结束、共享 GPU 锁释放后再卸载 LLM。各阶段记录测试证据和失败，不因成功 Mock 就宣称真实 GPU/模型全部通过。完成后检查 GitHub CI；没有进一步指令不得覆盖 Tag/Release。

---

**维护规则**：计划与实际状态分离。执行时勾选阶段条目并附日志/提交，不要把“建议的接口/文件/行为”描述成已存在或已通过。此计划首次撰写仅创建文档，不修改业务源码、配置、模型或运行中的服务。
