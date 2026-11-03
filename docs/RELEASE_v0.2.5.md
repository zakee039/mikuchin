# Mikuchin main program v0.2.5

## Independent versioning

- **Main program / web workspace:** `0.2.5` (this release).
- **Windows launcher:** `0.2.4` (**unchanged**, Tauri binary and NSIS installer reused from v0.2.4).
- **Android client:** `0.2.4`, versionCode **204** (**unchanged**, existing release-signed APK reused from v0.2.4).
- The About page now lists all three independent versions in Chinese, Japanese and English.
- Three complete localized READMEs remain separate, with Simplified Chinese the default. Personal website and support links are retained.

## Main-program changes since the v0.2.4 tag

- Session-local chat sampling controls: independent answer-token and thinking-token budgets, including user-editable thinking caps. New conversations start with the normal defaults rather than inheriting changes from another conversation.
- Conversation-scoped image awareness: after generating an image, the local vision LLM makes **one** short role-aware response with thinking disabled, all tools disabled and at most **256 answer tokens**.
- Subsequent visually relevant messages can reference the latest generated image in that conversation, while ordinary unrelated chats do not repeatedly send vision tokens.
- Image-change requests can use the last picture as an actual reference for Qwen Turbo `--ref-image` / SDXL init-image instead of blindly recreating it from text. Image edits are **not** guaranteed pixel-perfect; other details can still vary.
- Isolated image registration per conversation, trusted file handling and deletion cleanup. Failures in the short visual response use a fixed reply instead of recursively regenerating images.

## Assets

- `Mikuchin-Main-v0.2.5-source.zip`: main-program source with its pinned PolyStrata submodule, no binaries, dependencies, model weights or private data.
- `Mikuchin-Main-v0.2.5-source.zip.sha256`: source archive checksum.
- `Mikuchin-Launcher-v0.2.4.exe`: existing Windows x64 portable launcher **0.2.4**, not a new build.
- `Mikuchin-Launcher-v0.2.4-Setup.exe`: existing Windows x64 installer **0.2.4**, not a new build.
- `Mikuchin-Android-v0.2.4.apk`: existing Android client **0.2.4**, not a new build.

The launcher and Android APK connect to an independently updated Mikuchin
main-program service; neither carries the full LLM or image-model weights.

## Verification

Version consistency, JavaScript syntax, frontend build, backend regressions,
source archive integrity and byte-for-byte unchanged client artifacts are
checked as separate release gates. A successful build is not a substitute for
a physical-device end-to-end check of image generation, vision replies and edits.
