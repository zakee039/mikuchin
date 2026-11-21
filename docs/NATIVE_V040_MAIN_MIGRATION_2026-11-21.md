# Mikuchin v0.4.0：old-mixed → Native main 正式源码迁移

日期：2026-11-21。用户明确要求原设计直接迁移，Mikuchin 版本 **0.4.0**，**PolyStrata 固定 v0.1.45-poly.10**，保留原版完整回退。不可把当前仅含启动器的 Windows NSIS 误称为全套自包含安装包。

## Git 备份与最新提交

- 旧版 `main` 原本保留了本地未推送提交 `5dde9ac`（图像任务调用起点计时），已经完整改名并推送为 `old-mixed`；随后 `old-mixed` 新增 `79f9332`，将旧版默认端口改为 `25239`。
- 原仓库 `E:\LLM\deploy\mikuchin` 仍对应 `old-mixed`，源码和全部文件完整保留。**原版的 KV 快照与付费任务不得自动迁移重放。**
- 新版工作树 `E:\LLM\deploy\mikuchin-native` 保留完全未修改的官方 PolyStrata 子模块 `3e1642161198c50ff1abed4046f4e4f476099dbb`，标签 `v0.1.45-poly.10`。

## 迁移用户数据（原数据只读，先备份后合并）

- 旧版数据仓库 `character\character_cards.sqlite3`, `chat\conversations.sqlite3`, `chat\gallery-index.sqlite3` 的三份源数据库，以及 Native 迁移前三份目标数据库，均用 `sqlite3.Connection.backup` 备份到
  `E:\LLM\deploy\mikuchin-native-runtime\migration-backups\old-mixed-20261121`。
- `scripts/migrate-mixed-data-to-native.py` 使用目的数据库 `INSERT OR IGNORE`，拒绝冲突记录/错误文件，检查原 PNG 头部及复制后 SHA256，**不覆盖**新版本已有对话/图库。
- 本机迁移结果：角色卡 **2**，角色会话绑定原版 **28** 条（Native 原有 7 条一起保留，合计 35），聊天 **11** 会话（528 条带 `role/text/images/files` 字段的消息），画廊作品记录 **87** 条及 PNG 87 张、209,972,312 字节；Native 原有 5 条作品保留，合计 **92** 条。
- 另外 SHA256 确认将旧 `character/miku` 四个维护的世界书/YAML/Markdown 文件复制至 Native 的 `character/miku`。
- 原旧版图片任务表 58 成功/42 失败不复制执行状态、不自动重试；模型切换时不导入 KV 缓存，必要时重新 prefill。
- Python `CharacterStore/ConversationStore/Gallery` 真实读取 2/11/92 成功；Gateway 真实 Bearer API `/v1/strata/characters`、`/v1/strata/sessions`、`/v1/mikuchin/gallery` 同样为 2/11/92，未修改原库。
- `old-mixed` 与 Native 的运行设置及 DPAPI 加密凭据，切换前额外备份在
  `migration-backups\old-mixed-20261121\settings-and-secrets-before-cutover`（不进入 Git）。

## 端口与旧版保全

- 旧版 `old-mixed` 的代码默认端口已改 `25239`，本机 `%LOCALAPPDATA%\Mikuchin\settings.json` 也更新为 `25239`，并关闭旧版 `cf_enabled/autostart`，从 HKCU Run 中仅移除旧版 `Mikuchin` 自动启动项。
- 在旧版模型 `paused/loaded=false` 且旧图像待处理为 0 时，安全检查后退出旧版 Launcher 和全部自有子进程。旧版实际程序停止监听 `15239`，设置、密钥、原始作品、聊天和 Git 分支保持可回滚。
- 新版调试启动器已经通过独立计划任务重新启动，**Gateway `0.0.0.0:15239`**、官方引擎 **`127.0.0.1:15240`**。Native Supervisor 将 **25239 设为 old-mixed 保留端口**。Native `cf` 指标为 3 条 Tunnel 连接，图像 Worker 正常，任务与 GPU 独占锁空闲。
- Native prefs `%LOCALAPPDATA%\MikuchinNativeLauncher\preferences.json` 明确指定 `model_config=official-sm86-model-test.json`、`idle_unload_s=900`。发现 PowerShell Windows 5.1 的 UTF-8 BOM 会使 `serde_json::from_slice` 报错，已改用**无 BOM UTF-8**写回，当前 Native Tauri 服务成功拉起。以后迁移工具必须避免 BOM。

## Cloudflare Tunnel 与现有客户端 Key

- 只复制旧版 `cf-tunnel-token.dpapi` **加密字节**到 Native 独立 `native-cf-tunnel-token.dpapi`，不输出/保存 Token 明文。沿用已配置的 `key.zakee.fun`，旧版 Connector 停止后才启用 Native Connector，**绝不能两个 Connector 同时占用同一远程 Tunnel**。
- 为尽量维持现有远程设备连接，Native 改用旧版 `api-key.dpapi` 的**加密副本**，旧 Key 原文件、切换前 Native 独立 Key 均已经备份；在 Tauri API 页按用户要求直接显示 Key 并提供「复制」「更换」按钮。
- 本机真实浏览器/HTTP API：回环 `127.0.0.1:15239`、WLAN `172.26.193.25:15239`、Tailnet `100.96.190.44:15239`、公网 `https://key.zakee.fun` 的**带 Bearer Key 会话 GET 均返回 11 个会话**。公网不带 Key 的 `/health` 返回 Native 独有 JSON 401。**不能将本机多网卡访问当作 Android 真机访问**。

## 原版精心设计的 UI 复刻

使用与 old-mixed **完全相同 SHA256** 的旧启动器 `style.css`，不引入新风格；保留 440×650 客户区/4 标签总览/API/设置/原生状态。迁入旧 `i18n.ts` 以启用 zh-CN/en-US/ja-JP：

- 关于页引擎展示 `PolyStrata v0.1.45-poly.10`（独立 Gateway `official_polystrata_release` 字段），不改官方子模块。
- 总览将「选择配置文件 ▾」「查看」移回原版位置，配置文件选择弹窗支持查看、使用和通过系统文件选取器注册 JSON。设置中不再重复放模型注册输入和说明。
- API Key 展示可见的 Key 文本（用户明确要求）以及复制/更换操作，同一行，无冗余解释。
- CF Tunnel 设置沿用域名/Token/安装/测试/重启布局，不额外添加旧版没有的切换控件；Native 真实状态及公网延迟独立读取。旧版 LAN 卡片及真实 Tailscale/WLAN 地址显示保留。
- 设置页恢复「启动与守护」「全局语言」「空闲卸载时间」原版三卡式（分钟输入+保存并重启），后台 Native `get_native_language/set_native_language` 与 Gateway 授权持久语言 API 真实连接。
- 用户要求的「原生状态」页保留只读监控。Chat 不再增加之前用户明确要求删除的两个按钮。

## 构建与质量边界

- `versions.json` 三端统一 v0.4.0，Android versionCode400，`python scripts/versioning.py sync/check` 验证 13 个版本来源。
- Windows Debug Tauri/NSIS `Mikuchin Native Dev_0.4.0_x64-setup.exe` 真正编译通过、已经嵌入前端资源并在本机运行；仅包含启动器**不包含完整运行环境和模型**。
- Android `com.mikuchin.client.nativepreview` v0.4.0 预览包已构建；另用旧版签名配置**仅在本机临时使用**，成功构建 `com.mikuchin.client` **v0.4.0/versionCode400 正式包名 APK 升级候选**，APK v2 校验通过，**与 old-mixed v0.3.0 原 APK 的 SHA256 证书指纹一致**。签名配置文件恢复为 Native 原配置，未把签名材料放入 Git。候选在 `E:\LLM\deploy\mikuchin-native-runtime\migration-release-candidates\Mikuchin-Android-v0.4.0.apk`。
- 无 Android 真机 ADB 设备在线；不声称实机安装升级/性能已通过。未创建完整 Windows 跨机器可搬迁 Runtime、安装后自动升级/回滚，也未正式公开 GitHub Release。

## 迁移回退

保留 `old-mixed` 工作树及 Git 远程分支、全部源数据库/图片和迁移前设置/DPAPI 备份。若需要回退：
1. 仅在 Native 图像任务和 GPU 锁均空闲时，**先**通过 Native Launcher 安全卸载模型/退出 Native 自有 Tunnel；验证 15239 释放。
2. 从备份还原 old-mixed 的 `settings.json` 和 HKCU Run 偏好，旧 Key/Token 从其原文件读取，重新启动 old-mixed 的 Launcher/服务于旧端口。
3. 不合并/覆盖 `old-mixed` 的 SQLite 和 GPU 缓存，也不要把 Native 的新会话直接回灌旧版。独立 `25239` 始终可用作不占 15239 的调试回退端口。
