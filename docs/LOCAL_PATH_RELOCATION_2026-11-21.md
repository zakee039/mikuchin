# Mikuchin 本机目录归并记录（2026-11-21）

## 最终布局

| 路径 | 说明 |
| --- | --- |
| `E:\LLM\mikuchin` | 当前 Native `main` Git worktree；官方 PolyStrata 仍为干净 Git 子模块 |
| `E:\LLM\mikuchin\runtime` | 本机私有 `.venv`、官方引擎构建、模型 JSON、用户数据、图片索引与资源、Launcher Debug EXE、Tunnel 工具、迁移备份（Git 忽略） |
| `E:\LLM\mikuchin-old` | 旧 `old-mixed` 主 Git 工作树，完整历史及原数据保留 |
| `E:\LLM\models` | 共用模型文件（不迁移既有 GGUF 权重） |

`E:\LLM\deploy` 已完全移除；`E:\` 根目录原 11 个 `mikuchin-native-bench-20261113*`、`mikuchin-native-review-20261113*`、`mikuchin-llama-pinned-3cf` 目录已移除。

## 保护与清理

- 旧独立 PolyStrata 开发仓库包含未提交修改，先生成完整 Git bundle、`git diff --binary` 补丁、未跟踪资源 ZIP，再删除原独立仓库。
- 旧 benchmark 下 371 个小型研究报告、配置及脚本保存为 ZIP；原 KV 压测快照及独立测试构建删除。
- 恢复包：`E:\LLM\mikuchin-old\_migration-recovery\20261121`，该目录通过旧仓库本地 Git exclude 忽略。内容含 `.bundle`、`.patch`、两个 `.zip` 及 `legacy-TEST_RESULTS.md`。
- PolyStrata 中一份独有 MTP 权重另外保存在 `E:\LLM\models\mtp-gemma-4-26B-A4B-it-Q8_0.gguf`。
- 私有 SQLite 在搬迁前通过 SQLite backup API 备份；模型/图片配置和 DPAPI 资料亦在 `runtime\migration-backups\path-relocation-20261121` 保留迁移前副本。未删除原版聊天数据或图片。
- 删除旧 `benchmark`、`koboldcpp`、`llama-cpp`、`polystrata`、已归档的部署说明，以及 Native runtime 中约 4.58 GB 的 `tauri-promotion-build` 重复构建缓存。

## 路径及进程联动

- Git：旧 primary worktree 迁往 `mikuchin-old`，Native secondary worktree 迁往 `mikuchin`；更新 linked `.git`、子模块 `.git`、子模块 `core.worktree`，执行 `git worktree repair`。不能单独删除 `mikuchin-old`，否则当前 main 的 Git 元数据会失效。
- Native 代码、子进程安全隔离判断改为识别旧目录名 `mikuchin-old`，而不是把当前 `mikuchin/runtime` 错判为旧版。
- Native 模型 JSON、`active-model-config.json`、`native-local-images.json` 的旧绝对路径改成新目录，确保官方引擎、图像 CLI、超分、日志和 CUDA 动态库路径有效。
- 计划任务 `Mikuchin-Native-Dev-Launch` 指向 `E:\LLM\mikuchin\runtime\tauri-target\debug\mikuchin.exe`，工作目录 `E:\LLM\mikuchin`。两项旧实验启动任务迁址并禁用，防止错误唤起 old-mixed。
- Gateway `15239`；官方 PolyStrata loopback `15240`；旧版预留 `25239`；Named Cloudflare Tunnel 仍为原有 `key.zakee.fun`。DPAPI 密钥未进入 Git 或日志。

## 验收

- 新目录下 Python Gateway 86 项、Rust Launcher 13 项回归测试通过，TypeScript/Vite/Tauri Debug EXE 构建通过。
- 旧版 `old-mixed` 和新版 `main` 双 Git 工作树可访问，官方子模块固定 `3e1642161198c50ff1abed4046f4e4f476099dbb`（`v0.1.45-poly.10`）。
- 新目录下 Gateway/官方引擎/Tunnel 已启动；授权 API 返回原有 11 会话；SQLite 角色卡 2，画廊索引 92，图片文件 92，图像任务 5 条均成功且无运行任务。
- 本地未授权 `/health` 和公网 `https://key.zakee.fun/health` 均返回 HTTP 401；未启用旧版 25239。
- 本次为路径整理与运行环境接线，不增加产品版本号；不创建新的 GitHub Release 或覆盖已有 v0.4.0 Tag。
