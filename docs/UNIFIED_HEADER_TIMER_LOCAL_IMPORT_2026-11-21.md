# Mikuchin 2026-11-21：顶栏状态统一、聊天生图计时与本地模型注册

## 范围与不变项
- 用户明确授权本轮实施。仅修改 Mikuchin 自有 Web/Gateway，不碰官方 PolyStrata 子模块 `3e1642161198c50ff1abed4046f4e4f476099dbb`、现有 LLM 模型 JSON、角色卡及已提交图像任务。
- 版本号、启动器、APK、Tag、Release 均不变。
- 「导入本地模型」只注册**服务器机器上已存在**的 Qwen-Image Turbo 文件，不上传权重、不运行模型、不安装新推理程序。

## 1. 顶栏单一状态仲裁
旧版 `frontend/web/app.js` 的 `render(metrics)` 每秒写一次 `#pill`；`pollNativeHealthStage()` 每两次轮询再写一次，导致 `空闲` 与 `模型已空闲卸载` 轮换。

现增 `native-header-status.js` 独立纯函数 `resolve()`。Metrics/Native Health 只写时间戳快照，在一次 `paintHeaderStatus` 中组合后统一渲染，不在 `render` 或 `pollNativeHealthStage` 分头修改 DOM。优先级：
- API 鉴权失败；
- 独占 GPU 切换（卸载／恢复／超分）；
- LLM 读取上下文或生成文字；
- GPU 生图；
- 推理引擎不可用；
- 模型已卸载；
- 空闲／排队；
- 网络不可达。

LLM 聊天与在线/并行生图同时发生时，顶部主标签保留 LLM 状态；右侧辅助标签 `生图 N` 表示后台活跃图像数。无图像任务时隐藏辅助标签。HTTP 503 的 Native Health JSON 如果结构正确，仍可区分有意模型卸载和真正 Gateway 故障。

## 2. 聊天 Tool Calling 的真实执行时间
`backend/gateway/chat_turns.py` 的 `job` 摘要透传已有 Worker 数据库字段 `started_at`、`finished_at`、`elapsed_s`。它们由 Worker 真正开始请求供应商／本地 Qwen 推理时记录；排队和卸载 LLM 阶段不会启动计时。前端工具摘要显示 `已运行 MM:SS`、完成时 `耗时 MM:SS`，每秒只刷新计时文字，不重建图片或正在输入的控件；没有执行时间的旧任务不虚构数值。将原来英文 `Image generation succeeded; image available in this chat.` 换为中文状态摘要，完整结果仍由用户展开查看。

## 3. 本地模型导入
设置页的 `生图服务` 卡片现在分为「本地模型」「API 服务」，标题行提供「导入本地模型」「添加 API 服务」两项。新表单录入：模型显示名、已有基础 sd-cli 环境，以及 Diffusion/VAE/LLM 和可选视觉编码器的服务器**绝对路径**。

前端 `local-model-settings.js` 通过既有鉴权目录 `GET /v1/mikuchin/image-models` 显示已注册本地模型。注册使用 `POST /v1/mikuchin/local-image-models`，只允许带正确 Bearer Key 的、Host 和 Origin 均为本机 `http://127.0.0.1:<端口>` 或 localhost 的请求；拒绝非回环客户端和常见代理转发头，禁止 Tunnel/Tailscale 客户端执行注册。在非本机页面按钮不可用，需在主机本地浏览器打开 `http://127.0.0.1:15239/#settings`。

服务端 `local_images.register_existing_model` 严格校验输入字段和文件扩展名，仅接受现有 sd-cli 配置中的可用基础环境，拷贝其**可信 exe/args**（请求不允许自定义可执行程序、命令参数或脚本），新增随机 local-import ID。用同目录临时 JSON + `os.replace` 原子更新 `images/config/native-local-images.json`；保持已有 profile、LoRA、超分设置及凭据不变。不触发 GPU 调用，也不更改 LLM 模型配置。

当前导入器只适配现有 Qwen-Image Turbo/sd-cli 文件家族，非 SDXL/Flux 的通用适配器，不能把「通过路径验证」等同于 GPU 兼容性测试。已有本地模型可直接保留，导入无需复制几 GB 权重文件。

## 回归与部署
- Python 全量 `python -m unittest discover -s backend/gateway -q`：137/137。
- Node 全量 `node --test frontend/web/tests/*.test.mjs`：82/82。
- 新增本地模型注册 HTTP 安全测试：本机同源+Bearer 可注册，远端 Host/Origin/代理转发/无 Key 不能注册；旧 profiles/LoRA/超分配置不变。
- 新增顶栏状态仲裁测试：模型卸载、文本生成+生图任务、GPU 恢复、断线、缺 Key、计时排队与完成。
- 隔离 Chrome 浏览器验证设置页「生图服务」的本地模型列表、导入弹窗、取消关闭和无页面异常。测试使用可丢弃 Mock Gateway，没有接触正式图片 API。

## 正式部署结果

已经以 SQLite Online Backup 备份正式 Native Turn、图像任务、角色及画廊数据库，同时备份 Native 图像注册 JSON、在线 API 服务配置和活跃模型 JSON，目录：`runtime/migration-backups/header-timing-local-import-20261121-184239`。部署前无进行中的 Native Turn、图像任务及官方推理连接。用户明确允许重启，Gateway 仍有一条空闲的 Tailscale 客户端连接，因此它会在 Gateway 重载时短暂断线并由浏览器重连。

仅重载 Gateway 监听进程 `37040 → 29860`，Supervisor 自动恢复，官方 PolyStrata 的 `15240 / PID 41712`、Image Worker 和 Supervisor 官方子进程保持不变。生产静态入口、统一状态 JS、模型导入 JS、聊天 JS 和 CSS 均返回 HTTP **200**；无密钥的 `/health` 与本地模型注册 POST 均为 **401**。正式 **9 条 Turn**、**13 条成功图像任务**、原有 **2 个本地模型配置**仍完整，Worker 心跳正常，官方子模块 SHA 未变。

**未宣称的验证**：没有执行真实 Qwen 图像推理，也没有提交真实新本地模型，避免触发模型加载及用户当前设置修改。服务器端的有效模型注册、安全门槛、静态资源和 isolated Chrome UI 已分别验证。
