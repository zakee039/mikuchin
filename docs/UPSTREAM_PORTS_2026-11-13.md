# PolyStrata 上游增量移植记录（2026-11-13）

Mikuchin 现在是独立仓库。此文档记录对上游
[`simplexai-labs/PolyStrata`](https://github.com/simplexai-labs/PolyStrata)
的**选择性源码移植**，而非恢复 Git 子模块或覆盖 Mikuchin 的后端。

基线：Mikuchin v0.2.7（保留了自身的角色卡、会话、采样默认参数和生图工具）。

## 第一批：启动和视觉诊断（P0）

| 上游提交 | 移植内容 | 范围 |
|---|---|---|
| `d07c22fa` | 不向 strata-poly 自动传递不支持的 `--vram-elastic` / `--vram-segment-mib`；在 GPU 模式下不假定其视觉编码器支持 elastic 懒启动 | `serve/server.py`, `test_vram.py` |
| `5bad93b1` | 视觉编码器无 stdout 就退出时，显示日志末尾几行和日志位置 | `serve/server.py`, `test_vision_busy.py` |

## 第二批：Gemma 4 并发（P1）

来自上游 `e4e62b19`：

- 将 tokenizer 提供的 EOS/EOT/EOM Token 用作引擎实际结束标志，避免将 Gemma 的结束 Token 误判成客户端提前退出。
- 将槽位请求的 `slot_claims` 原子移交给等待 `BDONE` 的清理线程，消除前一个请求误删下一个请求占用记录的竞态。
- 新占用和拒绝后的临时停放均清除过时的 orphan-sighting 时间戳。
- 增加并发、槽位移交、Orphan 恢复回归测试。

## 第三批：图文混合 Prefill（P1）

来自上游 `f0aab997`：

- `src/poly/main.cpp` 以图像位置分割 Prompt；在图像之前或之后的纯文本段采用批量 `read()`，图像本身继续用 `eval()`。
- 未修改 Mikuchin 的 Python 接口、模型文件格式、会话或图片工具协议。
- C++ 源码已通过 MinGW g++ 15.2 的语法检查和目标文件编译。

**部署注意：** 更改 `main.cpp` 只会影响**重新编译之后**的
`strata-poly.exe`。已安装的可执行文件不会因为源码修改而自动获得优化。
没有在真实模型与 GPU 上测量吞吐量，不能把上游给出的性能数字当作 Mikuchin 的实测收益。

## 验证与范围

本次实际验证：

- `serve.test_parallel`：34 项通过（包含 Gemma EOS、BDONE 槽位移交和孤儿槽位恢复）。
- 后端相关回归测试：125 项通过（包括 `test_vram`、`test_vision_busy`、会话和生图工具）。
- Mikuchin 仓库自身测试：9 项通过。
- `serve/` 的 Python 文件编译检查通过；C++ `src/poly/main.cpp` 已使用 MinGW g++ 15.2 编译为目标文件。
- 原生完整 GPU 引擎链接、真实显卡图文 Prefill 吞吐以及实际多轮并发负载测试**尚未执行**。

移植均对应具体上游提交，可单独回滚；未引入额外 Git remote/submodule 依赖。
本次不顺带引入 Metal、HIP、NVFP4、MTP 或 `--vram-pool`，这些改动需要单独针对目标模型与显卡验证。
本次工作仅限源码与回归测试，不自动修改运行中的模型二进制、不推送 GitHub、不打 Tag 或 Release。

## 后续一批：CPU / Windows 显存预算 / Responses 时序

### CPU 专家线程（上游 `95e8fadb`）

- strata-poly 未指定 `--threads` 时，普通桌面取可用逻辑处理器的大约 70%。
- 对 Linux 有 CPU 配额的容器保留配额内全部可用线程。
- `--threads N` 仍然优先（手动填写逻辑线程数量；全部线程可以明确填写可用线程总数）。
- 逻辑通过独立头文件 `src/poly/thread_policy.hpp` 和无 GPU 的原生测试验证；未擅自新增或更改前端采样设置。

### Windows WDDM 本地显存预算（上游 `aa31d266`）

- 在 `src/platform/memory.cpp` 增加基于 DXGI `LOCAL` 区域的预算与当前进程显存使用量查询，
  保留原有 `NON_LOCAL` 共享内存查询。
- 新版原生引擎通过 `INFO budget_query=1` 宣告支持，并接受**只读** `BUDGET` 指令；
  原始配置、模型权重、显存预留和 GPU 内存分配均不会因此改变。
- Mikuchin 服务端增加带鉴权的 `GET /v1/strata/gpu-budget`，仅在服务未忙且必要时读取；
  数据缓存 5 秒，正在推理时不等待模型，并在返回旧样本时标注 `stale`。
- API 监控页显示 `WDDM GPU n: 进程使用量 / 预算 MiB`；老的
  `strata-poly.exe` 未支持该指令时显示破折号，不会尝试发给旧引擎。
- WDDM 数值由 Windows 的进程预算计算，**不能**代替 GPU 全卡空闲显存或 NVML 指标。

### Responses API 时序（上游 `d19ddb23`、`29a268a5`）

- 在流式 `response.completed` 事件顶层添加 `timings`（存在时）。
- 不更改 `response` 对象本身，避免把非标准字段混入 Responses API 对象；无时序数据则不添加字段。

### 验证及部署边界

- DXGI 查询已由 MSVC 在本机编译和链接成单独测试工具，并在 Windows WDDM 上读到真实预算。
- 使用 CUDA 13.2 的 `cudaDeviceProp::luid` 与 DXGI 查询进行匹配也已成功：本机
  NVIDIA GeForce RTX 3070 Ti 的 WDDM 本地预算为 **7249 MiB**（此值随桌面状态和
  其他程序变化，属于一次采样，不是物理显存容量），独立测试进程使用量为 0 MiB。
- CPU 自动线程算法已由 MinGW g++ 编译运行，含 20→14 及容器/小核数断言。
- 新增预算、鉴权、非阻塞锁、重启后废弃旧样本、原生指令解析和 Responses SSE 单元测试；
  后端整合回归 99 项中 98 项通过、1 项跳过；另有根目录 9 项通过。
- 完整原生构建使用**单独目录**和 pinned llama.cpp/ggml 源码，绝不覆盖
  `backend/polystrata/engine-poly/strata-poly.exe`。
- 完整 Windows CUDA 13.2 / MSVC 19.50 / SM86 的 `strata-poly` 构建与链接成功，
  候选程序位于 `E:\mikuchin-native-review-20261113-2\Release\strata-poly.exe`。
  新程序能够输出完整命令行用法；该项目的 `--help` 返回状态码 2（表示帮助选项
  不在接受的启动参数内），不意味着动态库或启动失败。
- 构建有上游/依赖相关警告（CUDA 头文件代码页 `C4819`，
  MSVC 静态/动态运行库 `LNK4098`）。完整模型加载、真实推理、图文 Prefill
  对照和持续运行负载仍未验证；**不能仅凭成功链接就替换线上程序**。
- 运行中的程序仍使用原来的 `engine-poly/strata-poly.exe`；
  此源码批次没有推送 GitHub、更新 Tag 或 Release。
