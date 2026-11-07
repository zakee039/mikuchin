<div align="center">

<img src="assets/icon.png" alt="Mikuchin" width="96" height="96" />

# Mikuchin · Miku亲

**本地多模态 AI 伴侣与图像创作工作台**

**主程序 v0.2.5** · [下载 / GitHub Releases](https://github.com/zakee039/mikuchin/releases/tag/v0.2.5)

**独立版本：**主程序 `0.2.5` · Windows 启动器 `0.2.4` · Android 客户端 `0.2.4`（versionCode 204）。本次只更新主程序，启动器与 APK 沿用原版构建。

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

### 4. 实时硬件与推理遥测监控（Live Monitor）
- 实时可视化展示 GPU 显存占用（已用/总显存）、系统内存（RAM）、处理器与显卡型号。
- 实时追踪模型运行状态（运行中 / Prefill / 生成中 / 空闲卸载）、**Prefill 吞吐率（tok/s）**、**Decode 生成速度（tok/s）**、输入/输出 Token 累计统计、**会话 KV 缓存命中率** 以及近期请求的详细耗时拆解。

### 5. Windows 原生桌面管理器（Windows Native Manager）
- 基于 **Tauri 2 + Rust** 构建的轻量级原生桌面管理器与系统托盘程序。
- **模型与服务生命周期管理**：一键切换已注册的模型配置文件、手动加载/卸载模型（API 保持常驻）、进程崩溃看门狗自动守护、运行日志实时查看。
- **空闲自动卸载（Idle Unload）**：支持设置 `0–1440` 分钟空闲超时自动释放显存，配置更新时自动备份并平滑重启后端。
- **网络与远程接入管理**：一键开关局域网（LAN）访问、管理 API 密钥（基于 Windows DPAPI 加密保护），并集成 **Cloudflare Tunnel** 状态监控、HTTPS 延迟测试与隧道快速重启。

### 6. Android 手机客户端（内置用户态 Tailscale）
- **亮色自适应弹性移动端壳层**：专为不同屏幕比例手机打造的紧凑扁平化界面（延续 `#39C5BB` 薄荷绿主题），未登录时仅展示极简连接卡片；连接成功后**自动直达最近一次聊天会话**，左上角常驻历史记录抽屉按钮，底部配备无外框五维功能栏（`图像`、`角色`、`设置`、`监控`、`关于`）。
- **内置用户态 Tailscale（`tsnet`）网络模块**：
  - 基于官方 `tailscale.com/tsnet`（Go 编写并通过 `gomobile` 编译为原生 AAR）实现应用内独立组网。
  - **不使用 Android `VpnService`**：不占用系统 VPN 槽位，可在系统代理 VPN 运行时使用，但具体路由仍取决于设备与代理配置，无需 Root 权限，也无需安装官方 Tailscale 客户端。
- **分步式网页 OAuth 授权与硬件级安全**：
  - 支持 **「直接连接」** 与 **「Tailscale」** 双模式切换。在 Tailscale 模式下，先通过「Tailscale 网页授权登录」拉起浏览器完成 OAuth 授权并持久化节点状态，授权就绪后再展开 Mikuchin 接口与 Key 输入框。
  - API Key 采用 **Android Keystore (`AES/GCM/NoPadding`)** 硬件级加密存储；应用内部通过仅绑定 `127.0.0.1` 随机端口的 SOCKS5 与带一次性会话 Token 校验的本地 HTTP 反向代理统一承载原生校验、SSE 流式聊天与图片上传。

### 7. 全局中日英三语实时国际化（Trilingual i18n）
- 内置完整的 **简体中文（`zh-CN`）**、**日本語（`ja-JP`）** 与 **English（`en-US`）** 语言包。
- 在 Web 端顶部、设置页或 Windows 管理器中切换语言时，Web 界面、移动端壳层、Windows 管理器与系统托盘菜单同步实时更新；严格仅翻译 UI 控件，绝不翻译或改动用户的聊天内容、角色卡与提示词。

---

## 📂 项目目录结构

```text
mikuchin/
├── assets/                 # 官方品牌插画与权威图标资源 (icon.png, half.png, full.png)
├── backend/
│   ├── polystrata/         # 高性能本地推理引擎 (独立 Git 子模块)
│   └── services/           # 编排与引擎无关的服务基础设施
├── character/              # 独立于模型的角色卡 SQLite 数据库与角色参考图存储
├── chat/                   # 本地运行时会话数据库、生成图片与模型 KV 快照 (Git 忽略)
├── config/                 # 本机部署配置与活跃模型设置 (Git 忽略)
├── docs/                   # 产品宣传官网 (GitHub Pages: mikuchin.zakee.fun)
├── frontend/
│   ├── android/            # Android 原生客户端工程 (Kotlin + WebView + Go tsnetbridge)
│   ├── launcher/           # Windows 原生桌面管理器与安装包工程 (Tauri 2 + TypeScript + Rust)
│   ├── locales/            # 权威三语词典 (zh-CN.json, ja-JP.json, en-US.json)
│   └── web/                # 共享 Web 前端 (Chat / Images / Characters / Monitor / Settings / About)
└── scripts/                # 多语言构建、桌面启动器打包与运维脚本
```

## 🚀 快速开始与构建指南

### 1. 克隆仓库（含推理引擎子模块）
```bash
git clone --recurse-submodules https://github.com/zakee039/mikuchin.git
# 若已克隆主仓库，请初始化子模块：
git submodule update --init --recursive
```

### 2. 构建多语言词典与 Windows 桌面管理器
```powershell
# 重新生成前端三语包
python scripts/build-locales.py

# 构建 Windows 原生桌面管理器与 NSIS 安装包
powershell -ExecutionPolicy Bypass -File scripts/build-launcher.ps1
```

### 3. 一键编译 Android 手机客户端 APK
```powershell
powershell -ExecutionPolicy Bypass -File frontend/android/build-apk.ps1
# 编译产物输出至：frontend/android/Mikuchin.apk
```

## 📦 下载安装

前往 [GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest) 获取 Windows 安装包与 Android APK。**Windows 安装包不包含模型权重**；请在本机准备模型文件并通过启动器注册配置文件。

Android 提供「直接连接」和「Tailscale」两种模式。Tailscale 需先完成浏览器授权、在 Tailnet ACL/Grants 中允许 APK 节点访问后端，且目标机器防火墙需允许 API 端口。**Android 客户端不负责在手机上执行本地模型推理**，它连接你的 Mikuchin 服务。

v0.2.4 的 APK 已使用项目发布证书签名。如果你之前安装的是 Android Debug 证书签名的 APK，通常需要先卸载旧版再安装；请提前备份需要保留的应用内设置。可用性取决于模型文件、驱动、设备和网络环境，不能把构建成功视为全部真机功能已验证。

## 🔒 安全及项目说明

不要将 API Key、Tailscale 授权状态目录、模型文件或聊天数据上传到 GitHub。远程访问建议使用 Tailnet 等受控网络，并保留服务端 API Key 验证。代码和底层 PolyStrata 的许可及归属分别以仓库与子模块中的实际声明为准。
