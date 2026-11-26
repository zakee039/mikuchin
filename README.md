<div align="center">

<img src="assets/icon.png" alt="Mikuchin" width="96" height="96" />

# Mikuchin · Miku亲

**本地多模态 AI 伴侣与图像创作工作台**

**主程序 v0.5.3** · [下载 / GitHub Releases](https://github.com/zakee039/mikuchin/releases/tag/v0.5.3)

**独立版本：**主程序 `0.5.3` · Windows 启动器 `0.5.3` · Android 客户端 `0.5.3`（versionCode 503）。本次三个组件均重新构建，详见 GitHub Release 资产清单。后续仍允许独立升级，所有版本号统一记录在 versions.json。

[产品官网](https://mikuchin.zakee.fun) · [个人主页](https://zakee.fun) · [Buy Me a Coffee](https://ifdian.net/a/zakee/plan)

[**简体中文**](README.md) · [**日本語**](README.ja-JP.md) · [**English**](README.en-US.md)

</div>

---

## 认识 Mikuchin（Miku亲）

**Mikuchin，也叫 Miku亲**，是一个面向个人使用的本地 AI 伴侣与创作工作台。它不只是聊天窗口：你可以在同一套界面中与模型对话、管理角色设定和世界书、处理图片参考与生成，并查看硬件资源和推理状态。

Mikuchin 使用 **PolyStrata** 作为本地推理引擎，提供浏览器工作台、Windows 托盘管理器，以及独立的 Android 客户端。安卓端可直接连接服务，或通过内置的用户态 Tailscale 加入自己的 Tailnet，远程访问运行在电脑上的 Mikuchin；**手机端本身不运行大模型**。

模型权重、会话记录、角色卡、生成图片等由你在自己的设备上管理。通过 Tailnet、Cloudflare Tunnel 或外部 MCP 服务联网时，仍应按实际网络路径和所用服务评估隐私与权限。

## ✨ 核心功能详解

### 1. 智能对话与持久化会话引擎（Chat & SessionV1）
- **低延迟流式交互**：支持实时 Token 流式输出、推理思考过程（Thinking）展开与折叠、多模态视觉输入（支持拖拽、粘贴与上传图片）以及代码高亮与复制。
- **按模型隔离的 SessionV1 KV 缓存**：本地 SQLite 会话数据库与每个模型的 KV 快照深度协同，支持长上下文秒级恢复、一键锁定/释放 KV、会话置顶、重命名及导出为 Markdown；删除会话时自动清理关联生成的图片与快照。
- **三种对话身份与上下文模式**：
  - **普通助手（Ordinary）**：继承全局用户身份（昵称与个人描述），拥有完整多轮上下文与 KV 记忆。
  - **无状态模式（Stateless）**：每次推理请求仅发送当前单轮消息，不携带历史上下文、用户身份、角色卡或外部 MCP 工具，适合独立指令测试；同时在界面中保留可见的聊天记录并允许调用内置生图工具。
  - **自定义角色（Custom Characters）**：加载专属角色卡设定、开场白、世界书与角色参考立绘。
- **原生工具调用**：支持接入外部 **MCP（Model Context Protocol）** 工具服务，并内置对话内 AI 生图工具（可根据对话语境自动生成配图）。

### 2. 角色工坊与世界书系统（Characters & Worldbook）
- **独立角色卡数据库**：基于 `character_cards.sqlite3` 存储，与底层推理模型解耦，完整兼容 SillyTavern `chara_card_v2` 规格角色卡导入与导出。
- **三级用户身份绑定**：每个角色可独立配置用户身份策略——`不使用用户身份`、`继承全局身份` 或 `角色专属独立身份`（切换模式时自动保留已填独立档案）。
- **会话级角色防篡改锁定**：新建空白对话在发送首条消息前可自由切换角色；一旦产生首条消息或角色问候语，当前会话即锁定该角色。历史记录列表中会自动渲染对应角色的彩色斜体水印标识。
- **角色立绘弱视觉参考**：每个角色支持上传参考图（自动归一化保存于 `character/<角色名>/reference.png`）。在启用官方 Qwen 图像模型且对话生图与角色主体相关时，服务端会自动将其作为弱身份/画风参考传入，同时优先遵循当前对话中的服饰、动作、节日与场景指令。
- **全自动实时保存（Autosave）**：角色基础设定、世界书（Worldbook）词条、Markdown 资料库、外部工作流绑定与全局设置均采用无感自动保存，切换角色时自动等待写入完成，防止编辑丢失。

### 3. 图像创作工作台（Image Studio）
- **多生图模型配置切换**（与聊天生图模型相互独立）：
  - **Qwen-Image 2.1 Turbo Official**：支持极速 8 步生图、基于 Qwen3-VL 视觉编码器的原生参考图编辑（`--ref-image`）以及允许列表内的 **Qwen LoRA** 挂载。
  - **Qwen-Image 2.1 Turbo Uncensored**：无限制文本编码器版本，共享 Turbo DiT 与 BF16 VAE。
  - **Animagine XL 4.0** & **SDXL Base 1.0**：支持标准 SDXL 文生图与真实图生图（`img2img`）。
- **三层提示词架构与「AI 一键解析」**：
  - 跨模型共享的 **自然语言描述** + 按模型独立持久化的 **Positive / Negative Prompt** 草稿。
  - 点击 **「一键解析（Parse with AI）」** 可调用当前活跃的大语言模型（以无状态单轮模式）将自然语言构思转化为专业英文正反提示词。
- **双轨参考图工作流**：支持 SDXL 原生 `img2img` 重绘、Qwen Official 原生参考图引导，或调用多模态视觉 LLM 将参考图解析为英文画面描述并追加至 Positive Prompt。
- **精细参数控制与一键清空**：支持独立选择画面长宽（`384` / `512` / `768` / `1024`）、采样步数、随机种子（Seed）与高清放大（Upscale）；提供「一键清空」重置当前输入与参考图而不误删已生成的作品；与聊天请求智能共享 GPU 队列。
- **OpenAI 兼容 API 生图（v0.2.9）**：在设置中集中管理服务、代理与 API Key，自动探测候选模型 ID；支持多参考图及按模型能力降级、生成阶段/耗时统计，并可手动启用本机 Real-ESRGAN 4× 超分。

### 4. 统一画廊（Gallery）
- **自动汇集、持久索引**：收录「生图」页面、本地模型/API 以及聊天内生成的图片。首次打开时补录历史作品，后续生成成功自动更新 `chat/gallery-index.sqlite3`，并为画廊建立缩略图缓存；不把个人图片上传到 GitHub。
- **筛选与大图查看**：可按来源（全部 / 生图 / 聊天 / 本地 / API）筛选，按新旧排序。点击缩略图放大，电脑使用左右方向键切换、`Esc` 退出，手机支持左右滑动。
- **原图与超分图合并**：同一作品的原图与 4× 超分结果只显示一张卡片，默认预览超分图，角标显示版本数（如 `2`）；详情中可以分别「删除原图」「删除4×」。
- **NSFW 遮罩**：右上角 NSFW 显示开关**默认关闭**，已标记图片以模糊遮罩展示，可单张临时查看、手动标记/取消，或多选后批量「标记为NSFW」。模型名含 `uncensored` 只是初始启发式，**不等于图像内容检测或安全隔离**。
- **多选与删除**：支持多选、全选已加载、取消选择和批量删除。普通删除和批量删除均按**整组**删除原图及超分图；删除前会确认，**永久删除不可恢复**，聊天历史若仍引用已删文件，其图片链接也会失效。

### 5. 实时硬件与推理遥测监控（Live Monitor）
- 实时可视化展示 GPU 显存占用（已用/总显存）、系统内存（RAM）、处理器与显卡型号。
- 实时追踪模型运行状态（运行中 / Prefill / 生成中 / 空闲卸载）、**Prefill 吞吐率（tok/s）**、**Decode 生成速度（tok/s）**、输入/输出 Token 累计统计、**会话 KV 缓存命中率** 以及近期请求的详细耗时拆解。

### 6. Windows 原生桌面管理器（Windows Native Manager）
- 基于 **Tauri 2 + Rust** 构建的轻量级原生桌面管理器与系统托盘程序。
- **模型与服务生命周期管理**：一键切换已注册的模型配置文件、手动加载/卸载模型（API 保持常驻）、进程崩溃看门狗自动守护、运行日志实时查看。
- **空闲自动卸载（Idle Unload）**：支持设置 `0–1440` 分钟空闲超时自动释放显存，配置更新时自动备份并平滑重启后端。
- **网络与远程接入管理**：一键开关局域网（LAN）访问、管理 API 密钥（基于 Windows DPAPI 加密保护），并集成 **Cloudflare Tunnel** 状态监控、HTTPS 延迟测试与隧道快速重启。

### 7. 从其它设备访问（Remote Access）

Mikuchin 的模型推理、会话和生成图片保存在运行服务的主机上。其它设备只需连接该主机，无须重复部署模型。请确保服务在线，API Key 有效，并按连接方式配置监听地址、防火墙和访问权限。

#### 7.1 桌面设备访问（Windows / Linux）

1. 在主机上启动 Mikuchin，并确认 API 端口（示例：`15239`）。
2. 在可信局域网内，通过另一台电脑的浏览器打开 `http://<主机局域网 IP>:15239/`；需要主机开启 LAN 监听，且防火墙允许访问。
3. 跨网络访问可通过已授权的 **Tailscale Tailnet** 或配置好访问控制的 **Cloudflare Tunnel HTTPS 域名**连接。输入 Mikuchin API Key 后即可使用聊天、生图和画廊。Mac 的浏览器访问方式也适用，见下方苹果设备小节。

#### 7.2 安卓设备访问（Android）

1. 从 [GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest) 下载并安装正式签名的 Mikuchin APK。**安卓客户端只连接远端推理服务，不在手机上运行大模型。**
2. 启动客户端后，选择 **「直接连接」** 或 **「Tailscale」**：
   - **直接连接**：输入可访问的服务地址（例如同一局域网地址，或自己的 HTTPS Cloudflare Tunnel 域名）和 Mikuchin API Key。
   - **Tailscale**：先通过「Tailscale 网页授权登录」完成浏览器授权，再填写目标 Mikuchin 服务信息和 API Key；确保 Tailnet ACL/Grants、主机监听和防火墙允许手机访问 API 端口。
3. 连接成功后即可使用聊天、生图和画廊。

**Android 客户端特性：**

- **亮色自适应弹性移动端壳层**：专为不同屏幕比例手机打造的紧凑扁平化界面（延续 `#39C5BB` 薄荷绿主题），未登录时仅展示极简连接卡片；连接成功后**自动直达最近一次聊天会话**，左上角常驻历史记录抽屉按钮，底部配备六项无外框功能栏（`生图`、`画廊`、`角色`、`设置`、`监控`、`关于`）。
- **内置用户态 Tailscale（`tsnet`）网络模块**：
  - 基于官方 `tailscale.com/tsnet`（Go 编写并通过 `gomobile` 编译为原生 AAR）实现应用内独立组网。
  - **不使用 Android `VpnService`**：不占用系统 VPN 槽位，可在系统代理 VPN 运行时使用，但具体路由仍取决于设备与代理配置，无需 Root 权限，也无需安装官方 Tailscale 客户端。
- **凭据与本地通信保护**：API Key 使用 **Android Keystore（`AES/GCM/NoPadding`）** 加密保存；应用内部以仅绑定 `127.0.0.1` 随机端口的 SOCKS5 和一次性会话 Token 校验的 HTTP 反向代理承载校验、SSE 流式聊天和图片上传。

**升级提醒：** v0.5.3 的 APK 已使用项目发布证书签名。如果你之前安装的是 Android Debug 证书签名的 APK，通常需要先卸载旧版再安装；请提前备份需要保留的应用内设置。可用性取决于模型文件、驱动、设备和网络环境，不能把构建成功视为全部真机功能已验证。

#### 7.3 苹果设备访问（iPhone / iPad / Mac）

**目前无需 Mac、Xcode、开发者签名或侧载 IPA。** Apple 设备直接使用 Mikuchin 的 Web 工作台：模型与会话仍运行/保存在你自己的 Mikuchin 主机上，iPhone/iPad/Mac 负责访问网页。**这是免安装的浏览器/主屏幕快捷方式，不是原生 iOS/macOS 客户端。**

##### iPhone / iPad：Stash + Tailscale + Safari

1. **准备主机**：在 Windows 上启动 Mikuchin，确保服务持续运行；启用允许 Tailnet 地址访问的监听方式（例如 LAN 访问），让系统防火墙放行所用 API 端口（默认示例 `15239`）。在 Tailscale ACL/Grants 中允许 Apple 设备访问此主机和端口。无需向公网开放端口。
2. **在 Stash 加入 Tailnet**：使用支持内置 Tailscale 的 Stash（iOS 3.4+；推荐 3.6+ 以使用 Tailnet 路由自动识别）。在现有 Stash 配置的 `proxies` 中**追加**如下节点，不要覆盖其他代理；然后进入该节点的 **Tailscale** 菜单完成浏览器交互授权。不要把 Tailscale 的认证密钥写入公开配置：

   ```yaml
   proxies:
     - name: mikuchin-tailnet
       type: tailscale
   ```

   Stash 3.6+ 可自动处理 Tailnet 地址路由和 MagicDNS；**不必再同时开启官方 Tailscale VPN**，从而避免 iOS 单 VPN 槽位冲突。不同 Stash 版本或分流规则可能仍需按实际网络调整。参考 [Stash 内置 Tailscale](https://stash.wiki/proxy-protocols/proxy-types#tailscale) 与 [Stash 内网穿透](https://stash.wiki/features/nat-traversal)。
3. **Safari 打开 Mikuchin**：在 Stash 的 Tailnet 节点已连接后，打开 `http://<MIKUCHIN_HOST_TAILNET_IP>:15239/`（将占位符换成运行 Mikuchin 电脑的 Tailscale IPv4 和实际端口），或使用可解析的 MagicDNS 主机名；在网页按提示输入 **Mikuchin API Key**。若无法连接，先检查主机是否在线、监听地址、防火墙、Tailnet 授权和 Stash 的路由策略。
4. **固定到主屏幕**：Safari 打开成功后，点击 **分享 → 添加到主屏幕**，如有 **「作为网页 App 打开 / Open as Web App」** 选项可开启，再点「添加」。此后可像启动应用一样从桌面图标进入。网页图标不会让模型在手机端离线运行，也不是可侧载的 `.ipa`。参考 [Apple 官方操作说明](https://support.apple.com/guide/iphone/iphea86e5236/ios)。

##### 其他 Apple 接入方式

- **没有 Stash 的 iPhone/iPad**：可使用官方 [Tailscale iOS 客户端](https://tailscale.com/docs/install/ios) 加入同一 Tailnet，再用 Safari 打开上述地址；若需要同时使用另一款系统级代理 VPN，须考虑 iOS 的 VPN 配置互斥。
- **不使用 Tailnet**：可使用自己配置并授权的 **HTTPS Cloudflare Tunnel 域名**，直接在 Safari 打开并完成 API Key 验证；不要把 [项目官网](https://mikuchin.zakee.fun) 误当作个人推理服务地址。
- **Mac**：用 Safari/其他浏览器通过 Tailnet 地址或已配置的 HTTPS 域名直接打开 Web 工作台即可；无需编译专用 Mac 程序。

**安全说明：** `http://` 地址在**正确建立的 Tailscale 加密隧道内部**传输时受到隧道层加密，但 HTTP 本身没有 HTTPS 的浏览器端 TLS/安全上下文属性；对浏览器安全上下文有要求时请使用有效证书的 HTTPS 入口。务必保留 API Key 验证和 Tailnet ACL，不要通过明文公网 HTTP 暴露服务。网络断开、主机休眠或重启期间，主屏幕图标也无法独立连接模型。

### 8. 全局中日英三语实时国际化（Trilingual i18n）
- 内置完整的 **简体中文（`zh-CN`）**、**日本語（`ja-JP`）** 与 **English（`en-US`）** 语言包。
- 在 Web 端顶部、设置页或 Windows 管理器中切换语言时，Web 界面、移动端壳层、Windows 管理器与系统托盘菜单同步实时更新；严格仅翻译 UI 控件，绝不翻译或改动用户的聊天内容、角色卡与提示词。

---

## 📂 项目目录结构

```text
mikuchin/
├── assets/                 # 官方品牌插画与权威图标资源 (icon.png, half.png, full.png)
├── backend/
│   ├── polystrata/         # 内置的本地推理引擎源码（随 Mikuchin 一同维护）
│   └── services/           # 编排与引擎无关的服务基础设施
├── character/              # 独立于模型的角色卡 SQLite 数据库与角色参考图存储
├── chat/                   # 本地运行时会话数据库、生成图片与模型 KV 快照 (Git 忽略)
├── config/                 # 本机部署配置与活跃模型设置 (Git 忽略)
├── docs/                   # 产品宣传官网 (GitHub Pages: mikuchin.zakee.fun)
├── frontend/
│   ├── android/            # Android 原生客户端工程 (Kotlin + WebView + Go tsnetbridge)
│   ├── launcher/           # Windows 原生桌面管理器与安装包工程 (Tauri 2 + TypeScript + Rust)
│   ├── locales/            # 权威三语词典 (zh-CN.json, ja-JP.json, en-US.json)
│   └── web/                # 共享 Web 前端 (Chat / 生图 / 画廊 / Characters / Monitor / Settings / About)
└── scripts/                # 多语言构建、桌面启动器打包与运维脚本
```

## 🚀 快速开始与构建指南

### 1. 克隆仓库（包含官方 PolyStrata 子模块）
```bash
git clone --recurse-submodules https://github.com/zakee039/mikuchin.git
# 已有仓库，请在其根目录执行：git submodule update --init --recursive
```

新版 main 将官方 PolyStrata 固定为 Git 子模块（v0.2.20-poly.5），不修改其源码，也不依赖个人 Fork。推理权重、驱动、Python/CUDA 运行时和生图后端需要单独安装；现有 Windows Launcher 安装包并不是完整的可搬迁运行时。旧版混合架构保留于 old-mixed。详见 [Native 迁移记录](docs/NATIVE_V040_MAIN_MIGRATION_2026-11-21.md)、[官方引擎 MIT 许可](backend/polystrata/LICENSE) 和 [第三方声明](THIRD_PARTY_NOTICES.md)。

### 2. 构建多语言词典与 Windows 桌面管理器
```powershell
# 重新生成前端三语包
python scripts/build-locales.py

# Native Launcher 本地预览构建（不包含完整 Python/GPU 运行时）
cd frontend/launcher
npm ci
npx tauri build --debug --no-bundle
cd ../..
```

### 3. 一键编译 Android 手机客户端 APK
```powershell
powershell -ExecutionPolicy Bypass -File frontend/android/build-apk.ps1
# 编译产物输出至：frontend/android/Mikuchin.apk
```

## 📥 模型准备与下载说明

> 💡 **最简单的部署方法**：核心推理部署使用 **PolyStrata**。如果你不想手动折腾配置，**直接将本仓库复制给你的 AI 助手，让她帮你拉取模型并完成部署～**

Windows 安装包与源码仓库不包含模型权重文件，请按需准备以下 GGUF / Safetensors 模型并放入你的模型目录（如 `models/`），再通过 Windows 启动器或配置文件注册：

### 1. 对话与多模态视觉主模型（Chat & Vision LLM，共 2 个文件）
用于日常对话、角色扮演、图片理解（识图）以及画图完成后的角色视觉反馈：
- `G4-MeroMero-26B-A4B-it-uncensored-heretic-Q4_K_M.gguf`（主语言模型 4-bit 量化权重）
- `G4-MeroMero-26B-A4B-it-uncensored-heretic-mmproj-BF16.gguf`（BF16 多模态视觉投影器 `mmproj`）
- **下载源**：Hugging Face [`llmfan46/G4-MeroMero-26B-A4B-it-uncensored-heretic-GGUF`](https://huggingface.co/llmfan46/G4-MeroMero-26B-A4B-it-uncensored-heretic-GGUF)

### 2. 图像生成模型套件（Qwen-Image 2.1 生图组件，共 5 个文件）
用于聊天内自动作画与「图像创作工作台（Image Studio）」：
- `Qwen-Image-2.1-Turbo-AD-Q4_K.gguf` — 8 步极速生图主模型 DiT（[`AtomicChat/Qwen-Image-2.1-Turbo-GGUF`](https://huggingface.co/AtomicChat/Qwen-Image-2.1-Turbo-GGUF)）
- `qwen_image_2.1-Q4_K.gguf` — 标准多步生图主模型 DiT（[`leejet/Qwen-Image-2.1-GGUF`](https://huggingface.co/leejet/Qwen-Image-2.1-GGUF)）
- `Qwen3VL-8B-Instruct-Q4_K_M.gguf` — 文本编码器 Text Encoder（[`Qwen/Qwen3-VL-8B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF)）
- `mmproj-Qwen3VL-8B-Instruct-F16.gguf` — 原生参考图编辑（`--ref-image`）视觉投影器（[`Qwen/Qwen3-VL-8B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF)）
- `qwen_image_2.1_vae_bf16.safetensors` — 共享 BF16 VAE 解码器（[`unsloth/Qwen-Image-2.1-FP8`](https://huggingface.co/unsloth/Qwen-Image-2.1-FP8) `vae/` 目录）

> 也可使用 PolyStrata 内置脚本一键编译生图后端并拉取基础组件：`python backend/polystrata/terminal/tools/image/install.py --models-dir models`。此外，图像工作台同样兼容标准 SDXL 单文件权重（如 `Animagine XL 4.0 Opt`、`SDXL Base 1.0`）。

## 📦 下载安装

前往 [GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest) 获取 Windows 安装包与 Android APK。**Windows 安装包不包含模型权重**；请在本机准备模型文件并通过启动器注册配置文件。

## 🔒 安全及项目说明

不要将 API Key、Tailscale 授权状态目录、模型文件或聊天数据上传到 GitHub。远程访问建议使用 Tailnet 等受控网络，并保留服务端 API Key 验证。代码和底层 PolyStrata 的许可及归属分别以仓库与子模块中的实际声明为准。
