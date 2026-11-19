# Mikuchin Android Client (`frontend/android`)

独立的安卓手机客户端工程，**完全不修改 `frontend/web` 网页端与 `backend/polystrata` 后端推理引擎**，内置用户态 Tailscale (`tsnet`) 网络，无需 Android `VpnService`，可与 Clash Mi / Mihomo 等系统 VPN 并存。

## 目录结构

- `tsnetbridge/`：Go 编写的用户态 `tailscale.com/tsnet` 模块（通过 `gomobile bind` 编译为 `app/libs/tsnetbridge.aar`）：
  - 提供用户态 Tailnet 节点（默认节点名 `mikuchin-android`，持久化在应用私有 `noBackupFilesDir/tailscale/tsnet-node`）。
  - 针对 Android 11–15（含 HyperOS）SELinux `netlink` 限制内置 `androidSafeInterfaces` UDP 路由探测回退。
  - 提供仅绑定 `127.0.0.1` 随机端口的本地 SOCKS5 服务与带随机 Session Token 鉴权、即时流式刷新（`FlushInterval: -1`）的本地 HTTP 反向代理。
- `app/src/main/java/com/mikuchin/client/SecureStore.kt`：基于 Android Keystore (`AES/GCM/NoPadding`) 的 API Key 加密存储。
- `app/src/main/java/com/mikuchin/client/ConnectionProfiles.kt`：多入口（名称、直连/Tailscale、接口、独立加密 API Key、SSID 记忆）、旧地址迁移及安全回退顺序。
- `app/src/main/java/com/mikuchin/client/TailscaleController.kt`：管理 `tsnetbridge` 生命周期、系统网络切换回调（`ConnectivityManager.NetworkCallback`）以及 Kotlin 原生请求与 WebView 的统一网络入口。
- `app/src/main/java/com/mikuchin/client/MainActivity.kt`：原生 Android WebView 容器、调用源校验的 `MikuchinAndroid` JS 桥接及外部链接拦截。
- `app/src/main/assets/login.html`：本地亮色**纵向入口选择页**，支持自动连接、手动点选、添加/编辑/删除入口、可选绑定 Wi-Fi SSID，以及原有 Tailscale 网页授权。
- `app/src/main/assets/android-shell.css` & `android-shell.js`：连接成功后仅在 Android 客户端内动态注入的亮色移动端布局与交互层：
  - **原版亮色主题**（薄荷绿 `#39C5BB` 主色）。
  - **连接后直达最近一个 Chat 会话界面**（按服务端 `/v1/strata/sessions` 的最新 `updated` 时间自动定位）。
  - **全局常驻左上角控制栏**（`☰ 历史`）与**无外框底部 5 按钮**（`图像`、`角色`、`设置`、`监控`、`关于`）。
  - **设置页管理**：支持「切换入口」、修改 `接口` / `key` 重连与断开，以及查看 Tailscale 节点名、IP、连接状态并执行重新连接或退出登录。

## 多入口与 Wi-Fi 网络记忆（开发预览）

1. 每次冷启动先呈现入口列表；自动连接默认开启，4 秒后按当前 SSID 绑定入口 → 已认证的私有/HTTPS 入口顺序探测。用户点按或滑动会取消倒计时，可以直接点击入口连接。
2. 点击「添加入口」，填写自定义名称、直连（含 Cloudflare HTTPS）或 Tailscale 地址、对应 API Key，再保存或连接。已有单直连和 Tailscale 地址会迁移为两个入口，不清空会话或用户密钥。每个入口的密钥单独用 Android Keystore 加密。
3. 编辑已保存入口，点击「绑定当前 Wi-Fi」后才会按需申请 Android 精确位置权限。读取 SSID 还需要系统定位开关；没有权限/无法识别时保持手动入口和安全回退可用。
4. **SSID 只用来决定候选顺序，不能证明服务器身份。** 为防止陌生 Wi-Fi 中出现相同私网 IP 的冒充设备，**未命中用户绑定 SSID 时不自动向明文 HTTP 局域网地址发送 Key**；仅尝试用户已保存的 Tailscale/HTTPS 入口。局域网仍可手动点选。
5. 选择入口前检查 `/health`，再使用该入口自己的 Key 验证 `/v1/strata/sessions`，通过后才切入 WebView。自动候选串行执行，手动选新入口可使旧尝试失效；切换网络不会强制重载正在使用的会话。

开发预览的 APK 与官方同为 `0.2.10 / versionCode 210`，尚未升级正式版本或覆盖 GitHub v0.2.10 Release；请使用本地 `Mikuchin-connection-preview-v0.2.10.apk` 测试。

## 一键编译方式

在 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build-apk.ps1
```

产物输出路径：`E:\LLM\deploy\mikuchin\frontend\android\Mikuchin.apk`
