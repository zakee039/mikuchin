# Native 本机安全重载管理接口

## 使用

Supervisor 在 `127.0.0.1` 随机可用端口监听，真实端口由私有运行目录的 `supervisor-status.json` 中 `admin_port` 提供，不经过公网 Gateway 15239、CF Tunnel 或 Tailscale。仅接受本机 HTTP、独立管理凭据或明确提供的 Mikuchin Bearer Key，并拒绝 Origin / Forwarded 等代理头；不提供 CORS 或 force 模式。

在项目根目录执行：

```powershell
runtime\.venv\Scripts\python.exe scripts/native-admin.py eligibility
runtime\.venv\Scripts\python.exe scripts/native-admin.py reload
```

Windows Supervisor 每次启动生成独立的随机管理凭据，以当前 Windows 用户 DPAPI 加密保存为 `native-admin-credential.dpapi`，绑定运行目录、Supervisor PID 和管理端口。CLI 自动使用该专用凭据，无需解锁桌面或输入聊天 API Key；不读取原有用户密钥，不打印任何凭据。该凭据仅能访问回环管理端口，不能访问 Gateway、聊天或生图，正常停机删除，旧进程凭据不能用于新进程。显式 `MIKUCHIN_GATEWAY_API_KEY` 环境变量仍可选；非 Windows 需显式鉴权。请在本机可信账户及可信运行目录中操作，不向公网转发管理端口。

## 协议

- GET `/admin/reload-image-api-stack/eligibility`：当前能否安全重载及阻碍原因。
- POST `/admin/reload-image-api-stack`：空请求体，202 + `operation_id` 表示接受检查，而非重载成功。重复执行或短时间连续执行返回 409/429。
- GET `/admin/operations/{operation_id}`：`queued/checking/reloading/done/blocked/failed`，最后三种为终态。仅保留最近一次操作。

Supervisor 主循环先检查所有进程、健康状态及独立 Worker 心跳，通过只允许私有 upstream Key 的本机内部命令冻结 Gateway 新 POST，再检查活动 HTTP 请求、推理、GPU、图像队列、Native Turn 和 SQLite 状态；有活动或状态未知直接拒绝。成功后复用私有 STOP → SQLite 备份/WAL 检查 → Worker/Gateway 启动的原有恢复流程，不重启官方引擎。失败时保留原有隔离机制，不强杀、不自动重放付费请求。管理口与 Supervisor 生命周期一致；首次启用需要一次正常启动器卸载/加载。

## 验证

`python -m unittest backend.gateway.test_admin_control backend.gateway.test_supervisor backend.gateway.test_app -q`：39 项通过；隔离 Mock 三进程验证无鉴权与代理请求被拒绝、冻结入口拒绝新 POST、GPU 活动时阻止重载、正常重载保留官方 PID 并更新 Worker/Gateway PID、SQLite 备份存在。不是收费 API 实测。

## 免交互管理验证

Windows 隔离 Supervisor 实测专用凭据与普通 Gateway Key 不同，管理端点接受，Gateway 拒绝；Origin 请求拒绝，错误端口 DPAPI 绑定拒绝解密，CLI 无环境变量时可检查安全门并完成受控重载。
