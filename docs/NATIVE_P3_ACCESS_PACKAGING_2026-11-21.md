# Mikuchin Native P3：跨设备入口与独立预览打包（2026-11-21）

工作区 `E:\LLM\deploy\mikuchin-native` / 分支 `refactor/official-polystrata-gateway`。用户确认暂不关心正文独立 Token 上限，本轮优先 P3。正式 main、15239、原有 Android 包和正式 CF Token 不修改；以下均为**开发预览而非正式发布**。

## 1. 局域网 / Tailscale 实际检查

Native `preferences.json` 原有 `lan_access=true` 已生效；桌面机当前实际监听：
- Gateway `0.0.0.0:15249`（由用户已有设置启用，未新开防火墙规则）
- Official PolyStrata `127.0.0.1:15240`（不会直接暴露到网卡）
- 生产 `15239` 未启动、未借用。

使用开发机自身的回环地址、WLAN IPv4 地址和 Tailscale IPv4 地址进行**真实 TCP/HTTP** 校验：三种地址下，不带 Key `GET /health` 均返回 Native 专有 401 JSON；持独立 Native Key 的 `GET /health` 和 `GET /v1/strata/sessions` 均返回 200；恶意 `Origin=https://evil.invalid` 返回 403。

**边界**：这证明 Windows 主机已在对应接口监听，并能经这些地址本机访问。它**不是**由手机/笔记本远端发起的 HTTP 测试；Windows 防火墙、学校 AP 隔离及 Tailscale ACL 仍可能阻断外部访问，不能凭本机回环路径宣称跨设备已全面通过。

## 2. Cloudflare 公网 HTTPS（只暴露隔离 Mock）

新增 `scripts/smoke-native-cloudflare-quick.py`，将一次性临时 Native MOCK Supervisor / Gateway / Image Worker 放在**随机回环端口+临时数据目录**，再用独立复制的 `cloudflared 2026.10.7` 创建临时 `trycloudflare.com` Quick Tunnel。私有 Key 随机生成，不复制真实 Native/Main 密钥。

实机执行成功：
- 公网 `https://<临时域名>/health` 返回 Native 鉴权挑战 HTTP **401**。
- 同一临时公网 URL 的 `/` 静态首页返回 HTTP **200**。
- 访问时**没有发送任何实际 API Key**，只读取公开首页和未授权的健康检查；不触发任何真实推理/收费生图，也不暴露真实用户会话。
- 测试最后终止临时 Cloudflared 和 Mock Supervisor，清理临时数据及日志。

**命名 Tunnel 未完成**：Native 真实设置仍 `cf_enabled=false`，`cf_hostname` 为空。用户需要在自己的 Cloudflare 账户新建**独立** Tunnel，添加公网 hostname 对应源站 `http://127.0.0.1:15249`，然后将此 Tunnel 的 Token 保存至 Native UI，最终再做鉴权、移动端网络和故障重连测试。**绝不能复用正式版的 Token 或路由**。Quick Tunnel 公网链路成功不能替代长期域名/Token 验收。

## 3. Android：修复 Native 鉴权预检与独立预览 APK

### 修复真实兼容性问题

原 `MainActivity.connectCandidate` 在发出 **不带 Key** 的 `GET /health` 后仅接受 HTTP 2xx。Native Gateway 出于安全要求会返回 401，所以原 Android 即使输入正确地址/Key也会被预检挡住。现在支持：
- 正式 main：原有公开 `/health` 返回 2xx；继续按原逻辑验证会话 API。
- Native：只接受**精确匹配**的 `401 + JSON(error.type=unauthorized,error.message=Missing or invalid gateway API key)`，随后才将本入口已保存的独立 API Key 发送给 `/v1/strata/sessions`。
- 其他 401、403、5xx、无效 JSON、模仿 HTML 认证页仍拒绝；正确回执也**不替代**后续会话授权。第一步不会泄露 Key。明文 WLAN 地址依旧按 SSID/手动连接安全策略处理。

`ServerHealthPreflightTest` 两项 Kotlin 本地单元测试已通过，主程序编译通过；`frontend/web/tests/native-p3-android-compat.test.mjs` 加入 CI 源码契约回归。

### 原版共存安全

新增 Gradle `nativePreview` 构建类型：
- **独立** `applicationId=com.mikuchin.client.nativepreview`，应用显示名 `Mikuchin Native Dev`，`versionName=0.3.0-native-preview`。
- APK 采用 Android 调试证书签名（APK v2 校验通过），**不使用/更改正式版发布证书**。
- Android app sandbox/Keystore、用户态 Tailscale 状态和 Login profiles 与正式 app 自然分离；tsnet 节点名 `mikuchin-native-android`，避免占用稳定版节点身份。
- 单独脚本 `frontend/android/build-native-preview.ps1`：显式准备 JDK17、SDK34、Gradle8.7、AAR 后执行 `testNativePreviewUnitTest + assembleNativePreview`；不调用正式版 `build-apk.ps1`，不输出/覆盖 `Mikuchin.apk`。
- 本机**实构建成功**，APK 约 **11.45 MB**，SHA-256 `0F579B77ECC233F32C18B84B52622CCD14F050C005D913692F0397A5460738E5`，`apksigner verify` 成功，`aapt dump badging` 返回独立包名/版本/标签。使用已存在的工具链作只读编译依赖；所有产物在 Native 开发工作区生成。

**真机未验证**：ADB 仅报告 `emulator-5554 offline`，没有可访问的实际 Android 设备。本轮没有擅自安装到手机；仍需用户在手机上安装此**独立预览包**，使用 Native Gateway 独立 Key，并分别测试局域网/Tailnet 或 HTTPS 下的真实页面、SSE、画廊和资源加载。

## 4. Windows Tauri 开发 NSIS 预览

- Native Tauri app identifier 继续为 `fun.zakee.mikuchin.native-dev`，与正式版隔离。
- 强化 `project_root`：优先显式 `MIKUCHIN_NATIVE_HOME`，再查找 EXE 所在实际目录的 Native backend；只在 **debug_assertions** 构建中保留 Cargo 编译时源码目录回退。**Release 不得静默依赖开发机源代码路径**。
- Native runtime 根支持独立 `MIKUCHIN_NATIVE_RUNTIME_HOME`（必须实际存在 `.venv/Scripts/python.exe`），或 Native 工作树的兄弟目录 `mikuchin-native-runtime`，或工作树内部 `runtime` 目录。仍不迁移/复制 main 的运行数据。
- `scripts/build-native-preview-installer.ps1` 在图像队列空、GPU 锁空闲、模型不在生成和 Gateway 请求计数 `active=0` 后，安全停止独立试用启动器、执行 `tauri build --debug --bundles nsis`，无论构建成功与否都恢复 Native 试用任务。正式 15239 不接管。
- **本机真实构建成功**：`Mikuchin Native Dev_0.3.0_x64-setup.exe`，约 **5.06 MiB**（5,311,801 字节），SHA-256 `5266A758BFB44208A2BB5051A86D8EE23A7F5292FA93E6DA2E073101E30689E3`。Native 试用启动器已重新拉起，重新监听 15249/15240。
- 本安装包**仅含 Windows 启动器，不包含**官方/Native backend、Python venv、GGUF、sd-cli、Real-ESRGAN、数据、密钥，因而**不是可直接跨机器使用的完整发布包**。本轮没有安装或卸载正式版、没有制造标记为生产版的 Release。未来应单独解决可搬迁 Python/官方 GPU runtime、首次安装引导、模型路径注册、运行时完整性校验、增量升级与自动回滚。

## 5. 预览产物完整性清单与限制

`scripts/stage-native-p3-preview.ps1` 将两个开发安装包复制到独立 `mikuchin-native-runtime/p3-preview-artifacts`，生成 SHA-256 manifest 和明确的 README。该清单**不是签名的安全更新 feed**；版本数字仍按 `versions.json`：主程序 0.3.1、Launcher 和 Android 0.3.0，未主动改版、Tag、GitHub Release 或灰度替换 main。

## 6. 不应误报完成的 P3 项目

1. 永久独立 Tunnel 的远程 hostname / Token / 连接器实际运行及公网真机访问，尚待用户 Cloudflare 配置。
2. Android 真机独立 APK 安装、Tailscale 用户授权及实机 Chat/SSE/图像/画廊测试，尚待手机在线。
3. Windows Python/backend/模型/生图运行时**可搬迁发行**与安装后更新/回滚，尚未实现；本次 NSIS 仅打通 launcher 安装构建。
4. macOS/iOS 平台的原生发布构建尚未进行；不以 Win10 Tauri + Android 预览替代 Apple 平台验收。
5. 原版 main 暂不切换，保留完整 P0/P1/P2/P3 差异表；用户已明确正文独立 Token 上限**暂不列为当前 P3 阻碍**。
