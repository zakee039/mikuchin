# Mikuchin v0.3.0 — Existing Architecture Baseline Before Official PolyStrata Migration

2026-11-19 · Main 0.3.0 / Windows Launcher 0.3.0 / Android 0.3.0 (`versionCode=300`)

## 定位

**v0.3.0 不是新的 Gateway 架构。** 本版本将现有 Mikuchin 全部功能和截至 2026-11-19 的未发布修复冻结为下一轮重构之前的**可回退基线**，不替换现有 PolyStrata Fork、不将旧版 KV 快照转换为新版官方格式、不删用户对话和图像。

## 相对 v0.2.10 的功能与修复

- 生图任务中心：草稿、进行中、成功、失败；所有状态都有「编辑」，重试仅对成功/失败展示；草稿编辑保留 ID 并刷新任务排序。
- 生成耗时改为从点击生成或重试的实际时间起算，成功/失败后冻结。旧任务无明确起点时显示未知，不能从草稿创建时间伪造。
- API 生图连接诊断：区分连接、响应头、响应体和图片下载等已知阶段，记录实际耗时、HTTP 状态与接收字节数；各 API 服务新增连接/TLS 超时设置，保留独立读取超时和并发设置。不会自动重放付费请求。
- Android 连接配置及移动端图库细节修复、相关网页与后端改进，具体以 v0.3.0 的源码和测试为准。
- `docs/PLAN_OFFICIAL_POLYSTRATA_GATEWAY_v0.3.0.md`：未来迁移至官方 PolyStrata + 独立 Mikuchin Gateway 的技术方案、端口/服务分工、兼容性决定、分阶段实施和验收门槛。

## 三个产品组件

| 组件 | 版本 | 构建目标 |
|---|---|---|
| 主程序 | 0.3.0 | 源码、完整功能基线，仍使用现有独立 Mikuchin PolyStrata 后端 |
| Windows Launcher | 0.3.0 | 重新编译 Tauri 可执行文件和 NSIS 安装包（不可重命名旧二进制） |
| Android | 0.3.0 / 300 | 重新编译 APK，以既有 release 证书签名，检查与 0.2.10 同证书、可升级 |

## 构建和验收

- 以 `versions.json` 为唯一版本号来源，执行 `python scripts/versioning.py sync` 和 `check`。
- 执行后端与浏览器端回归测试，重新构建 Launcher、NSIS 和 Android APK。
- 核验 APK 包名 `com.mikuchin.client`、`versionName=0.3.0`、`versionCode=300`、同证书签名；核对 Tauri 新二进制版本与 SHA256。
- 本文档是源码目标版本说明；**只有真正完成相应构建和 GitHub 发布才能声称其已发布**。不得捏造 Release 日期、二进制或测试结论。

### 2026-11-19 本机构建核验

- Android：`frontend/android/build-apk.ps1` 运行成功，Gradle `assembleRelease`（50 项任务，13 执行、37 UP-TO-DATE）；`Mikuchin-v0.3.0.apk` 为 **10,115,732 字节**；manifest 为 `com.mikuchin.client`、`versionCode=300`、`versionName=0.3.0`。`apksigner verify --print-certs` 与 **v0.2.10** APK 的 SHA-256 签名指纹一致：`18f530740202c00d0c3f003f46d7ce8f19cd4fc3a6eca23c407be5fc4f72b29e`。
- Windows：`scripts/build-launcher.ps1` 运行成功，Tauri/Rust `release` 编译了 v0.3.0；可执行文件 **13,949,952 字节**，NSIS `Mikuchin_0.3.0_x64-setup.exe` 为 **4,704,719 字节**；由于 v0.2.10 便携启动器当时正在运行，构建脚本先保存为 `frontend/launcher/portable/Mikuchin-v0.3.0.exe`，绝不以旧版 EXE 冒充新版本。
- 回归：`serve.test_mikuchin_image_jobs` **18** 项、`serve.test_mikuchin_image_api_transport` **6** 项、`serve.test_session_v1` **14** 项、前端 Node **13** 项通过。`versioning.py check` 通过。
- 构建 SHA256：Android APK `912A2B4A1250A1B3C6F2D41EF7C126FA88FA5C018463C3AE0BB8848EB0142562`；Launcher EXE `0EE523A2CE61CD42E29C51A35BB6EAA0D6CABFAC5D798E4AAF0D0009F932577B`；NSIS `37515A5851BF89732F71902AC06089948A7CD43D351CB73978D1AFC78DAFA44F`。
- 本条仅说明**已在本机编译的二进制**与源码测试结果，不代表新网关架构已实现，也不代表 GitHub 已发布。

## 回滚与下一步

- 保留 v0.2.10 正式发布二进制和 v0.3.0 基线产物，后续 Gateway 开发应使用独立工作目录与可回滚分支。
- 已有对话/旧 KV 不要求迁移到未来 Gateway，但 v0.3.0 本身**不清除**现有数据。角色卡、世界书、图像等非会话资产未来需要单独保留。
