# Mikuchin v0.5.2 — Hybrid Chat API & Image Compatibility

2026-11-26。主程序、Windows Launcher、Android 统一为 0.5.2（Android versionCode 502）；官方 PolyStrata 保持 v0.1.45-poly.10。

- 混合聊天：会话级本地/在线模型选择，OpenAI Chat Completions 流式及非流式、视觉和原生生图工具，独立聊天服务配置、获取模型列表、可选输出 Token。Windows API 凭据 DPAPI 加密。已提交任务锁定原服务配置，禁止自动切换或重试收费请求。
- 图像 API：参考图原始格式，64 KiB Chunked multipart 与可切换定长上传，Medium/JPEG 默认值、连接/读取超时配置、网络阶段诊断、完整脱敏错误详情及审核拒绝/服务异常等分类。
- 桌面与移动端统一 Enter 换行、Shift+Enter 或按钮发送，输入法确认不触发发送。
- Supervisor：本机独立管理端点、专用 DPAPI 管理凭据、严格空闲门槛及 Windows 扩展路径 SQLite 兼容。正常重载仅更新 Gateway 与 Worker，不重启官方引擎。

## 发行边界

源代码 ZIP 不包含模型、用户数据、密钥或运行环境。Windows 安装包仅启动器，Android 为连接 Gateway 的客户端。真实供应商能力取决于其协议实现；未发起额外收费验证请求，未进行 Android 真机安装测试。

## 构建验收

- Python 190/190、Web 103/103 测试通过；完整回归修复 standalone 测试入口相对导入问题。
- Windows Tauri Debug EXE 与 NSIS 实际编译，文件版本 0.5.2。
- Android `testReleaseUnitTest assembleRelease` 成功，包名 `com.mikuchin.client`，0.5.2/502，APK v2 签名有效且与 0.5.1 证书一致。
- 源码及资产哈希参见 Release manifest。
