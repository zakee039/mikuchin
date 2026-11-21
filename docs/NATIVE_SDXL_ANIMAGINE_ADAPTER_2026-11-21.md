# Native Mikuchin：SDXL Base 1.0 / Animagine XL 4.0 Opt 单文件模型接入

日期：2026-11-21｜仅修改 Native Mikuchin 自有源码，旧版 old-mixed 只读参考，官方 PolyStrata SHA 固定不变。

## 检查结论：文件与旧实现

在 `E:\LLM\models` 发现两个真实、完整存在的本地 Checkpoint：

- `SDXL-Base-1.0\sd_xl_base_1.0.safetensors`（6.462 GiB）
- `Animagine-XL-4.0-Opt\animagine-xl-4.0-opt.safetensors`（6.462 GiB）

本机未发现另一个名为 Anything 的独立 Checkpoint；Animagine 与 Anything 是不同名称，不要错误混同。

旧版 `E:\LLM\mikuchin-old\backend\polystrata\serve\images.py`（**只读参考，未修改**）确实包含 `family == "sdxl"`：以 `sd-cli --model <单文件>` 直接加载包含 UNet、CLIP-L/G 和 VAE 的 SDXL Checkpoint，默认 28 步、CFG 7.0、Euler 采样，支持 `--negative-prompt` 及 `--init-img --strength 0.65`。Qwen-Image Turbo 才使用 `--diffusion-model --vae --llm` 与 8 步 `--sigmas`。当前 Native 的 sd-cli --help 已确认具备这些参数。

## Native 实施边界

新增 `family:"sdxl"` 本地 Profile，与原 `qwen_turbo` 明确分离：

- 文件注册：本机 localhost + Bearer 的 `/v1/mikuchin/local-image-models` 接收 `{family:"sdxl", name, base_id, checkpoint}`，验证绝对路径、安全后缀、已配置 sd-cli；只继承可信的 backend / CPU offload / VAE tiling，移除 Qwen 特殊 flash-attn 参数，保留原有 2 个 Qwen Profile、LoRA、超分配置。重复注册同一 Checkpoint 返回原 Profile。
- 目录：两个家族均进入原 `/v1/mikuchin/image-models`，SDXL 标记 `steps=28`、`negative=true`、`reference_mode=single`、`family=sdxl`。Image Studio 与全局聊天生图选择器使用同一目录。
- 推理：Native Image Worker 在自己的 GPU 交接锁下调用同一 sd-cli，引擎分支生成 `--model checkpoint -p ... --steps 28 --cfg-scale 7.0`，不注入 Qwen 文本编码器或 Turbo sigmas；负面词 `--negative-prompt`；单张 img2img 图片先校正为目标尺寸再走 `--init-img ... --strength 0.65`。原 GPU 卸载/恢复及相同 Gallery/任务状态流程保留。
- 聊天 Tool Calling：选择 SDXL 时使用英文简洁场景描述/动漫标签的工具参数指导；SDXL 可以沿用全局选择的本地 GPU `exclusive` / `concurrent` 方式（3070 Ti 8GB 建议默认 exclusive），不允许直接混用 Qwen LoRA。
- UI：导入弹窗在「Qwen-Image Turbo 多组件」与「SDXL / Animagine XL 单文件」之间切换必填项；现有服务配置不被修改。

## 非承诺、核验与安全

隔离单测将检查旧 Qwen 和 SDXL 的文件隔离、CLI 参数、No Turbo sigmas、CPU offload 标志、Negative Prompt、img2img、错误文件拒绝、重复导入幂等和本机导入 HTTP 安全边界。隔离浏览器验证切换弹窗的 SDXL Checkpoint 字段。**单测命令执行由 Mock `_run` 返回，不能代表真实模型已经在 RTX 3070 Ti 8GB 上成功出图。**

生产阶段必须先检查 Native Turn 与 Image Worker 无在途任务、备份所有 SQLite 与 `runtime/launcher-user-data/images/config/native-local-images.json`，才能注册两个现有 Checkpoint；必要时在无人运行任务时由 Supervisor 安全重载 Gateway 和 Image Worker，官方 PolyStrata 不动。后台图像请求不可因重启自动重复提交；如果没有空闲窗口则保留代码待正式注册，不得假称上线。

## 状态

代码接入及对应测试完成。2026-11-21 首次正式环境预检发现 **一个进行中的图像任务和一个 running Native Turn**，按安全门槛先暂停生产写入和重启，没有中断当时用户正在生成的图片。

### 正式环境最终结果（上述暂停后继续）

- 已通过 SQLite Online Backup 备份原有 Turn、Conversations、Characters、Gallery、Image Jobs，以及现有本地模型注册、在线 API 服务、活跃模型 JSON 到 `runtime/migration-backups/native-sdxl-animagine-20261121-185749`；没有输出明文 API 密钥。
- 待原有 Image Job 和 Native Turn 自然结束后，重新确认 **0 个进行中的任务**再注册文件，不复制或修改原始 `.safetensors`。
- 注册 ID：`local-import-741b5e02696933` 对应 SDXL Base 1.0；`local-import-64d60e59dce22d` 对应 Animagine XL 4.0 Opt。目录合计四个本地模型，原有 `local-qwen-official`、`local-qwen-uncensored` 保持不变；四者注册文件就绪检查均为 True。
- 只重载 Mikuchin 独立 Image Worker（Supervisor worker restart 2）和 Gateway（Gateway restart 5）；官方 PolyStrata 引擎不改、不重启，子模块仍为 SHA `3e1642161198c50ff1abed4046f4e4f476099dbb`。可能存在空闲 Tailscale 浏览器长连接短暂重连，重载前无推理中的模型调用。
- 生产 Gateway 首页、`app.js`、本地模型导入 JS 和 Native Tool Client 均返回 HTTP 200；无 Key 的模型目录接口返回 HTTP 401；Worker 心跳正常。
- Python 全量测试 **145/145** 通过（包含动态 SDXL 工具描述和注册幂等）；Node **84/84** 通过；隔离浏览器实际验证 SDXL 导入切换只显示 Checkpoint 路径。
- **真实的 SDXL 或 Animagine GPU 出图尚未尝试**；目前只有可信文件路径与 Mock 执行的 CLI、图生图和结果保存验证，不可宣称 GPU 实测成功。生产目录后来出现更多用户的生成记录与短暂新 Turn，未人工重播这些任务。
