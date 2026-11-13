# Mikuchin 版本与发布规则（仓库级指令）

本仓库从 v0.2.8 起使用 **根目录 `versions.json` 作为唯一产品版本来源**。

每次开始版本相关工作（包括新对话、移植上游、Release、安装包构建），先执行：
```powershell
python scripts/versioning.py status
python scripts/versioning.py check
git status --short --branch
gh release list --repo zakee039/mikuchin --limit 5
```

- `versions.json` 的 release 指当前正在准备/发布的 Git tag，`previous_release` 只是历史标识。
- 产品版本三轴：`components.main.version`、`components.launcher.version`、`components.android.version` 与 `versionCode`，可以独立升版；**本次 v0.2.8 特别统一三者为 0.2.8**。
- 改动版本号时，修改 manifest，然后运行 `python scripts/versioning.py sync` 与 `check`。不得只改 README 或某个代码内的数字。
- 版本历史和实际发布资产见 `docs/VERSION_HISTORY.md`，GitHub Releases 则是**是否真正发布**的最终依据；仓库提交不等于发布。
- Android 必须签名有效且升级证书与旧版一致；版本号变更后必须重新构建 APK。Windows Launcher 必须重新构建 EXE/NSIS；绝不将旧二进制重命名成新版。
- 主程序 Release ZIP 使用 `scripts/package-main-release.py` 打包，必须通过版本校验和干净工作区检查；资源文件、模型、用户对话、密钥及临时构建目录禁止提交或打包。
- PolyStrata 是 vendored 后端源代码（`backend/polystrata`），它自带的旧 `manager` 示例版本 0.1.12 **不是 Mikuchin Launcher 产品版本**，勿全局替换它。
- 提交/打 Tag/上传 Release 之后核验版本、远程 Tag 指向、所有上传资产名称及 SHA256。若任何构建缺失不得宣称所有端均更新完毕。
- 历史实验：`docs/UPSTREAM_PORTS_2026-11-13.md`、`docs/NATIVE_AB_VALIDATION_2026-11-13.md`、`docs/LIVE_CPU14_ROLLOUT_2026-11-13.md`。
