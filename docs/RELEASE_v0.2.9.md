# Mikuchin v0.2.9 — API 生图与统一画廊

## 发布范围（2026-11-16）

本版最初仅发布主程序 0.2.9；**2026-11-16 同版本补发**时，根据画廊在 Android 导航中的入口缺失问题，重新构建 Windows Launcher 0.2.9 和 Android 0.2.9（versionCode 209），三轴统一至 0.2.9。保留既有 v0.2.9 Release 页面，Tag 随补发提交更新，旧版下载者应重新下载。

| 组件 | 当前发布 | 是否更新 | 说明 |
|---|---|---|---|
| Mikuchin Main | **0.2.9** | 是 | 独立源码 ZIP 含最新版前后端；部署时依原有 README 配置 Python/模型 |
| Windows Launcher | **0.2.9** | 是 | 重新构建 Tauri 便携 EXE 与 NSIS 安装包；不再使用 v0.2.8 二进制 |
| Android | **0.2.9 / 209** | 是 | 重新构建并用既有证书签名，升级保持相同应用 ID 和签名证书 |
| Windows CUDA SM86 推理引擎（可选） | **0.2.8** | 否 | 不重命名旧版可执行文件，详见此前发布 |

## 主要改动

### OpenAI-compatible 图像 API

- 在「设置」维护多个外部图像生成服务：服务名、Base URL、API Key、模型 ID、可选代理 URL、参考图和扩展参数能力。
- 支持通过 `GET /models` 自动探测可选模型 ID；探测仅按名称/元数据初筛，不保证模型可调用图像 API。
- 图像页和聊天内置生图工具可选择远端服务，支持 `/images/generations` 文生图与兼容 `/images/edits` 的参考图编辑。
- 支持多参考图上传和按提供商能力降级为首图或不使用参考图；支持带代理请求。
- API 生图可手动启用本机 Real-ESRGAN 4× 超分（默认关闭），超分失败仍保留原图；本地与远端生成状态显示阶段、耗时及错误。
- API Key 保存在本机服务端私有配置文件，不返回前端；**当前配置文件仍为磁盘明文**，用户需保护文件访问权限。使用云端模型会发送当前提示词/实际参考图，并可能计费。

### 统一画廊

- 顶栏「图像」改为「生图」，新增「画廊」；索引涵盖本地/API、聊天内生图/独立生图，首次进入时补录历史作品。
- SQLite 索引和 JPEG 缩略图缓存留在被 Git 忽略的 `chat/` 数据目录；生成成功后自动写入索引。
- 支持大图查看、键盘左右切换/ESC 退出、移动端滑动、来源筛选与排序。
- NSFW 展示开关默认关闭，已标记作品模糊遮罩；支持单张和批量手动 NSFW 标记。模型名含 `uncensored` 仅作为初始启发式，不构成内容识别；模糊遮罩也不等于加密。
- 4× 图片及对应原图按一组作品合并展示，缩略图显示带阴影的数量徽标（如 2）；查看器支持单独删除原图或 4× 图，普通删除和批量删除则删除整组。
- **删除不可撤销**：聊天记录若引用被删文件，其图片链接会失效；保存图像前应自行备份。

## 构建与验证

- `versions.json` 为三轴版本唯一来源；运行 `python scripts/versioning.py sync` 与 `check` 核实。
- 画廊 9 项、API 生图 17 项回归测试通过；增加 Android 画廊导航 2 项回归验证；全项目共 **40 项**自动化测试通过，完成 JavaScript 语法、版本及运行路径审计。
- 本地历史目录 17 个图片文件能合并为 10 组作品（7 对原图/超分）；测试在隔离目录中删除模拟图，**未删除用户实际作品**。
- Android 导航增加「画廊」，将「图像」更名「生图」，从五入口改为六入口，保留聊天历史抽屉及当前页面高亮。
- Android 正式签名 APK 已经 `apksigner verify` 通过，签名证书 SHA256 与 v0.2.8 完全一致，`aapt` 确认包名 `com.mikuchin.client`、版本 `0.2.9 / 209`；APK 内包含新的「画廊」与「生图」导航代码。
- Windows Tauri Release EXE 的 PE `FileVersion`、`ProductVersion` 均为 `0.2.9`，NSIS 安装包真实构建成功；已核对单独输出的便携 EXE 与编译产物 SHA256 一致。
- 运行中的启动器锁定了 `portable/Mikuchin.exe`，构建脚本改为保留正在运行的二进制，并安全地输出 `portable/Mikuchin-v0.2.9.exe`；不强行终止主程序/服务。
- 真实付费第三方图像服务可能有非标准参数/尺寸限制；不同厂商需自行测试。

## 发布资产与版本规则

- `Mikuchin-Main-v0.2.9-source.zip`、`Mikuchin-Main-v0.2.9-source.zip.sha256`：本次重新打包。
- `Mikuchin-Launcher-v0.2.9.exe`、`Mikuchin-Launcher-v0.2.9-Setup.exe`：v0.2.9 重新构建的 Windows 便携启动器与 NSIS 安装包。
- `Mikuchin-Android-v0.2.9.apk`：v0.2.9 / versionCode 209，重新构建并使用相同的正式发布证书签名。
- `Mikuchin-v0.2.9-release-manifest.json`：列出实际文件哈希、字节数和三个组件版本。
- CUDA SM86 独立引擎沿用 [v0.2.8](https://github.com/zakee039/mikuchin/releases/tag/v0.2.8) 提供的二进制，不以 v0.2.9 名义重命名发布。

**注意：** 主程序源码 ZIP 不包含模型权重、会话、图片、密钥、虚拟环境或已经安装的推理服务；Windows/Android 客户端仍需连接已部署的 Mikuchin 服务。
