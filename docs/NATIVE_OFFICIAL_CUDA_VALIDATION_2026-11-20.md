# 官方 PolyStrata CUDA 验证记录

> 这是实际的本机实验记录，不是上游的宣传基准，也不是最终端到端客户端验收。

## 复现实验环境

| 项 | 实测或配置 |
|---|---|
| 官方源码 | `simplexai-labs/PolyStrata`，tag `v0.1.45-poly.10`，Git commit `3e1642161198c50ff1abed4046f4e4f476099dbb` |
| 代码改动 | **无**。完全未修改官方 Git 子模块 |
| 构建平台 | Windows 10，MSVC BuildTools 18，CUDA 13.2，SM86 |
| GPU | RTX 3070 Ti，8 GiB |
| 引擎产物 | `E:\LLM\deploy\mikuchin-native-runtime\build-cuda86\strata-poly.exe`（74,803,712 字节） |
| 模型 | `G4-MeroMero-26B-A4B-it-uncensored-heretic-Q4_K_M.gguf`（16.1 GiB），原有文件只读 |
| 模型分词器 | 原 stable 安装中的 Gemma 4 tokenizer，只读 |
| Expert profile | 从原 stable 安装复制到单独 runtime/config 文件，再交给官方引擎写回 |
| context/KV | `--max-context 8192 --kv int8 --no-draft --window 1 --lookup 0` |
| 自动会话缓存 | `--conversation-cache-mib auto --conversation-cache-slots 4`，引擎日志报告 8192 MiB 停放预算 |
| 官方服务 | `127.0.0.1:15240`，独立 Python 3.12 venv，测试 Bearer Key |
| Mikuchin Gateway | `127.0.0.1:15249`，使用与官方服务不同的测试 Bearer Key |
| 正式服务 | `15239` 未启动；用户已主动退出稳定版启动器 |

## 实际结果

1. **官方服务成功装载模型**：`/health` 为 `ok`，模型加载状态 `loaded=true`。日志记录 2.1 秒加载阶段，802/3840 个 MoE experts 驻留 GPU，空闲时约 6.4 GiB GPU 使用量；具体数值与当时显存状态有关。
2. **真实 Chat Completions 已运行**：官方 `/v1/models` 返回测试模型，`/v1/chat/completions` 可用；经独立 Gateway 的相同接口也能够生成响应。关闭 thinking 的 `1+1` 测试得到 `2`；强制 64-token reasoning budget 的测试得到 `Correct.`。
3. **自动 KV 命中**：重复 6755-token 的合成文本（不涉及用户私人会话），第一次 API 返回 `cached_tokens=0`，第二次 `cached_tokens=6754`。首次耗时约 6.56 秒，再次约 2.24 秒，两次均生成 128 tokens。
4. **跨对话切换复用**：插入多个其他短对话请求后，再次提交原 6755-token prompt，仍为 `cached_tokens=6754`，约 0.59 秒。但该次只生成 8 tokens，因此**不得**直接把 0.59 秒与 128-token 的两次耗时作为同比。
5. **引擎原生日志 corroboration**：第一次长 prompt 6755 read tokens ~3750 ms；第二次只需 1 个新 token，~33 ms。之后日志出现 `conversation cache: parked 6754 tokens ... parked=1 ... evictions=0`。这确认当前缓存行为由官方引擎实现，而非 Mikuchin 自己的旧 SessionV1 KV 快照。

## 边界与后续测试

- 本次没有开启旧 `POLYKV1!` 快照，没有实现会话手动锁定、官方 `PIN`、磁盘 `SAVE/RESTORE` 或旧聊天迁移。这些不是原生新架构的前提。
- 没有验证断电/模型进程重启后的缓存保留；内存中的 prompt cache 在进程重启后不应当被假设仍然有效。
- 未进行大量混合上下文、完整 4 会话名额淘汰、Qwen 4B、视觉输入、不同量化/GPU、实际本地 Image Worker/4x/LoRA 的性能测试。
- Gemma 4 默认长思考时，`max_tokens=128` 的测试仅有 reasoning，没有正文；要测用户可见的正文，可用官方支持的 `reasoning_budget_tokens` 或 `chat_template_kwargs.enable_thinking=false`。这不是 KV 缺陷，不能把截断的 reasoning 错记为模型无法推理。
- 本次测试配置、日志、复制的 profile、模型构建和进程均属于单独的 `mikuchin-native-runtime`，不可提交到仓库或复用为正式用户配置。

## 编译指令摘要

```powershell
# 在 vcvars64.bat 设定好的 x64 MSVC 环境中执行。编译目录在工作树外。
cmake -S E:\LLM\deploy\mikuchin-native\backend\polystrata `
  -B E:\LLM\deploy\mikuchin-native-runtime\build-cuda86 `
  -G Ninja -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_CUDA=ON `
  -DCMAKE_CUDA_ARCHITECTURES=86 -DSTRATA_BUILD_TESTS=OFF `
  -DSTRATA_PORTABLE=ON
cmake --build E:\LLM\deploy\mikuchin-native-runtime\build-cuda86 `
  --target strata-poly --parallel 4
```

以后更新官方，只更换子模块指针，重新构建并重新执行实际模型与自动缓存回归测试；二进制格式、前缀复用策略和 GPU 兼容性不应被默认为跨官方版本稳定。
