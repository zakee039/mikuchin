# Mikuchin V1.1 迁移验收记录（2026-11-02）

## 迁移

- 旧项目：`E:\LLM\deploy\polystrata`，已退出，不再监听 18081。
- 新项目：`E:\LLM\deploy\mikuchin`，Mikuchin.exe 在托盘驻留，PolyStrata 作为 `backend/polystrata` 引擎使用。
- 统一网页标题、网页左上角品牌 Logo、Favicon、启动器和 Windows 图标。
- 兼容接口、原来的本地端口、API Key 和 Cloudflare Tunnel 凭据保留不变。凭据只在本机 DPAPI 加密存储。
- 原始目录和用户配置保留，用于回滚。Git 忽略运行时数据，不提交聊天、模型和凭据。

## 数据一致性

- 聊天数据库 `conversations.sqlite3` 与角色数据库 `character_cards.sqlite3` 均通过 SQLite `PRAGMA quick_check`。
- 两个数据库的全部数据表记录数与旧版一致。
- 迁移 3 个 KV 快照，对照旧版逐文件 SHA-256 一致。
- `generated-images` 17 文件、`images` 1 文件、`attachments` 0 文件，数量一致。
- 会话 API 返回 3 条历史会话。

## 功能回归

| 检查 | 结果 |
| --- | --- |
| 18081 HTTP /health | HTTP 200 |
| /v1/models，认证后 | HTTP 200 |
| /v1/strata/characters | 正常返回 |
| /v1/strata/sessions | 3 条历史会话 |
| Browser Chat / Characters / About 跳转 | 正常，网页标题 Mikuchin |
| 网页 Favicon、左上角 Logo 和静态资源 | HTTP 200 |
| 浏览器加载与导航 | 无 JS 未捕获异常、无网络错误（未授权浏览器请求返回 401 为预期行为） |
| Cloudflare `https://key.zakee.fun/v1/models`（认证后） | HTTP 200 |
| V1 会话、角色、生命周期等单元测试 | 41 tests OK |
| Tauri 隔离 --self-test-model | API 启停、实际模型加载/卸载均通过；卸载后 API 继续在线 |
| 真实 Gemma 4 推理 | 返回内容 `OK.`；非空 completion；完成后卸载成功 |
| 管理器后台驻留 | 正常；临时 Windows 启动计划任务删除后仍保持运行 |

## 尚未做的专项测试

- 完整图像生成、Anime 4x 超分流程（本次未触发重型图像模型）。
- 将真实旧会话中的 KV 恢复进 GPU 后继续生成（仅验证 3 份文件哈希一致及会话/KV 相关单元测试）。
- Windows NSIS 安装、卸载及开机重启后的自启动行为；当前保持迁移前 `autostart=false`。

本次验证未修改或删除旧版运行数据。回滚时须先从 Mikuchin 托盘退出，再启动旧版管理器；切勿让两个管理器同时控制端口 18081。
