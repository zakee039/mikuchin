# Native 桌面启动器 UI 与独立运行（2026-11-20）

开发分支：`refactor/official-polystrata-gateway`

这次按用户反馈将原生开发版的 Tauri 控制台恢复为 **正式版 Mikuchin 的紧凑设计**，但**没有移植旧版后端或破坏新架构的隔离**。

## 交互与界面

- 直接复用正式版 `frontend/launcher/src/style.css` 的全套视觉规则。Native 差异写在 `src/native.css`，不修改正式版。
- 恢复 **440×650** 的默认窗口（最小 420×650，不可最大化/最小化，关闭隐藏至托盘）。
- 四个标签：**总览、API、设置、原生状态**，删除「工作流」。
- 总览：当前官方模型/配置、真实 GPU 显存（nvidia-smi 5 秒缓存）、经 Gateway Bearer 鉴权读取的官方 `/metrics`（Token、Prefill、Decode、KV 缓存）、安全停止或启动服务、打开 Chat。
- API：隔离的 Gateway `15249`、私有官方引擎 `15240`、不在页面暴露明文的「复制 API Key」。
- 设置：守护/开机启动/服务控制状态；**尚未移植的开关均禁用或只读**，不会模拟已经生效的功能。
- 原生状态：官方 Engine / Image Worker / Gateway 的实际 PID、GPU 独占阶段、任务、ESRGAN、自动恢复信息。
- **CF Tunnel、LAN 访问、模型配置注册/切换、旧版自启动设置**当前并未完成原生后端移植；只展示真实情况，不提供假开关。
- 用 `renderBody` 只替换内容容器，并保存与恢复 `scrollTop`；2 秒轮询不再整体覆写 `root.innerHTML`，不会将当前标签或滚动位置重置为顶端。
- **150% DPI 修复**：Windows WebView 原生已经处理屏幕缩放，禁止再为整个 `documentElement` 设置 `zoom = 1/devicePixelRatio`。此前手动缩放使 UI 只占窗口约 2/3，底部形成大片空白。现已移除全局 zoom，以 Per-Monitor DPI aware 方式抓取真实桌面窗口（682×1031 物理像素），验证 440×650 逻辑窗口内界面从顶部至底部完整填充，四个标签正常显示。追加 1 项测试防止回归。

## 页面精简与待移植功能（后续反馈）

- API 页保留「从其它设备访问」入口，局域网 HTTP 与 Cloudflare Tunnel 都**尚未在 Native 接入**，标注「待接入」且禁用开关；不能把用户指出的功能缺失理解为要求删除入口。
- 删除 API 页独立鉴权/正式端口长说明；设置页删除重复的「服务控制」卡片（总览已有启动/安全停止操作）、未实现的开机自启开关及冗长的行为解释；原生状态页删除宣传式说明和重复的正式端口提醒。
- 后续真正接入局域网/Cloudflare 时，需要在 Gateway/Supervisor/Tauri 三层实现并测试，仅恢复 UI 不等于功能完成。

## 无黑色命令行窗口

`src-tauri/src/main.rs` Windows GUI 子系统改成 **debug/release 均启用**（`cfg_attr(target_os = "windows", windows_subsystem = "windows")`）。以前 `cargo build` 直接启动 Debug EXE 会带可见控制台，并且 Debug 模式默认走 Vite `1420`，无法独立运行。

正确的本地预览构建方式是：

```powershell
cd E:\LLM\deploy\mikuchin-native\frontend\launcher
$env:CARGO_TARGET_DIR = 'E:\LLM\deploy\mikuchin-native-runtime\tauri-target'
npx tauri build --debug --no-bundle
```

该命令会执行 Web 前端构建、将 `frontendDist` **嵌入 Tauri Debug EXE**，不用独立启动 Vite，也不会误制作 NSIS、Tag 或 GitHub Release：

`E:\LLM\deploy\mikuchin-native-runtime\tauri-target\debug\mikuchin.exe`

仅用 `cargo build --bin mikuchin` **不能保证嵌入新前端**，会导致 `127.0.0.1:1420` 拒绝连接。以后测试 Native EXE 不得再省略 Tauri build 步骤。

## 当前用户会话试用方式

本机用 Windows 计划任务 `Mikuchin-Native-Dev-Launch` 的 **Interactive** 会话启动已构建的 Native EXE（无计划触发器，仅手动运行）。任务用于在 AgentDock 命令进程退出后保持桌面 UI 运行，用户可以直接操作系统托盘和 Native 控制面板。它**不是开机自启动开关**。

调用 `Stop-ScheduledTask` 会直接结束这个试用 Launcher，用户正在执行图像/付费任务时禁止强制停止。需要替换 EXE 时，应先确认 `ImageJobStore.activity().running == 0`、`gpu_gate.read_state().busy == false`，再停止 Native 预览，重新 `tauri build --debug --no-bundle`，最后启动任务和检查窗口、真实三个子进程以及 15240/15249。

## 验收与版本边界

- `npm run web:build`：通过，嵌入资源的 Debug EXE 成功构建。
- `cargo test --lib`：4/4。
- `node --test frontend/launcher/tests/native-shell.test.mjs`：4/4，新加到开发分支 GitHub CI。
- `node --test frontend/web/tests/*.test.mjs`：28/28。
- 实际启动确认：Windows 会话 1，主窗口显示四个标签及 440×650 布局；无控制台窗口；Supervisor 独立管理官方 PolyStrata、Image Worker 和 Gateway；端口 15240/15249 可用；正式端口 15239 不接管。
- 仍未制作 NSIS 正式安装包，未发布新版本。版本继续为主程序 0.3.1、启动器 0.3.0、APK 0.3.0。
