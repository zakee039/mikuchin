# Mikuchin 版本历史（Release Index）

此文件提供**跨对话、跨设备的持久版本记录**。产品实际版本以根目录 `versions.json` 为准；发行状态以 [GitHub Releases](https://github.com/zakee039/mikuchin/releases) 为准。

| GitHub Release | 日期（UTC） | 主程序 | Windows Launcher | Android / versionCode | 内容 |
|---|---|---|---|---|---|
| `v0.2.8` | 2026-11-13 | **0.2.8** | **0.2.8（重新构建）** | **0.2.8 / 208（重新构建、签名）** | 上游增量移植、Gemma 并发和视觉修复、CPU 自动线程、WDDM 查询、Responses 时序、全部版本轴重建；详情见 `docs/RELEASE_v0.2.8.md` |
| `v0.2.7` | 2026-11-13 | 0.2.7 | 0.2.4 | 0.2.4 / 204 | 独立源代码仓库，无 PolyStrata submodule |
| `v0.2.6` | 2026-11 早期 | 0.2.6 | 0.2.4 | 0.2.4 / 204 | 主程序更新，启动器与安卓保持不变 |

## 下次开始开发或发布时的第一步

```powershell
python scripts/versioning.py status
python scripts/versioning.py check
gh release list --repo zakee039/mikuchin --limit 5
git status --short --branch
```

`versions.json` 标识源码目标版本，但只有 GitHub Release 与相应正确构建的安装文件存在，才能宣称对应版本已正式发布。发布完成后，真实资产和 SHA256 应记录在 `docs/RELEASE_v0.2.8.md` 和 Release 的资源清单中。

**注意：** 三个组件可能有各自的后续版号。Git tag 使用主程序的发布版本，不强制要求以后都同步升版；但所有版本信息必须来自唯一 manifest，且和实际二进制一致。
