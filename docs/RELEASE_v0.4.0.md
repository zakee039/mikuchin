# Mikuchin v0.4.0 — 原生架构迁移候选（尚未发布）

> 2026-11-21 研发中。此版本号仅表示新主分支目标，**没有创建正式 GitHub Tag 或 Release**。

- Mikuchin 主程序 / Windows 启动器 / Android 源码统一目标 **0.4.0**（Android versionCode 400）。
- **引擎始终固定**官方 PolyStrata Git 子模块 `v0.1.45-poly.10`，SHA `3e1642161198c50ff1abed4046f4e4f476099dbb`；不修改其内部源码。
- 旧版最后的 `main`（含本地计时修复 `5dde9ac`）已独立保存至 `old-mixed`；老端目标监听 25239，新主端目标监听 15239，内部官方 15240 只允许回环。
- 增量导入旧用户角色卡、世界书、聊天历史和画廊图片；原始数据库/图片保留、目标迁移前数据库备份，旧 KV 快照与付费任务不会重新执行。
- 恢复原版 440×650 启动器排版：总览模型选择与查看、API Key 明文与复制/更换、Cloudflare Tunnel、设置三卡式排版（启动/语言/空闲卸载），增设原生状态独立标签。
- 公网 Cloudflare 原域名/DPAPI Token 迁移须保证只有一个 Connector；使用实际 HTTPS Native 401 响应验证。
- Android/Windows 二进制均须重新构建并分别签名/验收；**安装器仅含启动器时不能宣称全新原生运行时完整交付**。
- 仍需 Android 真机安装/SSE/画廊及跨机器完整 Windows Runtime、自动升级/回滚验证；暂不创建正式 GitHub Release。

## 本机 v0.4.0 源码迁移与联通验收（已执行）

- 原版 `old-mixed` 已提交并推送 `79f9332`，包含之前的最新 `5dde9ac` 计时修复；配置中旧版端口已调整为 `25239`，旧版连接器和旧版自启已停止。
- 新 Native Gateway 实际监听 `0.0.0.0:15239`，官方引擎 `127.0.0.1:15240`；CLI/SQLite/API 均核对角色卡 2、迁移会话 11、画廊 92，世界书与参考文件4个按哈希复制。
- 原 `key.zakee.fun` 长期 Tunnel 已切换至 Native 专属 Connector 并真实连通；旧版 API Key 的 DPAPI 密文迁移后，公网 HTTPS、WLAN、Tailscale、Loopback 四个入口全部成功读取 11 个会话。查询不输出 Key 或用户消息。
- 实际构建 v0.4.0 Windows Tauri Debug/NSIS 启动器并重新运行，原始 440×650 设计样式 CSS 未变化（源码 SHA256 相同）；Windows NSIS 仍只是 Launcher，而不是自包含可搬迁分发。
- Android `com.mikuchin.client` v0.4.0/versionCode400 同证书签名升级候选 `migration-release-candidates/Mikuchin-Android-v0.4.0.apk` 构建成功，`apksigner` v2 校验和旧版 v0.3.0 签名 SHA256 指纹完全一致；未联网 Android 真机安装。
- 回退说明、数据库/DPAPI 设置备份位置、API/HTML 兼容检查详见 `docs/NATIVE_V040_MAIN_MIGRATION_2026-11-21.md`。

**发布边界：**主分支迁移、源码版本号变动不等于建立发行资产。只有 Android 升级候选完成签名；Windows 仍无完整 Python + PolyStrata + GPU/CUDA + 本地图像运行时的自包含安装方案，因此**不创建正式 v0.4.0 Tag 或 Release**。
