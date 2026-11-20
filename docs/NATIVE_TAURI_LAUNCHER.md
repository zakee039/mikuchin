# Native Tauri Launcher 集成（开发分支）

> 2026-11-20 更新：Native 控制面板增加 GPU 互斥阶段、图像队列数、
> Image Worker / Real-ESRGAN 可用性和子进程自动恢复记录；固定窗口内容区
> 可滚动。更详细的真实 CUDA/Vulkan 验证和单次 GPU 交接优化见
> `docs/NATIVE_LOCAL_IMAGE_GPU_2026-11-20.md`。

> 当前分支：`refactor/official-polystrata-gateway`；本说明只覆盖原生开发版。产品主程序仍为 0.3.1，Launcher/APK 仍为 0.3.0。没有打包或发布 Release。

## 工作内容

桌面启动器现已直接托管 Python `backend.gateway.supervisor`，而不是旧的单 Python `serve/server.py` 后端。Supervisor 依次拉起未修改的官方 PolyStrata、独立 Image Worker、Gateway；Tauri 通过**私有 stdin** 向其发送 `STOP`，不暴露未鉴权的 HTTP 停止接口。

- Tauri Rust 桥接：`frontend/launcher/src-tauri/src/native.rs`。
- Python 统一守护：`backend/gateway/supervisor.py`。
- 面板：`frontend/launcher/src/main.ts` 和 `src/style.css`。
- Tauri 独立应用标识：`fun.zakee.mikuchin.native-dev`（独立于旧安装包）。
- API Key：`%LOCALAPPDATA%/MikuchinNativeLauncher/api-key.dpapi`，Windows DPAPI 加密；不复用旧版密钥。
- 本地日志：`%LOCALAPPDATA%/MikuchinNativeLauncher/supervisor.log`。
- 开发数据：`E:\LLM\deploy\mikuchin-native-runtime\launcher-user-data`，不复用原本 stable 数据目录。
- 启动器只允许 Gateway `127.0.0.1:15249`、官方 Engine `127.0.0.1:15240`，不接管 `15239`。
- 当前读取单独的 CUDA 验证配置 `mikuchin-native-runtime/config/official-sm86-model-test.json`。这是**开发阶段模型配置**，非最终模型管理实现；配置不存在时明确报错，不回退到 Mock 冒充真实推理。

## 进程生命周期

1. 启动 Tauri 后守护器在后台启动 Supervisor，传入私有 Gateway Key 与 `--control-stdin`。
2. `get_status` 读取**本启动器拥有的进程 PID**、Supervisor 状态文件，并向 loopback 的 Gateway `/health` 进行 Bearer 授权探测。不向 HTTP 代理传输密钥。
3. Supervisor/子进程发生异常退出时由 Python 先尝试恢复；Supervisor 自身退出时 Rust 最多每分钟重启 3 次。已经手动停止的服务不会自动拉起。
4. 点击安全停止或托盘退出：**只发送 STOP**。Python 等待 Gateway、Worker 和官方 Engine 退出；付费生图未完成时允许 Worker 完成当前任务，Supervisor 保持运行并等待收尾。无 `taskkill /T /F`。
5. 顶层进程意外崩溃时，Supervisor 监听的 stdin EOF 触发安全停止。磁盘数据和日志位置与正式版隔离。

## 验证命令

在根目录运行：

```powershell
python scripts/versioning.py status
python scripts/versioning.py check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/native-polystrata.ps1 verify
git submodule status
$env:PYTHONPATH=(Get-Location).Path
& 'E:\LLM\deploy\mikuchin-native-runtime\.venv\Scripts\python.exe' -m unittest discover -s backend/gateway -v
```

在 `frontend/launcher` 运行 `npm ci; npm run check; npm run web:build`。在 `frontend/launcher/src-tauri` 运行：

```powershell
$env:CARGO_TARGET_DIR = 'E:\LLM\deploy\mikuchin-native-runtime\tauri-target'
cargo test --lib
cargo build --bin mikuchin
& "$env:CARGO_TARGET_DIR\debug\mikuchin.exe" --self-test-native
& "$env:CARGO_TARGET_DIR\debug\mikuchin.exe" --self-test-full
& "$env:CARGO_TARGET_DIR\debug\mikuchin.exe" --self-test-ui
```

`--self-test-native` 在临时用户目录和**操作系统分配的随机 loopback 端口**上运行真正的 Rust → Python Supervisor → 官方 Mock Engine + Worker + Gateway 生命周期测试，验证首页 200、未鉴权健康探测 401、鉴权健康 200、STOP 后进程退出及端口释放。Mock 不等同于 GPU 推理成功。额外 `--self-test-full` 使用独立 SM86 模型配置启动 CUDA 栈，但不会调用收费生图 API。

## 2026-11-20 实测验收

- Python Gateway 回归：**56/56**。
- Web UI Node 回归：**28/28**。
- Rust 单元测试：**3/3**，`cargo check --lib`、`cargo build --bin mikuchin` 成功。
- `--self-test-native`：Mock 三进程成功，首页 200、无 Key /health 401、STOP 后状态 stopped。
- `--self-test-full`：真实官方 SM86 CUDA 进程成功加载并经过 Gateway 验证（模型名 `official-gemma4-26b-sm86-test`），**本次仅验证装载和健康检查，不冒称重新测过真实 Token 推理**。
- `--self-test-ui`：真实 Tauri 事件循环/托盘、常规 15240/15249 服务启动、健康检查与安全退出成功。
- 测试全部退出后无 15239/15240/15249 监听；RTX 3070 Ti 显存恢复约 158 / 8192 MiB；官方 Git 子模块未被修改。
- `--self-test-ui` 的机器可读验收记录位于 `%LOCALAPPDATA%/MikuchinNativeLauncher/ui-smoke-result.json`。

## 边界与待办

- 当前 Native 面板专注进程状态、日志、启动、停止、访问网页和复制 API Key；旧启动器的模型配置管理、CF Tunnel、LAN 按钮没有移植到该全新界面。
- 现阶段默认限制 loopback。跨设备访问、Cloudflare Tunnel、密钥轮换和 GPU 共享调度应通过新架构的独立服务模块重新设计，不应原样搬回旧的 monolith。
- 下一步：本地 Qwen-Image、LoRA、4× 超分与 GPU 显存仲裁。
- 本分支尚无新的 Launcher 安装包、Git tag 或 Release。**不得用旧版打包脚本直接发布带 Git 子模块的新架构。**
