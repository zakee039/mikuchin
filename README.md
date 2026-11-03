<div align="center">

<img src="assets/icon.png" alt="Mikuchin" width="96" height="96" />

# Mikuchin

**个人本地多模态 AI 伴侣与创作工作台 · Personal Multimodal AI Companion & Creative Studio**

**Current Release: `v0.2.4`**

[个人主页](https://zakee.fun) · [Buy Me a Coffee](https://ifdian.net/a/zakee/plan)

[**简体中文**](#-mikuchin-简体中文) · [**日本語**](#-mikuchin-日本語) · [**English**](#-mikuchin-english)

</div>

---

## 🇨🇳 Mikuchin（简体中文）

**Mikuchin** 是围绕高性能本地推理引擎 **PolyStrata** 构建的跨端个人 AI 伴侣、角色扮演与图像创作系统，涵盖 **桌面/移动自适应 Web 工作台**、**Windows 原生服务管理器（Tauri 2）** 以及 **内置用户态 Tailscale 网络的 Android 手机客户端**。所有模型权重、对话历史、角色设定、生成的图像与 KV 缓存均保存在你自己的设备上，隐私安全可控。

### ✨ 核心功能详解

#### 1. 智能对话与持久化会话引擎（Chat & SessionV1）
- **低延迟流式交互**：支持实时 Token 流式输出、推理思考过程（Thinking）展开与折叠、多模态视觉输入（支持拖拽、粘贴与上传图片）以及代码高亮与复制。
- **按模型隔离的 SessionV1 KV 缓存**：本地 SQLite 会话数据库与每个模型的 KV 快照深度协同，支持长上下文秒级恢复、一键锁定/释放 KV、会话置顶、重命名及导出为 Markdown；删除会话时自动清理关联生成的图片与快照。
- **三种对话身份与上下文模式**：
  - **普通助手（Ordinary）**：继承全局用户身份（昵称与个人描述），拥有完整多轮上下文与 KV 记忆。
  - **无状态模式（Stateless）**：每次推理请求仅发送当前单轮消息，不携带历史上下文、用户身份、角色卡或外部 MCP 工具，适合独立指令测试；同时在界面中保留可见的聊天记录并允许调用内置生图工具。
  - **自定义角色（Custom Characters）**：加载专属角色卡设定、开场白、世界书与角色参考立绘。
- **原生工具调用**：支持接入外部 **MCP（Model Context Protocol）** 工具服务，并内置对话内 AI 生图工具（可根据对话语境自动生成配图）。

#### 2. 角色工坊与世界书系统（Characters & Worldbook）
- **独立角色卡数据库**：基于 `character_cards.sqlite3` 存储，与底层推理模型解耦，完整兼容 SillyTavern `chara_card_v2` 规格角色卡导入与导出。
- **三级用户身份绑定**：每个角色可独立配置用户身份策略——`不使用用户身份`、`继承全局身份` 或 `角色专属独立身份`（切换模式时自动保留已填独立档案）。
- **会话级角色防篡改锁定**：新建空白对话在发送首条消息前可自由切换角色；一旦产生首条消息或角色问候语，当前会话即锁定该角色。历史记录列表中会自动渲染对应角色的彩色斜体水印标识。
- **角色立绘弱视觉参考**：每个角色支持上传参考图（自动归一化保存于 `character/<角色名>/reference.png`）。在启用官方 Qwen 图像模型且对话生图与角色主体相关时，服务端会自动将其作为弱身份/画风参考传入，同时优先遵循当前对话中的服饰、动作、节日与场景指令。
- **全自动实时保存（Autosave）**：角色基础设定、世界书（Worldbook）词条、Markdown 资料库、外部工作流绑定与全局设置均采用无感自动保存，切换角色时自动等待写入完成，防止编辑丢失。

#### 3. 图像创作工作台（Image Studio）
- **多生图模型配置切换**（与聊天生图模型相互独立）：
  - **Qwen-Image 2.1 Turbo Official**：支持极速 8 步生图、基于 Qwen3-VL 视觉编码器的原生参考图编辑（`--ref-image`）以及允许列表内的 **Qwen LoRA** 挂载。
  - **Qwen-Image 2.1 Turbo Uncensored**：无限制文本编码器版本，共享 Turbo DiT 与 BF16 VAE。
  - **Animagine XL 4.0** & **SDXL Base 1.0**：支持标准 SDXL 文生图与真实图生图（`img2img`）。
- **三层提示词架构与「AI 一键解析」**：
  - 跨模型共享的 **自然语言描述** + 按模型独立持久化的 **Positive / Negative Prompt** 草稿。
  - 点击 **「一键解析（Parse with AI）」** 可调用当前活跃的大语言模型（以无状态单轮模式）将自然语言构思转化为专业英文正反提示词。
- **双轨参考图工作流**：支持 SDXL 原生 `img2img` 重绘、Qwen Official 原生参考图引导，或调用多模态视觉 LLM 将参考图解析为英文画面描述并追加至 Positive Prompt。
- **精细参数控制与一键清空**：支持独立选择画面长宽（`384` / `512` / `768` / `1024`）、采样步数、随机种子（Seed）与高清放大（Upscale）；提供「一键清空」重置当前输入与参考图而不误删已生成的作品；与聊天请求智能共享 GPU 队列。

#### 4. 实时硬件与推理遥测监控（Live Monitor）
- 实时可视化展示 GPU 显存占用（已用/总显存）、系统内存（RAM）、处理器与显卡型号。
- 实时追踪模型运行状态（运行中 / Prefill / 生成中 / 空闲卸载）、**Prefill 吞吐率（tok/s）**、**Decode 生成速度（tok/s）**、输入/输出 Token 累计统计、**会话 KV 缓存命中率** 以及近期请求的详细耗时拆解。

#### 5. Windows 原生桌面管理器（Windows Native Manager）
- 基于 **Tauri 2 + Rust** 构建的轻量级原生桌面管理器与系统托盘程序。
- **模型与服务生命周期管理**：一键切换已注册的模型配置文件、手动加载/卸载模型（API 保持常驻）、进程崩溃看门狗自动守护、运行日志实时查看。
- **空闲自动卸载（Idle Unload）**：支持设置 `0–1440` 分钟空闲超时自动释放显存，配置更新时自动备份并平滑重启后端。
- **网络与远程接入管理**：一键开关局域网（LAN）访问、管理 API 密钥（基于 Windows DPAPI 加密保护），并集成 **Cloudflare Tunnel** 状态监控、HTTPS 延迟测试与隧道快速重启。

#### 6. Android 手机客户端（内置零冲突用户态 Tailscale）
- **亮色自适应弹性移动端壳层**：专为不同屏幕比例手机打造的紧凑扁平化界面（延续 `#39C5BB` 薄荷绿主题），未登录时仅展示极简连接卡片；连接成功后**自动直达最近一次聊天会话**，左上角常驻历史记录抽屉按钮，底部配备无外框五维功能栏（`图像`、`角色`、`设置`、`监控`、`关于`）。
- **内置用户态 Tailscale（`tsnet`）网络模块**：
  - 基于官方 `tailscale.com/tsnet`（Go 编写并通过 `gomobile` 编译为原生 AAR）实现应用内独立组网。
  - **不使用 Android `VpnService`**：绝不抢占系统唯一 VPN 槽位，**可与 Clash Mi / Mihomo 等系统代理 VPN 同时运行**，无需 Root 权限，也无需安装官方 Tailscale 客户端。
- **分步式网页 OAuth 授权与硬件级安全**：
  - 支持 **「直接连接」** 与 **「Tailscale」** 双模式切换。在 Tailscale 模式下，先通过「Tailscale 网页授权登录」拉起浏览器完成 OAuth 授权并持久化节点状态，授权就绪后再展开 Mikuchin 接口与 Key 输入框。
  - API Key 采用 **Android Keystore (`AES/GCM/NoPadding`)** 硬件级加密存储；应用内部通过仅绑定 `127.0.0.1` 随机端口的 SOCKS5 与带一次性会话 Token 校验的本地 HTTP 反向代理统一承载原生校验、SSE 流式聊天与图片上传。

#### 7. 全局中日英三语实时国际化（Trilingual i18n）
- 内置完整的 **简体中文（`zh-CN`）**、**日本語（`ja-JP`）** 与 **English（`en-US`）** 语言包。
- 在 Web 端顶部、设置页或 Windows 管理器中切换语言时，Web 界面、移动端壳层、Windows 管理器与系统托盘菜单同步实时更新；严格仅翻译 UI 控件，绝不翻译或改动用户的聊天内容、角色卡与提示词。

---

### 📂 项目目录结构

```text
mikuchin/
├── assets/                 # 官方品牌插画与权威图标资源 (icon.png, half.png, full.png)
├── backend/
│   ├── polystrata/         # 高性能本地推理引擎 (独立 Git 子模块)
│   └── services/           # 编排与引擎无关的服务基础设施
├── character/              # 独立于模型的角色卡 SQLite 数据库与角色参考图存储
├── chat/                   # 本地运行时会话数据库、生成图片与模型 KV 快照 (Git 忽略)
├── config/                 # 本机部署配置与活跃模型设置 (Git 忽略)
├── docs/                   # 架构说明、各特性设计规范与版本发布记录
├── frontend/
│   ├── android/            # Android 原生客户端工程 (Kotlin + WebView + Go tsnetbridge)
│   ├── launcher/           # Windows 原生桌面管理器与安装包工程 (Tauri 2 + TypeScript + Rust)
│   ├── locales/            # 权威三语词典 (zh-CN.json, ja-JP.json, en-US.json)
│   └── web/                # 共享 Web 前端 (Chat / Images / Characters / Monitor / Settings / About)
└── scripts/                # 多语言构建、桌面启动器打包与运维脚本
```

### 🚀 快速开始与构建指南

#### 1. 克隆仓库（含推理引擎子模块）
```bash
git clone --recurse-submodules https://github.com/zakee039/mikuchin.git
# 若已克隆主仓库，请初始化子模块：
git submodule update --init --recursive
```

#### 2. 构建多语言词典与 Windows 桌面管理器
```powershell
# 重新生成前端三语包
python scripts/build-locales.py

# 构建 Windows 原生桌面管理器与 NSIS 安装包
powershell -ExecutionPolicy Bypass -File scripts/build-launcher.ps1
```

#### 3. 一键编译 Android 手机客户端 APK
```powershell
powershell -ExecutionPolicy Bypass -File frontend/android/build-apk.ps1
# 编译产物输出至：frontend/android/Mikuchin.apk
```

---

## 🇯🇵 Mikuchin（日本語）

[个人主页](https://zakee.fun) · [Buy Me a Coffee](https://ifdian.net/a/zakee/plan)

**Mikuchin** は、高性能ローカル推論エンジン **PolyStrata** を中核に据えたマルチプラットフォーム対応のパーソナル AI コンパニオン＆クリエイティブスタジオです。**デスクトップ／モバイル対応 Web ワークスペース**、**Windows ネイティブマネージャー（Tauri 2）**、そして**ユーザー空間 Tailscale ネットワークを内蔵した Android クライアント**を提供します。モデルの重み、会話履歴、キャラクター設定、生成画像、KV キャッシュはすべてローカルデバイス上に保存され、外部に送信されることはありません。

### ✨ 主な機能

1. **インテリジェントチャット＆SessionV1 エンジン**
   - リアルタイムのトークンストリーミング出力、思考プロセス（Thinking）の折りたたみ表示、マルチモーダル画像認識（ドラッグ＆ドロップ・貼り付け・アップロード）、MCP 外部ツール連携およびチャット内画像生成ツールを搭載。
   - **モデル別 SessionV1 KV キャッシュ**：SQLite データベースとモデルごとの KV スナップショットにより、長文コンテキストの高速復元、KV のロック／解放、ピン留め、Markdown エクスポートに対応。
   - **3つの会話モード**：「通常アシスタント（グローバルユーザー設定と履歴を継承）」「ステートレスモード（履歴やキャラクターを含めず現在の1ターンのみを送信しつつ、画面上の履歴保存と画像生成は維持）」「カスタムキャラクター」。

2. **キャラクタースタジオ＆ワールドブック（Worldbook）**
   - モデルから独立した `character_cards.sqlite3` により、SillyTavern `chara_card_v2` 形式のインポート／エクスポートに完全対応。
   - **3段階のユーザーアイデンティティ設定**：キャラクターごとに「ユーザー情報なし」「グローバル設定を継承」「キャラクター固有のユーザー設定」を選択可能。
   - **セッション単位のロールロック**：最初のメッセージ送信後に会話のキャラクターを固定し、履歴一覧にはキャラクター名のカラー透かしラベルを表示。
   - **キャラクター立ち絵の弱参照機能**：キャラクターに参照画像（`reference.png`）を登録すると、公式 Qwen 画像モデルでのチャット内画像生成時に画風・外見の弱い参照として自動活用（服装やシーンは会話の指示を最優先）。すべての編集は自動保存（Autosave）されます。

3. **画像生成スタジオ（Image Studio）**
   - **複数モデルプロファイル対応**：**Qwen-Image 2.1 Turbo Official**（8ステップ高速生成、`--ref-image` ネイティブ参照編集、Qwen LoRA 対応）、**Qwen-Image 2.1 Turbo Uncensored**、**Animagine XL 4.0**、**SDXL Base 1.0**（`img2img` 対応）を自由に切り替え可能。
   - **3層プロンプト＆AI ワンクリック解析**：モデル間で共有される「自然言語入力」と、モデルごとに保存される「Positive / Negative Prompt」下書きを備え、現在の LLM を使って自然言語から英語プロンプトへの自動変換が可能。
   - 縦横サイズの個別指定（`384` / `512` / `768` / `1024`）、ステップ数、シード値、アップスケール、LoRA 選択、ワンクリッククリアに対応。

4. **リアルタイムハードウェア＆推論モニター（Monitor）**
   - GPU VRAM 使用量、システム RAM、Prefill / Decode 速度（tok/s）、入出力トークン統計、KV キャッシュヒット率、直近リクエストのレイテンシをリアルタイム表示。

5. **Windows ネイティブマネージャー（Tauri 2）**
   - システムトレイ常駐、モデル設定のワンクリック切り替え、プロセスのウォッチドッグ監視、アイドル時の自動アンロード（0〜1440分）、LAN アクセス制御、Windows DPAPI による認証情報保護、および **Cloudflare Tunnel** の状態監視・遅延テスト・再起動をサポート。

6. **Android クライアント（ユーザー空間 Tailscale `tsnet` 内蔵）**
   - **ライトテーマ＆伸縮レイアウト**：ログイン前はシンプルな接続画面のみを表示し、接続後は**最新のチャット画面へ直行**。左上の履歴ドロワーボタンと、枠線のない下部5ボタンナビゲーション（画像・キャラクター・設定・モニター・概要）を搭載。
   - **VPN 競合ゼロの Tailscale 統合**：公式 `tailscale.com/tsnet`（Go + `gomobile` AAR）をアプリ内に内蔵。**Android の `VpnService` を一切使用しない**ため、Clash Mi / Mihomo などのシステム VPN と完全共存でき、Root 化や公式 Tailscale アプリの導入も不要です。
   - **2段階 Web OAuth 認証＆Keystore 暗号化**：Tailscale モードでは先にブラウザで OAuth デバイス認証を完了してからエンドポイントと API キー入力欄を展開。API キーは Android Keystore（`AES/GCM/NoPadding`）で暗号化保存されます。

7. **日・中・英 3言語リアルタイム切り替え（i18n）**
   - Web UI、モバイル画面、Windows マネージャー、トレイメニューの表示言語を `简体中文` / `日本語` / `English` 間で即座に切り替え可能（会話本文やキャラクター設定は翻訳されません）。

---

## 🌐 Mikuchin (English)

[个人主页](https://zakee.fun) · [Buy Me a Coffee](https://ifdian.net/a/zakee/plan)

**Mikuchin** is a cross-platform personal multimodal AI companion and creative studio built around the **PolyStrata** local inference engine. It combines an **adaptive desktop/mobile Web workspace**, a **native Windows Manager (Tauri 2)**, and a **native Android client with built-in user-space Tailscale networking**. All model weights, conversations, character cards, generated artwork, and KV snapshots stay strictly on your own hardware.

### ✨ Key Features

1. **Conversational AI & SessionV1 Engine**
   - Real-time token streaming, collapsible reasoning (`Thinking`) traces, multimodal vision input (drag-and-drop, clipboard paste, or file upload), external **MCP (Model Context Protocol)** tool execution, and in-chat image generation.
   - **Per-Model SessionV1 KV Persistence**: SQLite session storage paired with per-model KV cache snapshots enables instant long-context resumption, one-click KV lock/release, session pinning, renaming, and Markdown export. Deleting a session automatically cleans up its generated images and KV snapshots.
   - **Three Conversation Modes**: **Ordinary Assistant** (inherits global user identity and multi-turn memory), **Stateless Mode** (sends only the current turn to the model without history, identity, or character cards while still saving visible chat logs and supporting built-in image generation), and **Custom Characters**.

2. **Character Studio & Worldbook**
   - Backed by a model-independent SQLite store (`character_cards.sqlite3`) with full SillyTavern `chara_card_v2` import/export support.
   - **Three-Tier User Identity Binding**: Each character independently selects `None`, `Global Identity`, or `Character-Specific Independent Identity`.
   - **Per-Session Role Lock**: New chats can switch roles freely before the first turn and lock automatically once a message or greeting is recorded, displaying a deterministic color-coded role watermark in the history drawer.
   - **Character Reference Artwork & Autosave**: Upload reference portraits (`character/<role-name>/reference.png`) used as weak visual identity/style references during character-related chat image generation (while prioritizing the current turn's outfit, pose, and scene). All character fields, Worldbook entries, Markdown sources, and settings persist automatically with live status feedback.

3. **Image Studio**
   - **Multi-Profile Architecture**: Switch seamlessly between **Qwen-Image 2.1 Turbo Official** (8-step generation, native `--ref-image` editing via Qwen3-VL, and allowlisted **Qwen LoRA** loading), **Qwen-Image 2.1 Turbo Uncensored**, **Animagine XL 4.0**, and **SDXL Base 1.0** (native `img2img`).
   - **Three-Tier Prompting & Parse with AI**: Combines a shared **Natural Language** input with per-model persistent **Positive / Negative Prompt** drafts, plus a one-click stateless **Parse with AI** action that rewrites natural descriptions into structured English prompts using the active LLM.
   - **Flexible Controls**: Independent width and height selectors (`384`, `512`, `768`, `1024`), step count, seed, upscaling, LoRA selector, and one-click clear that resets inputs without deleting generated gallery items.

4. **Live Hardware & Inference Telemetry (Monitor)**
   - Real-time metrics for GPU VRAM usage, system RAM, Prefill and Decode throughput (`tok/s`), input/output token counters, SessionV1 KV cache hit rate, and per-request latency breakdowns.

5. **Native Windows Manager (Tauri 2)**
   - System tray integration, one-click model config switching, manual model load/unload while keeping the API resident, watchdog auto-restart, configurable **Idle Unload Timeout** (`0–1440` minutes), LAN access toggle, Windows DPAPI credential encryption, and integrated **Cloudflare Tunnel** monitoring, HTTPS latency probing, and restart controls.

6. **Android Client with Built-in User-Space Tailscale (`tsnet`)**
   - **Adaptive Light-Theme Mobile Shell**: Opens with a minimal connection gate before authentication and jumps straight to the most recent chat session once connected, featuring a persistent top-left history drawer toggle and a borderless 5-button bottom navigation bar (`Images`, `Characters`, `Settings`, `Monitor`, `About`).
   - **Conflict-Free User-Space Tailscale**: Powered by official `tailscale.com/tsnet` compiled into a native AAR via `gomobile`. **Does not use Android `VpnService`**—coexists seamlessly alongside system VPNs like Clash Mi / Mihomo without requiring Root or the official Tailscale app.
   - **Two-Step Web OAuth & Hardware-Backed Security**: Supports **Direct** and **Tailscale** connection modes. In Tailscale mode, users first complete interactive web OAuth device login before the endpoint and API key fields unfold. API keys are encrypted via **Android Keystore (`AES/GCM/NoPadding`)**, and all native checks, SSE streaming chats, and uploads traverse a localhost-only (`127.0.0.1`) reverse proxy guarded by per-session random tokens.

7. **Global Trilingual UI (`zh-CN` / `ja-JP` / `en-US`)**
   - Instant synchronization across the Web UI, mobile shell, Windows Manager, and tray menu without ever altering or translating user conversations, character cards, or prompts.

---

### 📄 License & Attribution

PolyStrata / Strata source attribution and licenses are retained in [`backend/polystrata/`](backend/polystrata/).
