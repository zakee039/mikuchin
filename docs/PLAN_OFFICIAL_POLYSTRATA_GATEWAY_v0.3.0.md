# Mikuchin 下一代架构迁移方案：官方 PolyStrata + 独立 Gateway

> 文档基线：2026-11-19，Mikuchin **v0.3.0**；官方对照版本 `v0.1.45-poly.10`（`3e1642161198c50ff1abed4046f4e4f476099dbb`）。
>
> **本次只确立基线和规划，不实施后端架构迁移**。不删除、覆盖现有用户目录和历史缓存，不重建模型权重。

## 1. 目标、边界、技术决策

**目标：** 未来逐次升级 PolyStrata 官方 Tag，不再每次手工合并我们的 `serve/server.py` / `src/poly/main.cpp` / 推理内核改动。

**明确决定：**

1. 官方 PolyStrata 源代码、引擎二进制及推理服务作为**独立的不可修改上游组件**；只依赖公开 HTTP API 和其声明的会话保存协议。不得继续在官方源码里插入 Mikuchin 业务分支。
2. Mikuchin 维护自己的 Gateway、会话/身份/角色/世界书/工作流/图像任务/画廊/设置和资源仲裁；所有远程用户继续访问单一的 Mikuchin 外部入口。
3. 已有聊天记录与旧的 `POLYKV1!` 快照**不必迁移或格式兼容**，新架构启用新的会话库与快照目录；但**此次 v0.3.0 基线不会删除它们**。角色、世界书、工作流、API Key、模型与画廊等其他数据需按业务实际需要保持或迁移。
4. **软件分发要支持其他电脑**：Windows、Linux、macOS 与不同 GPU 后端分别构建/安装官方引擎。绝不把 RTX 3070 Ti 专用二进制当成所有设备可用的构建。
5. 每个里程碑均要求可回退到此 v0.3.0 基线。任何服务切换必须先完成数据备份、运行时端口检查与回归测试。

## 2. 已确认的差异事实（不能当作已完成改造）

- 本地 `backend/polystrata` 与官方 Tag 主要可比源码：同名且完全相同 **690** 文件，同名不同内容 **74** 文件，仅本地 **36** 文件，仅官方 **15** 文件。统计排除第三方依赖与部分样例、基准和数据目录；仅用于定位改造范围，不代表 74 个逻辑冲突。
- `serve/server.py` AST 对比：本地 249 个函数/方法，官方 247 个；共有 241 个，其中 29 个源码实现不一致。`make_handler` 本地约 1705 行、官方约 1165 行，是最大的业务耦合中心。
- Mikuchin 在 `serve/` 中独有 `session_v1.py`、`character_cards.py`、`workflow_profile.py`、`lore_retriever.py`、`image_jobs.py`、`image_api_services.py`、`image_tools.py`、`image_task_status.py`、`gallery.py`、`upscale.py`、`cache_drop.py` 等约 **4,169 行**业务代码。不能仅复制模块就断开对 `Service`、引擎对象及内存状态的依赖。
- 官方现有 `SAVE/RESTORE` 与 `PIN`/Warm Start；但当前会话保存恢复在并行 Batch 配置下有限制，必须单独验证。官方 `PIN` 是**一个引擎级共享前缀**，并非 Mikuchin 多角色无限个同时驻留的 KV 快照。
- 本地 KV 文件使用 `POLYKV1!`，官方使用 `POLYSES1`；可丢弃旧格式，但新版需要对模型/版本/量化/上下文变更的失效与重新 Prefill 作出明确规定。
- 当前桌面启动器以固定 `backend/polystrata/.venv/Scripts/python.exe` 和 `serve/server.py` 进程启动 `15239` 服务，校验内置目录。迁移后需改由启动器同时管理 Gateway 和官方引擎服务，并更新诊断、日志与启停规则。

## 3. 目标组件及端口

```
Windows / Android / Browser / iOS (remote)
                  |
                  v
     Mikuchin Gateway (external :15239)
        - API authentication / Host-Origin policy
        - Chat SSE proxy / cancellation / tool orchestrator
        - Character / Persona / Worldbook / Workflow
        - Session store / sampling / KV snapshot index
        - Image Jobs / API provider / Gallery / 4x
        - Model and GPU resource arbiter
                  |
          +-------+-------+
          |               |
          v               v
 Official PolyStrata     Image Worker
 127.0.0.1:15240        local private worker
 models / inference      Qwen-Image / LoRA
 SAVE RESTORE PIN        online image API
 warm_start             upscaling / catalog
```

- 15240 是**拟议的默认内部端口**，后续应允许配置，不应与已有安装冲突。
- **安全边界**：官方服务必须仅监听 loopback；Gateway 独占外网/CF Tunnel/Tailscale 入口、API Key、Origin/Host/CSRF 检查。不要将内部 PolyStrata API 直接暴露到校园网。
- Gateway 为上游提供请求级取消、超时、进程健康和流式 SSE 透传；上游 HTTP API 不支持的内部状态不得依赖私有 Python 对象。
- 两个本地服务不需要额外 PyTorch Runtime 来执行原生 KV 保存；PyTorch、CUDA Toolkit 与构建依赖分别按**运行**和**编译**需求区分。

## 4. 必须重新实现的契约

| 子系统 | 当前嵌入点 | 新架构中的责任 | 接口/风险 |
|---|---|---|---|
| OpenAI 聊天 | 修改的 `server.py` `_openai` 等 | Gateway 组装请求、角色、世界书、处理流式回复 | 保持 `reasoning_budget_tokens`、正文预算、工具消息与 SSE 的可观察语义 |
| KV 快照 | `SessionV1` + 原生 C++ `session_disk.hpp` | Gateway 追踪对话/模型指纹与锁定/淘汰，官方 SAVE/RESTORE 做实际序列化 | 旧格式不迁移；过期或恢复失败完整 Prefill；先实现单槽再评估并行 |
| 系统提示词 | 本地预热 `warm_start` | 官方 `warm_start` + `PIN` | 角色前缀变化、角色隔离、是否能共享前缀须验证；不能默认多个角色同时 PIN |
| 会话与采样 | `session_v1.py` 与扩展 HTTP | Gateway 新 SQLite 会话库 | 用户数据权限、内容修订、会话模型路由、独立采样参数 |
| 角色 / 世界书 / 工作流 | `character_cards.py` 等及 `/v1/strata/characters` | Gateway 的私有 API | 保留角色参考图、无状态语义、世界书召回与工作流提交 |
| 本地图像 | `images.py` 定制/图像 profile / LoRA | 独立 Image Worker + Gateway 调度 | Qwen-Image official/uncensored、图生图、LoRA、显存卸载/恢复 |
| 在线图像 | `image_api_services.py` 与任务中心 | 独立 Image Worker | 直连/代理、连接/读取超时、实际耗时、费用风险、不自动重放 |
| 聊天生图 | `image_tools.py`/修改的 chat handler | Gateway 工具编排 + Image Worker | 断线后任务持续、图片归档、会话恢复、生成后 256 Token 视觉回复 |
| 画廊 | `gallery.py` | Gateway | 4x 一组计数、NSFW、缩略图、删除权限、手机手势查看 |
| 显卡监控 | WDDM 扩展 `gpu-budget` | Gateway 可选监控插件 | 不把 Windows DXGI 特性写进官方跨平台 core |
| 模型生命周期 | 手动卸载保持、15 分钟 idle 等 | Launcher + Gateway 状态机 | 有用户主动停止/忙碌任务时不自动重启；避免 KV/生成任务竞争 |
| 桌面启动 | Tauri 目前单进程 | 双进程 supervision | 原生文件路径、安全密钥、开机启动、退出恢复、可回滚 |

## 5. 官方接口的具体限制

1. 官方 `/v1/chat/completions` 能处理流式输出、思考预算和 `strata_mcp`，但不理解我们的 `strata_session_id`、`mikuchin_stateless`、`strata_image_tool` 和独立 `answer_budget_tokens` 语义；不能盲目透传。
2. 官方 `/slots/0?action=save|restore` 需要配置 `slot_save_path`，且对并行配置可能返回不可用；使用官方 `PIN` 前要测量它与正在运行的会话/工具调用的关系。
3. Gateway 要维持真正的取消语义：断开聊天 SSE 应取消普通生成，**但已独立提交的付费生图任务不能随浏览器断开而重复投递或隐式取消**。
4. 恢复 KV 前校验**模型内容、量化、上下文与引擎版本**；新架构不读取旧 `POLYKV1!` 文件，升级官方版本后若旧快照不适用则重新 Prefill。
5. 独立 Image Worker 与官方 LLM 必须共享唯一的 GPU 资源仲裁器：单张 8 GB 显卡上加载大图像模型之前先协调卸载/保存，不得两个进程互相抢显存。
6. 外部 API 不应透露内部进程/磁盘路径；密钥继续使用本机安全存储，不写入仓库或发布包。

## 6. 按阶段实施（每阶段可回退）

### P0 — 冻结基线与契约测试

- v0.3.0 保留现有全部功能，完成全量版本同步、Windows Launcher/NSIS 和 Android 正式签名包重新构建。
- 生成当前 `/health`、`/models`、聊天 SSE、工具、生图、画廊、模型卸载/恢复等接口的无收费契约测试；保留当前分支、Tag 及可重装的安装文件。
- 确定哪些配置可直接迁移、哪些在重构中按新结构重新录入。**旧对话与 KV 无需兼容，但迁移测试不能主动清空现有用户目录。**

### P1 — 官方核心独立验证

- 固定官方 Tag，单独的 `upstream/PolyStrata` 或包缓存和私有 `127.0.0.1:15240`；避免与旧引擎复用运行目录。
- 在 Windows + RTX 3070 Ti 用真实模型验证常规聊天/视觉、长上下文、SAVE/RESTORE/PIN、拒绝损坏/错配快照、加载/卸载。随后面向其他 OS/GPU 建构建矩阵。
- 记录实际 Prefill、保存、恢复时间、内存/显存占用，**不要把上游基准直接算作 Mikuchin 实测**。

### P2 — Gateway 最小闭环

- 将会话、角色、Persona、世界书、独立采样参数和鉴权迁入 `backend/mikuchin-gateway/`（目录名称可定稿时再决定）。
- 保持桌面 Web/Android 外部 `15239` 不变；SSE、思考/正文预算、取消、历史保存必须经契约测试。
- 新对话使用新的数据库；不对旧聊天文件做兼容迁移。

### P3 — KV 管理与 Warm Start

- 仅通过官方 API 做 KV 导出/恢复，Gateway 提供按模型独立名额、锁定/淘汰、失效、回退 Prefill；考察单槽与并发限制。
- `PIN` 用于可共享的公共前缀；多个角色的系统提示词不得错误共享一个可变的 PIN 状态。

### P4 — 生图与后台任务彻底独立

- 把 `image_jobs`、`image_api_services`、`gallery`、`upscale` 和本地 Qwen-Image/LoRA 从官方核心移到 Gateway/Worker。
- 测试同时执行 N 个 API 图片任务、浏览器断线、重试扣费防护、超分队列、图片/会话隔离、GPU 互斥和生成后视觉回复。

### P5 — 桌面管理、跨平台打包与灰度切换

- Tauri 启动器守护 Gateway + 官方进程，校验路径、版本及密钥，提供健康检查与安全重启。Android、远程苹果设备继续访问现有 Gateway。
- 做 Windows CUDA 本地部署包；Linux/macOS/AMD 依赖官方可用引擎及分别验证，不假设可直接移植 Windows 二进制。
- 初期保留 v0.3.0 旧架构可执行入口；通过验收后才切到新架构默认。

## 7. 必需验收与发布门槛

- API：`/health`、OpenAI/Anthropic/Responses、SSE 事件顺序、tool calls、取消、认证/Origin/CF Tunnel、Android 客户端。
- KV：多轮一致性、模型切换与不同版本/量化拒绝错配、错误格式回退 Prefill、锁定与淘汰、开关机/重启、PIN 只共享同前缀。
- 图像：本地双 Qwen-Image、LoRA、参考图优先级、云 API 代理/超时、付费重试、画廊 4x 与 NSFW、聊天 256 token 视觉跟进。
- 资源：idle 15 分钟卸载、手动停机状态、8 GB VRAM 下生图和 LLM 互斥、KV 保存/恢复时无重复竞态。
- 数据：新对话库从空白开始；保留用户角色/世界书/画廊等非聊天资产，或经明确的数据迁移步骤验证后再切换。
- 回滚：任何失败可用保留的 v0.3.0 Launcher/APK/后端恢复服务，不覆盖旧配置和用户数据。

## 8. 上游长期升级机制

1. 记录官方 Tag + Git commit SHA + Engine 构建目标，**固定版本**而不是直接追踪 `main`。
2. 官方源码不接受 Mikuchin 私有改动。Mikuchin 与官方只通过可验证的 HTTP/CLI 接口通信。
3. 每次更新：下载候选版本到独立目录 → 核对发布说明/协议差异 → 执行契约、模型、GPU、移动端冒烟测试 → 切换别名或启动配置 → 可回退。
4. 不自动更新已运行的原生引擎；完成中的付费生图和活跃模型/KV 会话未结束时不强制切换。

## 9. 本次 v0.3.0 与后续研发的严格区别

**v0.3.0 只是旧架构的稳定基线、方案文档和三端重新构建**：不交付 Gateway、官方 KV 格式、PIN 或双进程部署；这些属于未来里程碑，不可在 v0.3.0 的 Release 中宣称已经实现。
