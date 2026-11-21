# Native P2：Uncensored 生图与画廊手动 4× 真实验收（2026-11-21）

工作分支 `refactor/official-polystrata-gateway`；独立 Native Gateway 15249 / Official 15240 / Image Worker，正式 main 和 15239 不运行、不变更。**没有调用在线收费 API**，所有图片操作使用本地 Qwen-Image 与 Real-ESRGAN。

## 验收前安全门

- 原生 ImageJobStore：没有 queued / working / running 任务；独立 GPU 文件锁 `busy=false`。
- 官方引擎 `/metrics.live.state=idle`，Gateway `/health=ok`。
- Native `/v1/mikuchin/image-models`：`local-qwen-official`、`local-qwen-uncensored` 均 `available=true`，Real-ESRGAN `native_upscaler_ready=true`；Image Worker 已就绪。

## 实际 Uncensored 本地图片生成

- 使用 `local-qwen-uncensored`（生成结果标记 `qwen-image-2.1-turbo-uncensored`），`384×384`、4 步、seed 1138、`strata_lora_id=none`、`strata_upscale=off`。测试内容仅为简洁薄荷绿星形插画，非个人图像。
- 显式 **POST 一次** `/v1/mikuchin/image-jobs`，后续只查询任务状态；不做自动重试。提交回执 `state=running,phase=排队等待执行,started_at=null`，随后 Worker 真正进入推理时开始计时。
- 原始任务 `img-501cd579eebb9ba53192cb03` 最终 `success`，`elapsed_s=166.4`；画廊原图 `d3fdfc5d062ad58bb07227edc32f272b` 是经 Pillow 校验的有效 **384×384 PNG**，大小 79,732 字节；原作品 `provider=local,variant_count=1`。
- GPU 路径经过官方 LLM 临时释放 → 本地 sd-cli 推理 → 官方 LLM 恢复，结束后 Gateway 和 Worker 状态均正常。166.4 秒为单次实际观察值，**不是性能基准**。

## 真实「已有作品手动 4×」

- 对上述原图只提交一次 `kind=upscale`，Image Worker 原地使用已配置 Real-ESRGAN；没有重新调用原生 Qwen-Image 或在线提供商。
- 任务 `img-52cad9b26885a91e9d2927f2` 为 `success`，`elapsed_s=7.2`；生成有效 **1536×1536 PNG**，文件 265,916 字节。原图仍为 384×384，有效 PNG 不变。
- Gallery `detail` 对原图 ID 返回新封面 `04609f77ddfd4ab5f73380c1dee25fe2`，`variant_count=2`，`variants.original` 指回原图，`variants.upscaled` 指向新封面。
- 再次 POST 相同源图 `kind=upscale` 返回**同一个成功任务 ID**且 `already_submitted=true`，未产生第二次 4× 生成。

## 只清理本次测试产物

- 经原生鉴权 Gallery delete 只删除该封面所在作品组，实际 `deleted_groups=1,deleted=2,failed=0`；两个图片文件均不存在。
- 两个专用 image job 记录均被精确 ID 删除，之后查询均为 `unknown`；临时恢复标记已删除。其余用户图库、聊天、配置、密钥、模型和正式 main 不改动。
- 清理后 `/health=ok`，官方模型 `loaded=true, live.state=idle`，Image Worker 正常，GPU 锁空闲，Native 启动器继续运行。

## 尚未完成的 P2 问题

- **Official 单图参考已在本日后续实机验证成功**：见下节；Uncensored 仍 `reference_mode=none`，不可混用不同 LLM 的视觉投影文件。
- 本次没有评估二次元美学质量或对比 Official/Uncensored 的图像偏好；有效 PNG、模型调用和安全性验证不等于主观质量测评。
- Native 独立 Cloudflare Tunnel/Android 访问与正式打包属于 P3，尚未因这次测试而完成。

## 后续：Official 单张参考图真实 GPU 验收

- 本机已存在与 Official `Qwen3VL-8B-Instruct-Q4_K_M.gguf` 相配套的 `E:\LLM\models\Qwen-Image-2.1-Official-Components\mmproj-Qwen3VL-8B-Instruct-F16.gguf`。**只在独立 Native Official 配置**加入 `llm_vision`；原有 Native 配置备份为 `native-local-images.json.pre-vision-20261121.bak`。Uncensored 使用不同 LLM，**不启用该 mmproj**。配置生成脚本 `scripts/configure-native-local-images.ps1` 改为仅在 Official 匹配的文件存在时加入；临时目录干运行验证成功（不会重建用户配置或覆盖数据）。
- `sd-cli --help` 确认支持 `--llm_vision` 和 `--ref-image`，Native `GET /v1/mikuchin/image-models` 现场返回 Official `reference_mode=single`、Uncensored `reference_mode=none`，两者均 `available=true`。
- Python 单元测试以伪造 `sd-cli` 验证单张 PNG 被转为私有参考图文件，CLI 同时传入 `--llm_vision` 与 `--ref-image`；没有 `llm_vision` 时提交参考图严格拒绝。此单测不能代替真实运行。
- 单次真实 Native Official 请求：使用本地 Pillow 创建的 **128×128 薄荷绿三角形** PNG 作为参考，要求模型生成一张基于其几何轮廓的干净小图；参数 Official、`256×256`、4 steps、seed 1183、`strata_reference_mode=single`、一份 `strata_reference_assets`、`strata_upscale=off`。只提交一次，不触发任何在线 API。
- 任务 `img-55ab245a995986560af8450d` 实机 `success`，耗时 **170.6 秒**；生成 `8a4e31c75ce319356865bf5a8d88a8ce` 为有效 **256×256 PNG**（43,164 字节），`provider=local`、画廊 `variant_count=1`，私有参考素材 SHA256 校验/有效 PNG/尺寸 128×128 均通过。Worker 完成后官方文本 LLM 成功恢复。
- **验收口径**：证明 Official 经真实 GPU 执行成功、参考图路径及视觉投影参数成功加载，**尚未以视觉评价或指标证明生成结果忠实保留了参考三角形、姿态/人物一致性或一般图生图质量**。Uncensored 图生图未验收，仍关闭该能力。
- 只清理本次生成的图片、任务及不被其他任务引用的私有 reference asset，Gallery delete `deleted_groups=1,deleted=1,failed=0`；输入临时 PNG、恢复标记也已删除，未动其他用户作品。保留 Native Official 已验证的 `llm_vision` 配置及可恢复备份。
