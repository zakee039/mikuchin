# Mikuchin 测试与备份目录

这是项目**唯一**的测试产物及备份存放位置，不与线上运行数据混用。

| 目录 | 用途 |
| --- | --- |
| `test/scripts/` | 测试脚本、测试运行器、手动备份工具 |
| `test/temp/` | 临时会话、测试图片、模拟服务文件（可随时清空） |
| `test/results/` | 测试输出与日志（可随时清空） |
| `test/artifacts/` | 临时测试配置等产物（可随时清空） |
| `test/backups/` | 需要保留的检查点、配置与程序备份 |

`test/temp/`、`test/results/`、`test/artifacts/`、`test/backups/` 均被 Git 忽略。
不从这些目录读取正式配置、历史聊天或角色设定；不支持旧 PolyStrata 数据迁移。

运行测试：从项目根目录执行 `powershell -ExecutionPolicy Bypass -File test/scripts/run-tests.ps1`。
所有 Python/Node 子进程的临时目录设为 `test/temp/`。

项目正式数据只使用 `chat/` 和 `character/`；参考图与角色资料一起保存在
`character/<角色名>/reference.png`。模型权重可位于项目外 `E:\LLM\models\`。

**注意：** 已有 Python `serve/test_*.py`、`frontend/launcher/tests/` 及引擎原有
`tests/` 是随代码维护的**单元测试源文件**，不是可删除的测试产物。它们保持在
对应的源码包中以避免破坏测试发现，但运行产生的临时数据必须进入本目录。
