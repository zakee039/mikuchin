<div align="center">

<img src="assets/icon.png" alt="Mikuchin" width="96" height="96" />

# Mikuchin · Miku亲

**Self-hosted Multimodal AI Companion & Image Studio**

**Main app v0.5.1** · [Download / GitHub Releases](https://github.com/zakee039/mikuchin/releases/tag/v0.5.1)

**Independent versions:** main app `0.5.1` · Windows launcher `0.5.1` · Android client `0.5.1` (versionCode 501). All three artifacts were rebuilt for this release; see the release manifest. They remain independently versioned for future changes.

[Official Site](https://mikuchin.zakee.fun) · [Personal Website](https://zakee.fun) · [Buy Me a Coffee](https://ifdian.net/a/zakee/plan)

[**简体中文**](README.md) · [**日本語**](README.ja-JP.md) · [**English**](README.en-US.md)

</div>

---

## Meet Mikuchin (Miku亲)

**Mikuchin, also called Miku亲**, is a self-hosted AI companion and creative workspace for personal use. More than a chat window, it brings conversations, character profiles and Worldbooks, reference-guided image creation, and live inference monitoring together in one interface.

It uses **PolyStrata** for local inference and includes a browser workspace, a Windows tray manager, and a dedicated Android client. The Android app can connect directly or join your own Tailnet through embedded user-space Tailscale to reach Mikuchin on your PC. **The Android app is a remote client; it does not run the model on the phone.**

You manage models, conversations, character data, and generated images on your own hardware. Tailnet access, Cloudflare Tunnel, and optional external MCP integrations can still involve network services, so review their permissions separately.

## ✨ Key Features

### 1. Conversational AI & SessionV1 Engine
- Real-time token streaming, collapsible reasoning (`Thinking`) traces, multimodal vision input (drag-and-drop, clipboard paste, or file upload), external **MCP (Model Context Protocol)** tool execution, and in-chat image generation.
- **Per-Model SessionV1 KV Persistence**: SQLite session storage paired with per-model KV cache snapshots enables instant long-context resumption, one-click KV lock/release, session pinning, renaming, and Markdown export. Deleting a session automatically cleans up its generated images and KV snapshots.
- **Three Conversation Modes**: **Ordinary Assistant** (inherits global user identity and multi-turn memory), **Stateless Mode** (sends only the current turn to the model without history, identity, or character cards while still saving visible chat logs and supporting built-in image generation), and **Custom Characters**.

### 2. Character Studio & Worldbook
- Backed by a model-independent SQLite store (`character_cards.sqlite3`) with full SillyTavern `chara_card_v2` import/export support.
- **Three-Tier User Identity Binding**: Each character independently selects `None`, `Global Identity`, or `Character-Specific Independent Identity`.
- **Per-Session Role Lock**: New chats can switch roles freely before the first turn and lock automatically once a message or greeting is recorded, displaying a deterministic color-coded role watermark in the history drawer.
- **Character Reference Artwork & Autosave**: Upload reference portraits (`character/<role-name>/reference.png`) used as weak visual identity/style references during character-related chat image generation (while prioritizing the current turn's outfit, pose, and scene). All character fields, Worldbook entries, Markdown sources, and settings persist automatically with live status feedback.

### 3. Image Studio
- **Multi-Profile Architecture**: Switch seamlessly between **Qwen-Image 2.1 Turbo Official** (8-step generation, native `--ref-image` editing via Qwen3-VL, and allowlisted **Qwen LoRA** loading), **Qwen-Image 2.1 Turbo Uncensored**, **Animagine XL 4.0**, and **SDXL Base 1.0** (native `img2img`).
- **Three-Tier Prompting & Parse with AI**: Combines a shared **Natural Language** input with per-model persistent **Positive / Negative Prompt** drafts, plus a one-click stateless **Parse with AI** action that rewrites natural descriptions into structured English prompts using the active LLM.
- **Flexible Controls**: Independent width and height selectors (`384`, `512`, `768`, `1024`), step count, seed, upscaling, LoRA selector, and one-click clear that resets inputs without deleting generated gallery items.
- **OpenAI-Compatible Image APIs (v0.2.9)**: Configure providers, optional proxies and API keys in Settings; discover candidate model IDs and upload multiple reference images with capability-based fallback. View generation progress and elapsed time, and optionally apply local Real-ESRGAN 4× upscaling.

### 4. Unified Gallery (Gallery)
- **Unified Gallery — automatic indexing**: Collects generated pictures from Image Studio and conversations, whether produced locally or through an API. The first visit backfills existing pictures; successful generations update `chat/gallery-index.sqlite3` and create thumbnail caches. Private images are not uploaded to GitHub.
- **Gallery navigation and variants**: Filter by source (All / Image Gen / Chat / Local / API), sort by date, open a full-size viewer, use ← / → and `Esc` on desktop or swipe on mobile. Original and 4× upscaled images are grouped under one thumbnail (with a shaded count badge); the detail view can delete either version separately.
- **NSFW and bulk management**: The gallery's **Show NSFW** toggle defaults to off, blurring marked images. You can reveal an image temporarily, manually mark/unmark one, or batch-mark selected works as NSFW. A model name containing `uncensored` is only a heuristic, **not image-content classification or access protection**. Multi-select supports selecting loaded items, clearing selection and deleting several works; normal and bulk deletion remove **both versions of each work**, permanently. Chat references to deleted images will stop working.

### 5. Live Hardware & Inference Telemetry (Monitor)
- Real-time metrics for GPU VRAM usage, system RAM, Prefill and Decode throughput (`tok/s`), input/output token counters, SessionV1 KV cache hit rate, and per-request latency breakdowns.

### 6. Native Windows Manager (Tauri 2)
- System tray integration, one-click model config switching, manual model load/unload while keeping the API resident, watchdog auto-restart, configurable **Idle Unload Timeout** (`0–1440` minutes), LAN access toggle, Windows DPAPI credential encryption, and integrated **Cloudflare Tunnel** monitoring, HTTPS latency probing, and restart controls.

### 7. Access from other devices (Remote Access)

Inference, conversations and generated images remain on your Mikuchin host. Other devices only connect to that service; they do not need to install the model. Make sure the host is online, API-key authentication is enabled, and the listening address, firewall and access controls are configured.

#### 7.1 Desktop access (Windows / Linux)

1. Start Mikuchin on the host and check its API port (example: `15239`).
2. On a trusted LAN, open `http://<HOST_LAN_IP>:15239/` from another computer's browser. The host must enable LAN access and permit that port through its firewall.
3. For access across networks, use an authorized **Tailscale Tailnet** or your configured **Cloudflare Tunnel HTTPS hostname** with access controls. Enter the Mikuchin API key to use Chat, Image Gen and Gallery. For Mac browsers, also see the Apple device section below.

#### 7.2 Android device access

1. Download the release-signed Mikuchin APK from [GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest). **Android connects to your Mikuchin server; it does not run the model on the phone.**
2. Choose **Direct** or **Tailscale** in the app:
   - **Direct:** Enter a reachable host URL (such as the local LAN address or your own HTTPS Cloudflare Tunnel) and your Mikuchin API key.
   - **Tailscale:** Complete the in-app browser OAuth authorization first, then enter the Mikuchin endpoint and API key. Tailnet ACL/Grants, host listening and firewall rules must allow the connection.
3. Chat, Image Gen and Gallery are available once connected.

**Android client features:**

- **Adaptive Light-Theme Mobile Shell**: Opens with a minimal connection gate before authentication and jumps straight to the most recent chat session once connected, featuring a persistent top-left history drawer toggle and a borderless 6-button bottom navigation bar (`Image Gen`, `Gallery`, `Characters`, `Settings`, `Monitor`, `About`).
- **User-Space Tailscale**: Powered by official `tailscale.com/tsnet` compiled into a native AAR via `gomobile`. **Does not use Android `VpnService`**—can operate without taking over the VPN slot used by Clash Mi / Mihomo (actual routing depends on the phone configuration), without requiring root access or the official Tailscale app.
- **Credential and local transport protection**: API keys are encrypted with **Android Keystore (`AES/GCM/NoPadding`)**. Native checks, SSE chat streams and uploads use an internal localhost-only (`127.0.0.1`) reverse proxy guarded by per-session random tokens.

**Upgrade note:** v0.5.1 is release-signed. An APK signed with the same certificate can generally update in place; Debug-signed builds might require uninstalling first. Back up app-local settings before doing so.

#### 7.3 Apple device access (iPhone / iPad / Mac)

**Using Mikuchin on iPhone/iPad requires no Mac, Xcode, developer signing, IPA sideloading or native iOS app.** Open the existing web workspace in Safari. Your Mikuchin host still runs inference and stores conversations and generated images; the Apple device acts as a remote browser client. **A Home Screen shortcut is not a native app or offline model runtime.**

##### iPhone / iPad: Stash + built-in Tailscale + Safari

1. **Prepare the host.** Keep the Windows Mikuchin service running, enable listening on an address reachable over Tailscale (for example, LAN access), and allow its API port through the host firewall (example port: `15239`). Tailnet ACL/Grants must permit the iPhone/iPad node to reach this host and port. No public port forwarding is necessary.
2. **Join the same Tailnet from Stash.** Stash for iOS 3.4+ supports a built-in `type: tailscale` node; 3.6+ is recommended for automatic Tailnet routes and MagicDNS. **Append** this entry to the `proxies` section of your existing profile rather than replacing your other proxy settings. Open the node's **Tailscale** menu in Stash and complete interactive browser login. Never publish an authentication key.

   ```yaml
   proxies:
     - name: mikuchin-tailnet
       type: tailscale
   ```

   Integrated Tailscale shares Stash's VPN tunnel, so you generally do not need to run the separate Tailscale VPN concurrently. Actual routing depends on the Stash version and local rules. See the [Stash Tailscale reference](https://stash.wiki/en/proxy-protocols/proxy-types) and [Stash NAT traversal guide](https://stash.wiki/features/nat-traversal).
3. **Open Mikuchin in Safari.** After the Stash Tailnet node is connected, visit `http://<MIKUCHIN_HOST_TAILNET_IP>:15239/`, substituting your PC's Tailscale IPv4 address and real API port, or use a working MagicDNS hostname. Enter your **Mikuchin API key** when prompted. If it fails, check service availability, listen address, firewall, Tailnet permissions and Stash routing.
4. **Add it to your Home Screen.** In Safari, use **Share → Add to Home Screen** and optionally select **Open as Web App** where available, then tap **Add**. You can now launch the website from its icon. See [Apple's official instructions](https://support.apple.com/guide/iphone/iphea86e5236/ios).

##### Other Apple connection options

- **Without Stash (iPhone/iPad):** Connect to your Tailnet using the official [Tailscale iOS app](https://tailscale.com/docs/install/ios), then open the Mikuchin address in Safari. Note that separate system VPN apps can compete for the single iOS VPN slot.
- **Without Tailscale:** Use your own configured and authorized **HTTPS Cloudflare Tunnel hostname** in Safari, with Mikuchin API-key authentication. The [project website](https://mikuchin.zakee.fun) is **not** your personal inference endpoint.
- **Mac:** Open Mikuchin in Safari or another browser over the Tailnet or an authorized HTTPS endpoint. No dedicated macOS app build is required for browser access.

**Security:** `http://` traffic carried **inside a correctly connected Tailscale tunnel** benefits from the tunnel's encryption, but HTTP does not itself provide browser-level HTTPS/TLS security or a secure origin. Use a valid HTTPS endpoint if browser secure-context features are needed. Keep API-key authentication and Tailnet ACLs enabled; never expose plaintext HTTP directly to the public internet. The Home Screen icon cannot reach a sleeping or disconnected host.

### 8. Global Trilingual UI (`zh-CN` / `ja-JP` / `en-US`)
- Instant synchronization across the Web UI, mobile shell, Windows Manager, and tray menu without ever altering or translating user conversations, character cards, or prompts.

## 📂 Repository layout

```text
mikuchin/
├── assets/                 # Brand images and icons
├── backend/
│   ├── polystrata/         # Bundled inference engine sources, tracked by this repository
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

## 📥 Model Preparation & Download Guide

> 💡 **Easiest way to deploy**: Core inference is powered by **PolyStrata**. Simply **copy this repository to your AI assistant and let her deploy and configure it for you~**

The Windows installer and source repository do not include model weights. Prepare the following GGUF / Safetensors files in your local models directory and register the profile in the launcher:

### 1. Chat & Multimodal Vision LLM (2 files)
Used for roleplay chat, image understanding, and post-generation visual feedback:
- `G4-MeroMero-26B-A4B-it-uncensored-heretic-Q4_K_M.gguf` (4-bit quantized main LLM)
- `G4-MeroMero-26B-A4B-it-uncensored-heretic-mmproj-BF16.gguf` (BF16 multimodal vision projector `mmproj`)
- **Download**: Hugging Face [`llmfan46/G4-MeroMero-26B-A4B-it-uncensored-heretic-GGUF`](https://huggingface.co/llmfan46/G4-MeroMero-26B-A4B-it-uncensored-heretic-GGUF)

### 2. Image Generation Suite (Qwen-Image 2.1, 5 files)
Used for in-chat drawing and the Image Studio:
- `Qwen-Image-2.1-Turbo-AD-Q4_K.gguf` — 8-step Turbo DiT denoiser ([`AtomicChat/Qwen-Image-2.1-Turbo-GGUF`](https://huggingface.co/AtomicChat/Qwen-Image-2.1-Turbo-GGUF))
- `qwen_image_2.1-Q4_K.gguf` — Base multi-step DiT denoiser ([`leejet/Qwen-Image-2.1-GGUF`](https://huggingface.co/leejet/Qwen-Image-2.1-GGUF))
- `Qwen3VL-8B-Instruct-Q4_K_M.gguf` — Text encoder ([`Qwen/Qwen3-VL-8B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF))
- `mmproj-Qwen3VL-8B-Instruct-F16.gguf` — Vision projector for native `--ref-image` editing ([`Qwen/Qwen3-VL-8B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF))
- `qwen_image_2.1_vae_bf16.safetensors` — Shared BF16 VAE ([`unsloth/Qwen-Image-2.1-FP8`](https://huggingface.co/unsloth/Qwen-Image-2.1-FP8) under `vae/`)

> You can also run PolyStrata's helper script `python backend/polystrata/tools/image/install.py --models-dir models` to build the image backend and fetch core weights, or use standard SDXL checkpoints (`Animagine XL 4.0 Opt`, `SDXL Base 1.0`).

## 📦 Download and build

Get the Windows installer and Android APK from [GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest). **Model weights are not included**; prepare your local model files and register the configuration in the launcher.

```bash
git clone --recurse-submodules https://github.com/zakee039/mikuchin.git
# Existing clone: git submodule update --init --recursive
```

Native main pins the **official upstream PolyStrata** as a Git submodule (v0.1.45-poly.10), with no private fork or upstream source changes. Model weights, Python/CUDA, and image backends must be installed separately; the current Windows Launcher installer is **not a self-contained runtime**. The old mixed architecture is preserved as old-mixed. See [Native migration notes](docs/NATIVE_V040_MAIN_MIGRATION_2026-11-21.md), [upstream MIT license](backend/polystrata/LICENSE), and [third-party notices](THIRD_PARTY_NOTICES.md).

```powershell
python scripts/build-locales.py
cd frontend/launcher
npm ci
npx tauri build --debug --no-bundle
cd ../..
powershell -ExecutionPolicy Bypass -File frontend/android/build-apk.ps1
```

## 🔒 Security and compatibility

Do not publish API keys, Tailnet state, model files, or private conversation data. Coexistence with a system VPN depends on routing and should be verified on your device. See the bundled engine's license and third-party notices for attribution.
