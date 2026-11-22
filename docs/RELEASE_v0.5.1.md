# Mikuchin v0.5.1 — Native Health Watchdog

2026-11-22。主程序、Windows Launcher、Android 统一为 **0.5.1**；Android `versionCode=501`。从 `v0.5.0` 补丁升级，官方 PolyStrata 固定 `v0.1.45-poly.10`，未更改官方源码或 Git 子模块指针。

## 问题与修复

- 原版 Supervisor 仅监听子进程退出；SQLite `locking protocol` 导致 Image Worker 活着但反复失败，Gateway `/health` 因查询任务数据库抛异常而断开，启动器一直处于「启动中」。
- Gateway 健康接口把 Worker 心跳/任务数据库异常隔离为 `degraded`，保持官方 LLM 可达性信息，不假报图像任务数为 0；额外报告活跃推理请求数。
- Image Worker 将活跃任务数和数据库轮询/心跳故障连续计数写入**不包含敏感数据**的原子本地健康快照，SQLite WAL 故障时仍可判定是否存在执行中的任务。
- Supervisor 新增每 2 秒一次的应用层健康检查，连续 3 次失败才考虑恢复。恢复必须通过 GPU 独占、实时 Worker 空闲、图像任务状态、Native Tool Turn、推理活动安全检查；任何未知或忙碌状态都不会强杀 Worker 或重试付费请求。
- 无活跃工作且证据充分时，先通过私有 STOP 协议停 Gateway（阻断新请求），再等待 Image Worker 安全退出；SQLite `quick_check`、在线备份及 WAL checkpoint 成功后，只重启 Gateway + Worker，保持 PolyStrata 引擎及 KV 缓存不变。
- 状态机补充「正在自愈」「服务异常」，附带失败原因、重启计数；限制重复恢复尝试；手动卸载仍禁用自动启动。任何异常不转化为重发供应商扣费请求。

## 验证

- `python -m unittest discover -s backend/gateway -q`
- 隔离 Mock 三进程健康退化注入：验证网关/Worker 自动重建、官方 PolyStrata PID 不变。
- 错误注入 Gateway `/health`：模拟任务库 `sqlite3.OperationalError`，仍 HTTP 200 且标记 `degraded`。
- 安全阻断：存在活跃推理或 Native Tool Turn 时，不重启。
- 版本校验：`python scripts/versioning.py check`；Windows Tauri Debug/NSIS、Android release APK 均由新源码实际编译。

## 发行边界

主程序 ZIP 为源代码分发，不包含模型文件、密钥、SQLite 数据、虚拟环境。Windows NSIS 只包含启动器，非独立模型部署器。Android 客户端仅访问用户配置的 Native Gateway；其版本升级不在手机端安装推理服务。实际生成与签名校验结果以 `dist/release/Mikuchin-v0.5.1-release-manifest.json` 和 GitHub Release 资产为准。

## 三端实际构建验收（2026-11-22）

- Python 完整回归 `157/157` 通过，包含独立 Mock 三进程的连续健康故障注入、安全门验证与 Gateway 数据库退化响应测试。
- Windows Launcher EXE：`Mikuchin-Launcher-v0.5.1.exe`，19,032,064 bytes，SHA256 `1F21FEED52299A10F27D316E01460DB5203A3C27717BF5E00F79D93B3F240D2B`；NSIS：`Mikuchin-Launcher-v0.5.1-Setup.exe`，5,350,695 bytes，SHA256 `058ECC8FC0759DAF64FB90ACAE8DA83A16413E0A1317C266D4B92F5263A65A92`。两个文件版本均经检查为 `0.5.1`。
- Android：`Mikuchin-Android-v0.5.1.apk`，10,116,712 bytes，SHA256 `248E0D0B0714D4A4025AFA041A302B36334D1222A01466987276512C1ADB4E6D`。`testReleaseUnitTest assembleRelease` 通过，`apksigner` 验证 v2 签名有效、证书与 v0.5.0 完全相同；包名 `com.mikuchin.client`，版本 `0.5.1`（501）。
- 本机以启动器私有 STOP 安全关闭旧三进程，备份旧 EXE 后替换为 v0.5.1；重新启动，验证 Gateway 15239、PolyStrata 15240 和 Worker 均就绪。官方模型 `loaded: true`，Worker `active=0 / poll_errors=0 / heartbeat_errors=0`。
- 未实际扣费调用线上生图商；未进行 Android 真机安装测试。以上不代表可以独立在新 Windows PC 安装完整 Python/CUDA/模型环境。