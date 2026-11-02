# Mikuchin: Global UI language and idle unload (Phase 1)

## Global UI language

Three authoritative locale JSON files: `frontend/locales/zh-CN.json`, `ja-JP.json`, `en-US.json`.

- Windows Manager **Settings → Global language** and the Chat header switch the same preference.
- `config/ui-language.json` is shared across the Manager, its tray menu and the Web UI, and ignored by Git.
- The Manager watches this preference and updates the right-click tray menu without restarting inference.
- The Web UI fetches `/v1/mikuchin/ui-language` periodically to see external changes. Its same-origin POST requires the API key; an unauthenticated browser cannot change server-wide preferences.
- The strings are UI-only: stored conversations, character definitions, model responses, and prompts are never translated.
- Edit the JSON files, then run `python scripts/build-locales.py` to rebuild `frontend/web/i18n-data.js`. The Tauri build and Vite dev scripts regenerate it automatically.
- When a translation key is missing, the original source text remains. This phase covers the principal Chat, Characters, Monitor, About, Manager, status and tray UI. It does **not** translate user- or model-authored content.

## Idle unloading

The Manager reads `idle_unload_s` from the active model run config. **Settings → Idle unload timeout** allows 0–1440 minutes (0 means disabled).

Saving while the backend is managed by Mikuchin:

1. Confirm the current API is responsive.
2. Stop the current backend using the existing graceful service lifecycle.
3. Back up the active JSON to `.json.bak`, update only `idle_unload_s`.
4. Start the backend with the new value and wait for its metrics API to respond.
5. If the new backend cannot start, restore the previous config and try to bring the previous service back.

The Web API stays on the same port. A restart temporarily interrupts active requests, so avoid saving while generating. The conversation database and KV snapshot layout remain unchanged.

## Quality checks

- `python scripts/test_ui_language.py` — isolated mock backend, validates read/write, authentication and static assets.
- `npm run check` in `frontend/launcher` — TypeScript validation.
- `npm run build` in `frontend/launcher` — Tauri build and installer.
- Manual browser tests for zh-CN → ja-JP → en-US on Chat, Characters and About, including custom dropdown and console diagnostics.

## About and compact settings follow-up

- `About` no longer repeats a separate project-link card: the project overview and GitHub link appear within the Model & Engine card; the engine version remains identified as PolyStrata.
- Manager Settings removes all unnecessary gray subtitles and keeps the language and idle timeout actions compact.
- `get_idle_unload` and `set_idle_unload` ignore an optional UTF-8 BOM in the active JSON (the existing Windows config starts with a BOM). Failure to read the optional idle setting no longer blocks initial Manager UI rendering.
- Monitor dynamic telemetry and Images status labels use locale keys, including repeated asynchronous status updates.
