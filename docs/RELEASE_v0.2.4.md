# Mikuchin v0.2.4

## Android client and built-in user-space Tailscale

- Added the native Android client (`frontend/android`) with an adaptive light-theme mobile shell, persistent top-left history drawer toggle, borderless 5-button bottom navigation bar (`Images`, `Characters`, `Settings`, `Monitor`, `About`), and automatic jump to the latest chat session after connecting.
- Integrated an embedded user-space Tailscale network module (`frontend/android/tsnetbridge`, built on `tailscale.com/tsnet` and compiled to `tsnetbridge.aar` via `gomobile`):
  - Operates entirely in user space without Android `VpnService`, allowing simultaneous use alongside system-wide VPN clients such as Clash Mi / Mihomo without root or installing the official Tailscale app.
  - Supports two-step interactive web OAuth device login (`Tailscale 网页授权登录`) with persistent node state in `noBackupFilesDir` and automatic reconnection across network transitions.
  - Routes both Kotlin native verification checks (`/health`, `/v1/strata/sessions`) and WebView traffic (SSE streaming chat, image uploads, assets) through a localhost-bound (`127.0.0.1:0`) reverse proxy secured by per-session random tokens and origin verification.
  - Protects saved Mikuchin API keys with Android Keystore (`AES/GCM/NoPadding`), disables Android system backup (`allowBackup="false"`), and keeps initial endpoint fields blank without hardcoded private addresses.

## Documentation and release alignment

- Unified product, Windows desktop manager (`frontend/launcher`), and Android client (`frontend/android`) versions to `0.2.4` (`v0.2.4`).
- Rewrote `README.md` in Chinese, Japanese, and English (defaulting to Simplified Chinese) with comprehensive feature documentation and author links.

