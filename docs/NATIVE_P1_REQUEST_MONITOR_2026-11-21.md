# Native P0/P1 增量：请求级运行监控（2026-11-21）

开发分支 `refactor/official-polystrata-gateway`；正式 `main` 与 `15239` 不受影响。

## P0 正文 Token 预算：官方语义差异仍存在

审查未修改的官方 PolyStrata `serve/server.py` 解码路径：
- 上游 `max_tokens/max_completion_tokens` 是整次生成的上限，包含思考和最终回答；思考 `reasoning_budget_tokens` 是独立的思考限额。官方的回答预留机制（`ANSWER_ROOM_MIN_CAP`/`ANSWER_RESERVE_MIN`）是在总限额内截短思考，并不是最终可见正文 token 的独立计数上限。
- `/v1/chat/completions` 向 Gateway 公开 JSON/SSE 文本与合计 usage，没有一个稳定、逐 token 的“正文已生成 token ID/计数与正文停止控制”接口。Gateway 自行以 UTF-8 字节、字符或 BPE 估算截断将偏离原版精准语义，还可能在 JSON/工具调用结构中截断 SSE。
- 因此仍保留 `/health.answer_budget_tokens=false` 与 `answer_budget_tokens` 显式 501；不伪装已经完成 P0。真正实现需要官方可维护的解码事件/正文独立限额扩展或者其上游接口升级，不直接修改 `backend/polystrata` 子模块。

## P1 新增：可审计的请求级监控

Native Gateway 新增只读、私有 `GET /v1/mikuchin/request-monitor`：
- 严格 Bearer + Origin 鉴权（复用 Gateway 既有安全门），未授权 401、跨源 403。
- 服务进程内存计数：`total, failed, active, by_kind`（只含固定类别 chat/messages/responses/images）；最新 30 条成功/错误记录，每条仅有固定类别、HTTP 状态、结果码、持续毫秒数、发送给客户端的响应字节数、完成时间（秒）。
- 不存储/输出提示词、消息内容、会话标识、客户端 IP、用户名、设备名、请求原文、Token、密钥、URI 或请求体。只计算已通过协议校验、真正进入代理链路的 **POST 推理请求**；静态资源、保密资源读取与被拒绝的请求不计。Gateway 退出后清零，不落盘，不会成为包含原文的历史日志。
- HTTP 200 的流式 SSE 计时从进入 Gateway 推理链路开始，到最后一块数据到达并转发完成结束；如果发送中断标记 `client_disconnect`，上游错误标记 `upstream_error`，GPU 独占拒绝记为 `gpu_busy`，其余仅使用固定值。
- **不假装具有每请求准确 token/prefill/decode 指标**，该字段明确标记 `not_available_per_request`；官方 `/metrics` 的累计 token / 硬件信息仍可用。
- Tauri `get_status` 仅使用 Native 私有密钥读取新监控端点；「原生状态」增加请求汇总及最近五条耗时。所有端点类别经过前端 HTML 转义处理，不增加可触发写操作的页面控件。

### GPU 预算现状

- 现有本机 `nvidia-smi` 的显存已用/总量，以及 Native `native_gpu` 的 GPU 文件锁与 `phase` 属真实状态；Image Worker 仍在独占 GPU 时卸载官方文本 LLM，完毕后安全恢复。
- **尚无等价原版动态 GPU 预算配置 API**。启动器只显示真实只读状态，不呈现虚假的「可调 GPU预算」开关。后续需明确内存配额、WDDM 预算测量、驱逐/抢占与不可用显存阈值策略后再设计控制接口。

## 测试

- FakeOfficial：端点 401/403/200；普通非流式与 SSE 完整计时；统计累计；响应用 Mock 回显私有提示词但监控 JSON 不含该私有内容。
- 并发纯单元测试：100 个请求与失败计数，最大 30 条记录、inflight 不泄漏；固定字段限制。
- Rust/TS：Tauri 通过独立 API Key 读取 Monitor，启动器类型检查与契约测试。
- 真实 Native 冒烟须先确认无收费图片任务、模型不在生成和 GPU 独占锁空闲，才安全重启。GitHub CI、正式发布和额外硬件性能数据以实测记录为准。

### 真实本机验证记录

- Native 图像队列空、GPU 独占锁空闲、官方模型状态 `idle` 后，仅重建独立开发 Tauri Debug 启动器与 15249/15240/Worker 三进程。正式端口 15239 未监听，正式 main 没有被启动。
- 实机 `GET /health` 为 `status=ok`；鉴权的 `GET /v1/mikuchin/request-monitor` 最初显示 `total=0,active=0,persistence=memory_only`，无 Key 为 HTTP 401。
- 真实官方 Native 本地 LLM，`reasoning_effort=none`、`max_tokens=24` 非流式短提示：返回结构化 choices，调用约 1 秒；随后监控由 `total=0` 变为 `total=1`，最近一项为 `chat/HTTP 200/duration_ms=1016`、`active=0`。未触发收费图像 API。
- CI 与源码回归详见独立提交状态；该单次样例不是请求性能基准测试。

**不能将上述 P1 请求监控当作 P0 完成，亦不能将只读显存状态当作可调 GPU 预算。**
