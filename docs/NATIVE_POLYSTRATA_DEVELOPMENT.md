# Native PolyStrata integration branch

## Current state

- **Working tree:** `E:\LLM\deploy\mikuchin-native`
- **Branch:** `refactor/official-polystrata-gateway`, branched from the immutable Mikuchin `v0.3.0` rollback baseline.
- **Official upstream:** `backend/polystrata` is a **Git submodule** from `https://github.com/simplexai-labs/PolyStrata.git`, pinned to `v0.1.45-poly.10` (`3e1642161198c50ff1abed4046f4e4f476099dbb`).
- **Local development Gateway:** `backend/gateway/app.py` is a standalone HTTP transport adapter plus new session/character endpoints. It does **not** import private PolyStrata Python modules: only the official localhost HTTP API is called. **Character cards, Markdown retrieval and workflow APIs are now present**; image-worker scheduling, full browser application, model supervision and cross-device packaging remain unfinished.
- **Original stable installation:** `E:\LLM\deploy\mikuchin` (main, v0.3.1); running service remains on its established ports and data. Do not point it at this worktree before acceptance testing.

### Shared image-resolution UI (ported from main)

The `frontend/web` Image Studio and global chat settings share `image-resolution.js`:
standard 9 exact `WIDTHxHEIGHT` presets (including 1536x1536 square), local recommended 384/512/768/1024,
and separate custom width/height snapped to 16-pixel steps (256–4096).
The server-side validation contract for the *future* Gateway Image Worker is
`backend/gateway/image_resolution.py`; it intentionally lives **outside the
official PolyStrata submodule**. The native Gateway prototype does not yet
implement image service management or generation, so the new UI is synchronized
but is not yet fully functional on this experimental branch.

### Main v0.3.1 retry behavior synchronized (frontend contract)

The development branch now shares the v0.3.1 task-list interface: when a
retry response explicitly contains `deleted_original_id`, the original failed
record disappears immediately; successful-task retries keep their original
record. A failed retry submission never deletes the source locally.

**Important:** this experimental Gateway still has no Mikuchin image-task
backend, so this is a shared frontend contract **not a working image retry
endpoint in the native branch yet**. When the independent Image Worker is
implemented, its failed-to-running replacement must be one atomic database
transaction and must preserve any transferred reference images. Do not modify
official `backend/polystrata` to implement that behavior.

The product manifest on this branch reflects **main 0.3.1**, while Launcher
and Android remain **0.3.0** without new binaries. No native-architecture
release is implied by this version synchronization.

## Simplified KV policy (2026-11-19 design decision)

- **No migration of existing chats or `POLYKV1!` snapshots** into the new Gateway. The new application starts a clean chat store for chats created there. The stable v0.3.0 data directory is not deleted.
- **Do not port the old manual “Lock KV” / “Pin session” UI or its custom 5-snapshot-per-model manager.** Favor the official native engine's automatic exact-token-prefix checkpoint matching and opt-in parked-conversation cache (`--conversation-cache-mib auto` / `--conversation-cache-slots`). On cache miss simply prefill again.
- **Do not enable the manual disk `/slots/0?action=save|restore` path in the first implementation.** This is a separate, opt-in cross-restart mechanism, not the automatic conversation cache; it complicates serialization with parallel requests.
- Official `warm_start` and its engine `PIN` are for **one reusable common system prompt** and are distinct from the old user's manual pinned conversation snapshots. Leave `warm_start` off initially; measure repeated prompt-prefix use before enabling it.
- The new UI may still keep **new** chat transcripts and a “pin to top” ordering control; neither is a KV persistence contract. Chat messages must be resent to the engine when in-memory cache is lost.

## Fresh native sessions: implemented subset

- `backend/gateway/conversations.py` is a standalone SQLite WAL-backed new-session store. Default storage: `%LOCALAPPDATA%\MikuchinNative\native-conversations.sqlite3` on Windows (or the user-specific XDG data directory on Linux). Set `MIKUCHIN_NATIVE_DATA_DIR` to choose an isolated directory.
- `GET/POST /v1/strata/sessions` lists or saves fresh Web chat messages. `GET/POST/DELETE /v1/strata/sessions/{32-hex-id}` reads, renames, lists-pins, saves independent sampling, or deletes one fresh conversation. `GET/POST /v1/strata/sampling-default` reads/writes shared default sampling for new conversations.
- The Gateway accepts and validates the existing frontend's `strata_session_id` and `mikuchin_stateless` hints, **removes these Mikuchin-only keys before forwarding the supplied full text context to official PolyStrata**. It does not use the old session object, write an engine KV snapshot, or attempt an undocumented model restore.
- UI sessions sidebar no longer offers manual KV locking, cache badges, or KV sizes. **List pin (置顶) is preserved and has no KV effects.** The API explicitly rejects legacy `lock_kv` actions with HTTP 410.
- The session store is one completed subset, not an entire app transition. In particular `answer_budget_tokens` and `strata_image_tool` still return an explicit HTTP 501 rather than losing their semantics; image tasks, gallery/history assets and complete site static serving are not yet available. Character/worldbook/workflow APIs are implemented separately below.
- Tests use disposable temporary directories and check multi-client concurrent saves, persistence across store reopening, API authentication and no KV pin endpoints. Old chats, old images and stable settings are not read or modified.

## Native character/worldbook/workflow: completed Gateway APIs

Mikuchin's previously owned business logic was moved out of the old embedded
`serve` source into **`backend/gateway/characters.py`, `lore.py` and
`workflows.py`**. The engine itself is never edited. Every file read/write
belongs either to a new Native data root or to an **explicitly configured**
Markdown reference path.

- `GET/POST /v1/strata/characters`: card creation, edit, delete, Tavern JSON V2/V3 import, global persona, default role, per-session role assignment, Markdown retrieval, workflow inspection/preparation/commit, and role-reference upload/removal. All carry Gateway Bearer authentication. Roles can only be reassigned while a fresh conversation has zero persisted messages.
- `GET /v1/strata/characters/reference/{card-id}`: authenticated, private/no-store PNG reference image, normalized with Pillow and kept beside the card in the new Native character folder; image path and credentials are never echoed into HTTP logs.
- Workflow initialization is frozen per session and commits only after a successful first response; a modified Markdown source does not rewrite the active session's pinned workflow **text** (this is not KV/PIN caching).
- `DELETE /v1/strata/sessions/{id}` also clears the independent character assignment and frozen workflow metadata. A list **pin to top** remains a UI action unrelated to the engine.
- Global chat-image preferences currently permit only the placeholder `default` profile with valid local sizes and **no LoRA**; user-facing image-model catalog and Image Worker are not implemented. The Gateway deliberately rejects unavailable model names rather than falsely advertising image generation.
- `characters.js` already composes character identity, worldbook snippets and workflow instructions into the **full system prompt sent to official PolyStrata**. This does not turn external `/v1/chat/completions` calls into a server-side role injector; separate non-browser callers must still construct their own context.
- Character module unit tests were carried forward and adapted as native Gateway tests; HTTP tests now cover locked-after-first-message role assignment, Markdown lookup, workflow first-turn initialization/version freeze and protected reference images. The one-command official-process smoke test also verifies a character + Markdown + workflow through the Gateway.

## One-time setup in a new worktree

```powershell
cd E:\LLM\deploy\mikuchin-native
git -c core.longpaths=true submodule update --init --depth 1
.\scripts\native-polystrata.ps1 verify
python -m unittest discover -s backend/gateway -v
```

On Windows enable `core.longpaths=true` for checkout. Official PolyStrata's tracked benchmark paths can exceed Windows' traditional short-path limit. Its source, license and tests remain **unmodified**.

To actually serve a real GPU model, set up a separate official engine through its upstream instructions in `backend/polystrata/README.md`. Prepare an official model config outside user data directories, bind official HTTP only to `127.0.0.1:15240`, and assign it an API key. A real CUDA engine/model launch is **not yet automated or verified**; only the official Mock Engine has been started as a transport test.

An isolated Python **3.12** environment with the official pinned Python requirements was installed at `E:\LLM\deploy\mikuchin-native-runtime\.venv` for testing. The smoke script automatically finds a sibling `mikuchin-native-runtime` directory, or accepts `-RuntimeRoot` and `-Python` parameters. It lives outside either Git worktree and never shares the stable application's chat database. The official CUDA executable has **not** been installed or model-loaded here yet; it must be obtained from a verified official release or compiled from the pinned source. The original stable application's patched `strata-poly.exe` must not be used as if it were official.

### Verified official-process transport smoke test (Mock Engine, no real GPU)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-native-transport.ps1
```

This starts the **unmodified official** `python -m serve.server --engine mock` on `127.0.0.1:15240` and the standalone Gateway on `127.0.0.1:15249`, using two freshly generated API keys inherited as environment variables. It verifies `/health`, `/v1/models`, Chat Completions, SSE streaming, fresh session CRUD, role assignment and immutability, character Markdown retrieval, one-time workflow initialization, and HTTP 501 for unported answer-budget semantics. Both children are stopped and disposable conversation data deleted when the script exits. The original stable port **15239 is neither opened nor restarted**. A successful mock test does not demonstrate GPU throughput or KV cache speed.

For an isolated Gateway smoke test after official engine setup:

```powershell
$env:MIKUCHIN_GATEWAY_API_KEY = '<private-new-key>'
$env:MIKUCHIN_UPSTREAM_API_KEY = '<official-private-key>'
.\scripts\start-native-gateway.ps1 -Port 15249 -OfficialPort 15240
```

Never hard-code real keys in scripts, commit them, or copy existing Mikuchin secrets into this branch. `15249` is a development Gateway port; later production will retain external `15239`. The official upstream should **never** bind to the public interface.

## Current Gateway contract (first milestone)

Supported: authorized `GET /health`, `GET /v1/models`, standard inference `POST /v1/chat/completions`, `POST /v1/messages`, `POST /v1/responses`, `POST /v1/images/generations`, and generated-image reads. It forwards directly to official localhost PolyStrata with an **independent upstream key** and streams response bytes without buffering the full response. New-session, character, Markdown/workflow, role reference and global sampling APIs are handled by Mikuchin's own stores and **never** forwarded upstream.

Explicitly blocked (HTTP 501): `strata_image_tool`, `answer_budget_tokens`. The UI-only `strata_session_id` and `mikuchin_stateless` are validated and stripped from otherwise full-context inference requests. The old `lock_kv` API returns HTTP 410 (retired). No `/slots`, `/config`, direct model control or other private application endpoints are exposed to remote clients.

The transport deliberately does **not** automatically retry POST requests, particularly paid image calls. Client requests require a Bearer key; cross-origin access is denied unless the origin matches the Host or is allowlisted.

## Updating PolyStrata (no source merge)

```powershell
.\scripts\native-polystrata.ps1 status
.\scripts\native-polystrata.ps1 pin -Tag v0.1.45-poly.10  # replace with the candidate release
.\scripts\native-polystrata.ps1 verify
python -m unittest discover -s backend/gateway -v
git diff --cached --submodule=short -- backend/polystrata
```

Run the engine model/KV/tool/SSE compatibility suite **before** committing the new submodule pointer. The update mechanism changes only which **official commit** is checked out. No Git merge or C++ diff reconciliation is needed. It does **not** guarantee that future official HTTP/protocol behavior remains compatible; all candidate versions must pass tests and an actual model check.

## Planned work (not yet implemented)

1. Native PolyStrata bootstrapping + real model smoke test (chat, visuals, automatic checkpoints and parked-conversation cache; optional Warm Start and official PIN in isolation).
2. Extend the **newly implemented** session/character/worldbook/workflow APIs to all remaining UI state, then serve the full new Web UI only when all required endpoints, image hooks and access-control checks exist. Old chat/KV history need not migrate and no manual KV lock feature returns.
3. Chat tool orchestration, answer token budget, `strata_mcp` events, image-worker scheduling and GPU mutual exclusion.
4. Desktop launcher to supervise *both* Gateway and official PolyStrata, mobile/gallery parity, authentication and upgrade rollbacks.
5. Replace the original single-repo release packager: its current `.gitmodules` restriction belongs to v0.3.0, and cannot be used unmodified for this development branch. Packaging must include a separately versioned official engine with verifiable commit and license.

The detailed migration design is in `docs/PLAN_OFFICIAL_POLYSTRATA_GATEWAY_v0.3.0.md`.
