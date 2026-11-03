# Mikuchin Android Client (`frontend/android`)

独立的安卓手机客户端工程，**完全不修改 `frontend/web` 网页端与 `backend/polystrata` 后端推理引擎**，内置用户态 Tailscale (`tsnet`) 网络，无需 Android `VpnService`，可与 Clash Mi / Mihomo 等系统 VPN 并存。

## 目录结构

- `tsnetbridge/`：Go 编写的用户态 `tailscale.com/tsnet` 模块（通过 `gomobile bind` 编译为 `app/libs/tsnetbridge.aar`）：
  - 提供用户态 Tailnet 节点（默认节点名 `mikuchin-android`，持久化在应用私有 `noBackupFilesDir/tailscale/tsnet-node`）。
  - 针对 Android 11–15（含 HyperOS）SELinux `netlink` 限制内置 `androidSafeInterfaces` UDP 路由探测回退。
  - 提供仅绑定 `127.0.0.1` 随机端口的本地 SOCKS5 服务与带随机 Session Token 鉴权、即时流式刷新（`FlushInterval: -1`）的本地 HTTP 反向代理。
- `app/src/main/java/com/mikuchin/client/SecureStore.kt`：基于 Android Keystore (`AES/GCM/NoPadding`) 的 API Key 加密存储。
- `app/src/main/java/com/mikuchin/client/TailscaleController.kt`：管理 `tsnetbridge` 生命周期、系统网络切换回调（`ConnectivityManager.NetworkCallback`）以及 Kotlin 原生请求与 WebView 的统一网络入口。
- `app/src/main/java/com/mikuchin/client/MainActivity.kt`：原生 Android WebView 容器、调用源校验的 `MikuchinAndroid` JS 桥接及外部链接拦截。
- `app/src/main/assets/login.html`：未登录时的本地亮色连接页（支持 **直接连接 / Tailscale** 切换、交互式 OAuth 授权、`接口 []` 与 `key []` 独立验证）。
- `app/src/main/assets/android-shell.css` & `android-shell.js`：连接成功后仅在 Android 客户端内动态注入的亮色移动端布局与交互层：
  - **原版亮色主题**（薄荷绿 `#39C5BB` 主色）。
  - **连接后直达最近一个 Chat 会话界面**（按服务端 `/v1/strata/sessions` 的最新 `updated` 时间自动定位）。
  - **全局常驻左上角控制栏**（`☰ 历史`）与**无外框底部 5 按钮**（`图像`、`角色`、`设置`、`监控`、`关于`）。
  - **设置页管理**：支持修改 `接口` / `key` 重连与断开，以及查看 Tailscale 节点名、IP、连接状态并执行重新连接或退出登录。

## 一键编译方式

在 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build-apk.ps1
```

产物输出路径：`E:\LLM\deploy\mikuchin\frontend\android\Mikuchin.apk`
