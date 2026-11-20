# Mikuchin 版本与发布规则（仓库级指令）

## Native PolyStrata 重构分支（优先级高于下方旧版发布规则）

当前目录 `E:\LLM\deploy\mikuchin-native` 对应 `refactor/official-polystrata-gateway`，是从正式 `v0.3.0` 基线创建的独立 Git Worktree。原始 `E:\LLM\deploy\mikuchin` 和其正在运行的 15239 后端**绝对不得被本分支的开发脚本、重启或清理操作影响**。

- 本分支 `backend/polystrata` 是来自 `simplexai-labs/PolyStrata` 的**未修改官方 Git 子模块**，而非下文描述的旧 vendored Fork。不得修改/提交其 Python/C++ 内部源码；官方更新只能通过 `scripts/native-polystrata.ps1 pin -Tag ...` 更新 Git 子模块指针，再跑兼容性测试。
- 新业务代码全部写入 `backend/gateway` 等 Mikuchin 自有目录；官方服务只允许绑定内部 loopback，预定内部端口 `15240`。当前 Gateway 开发端口 `15249`；在完成验收前**不得占用正式生产的 15239**。
- 旧版 `scripts/package-main-release.py` 不支持 `.gitmodules`，因此本分支暂时**不得使用旧版主程序发布流程或以 v0.3.0 名义发布新架构**。`versions.json` 的 0.3.0 是开发起点，不是新架构完成版本。
- 必做检查：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/native-polystrata.ps1 verify`、`python -m unittest discover -s backend/gateway -v`、`git submodule status`、`git status`。未来真实模型/显存/KV 测试须独立执行。
- 如改动 Gateway 协议，可执行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke-native-transport.ps1`，它将官方 Mock Engine、Gateway 以及独立 Image Worker 临时运行在 15240/15249（或指定替代端口），结束时自动退出；使用临时随机密钥和新会话测试目录，不会影响 15239。不要把 Mock 测试误报为真实 GPU/KV 推理验证。
- 独立在线生图 Worker：`scripts/start-native-image-worker.ps1`；Gateway 只写任务/草稿，不得自动在 HTTP 进程执行收费请求。独立 Worker 必须持有单例锁，持续心跳；任务进程重启后绝不能自动重复付费请求。受保护图片使用 `frontend/web/auth-images.js` 通过 Bearer `fetch`+Blob URL，绝不将 API Key 加到图片 URL。
- 官方 SM86 CUDA 编译产物和测试 GGUF 配置放在 `E:\LLM\deploy\mikuchin-native-runtime`，绝不提交模型、密钥、缓存或编译产物。真实模型验证记录见 `docs/NATIVE_OFFICIAL_CUDA_VALIDATION_2026-11-20.md`；测试结束时关闭 15240/15249 的开发服务，不能误杀或更改正式 15239。
- 新增 `scripts/start-native-stack.ps1` 与 `backend/gateway/supervisor.py`，统一启动官方引擎→独立 Worker→Gateway；默认使用 15240/15249、独立 Native 数据目录和私有 Gateway Key，禁止占用 15239。Tauri Native 开发版已经通过 `frontend/launcher/src-tauri/src/native.rs` 接入 Supervisor（不使用旧 15239 启动逻辑）；独立 App ID `fun.zakee.mikuchin.native-dev`、独立 DPAPI Key 和数据目录，真实窗口/托盘生命周期及 Mock/CUDA 已验证。未制作正式安装包或 Release。守护器允许在父进程显式使用 `--control-stdin` 时收取私有 `STOP` 指令；普通交互式 PowerShell 使用 Ctrl+C。发生付费生图时须等待 Worker 完成，不得强杀或重复付费请求。
- 新的 Gateway GET `/` 与 `/web/*.js|css|svg` 是不含秘密的浏览器静态资源，`/health`、聊天、画廊及图片 API 仍需 Bearer Key，`/config` 等危险上游接口继续禁用。真实三进程的 CUDA 验证及自动缓存结果见上述日志文档，避免与 Mock 冒烟测试混淆。
- Native 独立本地生图架构（2026-11-20）：`backend/gateway/local_images.py` + `gpu_gate.py` 在官方源码之外接入本地 Qwen-Image 官方/无审查模型、三款 LoRA 与 Real-ESRGAN 4×；`image_jobs.py` 仍是唯一任务数据库，在线付费请求的重启不自动重试规则保持不变。浏览器仅传本地模型及 LoRA ID，执行程序与权重路径由独立 Native 数据目录下的 `images/config/native-local-images.json` 决定，使用 `scripts/configure-native-local-images.ps1` 独立配置。程序和超分资源复制到 `E:\LLM\deploy\mikuchin-native-runtime\image-engines`，绝不提交到 Git 或引用正式版的运行进程。本地生图期间 Gateway 聊天持共享 GPU 文件锁，独立 Worker 获取独占锁，私有认证上游接口完成官方 LLM 的卸载与重新加载；真实测试脚本 `scripts/smoke-native-local-real.py`，详细记录 `docs/NATIVE_LOCAL_IMAGE_GPU_2026-11-20.md`。真实 GPU 检验结果以实际日志为准，不得将模拟子进程测试当成 GPU 生成成功。
- Native GPU 协调后续优化（2026-11-20）：本地 Qwen 生成和 Real-ESRGAN 4× 现在共用 **一次** 独占 GPU 文件锁及官方 LLM 卸载/加载周期，不再在两阶段之间重新加载 LLM；在线 API 的后处理仍单独请求本地 GPU。Native Gateway 授权 `/health` 提供 `native_gpu`、`native_image_jobs`、`native_upscaler_ready`，Tauri `get_status` 面板显示任务阶段/Worker/超分/子进程重启次数；官方引擎异常退出时守护器在 GPU 仍独占期间延后模型重启。真实模型含 LoRA + 4× 测试已确认 384×384→1536×1536、`gpu_handoffs=1`，但单次总耗时不构成性能提升证据；详细结果与局限见 `docs/NATIVE_LOCAL_IMAGE_GPU_2026-11-20.md`。分支未发布任何新安装包或 Release。
- 迁移文档 `docs/NATIVE_POLYSTRATA_DEVELOPMENT.md`，总体计划 `docs/PLAN_OFFICIAL_POLYSTRATA_GATEWAY_v0.3.0.md`。

本仓库从 v0.2.8 起使用 **根目录 `versions.json` 作为唯一产品版本来源**。

每次开始版本相关工作（包括新对话、移植上游、Release、安装包构建），先执行：
```powershell
python scripts/versioning.py status
python scripts/versioning.py check
git status --short --branch
gh release list --repo zakee039/mikuchin --limit 5
```

- `versions.json` 的 release 指当前正在准备/发布的 Git tag，`previous_release` 只是历史标识。
- 产品版本三轴：`components.main.version`、`components.launcher.version`、`components.android.version` 与 `versionCode`，可以独立升版；**本次 v0.2.8 特别统一三者为 0.2.8**。
- 改动版本号时，修改 manifest，然后运行 `python scripts/versioning.py sync` 与 `check`。不得只改 README 或某个代码内的数字。
- 版本历史和实际发布资产见 `docs/VERSION_HISTORY.md`，GitHub Releases 则是**是否真正发布**的最终依据；仓库提交不等于发布。
- Android 必须签名有效且升级证书与旧版一致；版本号变更后必须重新构建 APK。Windows Launcher 必须重新构建 EXE/NSIS；绝不将旧二进制重命名成新版。
- 主程序 Release ZIP 使用 `scripts/package-main-release.py` 打包，必须通过版本校验和干净工作区检查；资源文件、模型、用户对话、密钥及临时构建目录禁止提交或打包。
- PolyStrata 是 vendored 后端源代码（`backend/polystrata`），它自带的旧 `manager` 示例版本 0.1.12 **不是 Mikuchin Launcher 产品版本**，勿全局替换它。
- 提交/打 Tag/上传 Release 之后核验版本、远程 Tag 指向、所有上传资产名称及 SHA256。若任何构建缺失不得宣称所有端均更新完毕。
- 历史实验：`docs/UPSTREAM_PORTS_2026-11-13.md`、`docs/NATIVE_AB_VALIDATION_2026-11-13.md`、`docs/LIVE_CPU14_ROLLOUT_2026-11-13.md`。

## 修复后的本机生效约定

- 用户明确要求：以后每次完成并验证 Mikuchin 修复，**默认在本机直接重启需要重启的服务，并核实新代码已生效**，不要只留下未加载的源代码让用户自行重启。纯网页资源修改可通过缓存版本更新直接生效，不要无故中断后端。
- 重启前先检查任务数据库中没有 `queued` / `working` / `running` 任务，并检查 `/health`、模型加载状态；正在生成或存在活跃会话、状态不明时**不要强杀**，应说明阻碍。避免中断付费 API、生图、用户 KV 会话。
- Windows 托盘启动器在 `frontend/launcher/portable/Mikuchin.exe`，由它管理 `15239` 后端服务。安全空闲时可借助独立启动流程重启启动器和子服务，之后核验新进程 PID、`/health`、已鉴权 API 是否暴露新字段，以及网页资源。临时重启任务完成后必须清理。
- 源码生效、启动器重启、版本号更新、GitHub 提交和 Release 是不同的事；如实汇报，不擅自发布。
