# Mikuchin v0.2.2

## Highlights

- A dedicated mobile layout for the shared Web Chat: horizontal navigation, a full-width conversation view, a slide-over history drawer, touch-friendly controls, and a compact composer.
- Mobile history now opens and closes without squeezing the chat or losing the active conversation. Desktop history remains a side panel.
- Image Studio supports model-specific prompt drafts, reference conversion, and separate image model selection. The Chat image model is configurable independently from the Images page.
- Fixes for image rendering after service restarts, chat image-tool availability, and session handling.

## Compatibility and deployment

- Product, native Windows Manager, portable executable and installer version: `0.2.2`.
- PolyStrata remains an independently versioned inference-engine submodule.
- No schema migrations or deliberate changes to user conversations, model files, KV snapshots, API secrets or local settings.
- Frontend changes are served by the existing Mikuchin service; the updated Windows Manager requires a rebuilt executable and a controlled restart.

## Verification

- TypeScript type checking and all 7 native launcher regression tests passed.
- Responsive Web Chat was checked at 320 px and 390 px mobile viewport widths and 1280 px desktop, including history open/close and chat width.
- Tauri release build and NSIS bundling succeeded; the built and deployed executable both report FileVersion and ProductVersion `0.2.2` and have identical SHA-256.
- At initial release verification, the native Manager stayed resident and the local API on 15239 returned HTTP 200. Historical forwarding on 18081 was subsequently removed and is not supported. Cloudflare's remotely configured origin must target 15239; this is verified separately from local health. The temporary one-shot launch task was removed after the process was verified independent.

## Windows release artifacts (local build)

- Portable binary: `frontend/launcher/portable/Mikuchin.exe` (SHA-256 `B351FF8B3D6FB06620FE9EEAAE2AB6F02179A51D6D021D79D4D22696830C398C`)
- NSIS installer: `frontend/launcher/src-tauri/target/release/bundle/nsis/Mikuchin_0.2.2_x64-setup.exe` (SHA-256 `05F148B606DEF23091BA7FECA5B291FF40B6005798AA47776EF7A571CD3DFCF2`)
- These executable artifacts are local build outputs and are not committed to Git. The prior 0.2.1 executable is backed up separately for rollback.
