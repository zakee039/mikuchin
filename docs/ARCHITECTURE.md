# Mikuchin V1.1 migration

This is an **in-parallel migration**. Until validation and cutover, the old deployment `E:\LLM\deploy\polystrata` remains the running service and authoritative source of new chat writes.

1. Keep PolyStrata an independent Git submodule in `backend/polystrata`, preserving upstream attribution and history.
2. Own the public Web UI in `frontend/web`, and the Windows launcher in `frontend/launcher`. Engine APIs and model IDs remain unchanged.
3. Share `assets/icon.png` for browser Favicon, header logo, tray, executable and installer. Keep `half.png` and `full.png` unmodified.
4. Keep `character/` model-independent and `chat/` private; a character persona is not the chat database.
5. Copy conversations with SQLite online backup, not raw file copying during a live transaction. Copy KV snapshots only once the engine stops writing them. Never copy a live database over a newer destination.
6. Transition the local run config from old absolute paths to paths under Mikuchin before first start. Keep a rollback copy of all old user data.
7. Start the new manager only after the old manager/service is stopped; two watchdogs must never control the same API port.
8. Do not expose an unauthenticated API beyond 127.0.0.1. Preserve encrypted DPAPI tokens.

**Status:** Layout and branding staged. Full runtime cutover requires engine binary/venv copy, verified data snapshot, configuration checks, application bootstrap, and smoke tests.

## Safe final cutover

Once the old manager is no longer being used, **right-click its tray icon and choose Exit manager**. This gracefully stops its API and Cloudflare connector. Run `powershell -ExecutionPolicy Bypass -File scripts/cutover.ps1` from this product root. The script refuses to continue if the old manager or API port is still active, takes a final snapshot of chats and KV, migrates encrypted local credentials without displaying them, and starts the new manager. The old root and settings are preserved for rollback.

Never run this cutover automatically during an active conversation or while the tunnel is serving requests. If verification fails, use `frontend/launcher/portable/Mikuchin.exe` logs under `%LOCALAPPDATA%\Mikuchin`, stop it through its tray icon, and relaunch the original PolyStrata manager after restoring the original service conditions.
