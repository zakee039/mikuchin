# Native Image Worker — API 并发调度修复（2026-11-21）

## 用户现象与根因

用户在「设置 → API 生图服务」填写 `并发数=5`，但连续提交的任务实际上严格一个接一个运行。

检查发现：`backend/gateway/image_providers.py` 的配置验证、持久化、UI 读取一直支持 `concurrency=1..20`，但 `backend/gateway/worker.py` 旧 `run_forever()` 直接同步调用 `run_once()`，一次只调用一家提供商一个任务，因此并发字段**没有参与调度**。没有证据表明供应商拒绝并发；瓶颈位于 Mikuchin 自己的独立 Worker。

## 实施

只修改 Mikuchin 的 `backend/gateway/worker.py`、`image_jobs.py`（官方 PolyStrata 子模块不动）：

- API 任务使用独立有界线程池，全局最多 **20** 条 API 调用；每个 API 服务按已持久化的 `concurrency` 独立限流，不跨服务共用“只能一个”锁。运行中上调/下调配置只影响**后续领取**，已经发起的请求不强杀。
- 本地 Qwen、SDXL 和单独 4× 超分进入另一条**容量 1** 的本地 GPU 通道。API 请求与本地 GPU 调度互不抢线程池；GPU 侧原有显存锁、LLM 卸载→恢复/KV 路径不改变。正在运行中的本地图像任务不会同时启动第二个本地 GPU 任务。
- `take_pending(eligible=...)` 逐个检查等候队列中最早的**可调度**任务。若某个 API 服务已达并发上限，则可越过它领取另一服务或 GPU 通道的任务，而不是全局队头阻塞。领取到任务时原子将 phase 从「排队等待执行」变为「准备请求提供商」，避免重复领取。
- 排队时间**不计入** `started_at/elapsed_s`，只有真正进入 API 请求时才开始计时，延续原有进度卡片语义。
- 不改动扣费任务的幂等键、提交次数、任务确认、提供商错误回传、失败不自动重试和 Worker 单实例 OS 锁。服务恢复不会补发来源不确定的在途收费请求。
- Worker 收到正常停止信号后不领取新任务，等待已启动的线程结束再退出，保持心跳到执行全部结束；异常进程退出仍按旧机制标记不确定任务失败，不自动重放。

## 自动化验证

- 新增 `test_worker_concurrency.py`：同一配置为 5 的 API 服务 6 项任务中 **5 项同时开始、第 6 项保持排队**；配置为 2 的 API 服务与配置为 1 的另一个服务可同时运行、分别严格遵守限额且不存在队头阻塞；本地 GPU 和超分互斥且不占 API 名额；Worker 正常停止后不能启动尚在队列的收费任务。
- 保留现有 `test_worker_process.py` 的**真实独立 Worker 子进程、假 localhost HTTP API、单实例锁、无双重收费**验证；其余 Native Gateway 回归、前端测试照旧。
- 不调用任何真实收费图片 API；并发效果通过隔离测试可证，不借用用户凭据或生产提供商。

实际结果：Worker 并发测试 **4/4**、Gateway 全量 **154/154**、Web 全量 **94/94**、版本一致性校验 **13/13** 通过。

## 生产发布规则

- 版本仍为 **Mikuchin v0.5.0**，不更新 Launch/Android 的二进制。只需更新独立 Image Worker 进程；Gateway 不需要重启（提交 API 配置和队列结构不变），官方 PolyStrata 不重启。
- 在生产 Image Jobs 和 Native Turn 均无活动请求时，用 SQLite Online Backup 备份五类数据库及配置，再安全重启 Image Worker，校验心跳、服务状态、历史任务、正在执行的 Task 未丢失后完成部署。
- **若还有真实执行中的付费 API 请求：不能强制杀死 Worker**，否则提供商可能已经扣费但本地任务被标记失败。先完成代码与测试，等天然空闲窗口再部署，并向用户如实说明是否已上线。

## 上线结果

- 数据备份：`runtime/migration-backups/image-api-concurrency-20261121-204010`，包含 Native Turn、会话、角色、画廊、图片任务五份 SQLite Online Backup 及三份当前配置备份（其中可能含用户自己的私密密钥，**此目录不得上传到 GitHub**）。
- 上线前两次核验生产处于 **0 个进行中图像任务、0 个进行中 Native Turn**，没有取消、重播或重试任何已发起的付费请求。
- 只重载独立 Image Worker 的实际 Python 进程 **15352 → 34064**，Native Supervisor 自动恢复受控 Worker 子进程 **24292 → 11176**，Worker 自动重启计数 **1**；官方 PolyStrata 的 Supervisor 子进程 **40496**、Gateway 子进程 **46348** 保持不变，LLM 服务没有重新加载。
- 重载后 Worker 心跳刷新正常；任务历史保留，服务配置仍为 **5 并发**。代码对现有和新建的 API 服务一视同仁按各自并发设置执行；用户不需要重新保存 API 配置。
- 本次**没有直接向用户真实的收费 API 一次提交五张图**，以免擅自产生费用。新调度线程的真实并行能力由独立 Mock 供应商测试验证；如果上游有自身的 RPM 或并发限制，最多只会执行到服务商允许的数量，仍不会自动重试失败的扣费任务。
