# Mikuchin v0.2.8 — 版本统一与 PolyStrata 增量更新

## 版本矩阵（以 versions.json 为准）

| 组件 | 上一发布版本 | 本次发布版本 | 发布要求 |
|---|---|---|---|
| Mikuchin Main | 0.2.7 | **0.2.8** | 含已集成后端的完整独立源码归档 |
| Windows Launcher | 0.2.4 | **0.2.8** | 重新编译便携 EXE 和安装包，不重命名旧文件 |
| Android | 0.2.4 / 204 | **0.2.8 / 208** | 重新编译并使用与上一发布相同的签名证书 |

以后三个组件可以继续独立升级；每次版本变更先更新根目录 `versions.json`，然后运行 `python scripts/versioning.py sync` 与 `check`。

## 内容

- Mikuchin 源码仓库继续保持完全独立，**不依赖 PolyStrata fork 或 Git submodule**。
- 选择性移植上游：修复 strata-poly 弹性显存参数兼容、视觉编码器故障诊断、Gemma 4 EOS 与并发槽位管理。
- 图文混合 Prefill 使用文本片段批量读取路径；保持混合图文及 KV 缓存语义。
- CPU 专家自动线程，桌面默认预留约 30% 逻辑线程，`--threads N` 手动指定优先。
- Windows WDDM 本地显存预算只读查询和独立鉴权 API，监控页可展示预算与进程用量。
- Responses API `response.completed` 流式事件额外携带 `timings` 字段，不改变标准 response 内部结构。
- 构建与运行回归详见 `UPSTREAM_PORTS_2026-11-13.md`、`NATIVE_AB_VALIDATION_2026-11-13.md`、`LIVE_CPU14_ROLLOUT_2026-11-13.md`。

## 测试与限制

- Windows CUDA 13.2 / RTX 3070 Ti 8GB：原生 `strata-poly` 独立构建和完整链接成功。
- Windows Launcher v0.2.8 已重新经 Tauri 2 / Rust Release 配置编译，便携 EXE、NSIS 安装包均为新产物；PE ProductVersion / FileVersion 都是 0.2.8。
- Android v0.2.8 已重新经 Gradle Release 构建，内部应用包名 `com.mikuchin.client`、
  versionName 0.2.8 / versionCode 208；`apksigner` 验签成功，签名证书 SHA-256 与 v0.2.4 完全一致，可满足覆盖升级的签名要求。
- 固定专家分配的 Gemma 4 旧/新 14/20 线程对照：输出逐 Token 一致。
- 双会话交替、KV 恢复、单图视觉推理通过实际模型的旧/新 A/B 测试。
- 旧版正式引擎启用 14 CPU 线程后，聊天 API、Function Calling、图像理解和 Responses SSE 均通过。
- **大部分吞吐改进来自 CPU 线程数减少，不应把它宣传为新 CUDA 算法的普遍加速。**
- 尚无多设备、长时间生产负载和完整生图联动回归；CUDA 原生构建存在第三方构建警告 C4819 / LNK4098。

## 发布资产

发布时按 manifest 实际版本命名并验证签名、内部版本、SHA256：

- `Mikuchin-Main-v0.2.8-source.zip` 及其 `.sha256`
- `Mikuchin-Launcher-v0.2.8.exe`
- `Mikuchin-Launcher-v0.2.8-Setup.exe`
- `Mikuchin-Android-v0.2.8.apk`
- `Mikuchin-Engine-v0.2.8-Windows-CUDA13.2-SM86.exe`（可选）：仅限已验证的 Windows / CUDA 13.2 / NVIDIA SM86 平台，
  依赖与原有部署相同的模型及 CUDA DLL；此文件不是完整一键安装包，也不会自动覆盖用户本机现有引擎。
- `Mikuchin-v0.2.8-release-manifest.json`：发布资产 SHA256、字节数与组件版本

所有资产必须是本次构建且能验证对应版本；发布前不得将旧 v0.2.4 二进制改名冒充 v0.2.8。

## 后续对话与发布

仓库根目录 `AGENTS.md`、`versions.json` 和 `docs/VERSION_HISTORY.md` 包含版本规则、当前版号、历史版号与核验命令。新对话无需依赖聊天记忆猜测版本号，优先读取仓库并实际查询 GitHub 最新 Release。
