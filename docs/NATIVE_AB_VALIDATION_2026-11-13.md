# Mikuchin / PolyStrata 原生引擎 A/B 真实验证（2026-11-13）

## 范围与部署决策

**结论：在 RTX 3070 Ti 8GB + 64GB RAM 上，新候选引擎通过了真实的 Gemma 4 文本、交替多会话、KV 恢复及单图视觉混合 Prefill 回归测试。可进入受控灰度，但不应仅凭这批短测直接替换正式运行二进制或发布 Release。**

主要性能收益来自**自动 CPU 线程数由 20 降为 14**：固定 14 个线程后，旧版与新版大多数测试的速度相近。没有证据证明混合图文 Prefill 移植带来了普适性能提升，动态专家调度模式下吞吐量也存在明显的案例波动。

原服务配置 `config/active.json`、现用 `backend/polystrata/engine-poly/strata-poly.exe`、用户聊天/角色/图像与生产专家缓存未修改。全部测试是独立进程，每轮从同一份专家缓存**复制**一个临时副本；启动前检查 GPU 是否空闲。

## 测试对象

- 旧程序：`backend/polystrata/engine-poly/strata-poly.exe`，2026-11-01 的在用版本。
- 候选程序：`E:\mikuchin-native-review-20261113-2\Release\strata-poly.exe`（CUDA 13.2、MSVC 19.50、SM86 独立 Release 构建）。
- 模型：`G4-MeroMero-26B-A4B-it-uncensored-heretic-Q4_K_M.gguf`，16.14 GiB。
- 显卡：NVIDIA RTX 3070 Ti，8GB；主机 RAM 64GB；旧默认使用 20 逻辑线程，新默认使用 14 逻辑线程。
- 配置复用：生产 `--max-context 131072`、`--vram-reserve-mib 1024`、`--window 1`、`--lookup 0`、`--no-draft`、`--kv int8` 和 `--conversation-cache-mib auto`。
- 基准为固定提示词的单 GPU、顺序请求。常规 A/B 为 greedy（`temperature=0`、`seed=42`），并设定 `STRATA_FREEZE_EXPERTS=1`，使专家所在 GPU/CPU 的分配固定、便于逐 Token 对照。每组的首个 128 Token 请求属于 CUDA 初始化/预热，不作为稳态 Prefill 指标。

## 1. 相同模型与输入，2 × 2 线程数控制实验

Prefill / Decode 单位均为 **Token/s**。列顺序：旧 20、新 20、旧 14、新 14。

| 请求 | 旧20 Prefill | 新20 Prefill | 旧14 Prefill | 新14 Prefill |
|---|---:|---:|---:|---:|
| 384 Token | 404.1 | 405.1 | 424.4 | 420.3 |
| 1,536 Token | 941.6 | 960.8 | 968.7 | 956.2 |
| 4,096 Token | 1,729.1 | 1,729.1 | 1,750.7 | 1,756.5 |

| 请求 | 旧20 Decode | 新20 Decode | 旧14 Decode | 新14 Decode |
|---|---:|---:|---:|---:|
| 384 Token | 39.9 | 43.5 | 46.3 | 47.0 |
| 1,536 Token | 34.8 | 35.9 | 38.4 | 38.2 |
| 4,096 Token | 36.1 | 37.0 | 38.8 | 38.9 |

- 四种条件下，7 组测试（包含预热、三种长度、三轮顺序聊天）的输出 Token 序列**全部一致**。
- 第二轮历史上下文复用 511 Token，第三轮复用 569 Token；四种条件一致。
- 上述四次运行中，GPU 监控记录的显存峰值皆为 **6,668 MiB**；退出后回到 0 MiB（NVML 口径）。
- 固定线程数后，性能差异多数在几个百分点内；仅凭这一轮测量不足以将小幅差异认定为稳定算法收益。
- 旧版从 20 减少到 14 线程，同样出现 Decode 提速。因此，“首轮新默认配置 Decode 快约 8%–25%”主要是线程策略的效果，不应写成 CUDA 算法提升。

## 2. 交替双会话稳定性（固定 14 线程）

两套独立对话 A、B 按 A1→B1→A2→B2→A3→B3→A4→B4 交替，第一轮输入 1,400 Token，超过 1,024 Token 的默认驻留门槛，以实测 `conversation-cache` 的驻留/恢复机制。

| 会话阶段 | 旧版复用 Token | 新版复用 Token | 输出逐 Token 一致 |
|---|---:|---:|---|
| A1 / B1 | 0 / 0 | 0 / 0 | 是 |
| A2 / B2 | 1,399 / 1,399 | 1,399 / 1,399 | 是 |
| A3 / B3 | 1,455 / 1,456 | 1,455 / 1,456 | 是 |
| A4 / B4 | 1,510 / 1,510 | 1,510 / 1,510 | 是 |

两版各 8 个请求均正常结束，进程退出码 0；日志显示对话确实发生了 RAM 驻留与恢复，不是仅重用相邻的单一路径 KV。GPU 峰值均约 **6,666 MiB**，退出后释放。没有在该轮短测中观察到进程崩溃或显存泄漏；**不能据此证明长期稳定性**。

## 3. 真实 Gemma 4 视觉输入：图文混合 Prefill

测试通过原有 `strata-vision.exe`（CPU 配置）和当前 Gemma 4 mmproj，将一张程序生成的 160×160 彩色几何图形编码为 **81 个视觉 Token、912,404 字节的 SVE**。同一份编码结果分别传入两套原生引擎的 `GENI` 协议。生成提示词按服务端 Gemma 4 格式使用 `<|image>` / `<|image|>` / `<image|>`，图前图后均有文本。

- 视觉混合提示词共 **149 个 Token**，新旧版均生成 16 Token，**内容逐 Token 一致**。
- 再次发送相同图文请求，新旧均复用 **148 Token**，生成内容仍一致。
- 编码器首次准备并编码耗时约 21.5 秒；图文首轮 Prefill 约 12 秒，包含首次 GPU 计算和 CUDA 图初始化，**不用于比较纯图文 Prefill 算法吞吐**。
- 新版 DXGI WDDM 查询返回 RTX 3070 Ti 的本地显存预算约 **7,249 MiB**，进程占用在加载后约 **6,226 MiB**；这是进程预算/使用量，不是 NVML 的全 GPU 总占用，也不是物理显存大小。
- 该测试涵盖单图、一种尺寸与一次重复输入；没有测试多图、极大图、全套图像生成工具或移动客户端。

## 4. 更接近日常运行的动态专家调度模式

另使用不设置 `STRATA_FREEZE_EXPERTS` 的默认方式，旧版 20 线程与新版 14 线程各进行一次相同的 7 请求测试：

| 请求 | 旧版 Decode (tok/s) | 新版 Decode (tok/s) |
|---|---:|---:|
| 384 Token | 42.4 | 85.0 |
| 1,536 Token | 54.3 | 43.8 |
| 4,096 Token | 56.2 | 53.3 |
| 会话第二轮 | 48.8 | 59.0 |
| 会话第三轮 | 50.9 | 55.6 |

所有请求成功，第二轮/第三轮同样复用 511/569 Token，显存峰值均 6,668 MiB，进程退出后 GPU 显存回到 0 MiB。但有 **4/7 组的生成 Token 序列不同**；专家在 CPU/GPU 间动态调度，可能导致浮点计算路径及生成结果差异。因此冻结专家的严格等价结论**不能直接扩展**到动态模式。

同一模式下不同提示词的速度有明显快慢交错，且只有单次运行；不能据此声称新版本在日常任务全面更快，尚缺多轮随机化、GPU 频率/温度控制、任务质量评价。

## 5. 复现方法与原始结果

在 `backend/polystrata` 目录中，以项目虚拟环境执行：

```powershell
.\.venv\Scripts\python.exe bench\benchmark_mikuchin_native.py --only both --output E:\bench-ab-default
.\.venv\Scripts\python.exe bench\benchmark_mikuchin_native.py --only both --threads 14 --output E:\bench-ab-14
.\.venv\Scripts\python.exe bench\benchmark_mikuchin_native.py --only both --threads 14 --stress-only --output E:\bench-stress
.\.venv\Scripts\python.exe bench\benchmark_mikuchin_vision.py --threads 14 --output E:\bench-vision
.\.venv\Scripts\python.exe bench\benchmark_mikuchin_native.py --only both --unfrozen --output E:\bench-dynamic
```

脚本采用独立的 `--serve` 原生进程、相同 GGUF、相同 token ID、同一份复制的初始专家画像，记录完整 `DONE` Prefill/Decode 时间、KV 命中、生成 ID、GPU 峰值、进程 RSS、WDDM 显存预算，以及退出码；默认开启专家分配冻结。运行前检测 GPU 空闲和是否存在其他 `strata-poly.exe` 进程，不修改用户生产会话和配置。

本次实际原始 JSON/日志在以下本机目录：

- `E:\mikuchin-native-bench-20261113`（旧20，冻结）
- `E:\mikuchin-native-bench-20261113-candidate`（新14，冻结）
- `E:\mikuchin-native-bench-20261113-candidate-20threads`（新20，冻结）
- `E:\mikuchin-native-bench-20261113-baseline-14threads`（旧14，冻结）
- `E:\mikuchin-native-bench-20261113-interleaved`（旧/新14，多会话）
- `E:\mikuchin-native-bench-20261113-vision`（旧/新14，真实视觉）
- `E:\mikuchin-native-bench-20261113-baseline-production-mode`（旧20，动态）
- `E:\mikuchin-native-bench-20261113-production-mode`（新14，动态）

## 局限与建议

这次验证覆盖同一台 RTX 3070 Ti、一种 Gemma 4 GGUF、单 GPU、顺序推理，以及短时双会话/单图输入；没有验证其他模型、Android/Cloudflare 入口、长时间压力、复杂工具联动、真实生图、图像理解准确率或并发批处理。原生编译依赖有 `C4819` 和 `LNK4098` 警告，尚未专门清理。

**推荐路径**：优先给现有旧引擎设置显式 `--threads 14` 做日常灰度，可先获得主要 Decode 收益，且不必替换核心原生程序。新候选程序已有强于基础冒烟的文本/缓存/视觉验证，可独立备份后进行受控切换，但建议在日常业务回归和至少一次较长稳定性测试之后，再替换正式版本与执行 GitHub Release。当前不自动修改生产引擎、配置或 Release。
