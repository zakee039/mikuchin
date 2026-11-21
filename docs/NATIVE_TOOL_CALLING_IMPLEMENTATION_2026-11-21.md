# Mikuchin Native Tool Calling 实施与验证记录

> 日期：2026-11-21｜执行仓库：`E:\LLM\mikuchin`，`main`。
>
> 本文只记录已经执行的动作与证据；模拟和真实测试严格区分。计划来源：`PLAN_NATIVE_TOOL_CALLING_IMAGE_2026-11-21.md`。

## 基线与不变量

- 开工 HEAD：`a5c69b2`，工作区干净；计划初稿中 `77bf25b` 是更早的审计 HEAD，不应用它覆盖当前 `main`。
- 官方子模块 `backend/polystrata` 仍固定 `3e1642161198c50ff1abed4046f4e4f476099dbb`（v0.1.45-poly.10）；**从未修改其源码、版本、依赖或 Git 指针**。
- 正式端口 `15239/15240` 在开工及代码阶段均正常监听；起始图库任务 6 条历史成功、0 条运行中，Worker 心跳正常。
- 备份：`runtime/migration-backups/tool-calling-P0-20261121-154032`，含 SQLite 在线备份、模型/图像配置与基线 manifest；未导出明文生产密钥。
- 不执行收费 API；GPU 测试采用本地模型、独立数据目录与临时随机 Key。
- **已部署并默认启用** Native Gateway Tool Calling；设置 `MIKUCHIN_NATIVE_TOOL_CALLING=0` 并重启 Gateway 可回退到普通文字转发。P4 仅重启 Gateway，官方 LLM、Image Worker 的 PID 不变；未更改 v0.4.0 Tag、Release、Launcher 或 APK。

## P0：真实 MeroMero Tool Calling

`runtime/p0-tool-probe.py` 使用临时 `15340` 官方引擎实例，`tools/tool_choice=auto`，只判断、不触发图片任务：

| 实验 | 真实输出 |
| --- | --- |
| 明确插画请求（两组） | `finish_reason=tool_calls`；`generate_image`；合法 JSON |
| Qwen-Image 原理解释 | 无 `tool_calls`；普通文字 |
| 否定“不要生成图片” | 无 `tool_calls`；普通文字 |
| 带前图上下文“眼睛调大” | `edit_image`；合法 JSON |
| 隐含生日贺图 | `generate_image`；合法 JSON |
| 真实 SSE 分片 | 4 个事件，重组后 `generate_image` 合法 JSON，终止 `tool_calls` |
| 低思考解释 | 无工具，但 `finish_reason=length`，证明不能把低思考输出都宣称完整 |

另用真实 MeroMero 测试低思考（1024 思考 Token）：生图 `generate_image` 与同图修改 `edit_image` 均以 `finish_reason=tool_calls`、合法 JSON 完成；结果在 `results-low.json`。其余结果保存在 `runtime/tool-calling-p0-isolated/results.json` 与 `results-extended.json`。样本小，不代表长上下文稳定率。

另在真实 MeroMero 的 `tool_choice=none` 视觉续写中，用合成 JPEG 经 `assistant.tool_calls → tool(tool_call_id) → image_url` 回喂；HTTP 200，`finish_reason=stop`，没有新工具调用，准确识别为“青绿色的圆形图标”。证据：`runtime/tool-calling-p0-isolated/results-vision.json`。**这张 JPEG 是测试图，不是实际 Qwen 图像**。

## P1：受控 Gateway 调度

新增自有模块：

- `backend/gateway/chat_tool_dispatch.py`：两种只接收 prompt/instruction 的工具 Schema、JSON 严格校验、在线服务风险判断和用户已保存 Profile/分辨率/LoRA 等配置的服务端解析。
- `backend/gateway/chat_turns.py`：SQLite Turn 状态机、会话作用域、确定性的请求 ID、幂等重连、不确定写入后只读恢复、一次性收费批准摘要、取消及失败状态。
- `backend/gateway/chat_turn_service.py`：官方模型决策完成且释放 GPU 共享锁后才提交 Worker，后台轮询结果，并在图片生成后追加至多一次真实视觉短尾（`tool_choice=none`、`max_tokens=256`）。
- `backend/gateway/app.py`：认证的 POST/GET Turn API 与 approve/cancel，测试阶段默认关闭，P4 验收后已默认启用；显式环境变量 `MIKUCHIN_NATIVE_TOOL_CALLING=0` 仍可关闭新 Turn 写入；保留标准 OpenAI 兼容代理。
- `backend/gateway/image_jobs.py`：增加精确只读 `chat_lookup`；沿用原 `chat_submit` SQLite 唯一 ledger，不复制收费队列。

安全原则：不可信模型不能选任意路径、API Key、程序命令或文件；模型只建议自然语言生成/编辑指令。编辑只按会话查找上一张服务端成功图片；收费在线服务需要每 Turn 单独确认，拒绝后不创建 Job；没有自动网络重试。

## P2：Web 主路径迁移

- `frontend/web/app.js`：取消前端关键词/正则决定生图；启用功能时先经过模型 `tool_calls`，保存稳定 Turn ID，结果只读 GET 轮询；未收到合法工具就普通文本，不再靠 `dalle.text2im` 文本补调用。
- `frontend/web/native-tool-client.js`：展示决策中、等待确认、执行中、成功/失败、图片和尾部，并隔离旧任务轮询；旧命令文本只作诊断，不执行。
- `frontend/web/index.html`：加载新客户端脚本，移除主页面旧关键词路由脚本。
- 任务卡的执行中参数已解析后显示参数，结果字段显示 Status 而非错误；原会话持久消息和跨刷新展示由现有服务端 ConversationStore 维持。

## P3：模拟完整闭环与真实多模态

独立 `scripts/smoke-native-chat-browser.py --tools` 的 Chrome 全流程，在临时端口、临时 SQLite、无收费/无 GPU 的 Mock Worker 测试：

- 从浏览器输入实际走模型 `tool_calls` → Turn → ImageJob → PNG 图像卡 → 视觉回复；
- 生成、同会话“眼睛调大”编辑、再次生日生图三次任务的**真实参考素材数量为 `0,1,0`**，证明编辑任务携带上一张原图，而非重新生图；
- 模型判定依次 `generate_image, edit_image, text, generate_image`，否定请求纯文字；
- 三次视觉尾部接收到 JPEG+tool 结果，刷新后原会话图片仍显示；
- Chrome Page Errors 为空，关闭浏览器与测试夹具后没有遗留监听。

上述**只是模拟图片模型**，不把它替代真实验证。随后已完成独立本地 Qwen-Image Official 测试：`runtime/real-qwen-tool-e2e.py`，临时官方 `15340`、临时 Gateway `15339`、全新 SQLite、只读引用原有模型文件，未触发在线图像 API。真实结果：

- `tool_generate=true`，`tool_edit=true`：真实 MeroMero 分别输出 `generate_image` 与 `edit_image`；
- `real_local_pngs=2`，两张 384×384 PNG 均成功落盘（约 107,760 / 105,671 字节）；
- `reference_count=1`，第二张引用同会话第一张的源图，结果 `edited_previous=true`；
- `vision_done=2`，MeroMero 分别得到真实 Qwen 生成的视觉图像后完成两次 `tool_choice=none` 续写；
- 配置启用 `--offload-to-cpu`，日志显示权重主要在 RAM；这里验收的是实际本地模型输出、GPU 互斥与 LLM 卸载/重载，而**不是纯 GPU 加速效率**；
- 官方隔离引擎的 KV 快照文件实际生成，单份约 338,979,120 字节，恢复尝试后清理；`kv-handoffs` 无遗留；
- `elapsed_seconds=428.6`，临时进程退出码 `0`，生产端口 `15239/15240` 仍监听，生产图像任务 6 条成功、没有新增任务。

真实测试依据 `runtime/tool-calling-real-e2e/summary.json`、`native-chat-turns.sqlite3`（2 行 `vision_done`）、`images/native-image-jobs.sqlite3` 与生成的 PNG。全部结果严格留在隔离目录。

## 自动化回归

- Python：`runtime/.venv/Scripts/python.exe -m unittest discover -s backend/gateway -q` → **111/111 通过**（含停止决策不派单、同会话检索、付费授权、鉴权、Worker 失联与重复请求）。
- Node：`node --test frontend/web/tests/*.test.mjs` → **57/57 通过**；含 Running 显示 Status、旧命令文本绝不执行、跨会话不替换状态。
- `node --check frontend/web/app.js`、`node --check frontend/web/native-tool-client.js` 与 `git diff --check` 均通过。
- 验证证据不含生产 API Key，测试时没有向在线图像服务发送任何请求。

## P4：生产 Gateway 部署与状态核验

- 在真实 E2E 成功后，P4 二次备份到 `runtime/migration-backups/tool-calling-P4-20261121-162703`（4 个 SQLite 数据库及本地配置）。
- 再次核验生产图库只有 6 条历史成功任务、0 条在途任务；Gateway 15239 没有已建立的客户端连接；Worker 心跳正常。
- 只重新加载 Gateway 单进程；Supervisor 自动恢复成功，服务 PID `37032 → 12656`，`phase=running`，`child_restarts.gateway=1`。**官方 PolyStrata 引擎 PID `41712` 与独立 Worker 不变**。
- 新前端 `GET /web/native-tool-client.js`、`/web/app.js` 都得到 200；无 Bearer 的 `/health`、Turn GET 和 Turn POST 均为 **401**；`15239/15240` 仍监听；原有图像库 6 条成功，生产 Turn DB 为空（无测试污染）。
- 390px Chrome 付费 UI 验证中，在线 Profile 进入 `awaiting_approval`，点击应用内“取消”后 `cancelled`，图像 Job **0 条**；可见按钮、页面无脚本错误。
- 真实本地 Qwen GPU/KV 闭环证据见 P3 章节；测试结束后独立进程退出码 0。

**仍未覆盖的验收范围**：正式生产账号 Bearer（遵循 DPAPI/隐私约束未尝试读取）下的完整手工聊天；CF Tunnel 的远端认证请求、Android APK 端到端；P4 的所有 11 个 Chrome 长任务/跨会话/异常分支未全部通过浏览器逐一操作（其中部分由 Python/Node 合约测试替代）。这些是上线后的剩余验收风险，不能宣称已做过。

**已知体验取舍**：本阶段模型决策使用非流式 `tools` 响应，普通文本聊天会等待这次模型完整回复才显示正文；旧 OpenAI 兼容转发接口仍支持流式，但自动 Tool Calling 主路径的逐 Token 流式展示尚未实现。需要后续 SSE Tool Calling 升级，不能把当前版本称作全功能流式等价替换。

## 回退

1. 将 `MIKUCHIN_NATIVE_TOOL_CALLING=0` 置于 Gateway 进程环境并安全重启 Gateway，停止新的模型工具 Turn POST；旧标准 OpenAI 兼容代理仍可用。**仅删除环境变量不会关闭默认启用的功能。**
2. 任何已认领的真实 Worker 或可能收费请求绝不因禁用新功能而被强杀/重试；已完成图片从原任务数据库只读获取。
3. 回退源代码可用执行前的 Git HEAD；所有用户原有会话、画廊、Key 留在生产 `runtime/launcher-user-data`，不能用一次测试目录覆盖它。
