# v0.2.8 覆盖发布修复：Gemma 4 生图工具伪调用回收（2026-11-13）

**发布决策：经用户明确要求，将此补丁合并进已有 `v0.2.8` Tag 与 Release，
替换主程序源码 ZIP、SHA256 和发行清单。**
产品版本仍取自 `versions.json`。原始 v0.2.8 发布对应源码提交
`b62a05c3fe43cb74bdd456feb657a3bb2564a37c`，覆盖后远程 Tag 会指向包含本修复的新提交。
Windows Launcher、Android 和 Windows CUDA 引擎二进制不因 Python 修复而变化，
保留原已验证的 v0.2.8 构建文件与签名。

## 用户可见故障

Gemma 4 在图像请求时，有时把工具调用写成一行：

```xml
<call:polystrata__generate_image prompt="a simple illustration" style_hint="anime" />
```

原来 `serve/frontend.py` 仅识别正式的 Gemma `<|tool_call>` 包装和
`polystrata__generate_image{...}` 裸映射格式，**没有识别自闭合 XML 风格**。
因此前端只显示了一段像调用的文本，并没有产生实际 `strata_mcp` 工具任务；
不是图像模型收到请求后失败。

## 改动

- 在 Gemma 4 `OutputParser` 增加这一种**仅限已提供第一方生图工具**的调用兼容；
  可以逐 Token 流式识别，完整参数才发出 `tool_call` 事件，调用实际的 `ChatImageHub`。
- 严格验证 `prompt`、尺寸、放大、风格、角色关联和编辑已有图片参数；
  拒绝重复、额外、未闭合或非字符串参数，**不执行未知工具**。
- 代码围栏、内联代码、非独立行的演示文字只按文字处理；
  异常格式提示“图像任务未创建”，不将内部伪调用语法或部分提示词暴露成普通消息。
- 工具供应商抛出意外异常时，也发出真实 `strata_mcp` 失败状态和工具详情，
  而不让前端停留在“调用中、无图片、无结果”的状态。
- 生图工具说明要求忠于用户场景/衣着/姿态，不主动添加新元素；
  **保留原有角色人格、上下文、现有生图模型选择、LoRA 与参考图策略**。
- 这不是禁用模型的生图自由度，也不是让前端猜测字符串并绕过后端权限。

## 测试

```powershell
cd backend/polystrata
.\.venv\Scripts\python.exe -m unittest serve.test_gemma_image_recovery serve.test_image_tools -v
```

覆盖截图同类格式、1/2/3 Token 切片、合法与非法参数、提前结束、
未授权工具名、引用/代码块误触发，以及真实 `run_with_mcp` 到
`ChatImageHub` 模拟生成成功或后端抛异常。模拟图像使用测试 PNG，
不调动大型生图模型。

## 运行与发布边界

- Python 服务必须安全重启后才会加载新的解析器；原生 `strata-poly.exe`
  不需要重新编译/替换。
- 覆盖发布后 GitHub `v0.2.8` Tag 指向新的源码提交，主程序 ZIP 与发行清单
  同步替换；**保留原始提交 ID 与重新发版记录，以免后续误把旧下载文件当新版**。
- 一般聊天、原生 Gemma tool call、现有截图以外的工具行为保持不变。
- 真实大模型是否在每种生图指令下都正确选择工具，以及高负载图像生成耗时，
  仍需在用户日常使用中进一步观察。

## 本机热部署与真实生图测试

- 本地源码热修复已经部署到正在使用的 Mikuchin Python 服务；
  启动器和 CUDA 13.2 SM86 原生引擎二进制未修改。
- 实测 `POST /v1/chat/completions`（`strata_image_tool=true`，SSE）
  发起**简单蓝色圆形**测试图片。模型产生真实工具调用，事件顺序为
  `start → call → result`，结果 `ok=true`、`image_file` 非空，
  HTTP 200，响应正文没有 `<call:` 语法残留。
- `sd-cli.exe` 实际启动并生成可由 Pillow 验证的 PNG；
  完成后模型重新加载并恢复此前的会话 KV，视觉回喂后的回答正常结束。
  该请求总耗时 **213.4 秒**，其中图像工具执行 **180.0 秒**（包含首次生图模型加载）。
  这验证了从聊天到生图的端到端成功，但**不代表生图速度已优化**。
- 本次真实模型恰好采用它认可的工具调用格式；截图中 XML 自闭合格式
  已由逐 Token 解析测试和模拟 ChatImageHub 执行测试覆盖，不能把上述
  真实请求误称为模型又一次输出了同样的 XML 文本。
- 单次测试产生的 PNG 已验证并删除；不改动用户原有历史、已生成图片及角色文件。
- 本机 Manager 的 Python API 热重启曾因守护未重拉服务而临时离线；
  最终使用用户登录会话的 Windows Task Scheduler 启动器恢复。
  `/health` 返回 200，`image_generation=true`，推理队列为 0。
  恢复用的 `Mikuchin-Restore-Live-20261113` 任务已经**禁用后续触发**，
  避免重复启动；本次已运行的 Manager 正常保留驻留。
- 上一版三个 Python 源码文件的校验备份：
  `%LOCALAPPDATA%\Mikuchin\backups\image-tool-hotfix-20261113\`。
