# Mikuchin 正式服务 CPU 专家线程数灰度记录（2026-11-13）

## 改动与边界

本次灰度只在现用 `config/active.json` 的模型 `args` 数组中插入：

```json
"--threads",
"14"
```

- 现用引擎仍为 `backend/polystrata/engine-poly/strata-poly.exe`（**旧版**），未替换原生可执行文件。
- 原配置完整备份于 `%LOCALAPPDATA%\Mikuchin\backups\active_pre_threads14_20261113_0918.json`；
  `config/active.json` 属于 Git 忽略的用户运行配置，修改**不会通过 Git 提交同步**到别的设备。
- `config/active.json` 其余顶层配置键保留，模型文件、上下文大小、专家画像、图像生成配置、
  聊天历史与角色设置均未修改。
- 修改前模型处于 unloaded，手动停留标志 `manual_hold=false`。
- 先通过本机鉴权 API 执行 `POST /unload?wait=30` 确认无需打断推理，再重新启动受 Mikuchin
  启动器守护的 API 服务。原进程 PID 54132，启动器自动恢复后服务 PID 为 38108；
  健康检查通过。
- 再次加载模型后，由原生进程参数及日志同时确认 `--threads 14`、
  `801 of 3840 routed experts in VRAM` 和 `14 CPU threads`。

## 正式服务实测

所有测试都经 `127.0.0.1:15239` 的鉴权 API 访问；本地 Windows DPAPI
密钥仅在临时进程内解密并用于请求，没有出现在日志、命令输出或测试报告中。

| 路径 | 实测 |
|---|---|
| `POST /v1/chat/completions` | 200，1.68s，助手正常结束（输入 27 Token、输出 35 Token） |
| `POST /v1/chat/completions` + function tools | 200，2.41s，`finish_reason=tool_calls`，模型实际生成 1 次 `echo_test` 工具调用（未执行外部操作） |
| `POST /v1/chat/completions` + image_url | 使用程序生成的几何测试图真实走视觉编码器与多模态推理；在 `reasoning_effort=none`、禁用思考后 1.75s 返回 114 字符，正确说明红色方形、蓝色圆形和绿色三角形 |
| `POST /v1/responses` + stream | 200，SSE 9 个 JSON 事件，最后为 `response.completed`，含 Prefill / Decode `timings` 字段 |
| `GET /v1/strata/gpu-budget` | 当前旧二进制返回 `supported=false`，符合预期；此查询需要切换到新候选原生引擎才可用 |

视觉补充：首次 `reasoning_effort=low`、正文预算 96 Token 的测试没有产生正文且以 `length` 结束；
关闭思考、上限 160 Token 后正确产生正文。因此该现象不能归因于 CPU 线程设定，也不表示视觉路径失效。

## 与先前控制实验的关系

完整旧/新二进制 2×2 CPU 线程控制实验及单图和 KV 回归见
`docs/NATIVE_AB_VALIDATION_2026-11-13.md`。
旧引擎固定专家分配时，384 Token 测试中从 20 线程调整到 14 线程：
Decode 39.9 → 46.3 tok/s。该结果并不保证每种模型、输入和时段都会加速。

## 回滚与最终状态

如需恢复，复制上述备份覆盖 `config/active.json`，由启动器**安全停止并重启 API**
让配置重新加载；勿在活跃生成时强行结束推理进程。

实际测试结束后，已通过 `POST /unload?wait=30` 让模型恢复 unloaded，`manual_hold=false`
维持不变，下次请求仍可正常自动加载。API 健康检查 200，NVML 显示 GPU 使用量回到 0 MiB。

本次未更换候选引擎、未发布版本、未测试长时间负载、Cloudflare/Android 客户端
或真实图像生成任务。当前本地配置仍保持 `--threads 14`，后续自动加载将使用它。
