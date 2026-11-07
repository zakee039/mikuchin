<div align="center">

<img src="assets/icon.png" alt="Mikuchin" width="96" height="96" />

# Mikuchin · Miku亲

**Self-hosted Multimodal AI Companion & Image Studio**

**Main app v0.2.5** · [Download / GitHub Releases](https://github.com/zakee039/mikuchin/releases/tag/v0.2.5)

**Independent versions:** main app `0.2.5` · Windows launcher `0.2.4` · Android client `0.2.4` (versionCode 204). Only the main app changes in this release; the launcher and APK binaries are unchanged.

[Official Site](https://mikuchin.zakee.fun) · [Personal Website](https://zakee.fun) · [Buy Me a Coffee](https://ifdian.net/a/zakee/plan)

[**简体中文**](README.md) · [**日本語**](README.ja-JP.md) · [**English**](README.en-US.md)

</div>

---

## Meet Mikuchin (Miku亲)

**Mikuchin, also called Miku亲**, is a self-hosted AI companion and creative workspace for personal use. More than a chat window, it brings conversations, character profiles and Worldbooks, reference-guided image creation, and live inference monitoring together in one interface.

It uses **PolyStrata** for local inference and includes a browser workspace, a Windows tray manager, and a dedicated Android client. The Android app can connect directly or join your own Tailnet through embedded user-space Tailscale to reach Mikuchin on your PC. **The Android app is a remote client; it does not run the model on the phone.**

You manage models, conversations, character data, and generated images on your own hardware. Tailnet access, Cloudflare Tunnel, and optional external MCP integrations can still involve network services, so review their permissions separately.

## ✨ Key Features

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
   - **User-Space Tailscale**: Powered by official `tailscale.com/tsnet` compiled into a native AAR via `gomobile`. **Does not use Android `VpnService`**—can operate without taking over the VPN slot used by Clash Mi / Mihomo (actual routing depends on the phone configuration), without requiring root access or the official Tailscale app.
   - **Two-Step Web OAuth & Hardware-Backed Security**: Supports **Direct** and **Tailscale** connection modes. In Tailscale mode, users first complete interactive web OAuth device login before the endpoint and API key fields unfold. API keys are encrypted via **Android Keystore (`AES/GCM/NoPadding`)**, and all native checks, SSE streaming chats, and uploads traverse a localhost-only (`127.0.0.1`) reverse proxy guarded by per-session random tokens.

7. **Global Trilingual UI (`zh-CN` / `ja-JP` / `en-US`)**
   - Instant synchronization across the Web UI, mobile shell, Windows Manager, and tray menu without ever altering or translating user conversations, character cards, or prompts.

## 📂 Repository layout

```text
mikuchin/
├── assets/                 # Brand images and icons
├── backend/
│   ├── polystrata/         # Inference engine (Git submodule)
│   └── services/           # Model-independent services
├── character/              # Character cards and reference artwork
├── chat/                   # Sessions, generated images and KV snapshots
├── config/                 # Local configuration (Git-ignored)
├── docs/                   # Official website (GitHub Pages: mikuchin.zakee.fun)
├── frontend/
│   ├── android/            # Kotlin / WebView / tsnet client
│   ├── launcher/           # Windows Tauri 2 manager
│   ├── locales/            # Chinese, Japanese and English translations
│   └── web/                # Shared web workspace
└── scripts/                # Build and maintenance scripts
```

## 📦 Download and build

Get the Windows installer and Android APK from [GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest). **Model weights are not included**; prepare your local model files and register the configuration in the launcher.

```bash
git clone --recurse-submodules https://github.com/zakee039/mikuchin.git
# Already cloned? git submodule update --init --recursive
```

```powershell
python scripts/build-locales.py
powershell -ExecutionPolicy Bypass -File scripts/build-launcher.ps1
powershell -ExecutionPolicy Bypass -File frontend/android/build-apk.ps1
```

On Android, choose Direct or Tailscale connection. Tailscale mode requires browser authorization, Tailnet ACL/Grants permitting the APK node to reach your server, and an appropriate server firewall rule. The Android app **connects to your Mikuchin backend**; it does not run the model locally on the phone.

## 🔒 Security and compatibility

Do not publish API keys, Tailnet state, model files, or private conversation data. Coexistence with a system VPN depends on routing and should be verified on your device. The v0.2.4 APK is release-signed. Older APKs signed with an Android Debug certificate may need to be uninstalled before installing this build; back up any app-local settings first. See the PolyStrata submodule for its own licensing and attribution.
