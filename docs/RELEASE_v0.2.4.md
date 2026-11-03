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
- The repository landing page `README.md` is now a concise navigation and download guide. The full descriptions are maintained independently in `README.zh-CN.md`, `README.ja-JP.md`, and `README.en-US.md`.
- Documented installation, source builds, Tailnet ACL/firewall requirements, credential handling, and the difference between an embedded Android remote client and a local inference server.

## Release downloads

- `Mikuchin_0.2.4_x64-setup.exe`: Windows x64 NSIS installer for the desktop manager.
- `Mikuchin-Android-v0.2.4.apk`: Android arm64 APK (minSdk 26). This build is **debug-signed**, not a production-signing-key release; sideloading and future upgrades must account for the signature. It contains a user-space `tsnet` client but does not contain model weights.

## Validation scope

- Desktop build and Android APK package/signature validation are separate from physical-device end-to-end validation.
- Tailscale networking uses the embedded module's own Tailnet identity; it requires appropriate Tailnet Grants/ACLs and host firewall rules. It does not use the Android `VpnService` slot, but other VPN software can still influence routes.

