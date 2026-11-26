# Mikuchin v0.5.3 — PolyStrata Engine Upgrade

2026-11-26。主程序、Windows Launcher、Android 统一为 0.5.3（Android versionCode 503）。

- 官方 PolyStrata `v0.2.20-poly.5` / `d62dfacbe185dfbb447e79c5fb1091ae189afc64`，保持官方源码零修改。
- 适配新版 terminal/serve 布局、启动器、版本显示、CI 和传输验证；保留旧版回退路径。
- 官方预编译包 SHA256 校验、真实 MeroMero 推理/SSE/视觉/自动工具调用/KV 交接测试通过；不把单轮测试视作稳定性能增益。
- 正式环境已在 0.5.2 产品号下完成新引擎切换，五份数据库完整性及数据行数一致。独立管理接口鉴权与安全门已验证。
- RAM Prefix Cache 暂未接入。旧 `v0.5.2` GitHub Tag/Release 保留。

详细迁移记录：`docs/NATIVE_POLYSTRATA_V0220_MIGRATION_2026-11-26.md`。

## 构建验收

- 14 项版本同步校验与 103 项 Web 回归通过。Windows EXE、NSIS 文件版本均为 0.5.3，Android APK 包名 `com.mikuchin.client`、版本 0.5.3 / 503，签名有效且与 v0.5.2 一致。Android 未真机安装测试。
- 构建文件已保存至 `dist/release/`，发行状态以 GitHub Release 为准。

## Source bundle availability / 源码包说明

完整（含官方子模块）源码 ZIP 生成期间，本机安全软件隔离了官方 PolyStrata 的集成测试脚本 `terminal/integrations/harness/tool_flow_e2e.py`（TrojanDownloader/Python.NetLoader.o）。目前未确认误报；不恢复、执行或重新分发该文件。官方子模块指针保持原始 release SHA，Mikuchin GitHub 自动生成的源码归档不包含子模块文件。此次仅上传独立构建的 Windows Launcher EXE/NSIS、Android APK 与三项资产校验清单；完整源码 ZIP 及其校验文件暂缓发布。已有引擎升级与隔离测试不等于安全认证。
