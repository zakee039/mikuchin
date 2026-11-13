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
