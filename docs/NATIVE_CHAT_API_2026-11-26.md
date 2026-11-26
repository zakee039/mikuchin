# Mikuchin 混合聊天 API（2026-11-26）

## 使用

设置 → 聊天服务 → 添加 API 服务：配置 OpenAI Chat Completions Base URL（含 `/v1`、不含 `/chat/completions`）、API Key、Model ID、代理、流式/视觉/工具/思考能力、可选输出 Token 上限、超时。输入框角色右侧选择本地模型或指定 API。新会话默认本地；会话保存 `chat_profile` 与经确认的 `chat_revision`。编辑服务后重新选择确认；历史消息不会删除。

获取模型按钮通过配置的连接与代理调用 `GET <Base URL>/models`，不执行推理、不保存未提交配置。允许手动填写 Model ID；只有服务商明确返回的布尔能力元数据才自动勾选，不按模型名猜测。

## 边界

- Gateway `/v1/mikuchin/chat-api-services` GET / POST save/delete，沿用原有鉴权。Windows 新录入的 provider key 使用 DPAPI 当前用户加密，与服务 ID、Base URL 和代理绑定；非 Windows 使用权限 0600 的注册文件。浏览器、Turn 数据库和返回 JSON 不含 provider key。HTTPS 远程地址；HTTP 仅本机。
- Native Turn 记录非秘密服务 ID 和 revision，统一走本地或在线模型。API 请求不占本地 GPU 共享锁，无自动重试或切换服务；禁止重定向。在线模型能力由用户配置。流式遵循 OpenAI SSE 规范；兼容非流式 JSON。工具决策仍经 Native Turn 验证、现有授权与 Image Worker 去重。只支持已有 generate_image/edit_image，不自动把本地 MCP/私有参数暴露给 API。
- 图像任务开始/失败/视觉回复固定发起时的服务 revision。改删服务后不再发送后续请求，保留已完成图片；线上后续回复只使用原始提交时的上下文，不读取切回本地之后新增的历史。非视觉 API 只保留历史图片的文字描述和占位符，拒绝当前用户的图片输入；完成回复不虚构视觉结果。
- 本阶段只实现通用 OpenAI Chat Completions；不保证各种供应商专有思考/采样/输出 Token 参数兼容。不再要求填写无实际控制作用的上下文容量。高级设置的输出 Token 上限可留空，普通聊天不主动发送 max_tokens，生图后续短回复仍保留专用预算。真实收费服务需用户配置并主动测试。

## 激活

保留原 PolyStrata 子模块和版本 0.5.1。使用 `runtime\.venv\Scripts\python.exe scripts/native-admin.py reload` 按已有本机管理接口执行，输入现有 Gateway Key（或已配置环境变量）。管理接口冻结新请求、严格检查空闲状态，只重载 Worker/Gateway，保持官方进程不变。部署后刷新客户端；无需重打 Android APK。未授权时不得读取密钥、绕过鉴权或强杀。
