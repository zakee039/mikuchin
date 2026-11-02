# Mikuchin v0.2.0 — Baseline release

This is the first formal baseline version of **Mikuchin** as its own product. It supersedes the previous experimental `v0.1.12` identity; the underlying PolyStrata inference engine has an **independent version**.

## Scope

- Branded desktop Manager, tray launcher, web Chat, About page, logo and Windows package.
- PolyStrata as a separately versioned inference engine in `backend/polystrata`.
- Models, character profiles, conversations and per-model KV snapshot infrastructure remain in separate directories.
- Shared Chinese, Japanese and English UI strings for Manager, tray and Web UI.
- Configurable idle unload via Manager and service restart, retaining current values by default.
- The default API endpoint is TCP 15239 (the prior 18081 endpoint is a local compatibility forwarding rule on the deployment host).

## Versioning

- Product source: `v0.2.0` tag on `zakee039/mikuchin`.
- Desktop product and installer: `0.2.0`.
- PolyStrata engine: independently versioned; do not bump the engine as part of a product-only release.
- This is a baseline release, **not** an assertion that experimental model features are production-stable.

## Runtime data and safety

Model weights, chats, KV snapshots, model-specific local configuration and secrets are not part of the Git tag or distributable installer. Runtime data under `E:\LLM\deploy\mikuchin` remains on the host. An update does not imply removing the old `polystrata` deployment backup.

## Verified Windows build (2026-11-02)

- Portable binary: `Mikuchin-v0.2.0.exe`, SHA-256 `3A95994FE18CDAAC903B69134F1DB28B854E992A66CD13C02E71526730E6DF1B`
- NSIS installer: `Mikuchin_0.2.0_x64-setup.exe`, SHA-256 `83593B2FBF35B143633A228B2AAA69DDA44B014D53EEC930DE99A75FD98E11A9`
- TypeScript/Vite and Rust/Tauri release build: successful.
- Version resources: FileVersion and ProductVersion both `0.2.0`.
- Isolated `--self-test` (port 18086, lazy model): API started and stopped successfully; no model weights were loaded.
- Runtime files remain excluded from Git and are not part of the source tag.
