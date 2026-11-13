# Mikuchin main program v0.2.6

## Component versions

- **Main program / web workspace:** 0.2.6.
- **Windows desktop launcher:** 0.2.4, unchanged; existing portable EXE and setup EXE reused.
- **Android client:** 0.2.4 (versionCode 204), unchanged; existing release-signed APK reused.

## Main-program changes since v0.2.5

### Reliable image tool dispatch

- Add compatibility parsing for the Gemma-family case where the model emits a bare `polystrata__generate_image{...}` mapping without the normal tool-call wrapper.
- Only convert a completed, validated invocation of the explicitly offered built-in image tool. Unknown tools, incomplete mappings and malformed arguments cannot be dispatched through this recovery path.
- Cover streamed output split at token boundaries and preserve the standard native tool-call parser.

### Shared chat sampling defaults

- Add **Set default** next to Reset and Apply in chat sampling.
- Store the user-selected sampling defaults on the server instead of browser-local storage; new conversations on different browsers/devices connected to the same server start with the saved configuration.
- Keep existing conversation-specific sampling unchanged; Reset returns to the shared default, Apply writes the current conversation only.
- Validate persisted budgets, sampling parameters, seed and toggles, with Simplified Chinese, Japanese and English UI support.

### Chat image settings

- Add **LoRA / height / width / 4× upscale / steps** controls under Settings → Chat image model.
- Persist the controls in the server-side global configuration. Validate numeric limits, available sizes and registered LoRA IDs before saving or executing.
- Apply the settings to chat-triggered image jobs even when the model suggests a different size/upscaling mode, while keeping the separate Images page's drafts unchanged.
- Restrict LoRA to compatible Qwen image models, reuse the configured fixed LoRA strength of 1.0, and adapt the controls for narrow/mobile viewports.

## Assets

- `Mikuchin-Main-v0.2.6-source.zip` — tracked main source plus the pinned PolyStrata submodule, excluding model weights, credentials, live user data and build dependencies.
- `Mikuchin-Main-v0.2.6-source.zip.sha256` — SHA-256 checksum.
- `Mikuchin-Launcher-v0.2.4.exe` and `Mikuchin-Launcher-v0.2.4-Setup.exe` — unchanged launcher artifacts.
- `Mikuchin-Android-v0.2.4.apk` — unchanged Android client artifact.

## Testing and limits

Automated parsing, tool dispatch, server-side configuration, frontend syntax, release version and archive checks are performed for this release. Real-device end-to-end image generation is **not** implied by passing these tests; image inference still requires valid model files and working GPU infrastructure.
