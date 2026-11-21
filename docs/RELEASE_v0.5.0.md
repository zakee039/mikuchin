# Mikuchin v0.5.0 — Native Tool Calling / 三端同步版本

2026-11-21；从 v0.4.0（官方 PolyStrata Native 重构基线）提升次版本 +0.1。
源码目标：主程序 0.5.0、Windows Launcher 0.5.0、Android 0.5.0（versionCode 500）。

## 更新内容

- 原生模型 Tool Calling：生图不再依赖关键词判断；先保留模型的思考与真实工具调用，工具任务有确定的会话 ID 和图片任务 ID。
- 完成/失败可恢复：持久化图片任务与 Tool Turn，支持并行 API 图像请求期间继续聊天。结束时根据图片理解、原请求和当前会话上下文自然回复；错误回传 LLM 分类、解释并询问用户是否需要手动重试，不自动二次收费。
- API 图片模型在聊天全局设置中隐藏不适用的“运行方式”；仅本地模型可选互斥切换／同时运行。
- 图像服务支持 SDXL Base 1.0、Animagine XL 4.0 Opt 单文件 Checkpoint，同时保留 Qwen-Image Turbo 官方/其他配置；本机导入要求仅服务器本机与授权操作。
- 图片在聊天中的只读全屏预览、画廊下载按钮、后台任务计时/顶栏状态单一仲裁、多会话刷新恢复。
- Android 客户端的 Host/Key、SSE、聊天/画廊兼容 Native Gateway。Windows Tauri Launcher 继续提供独立应用托盘与服务状态及模型管理。

## 上游与分发边界

官方 PolyStrata 是干净 Git 子模块，固定 **v0.1.45-poly.10**，Git SHA `3e1642161198c50ff1abed4046f4e4f476099dbb`；**本次不修改官方源码或指针**。

- 主程序是 Native Gateway + 官方 PolyStrata 的**源码发行包**，不含用户 SQLite、API 凭据、图片权重、CUDA/Python/虚拟环境；仅源码发行包需有 `.gitmodules`、官方子模块源码及固定 SHA，可按项目文档从源码部署。
- Windows EXE / NSIS 仍**仅包含 Native Launcher**，没有打包官方模型权重、Python、CUDA、sd-cli 等本地运行时。其他电脑上安装后需另行配置有效的 Native 后端。
- Android APK 包名 `com.mikuchin.client`，同签名才允许原位升级；可用 Tailscale/局域网/Cloudflare 路由访问用户自行提供的 Native Gateway。不是本机部署安卓推理服务。
- 不声称已完成 Android 真机安装或一键跨机器部署。

## 实际构建与签名核验

- Windows Tauri 2：`npx tauri build --debug --bundles nsis`，使用原有 Native Launcher 受控停止/恢复工作流（无运行中的图像/LLM 请求时才执行）。打包完整包含新 Tauri 前端资源。Windows 文件版本 `0.5.0`。当前 NSIS 由 **Debug 配置**构建，名称仍为 `Mikuchin Native Dev`，不是便携全功能部署包。
- Windows portable EXE：`Mikuchin-Launcher-v0.5.0.exe`，**19,026,432 字节**，SHA256 `7FFDCE222FEC7BBFC38441A572E33FCE8EC4D9AF75D1B70FD4A5674714C229DF`。
- Windows NSIS：`Mikuchin-Launcher-v0.5.0-Setup.exe`，**5,347,277 字节**，SHA256 `0548BF9E11DB19B75253343A7E3A5EFC7F7702664F15FB9A4784164CFC430DB8`。
- Android：使用已存在的本机 JDK17 / SDK34 / Gradle 8.7 + 上一个正式 APK 的相同发布密钥执行 `testReleaseUnitTest assembleRelease --no-daemon`，**BUILD SUCCESSFUL**。当前 APK：`Mikuchin-Android-v0.5.0.apk`，**10,116,712 字节**，SHA256 `CE3DF1A5176A01BB28A0DC3305E2EEAED3F42D386AF01A0CCD28A293F059B6F7`。
- `apksigner verify --verbose --print-certs`：APK v2 签名有效，原版本 v0.4.0 和新 v0.5.0 证书 SHA256 均为 `18f530740202c00d0c3f003f46d7ce8f19cd4fc3a6eca23c407be5fc4f72b29e`；`aapt dump badging` 返回 `com.mikuchin.client`、`versionCode 500`、`versionName 0.5.0`。
- 根 manifest `scripts/versioning.py check` 完整校验 13 个版本源；版本测试 8/8 通过。其它回归/上传后 SHA256 和 Release Tag 以正式资产 manifest 为准。

## 源码 ZIP 说明

原 `scripts/package-main-release.py` 假设 PolyStrata 是 vendored 目录，而 Native main 已更换为官方 Git 子模块。因此本版修改为：先核验主仓库干净、子模块 SHA 与 Gitlink 一致、上游远端 URL 正确且没有未提交修改，再将**仅已追踪**的主仓库和官方子模块源代码文件加入 ZIP，不打包 `.git`、设备上的 `runtime`、用户数据、任何密钥或下载模型文件；额外附 `OFFICIAL_POLYSTRATA_PIN.txt` 说明精确上游版本。构建完成以后由 `scripts/release_assets.py` 将 ZIP、Windows、Android 全部做 SHA256 资产清单。

**限制：** 未做 Android 真机升级安装、跨机器 Windows 完整运行时验收；NSIS 不包含 Python / CUDA / 模型，安装后需要正确部署 Native Runtime。
