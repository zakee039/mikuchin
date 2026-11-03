<div align="center">

<img src="assets/icon.png" alt="Mikuchin" width="104" height="104" />

# Mikuchin

**Local AI Companion · Image Studio · Windows & Android**

**v0.2.4** · [Download / Releases](https://github.com/zakee039/mikuchin/releases/latest) · [Website](https://zakee.fun)

### Choose a language / 选择语言 / 言語を選択

[**简体中文**](README.zh-CN.md)　|　[**日本語**](README.ja-JP.md)　|　[**English**](README.en-US.md)

</div>

---

Mikuchin is a self-hosted multimodal AI companion powered by [PolyStrata](backend/polystrata). It provides a Windows desktop manager, a browser workspace, and an Android client with embedded user-space Tailscale networking. See the language-specific guides above for features, setup, network access, and safety notes.

**Highlights:** Streaming chat and per-model sessions; character cards and Worldbook; Qwen/SDXL image workflows with prompts, references, and LoRA; resource monitoring; Windows tray controls; Android remote access without requiring the system VPN slot.

| Platform | Distribution | Source |
| --- | --- | --- |
| Windows 10/11 | [Windows installer](https://github.com/zakee039/mikuchin/releases/latest) | [`frontend/launcher`](frontend/launcher) |
| Android (arm64, Android 8+) | [Android APK](https://github.com/zakee039/mikuchin/releases/latest) | [`frontend/android`](frontend/android) |
| Browser | Hosted by your own Mikuchin backend | [`frontend/web`](frontend/web) |

> Model files and private user data are not bundled with release artifacts. The Android app connects to a running Mikuchin backend; Tailnet ACL/Grants, API authorization, and your server firewall still apply.

## Build from source

```bash
git clone --recurse-submodules https://github.com/zakee039/mikuchin.git
```

```powershell
# On Windows: manager + installer
powershell -ExecutionPolicy Bypass -File scripts/build-launcher.ps1

# Android APK (requires Android SDK, JDK, Gradle and Go/gomobile)
powershell -ExecutionPolicy Bypass -File frontend/android/build-apk.ps1
```

[Detailed instructions (简体中文)](README.zh-CN.md) · [詳細ガイド (日本語)](README.ja-JP.md) · [Full guide (English)](README.en-US.md)

---

[Project website](https://zakee.fun) · [Support](https://ifdian.net/a/zakee/plan) · [PolyStrata source & attribution](backend/polystrata/)
