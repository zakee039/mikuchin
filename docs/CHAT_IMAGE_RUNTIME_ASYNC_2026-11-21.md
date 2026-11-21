# 2026-11-21 聊天图片运行方式与异步结果交付

## 最新产品决定

运行方式**不属于 LLM 模型 JSON 配置**。位置是 Mikuchin 全局设置「聊天生图模型」右侧的「运行方式」，随 `chat_image_settings.runtime_mode` 存在 Mikuchin 角色全局选项 SQLite 内并自动保存。

- `exclusive`（默认/兼容旧设置）：共享 GPU 独占锁；原有 LLM KV 快照→卸载→Qwen-Image→4×→加载 LLM→尝试恢复 KV；此期间聊天请求等待。
- `concurrent`：同机显存足够或多 GPU 条件下，**只允许本地聊天生图与 LLM 同时运行**，使用共享 GPU 锁，不调用官方 LLM unload/load/KV 接口。超分包含在同一共享锁中；显存不足时任务失败，不自动改回互斥重跑（避免重复费用或改变用户意图）。注意本选项不会自动判断显存够不够、也不负责分配 GPU。
- 在线图像 API 与本机 GPU 模型解耦，始终可后台执行，不需要该本地运行方式控件。独立「生图」页不受此控制，且不再使用聊天的付费确认选项。

## 其余图像交互

- 聊天图片为真正全屏只读预览，不保留顶栏，下载/关闭悬浮右上角；画廊右上增加对当前原图或超分图进行授权下载按钮。仍由安全 Blob 加载器 Bearer 鉴权。
- `edit_image` 保留上一次**同一会话**成功生成图片的服务器端所有权；多图参考 API 合并上图与用户本次上传参考图；单图 API 仅使用上图；无参考能力时从原图任务 prompt + 本次指令重绘。不调用不支持的图片引用能力。
- 在线/同时运行的后台工作：原助手先报备「已经开始为你生成图片…」且聊天输入恢复；后台完成后视觉 LLM 使用原生图 prompt、实际生成图及同会话中新消息，采用 `tool_choice=none`, `reasoning_effort=none`, `max_tokens=256` 的短回复；前端将图片与结果作为**单独一条**助手消息持久保存。另一条普通回复还在流式输出时延迟插入，任务 ID 去重，不会自动再次发起提供商请求。
- 互斥本地模式仍按独占 GPU 串行流程，保留状态与 KV 尽力恢复。

## 验证与限制

离线 Python 全量、Node 全量测试；另用独立无收费的 Mock 网页验证后台开始提示、普通聊天独立回复、完成结果、全屏浮动控件、画廊下载，用户选择的 runtime_mode 持久 SQLite。单图/多图/无参考 API 及运行锁分别由单测覆盖。**没有再次使用真实收费图像 API，也没有将本机 RTX 3070 Ti 8GB 上的真实双模型同时驻留验证为可用**：同时运行是用户显式开启的资源模式，若不足需手动改回互斥模式。

部署要求：先备份 SQLite 与配置、核实 15239 无活跃请求、Worker 无在途图像任务、Turn 无未完成，再仅重载 Mikuchin Gateway；更改 Image Worker 代码只有在确保无在途任务时才能让 Supervisor 安全重载 Worker，不能杀掉已发送的在线请求。不得修改官方 PolyStrata 子模块、模型 JSON 或产品版本/Tag/Release。

## 关键文件

`frontend/web/index.html`、`app.css`、`characters.js`、`app.js`、`native-tool-client.js`、`chat-image-viewer.css`、`gallery.js`；
`backend/gateway/characters.py`、`chat_tool_dispatch.py`、`chat_turn_service.py`、`chat_turns.py`、`image_jobs.py`、`local_images.py`。
