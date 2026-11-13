# Mikuchin 版本历史（Release Index）

此文件提供**跨对话、跨设备的持久版本记录**。产品实际版本以根目录 `versions.json` 为准；发行状态以 [GitHub Releases](https://github.com/zakee039/mikuchin/releases) 为准。

| GitHub Release | 日期（UTC） | 主程序 | Windows Launcher | Android / versionCode | 内容 |
|---|---|---|---|---|---|
| `v0.2.8` | 2026-11-13 | **0.2.8** | **0.2.8（重新构建）** | **0.2.8 / 208（重新构建、签名）** | 上游增量移植、Gemma 并发和视觉修复、CPU 自动线程、WDDM 查询、Responses 时序、全部版本轴重建；详情见 `docs/RELEASE_v0.2.8.md` |
| `v0.2.7` | 2026-11-13 | 0.2.7 | 0.2.4 | 0.2.4 / 204 | 独立源代码仓库，无 PolyStrata submodule |
| `v0.2.6` | 2026-11 早期 | 0.2.6 | 0.2.4 | 0.2.4 / 204 | 主程序更新，启动器与安卓保持不变 |

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

`versions.json` 标识源码目标版本，但只有 GitHub Release 与相应正确构建的安装文件存在，才能宣称对应版本已正式发布。发布完成后，真实资产和 SHA256 应记录在 `docs/RELEASE_v0.2.8.md` 和 Release 的资源清单中。

**注意：** 三个组件可能有各自的后续版号。Git tag 使用主程序的发布版本，不强制要求以后都同步升版；但所有版本信息必须来自唯一 manifest，且和实际二进制一致。
