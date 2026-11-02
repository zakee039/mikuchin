# Mikuchin

Mikuchin is a desktop and browser-based personal AI companion built around the PolyStrata inference engine.

- `frontend/web/`: shared Chat/Characters/Monitor pages and official Miku brand assets.
- `frontend/launcher/`: Tauri 2 Windows manager, tray and installer.
- `backend/polystrata/`: upstream-based inference engine, kept as a separate Git submodule.
- `backend/services/`: orchestration layer; engine-neutral infrastructure belongs here.
- `character/`: identity and role specifications, independent of models and conversations.
- `assets/`: three authoritative illustrations; generated icon sizes are derived from `icon.png`.
- `models/`: model storage (weights intentionally excluded from Git).
- `chat/`: runtime conversations, attachments, and per-model KV data (never commit).
- `config/`: deployment settings; local config files are ignored by Git.

See `docs/ARCHITECTURE.md` for migration and compatibility details.

PolyStrata / Strata source attribution and licenses are retained in `backend/polystrata/`.

## Preparing a checkout

Clone with `git clone --recurse-submodules` or run `git submodule update --init --recursive`. The engine submodule tracks the `mikuchin-webroot` branch of the PolyStrata fork; it contains a small optional `MIKUCHIN_WEB_DIR` override. The product Web UI is served from `frontend/web` only when that variable is set, and standalone PolyStrata still serves its original page.

The current build includes local runtime data under Git-ignored paths and must not be pushed. Use `config/active.json` for a machine-local model config.
