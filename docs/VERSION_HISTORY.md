# Mikuchin 版本历史（Release Index）

此文件提供**跨对话、跨设备的持久版本记录**。产品实际版本以根目录 `versions.json` 为准；发行状态以 [GitHub Releases](https://github.com/zakee039/mikuchin/releases) 为准。

| GitHub Release | 日期（UTC） | 主程序 | Windows Launcher | Android / versionCode | 内容 |
|---|---|---|---|---|---|
| `v0.5.2` | 2026-11-26 | **0.5.2** | **0.5.2** | **0.5.2 / 502** | 混合聊天 API、获取模型、图像 API 兼容与错误分类、统一换行键、安全重载。详见 `docs/RELEASE_v0.5.2.md`。 |
| `v0.5.1`（健康守护修复） | 2026-11-22 | **0.5.1** | **0.5.1（重编译）** | **0.5.1 / 501（重编译、原证书签名）** | Native 健康探测、SQLite 锁异常隔离与安全恢复，活跃收费任务/Turn 保守保护；详见 `docs/RELEASE_v0.5.1.md`。 |
| `v0.5.0`（本次三端同步构建） | 2026-11-21 | **0.5.0** | **0.5.0（重新编译）** | **0.5.0 / 500（重新编译、旧版签名继承）** | 原生 Tool Calling 图片任务、自然开始/完成/失败回复、API 本地运行方式分离、SDXL/Animagine 导入、状态/图像预览与并发聊天体验。官方 PolyStrata 固定子模块不改；主程序源代码 ZIP、Windows Launcher、Android APK 发行说明见 `docs/RELEASE_v0.5.0.md`。 |
| `v0.4.0`（Native 迁移候选，尚未发布） | — | **0.4.0** | **0.4.0（Native NSIS 启动器已构建）** | **0.4.0 / 400（同证书已签名，未实机安装）** | 旧 main 完整保留为 old-mixed，正式推进官方 PolyStrata v0.1.45-poly.10 + Gateway；迁移角色、画廊、会话及 Tunnel，恢复原有启动器设计和版本管理，详见 `docs/RELEASE_v0.4.0.md`。未发布正式安装包或 Release。 |
| `v0.3.1`（待发布） | — | **0.3.1** | **0.3.0（沿用，无需重建）** | **0.3.0 / 300（沿用，无需重建）** | 生图任务失败后点击重试：新任务成功创建时，原失败记录在同一数据库事务内删除；成功记录重试仍保留原记录。前端立即移除已销毁记录，失败提交不丢失原任务。保留 v0.3.0 架构基线，见 `docs/RELEASE_v0.3.1.md`。 |
| `v0.3.0`（待发布） | — | **0.3.0** | **0.3.0（本次重新构建）** | **0.3.0 / 300（本次重新构建并核验签名）** | **官方 PolyStrata + Gateway 重构前的功能基线**。本次不替换现有引擎；整合 v0.2.10 后尚未发布的网络诊断、任务计时、画廊/移动端修复，并制定未来架构迁移方案；见 `docs/RELEASE_v0.3.0.md` 与 `docs/PLAN_OFFICIAL_POLYSTRATA_GATEWAY_v0.3.0.md`。日期及发布状态以实际 GitHub Release 为准。 |
| `v0.2.10` | 2026-11-19 | **0.2.10** | **0.2.10（重新构建）** | **0.2.10 / 210（重新构建、同证书签名）** | 桌面端独立生图与 4x 超分任务、聊天生图断线续跑和会话结果恢复、移动画廊横屏及手势看图、局域网多网卡直连列表；见 `docs/RELEASE_v0.2.10.md` |
| `v0.2.9` | 2026-11-16 | **0.2.9** | **0.2.9（重新构建）** | **0.2.9 / 209（重新构建、同证书签名）** | API 生图、统一画廊/NSFW/分组与批量管理、Android 画廊导航入口、Windows/Android 版本同步；见 `docs/RELEASE_v0.2.9.md` |
| `v0.2.8` | 2026-11-13 | **0.2.8** | **0.2.8（重新构建）** | **0.2.8 / 208（重新构建、签名）** | 上游增量移植、Gemma 并发和视觉修复、CPU 自动线程、WDDM 查询、Responses 时序、全部版本轴重建；详情见 `docs/RELEASE_v0.2.8.md` |
| `v0.2.7` | 2026-11-13 | 0.2.7 | 0.2.4 | 0.2.4 / 204 | 独立源代码仓库，无 PolyStrata submodule |
| `v0.2.6` | 2026-11 早期 | 0.2.6 | 0.2.4 | 0.2.4 / 204 | 主程序更新，启动器与安卓保持不变 |

## v0.2.9 同版本补发记录

- 2026-11-16 最初的 v0.2.9 仅更新主程序，Windows Launcher 和 Android 仍为 0.2.8。
- 随后发现 Android 独立导航抽屉缺少「画廊」入口；按用户要求在同一 v0.2.9 Tag/Release 中重新构建并发布 Launcher 0.2.9、Android 0.2.9 / 209。
- 本次更新 v0.2.9 Tag 指向新提交，重新打包主程序 ZIP 与发布清单，不将 v0.2.8 APK/EXE 重命名为新版。已经下载旧版的用户应重新获取。

## v0.2.8 覆盖发布记录

- **2026-11-13（覆盖现有 v0.2.8）**：修复 Gemma 4 在聊天里输出自闭合
  生图伪调用而没有创建任务的问题，补充工具异常与参数错误反馈，
  见 `docs/IMAGE_TOOL_FIX_2026-11-13.md`。
- 经用户明确要求，重新指向既有 `v0.2.8` Git Tag 并覆盖 Release 中
  的主程序 ZIP、SHA256 及发行清单；不是新创建 v0.2.9 Release。
- 原始 Tag 指向的提交为 `b62a05c3fe43cb74bdd456feb657a3bb2564a37c`；
  新 Tag 指向的提交以后续发布记录为准。已经下载过旧 ZIP 的用户需重新下载。
  Windows Launcher、Android 和可选 CUDA 引擎保持原 v0.2.8 二进制及校验值，
  **本次并未重新编译这些平台产物**。

## 下次开始开发或发布时的第一步

```powershell
python scripts/versioning.py status
python scripts/versioning.py check
gh release list --repo zakee039/mikuchin --limit 5
git status --short --branch
```

`versions.json` 标识源码目标版本，但只有 GitHub Release 与相应正确构建的安装文件存在，才能宣称对应版本已正式发布。发布完成后，真实资产和 SHA256 应记录在对应版本的 `docs/RELEASE_v*.md` 和 Release 资源清单中。

**注意：** 三个组件可能有各自的后续版号。Git tag 使用主程序的发布版本，不强制要求以后都同步升版；但所有版本信息必须来自唯一 manifest，且和实际二进制一致。
