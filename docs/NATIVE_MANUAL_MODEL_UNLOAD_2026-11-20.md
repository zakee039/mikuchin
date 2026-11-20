# Native 启动器：手动卸载模型（2026-11-20）

开发分支 `refactor/official-polystrata-gateway`。**按照最新产品约定，界面叫「卸载模型／加载模型」，底层允许安全停止／启动 Native 整个服务栈。**

## 用户操作语义

- 「总览」主按钮：Native 服务正在运行时显示 **卸载模型**，停止或手动卸载完成后显示 **加载模型**。
- 点击卸载时调用原有 Tauri `stop_service` → `stop_managed` 的**安全停止**协议。Supervisor 处理尚未结束的 Image Worker 请求，不能强制杀死或重复发起付费任务。服务收尾期间按钮禁用、顶部显示「正在卸载」。
- 手动卸载完成后顶部显示「手动卸载」，与官方 PolyStrata 的 **900 秒空闲卸载**（顶部「空闲卸载」）不同。
- 为避免手动卸载马上被自动恢复，`stop_managed(state, true)` 在同一把锁内先写 `desired=false` 且持久化 `manual_unloaded=true`；Tauri 守护器本就只有在 `desired=true` 时自动重启。退出启动器、意外崩溃或再次打开 Tauri 时，`auto_start_service=true` 不能覆盖 `manual_unloaded=true`。
- 点击加载时调用 Tauri `start_service`：清除持久标志，再按原有配置启动 Supervisor、Official Engine、Image Worker、Gateway、已启用的 Tunnel。读取健康状态确认服务真实启动；加载过程中不能再点卸载。
- **普通退出托盘或关闭程序不代表手动卸载**：正常退出调用 `stop_managed(state, false)`，保留用户原本的下次自动启动偏好；仅主动点击卸载按钮才置位手动标志。
- Native GUI 启动器进程在手动卸载后保持运行，但**实际后端 Gateway/Official/Image Worker 会一起暂停**；这意味着 15249/API/Chat 和后台图像新任务入口暂时不可用，下次点击加载才恢复。不能对外宣称「仅卸载模型而保留 API 可用」。这是用户明确允许的简化实现；未来如果需要 API 永久在线，应另行设计仅卸载模型的守护状态而不是伪装。
- 旧偏好文件自动得到 `manual_unloaded=false` 默认值。手动标志仅存 Native 自己的 preferences.json；不修改正式版、端口 15239 或 PolyStrata 官方源码。

## 安全与测试

- Rust `should_auto_start` 测试：首次启动自动加载，手动卸载后阻止自动启动，单独的 UI smoke 有明确豁免；再次手动加载后遵循原有设置。
- Rust JSON 向后兼容测试：旧 preference 不包含 `manual_unloaded` 时默认 false，序列化新标志后恢复 true。
- Native UI 契约测试：按钮只能显示「卸载模型／加载模型」、停止时禁用，且保留空闲卸载与手动卸载两种独立状态。
- 编译测试：`cargo test --lib`；`node --test frontend/launcher/tests/native-shell.test.mjs`；`npm run web:build`；`npx tauri build --debug --no-bundle`。
- 开发版更新前检查没有活跃的图像任务、付费请求和 GPU 锁；正式端口 15239 不受影响。

## 本机真实端到端验证

- 更新前确认本机图像任务的运行数为 0、没有 queued/working/running 记录、GPU 锁空闲、官方引擎并未执行推理，然后以 `npx tauri build --debug --no-bundle` 构建并启动桌面试用版。
- 使用 Windows UI Automation **直接调用真实 Tauri 窗口中的「卸载模型」按钮**（不是测试程序仿造的回调），确认 Native preferences.json 中 `manual_unloaded=true`、Gateway 15249 和 Official 15240 不再监听，而启动器进程继续运行。
- 额外等待 8 秒，确认 Tauri Watchdog **没有重启**三进程。
- 重新启动 Tauri 开发启动器，`auto_start_service=true` 设置保持，但持久 `manual_unloaded=true` 阻止 Native 栈启动：15240/15249 依然不监听，UI 显示「加载模型」按钮。
- 用 UI Automation 调用「加载模型」，确认 `manual_unloaded=false`、Supervisor `phase=running`、Official Engine / Image Worker / Gateway 均出现真实 PID，15240/15249 恢复监听；开发版留在可用状态。
- 检查范围为本机试用版；**本轮未打 NSIS、更新 Android 或发布 Release**。
