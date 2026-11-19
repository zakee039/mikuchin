# Native PolyStrata integration branch

## Current state

- **Working tree:** `E:\LLM\deploy\mikuchin-native`
- **Branch:** `refactor/official-polystrata-gateway`, branched from the immutable Mikuchin `v0.3.0` rollback baseline.
- **Official upstream:** `backend/polystrata` is a **Git submodule** from `https://github.com/simplexai-labs/PolyStrata.git`, pinned to `v0.1.45-poly.10` (`3e1642161198c50ff1abed4046f4e4f476099dbb`).
- **Local development Gateway:** `backend/gateway/app.py` is a standalone, dependency-free minimal transport adapter. It has **not** yet ported Mikuchin sessions, character cards, KV management, workflows, image tools, gallery or launcher supervision. The existing Web/Android clients are retained for incremental porting but are not presently end-to-end usable against this Gateway.
- **Original stable installation:** `E:\LLM\deploy\mikuchin` (main, v0.3.0); running service remains on its established ports and data. Do not point it at this worktree before acceptance testing.

## Simplified KV policy (2026-11-19 design decision)

- **No migration of existing chats or `POLYKV1!` snapshots** into the new Gateway. The new application starts a clean chat store for chats created there. The stable v0.3.0 data directory is not deleted.
- **Do not port the old manual “Lock KV” / “Pin session” UI or its custom 5-snapshot-per-model manager.** Favor the official native engine's automatic exact-token-prefix checkpoint matching and opt-in parked-conversation cache (`--conversation-cache-mib auto` / `--conversation-cache-slots`). On cache miss simply prefill again.
- **Do not enable the manual disk `/slots/0?action=save|restore` path in the first implementation.** This is a separate, opt-in cross-restart mechanism, not the automatic conversation cache; it complicates serialization with parallel requests.
- Official `warm_start` and its engine `PIN` are for **one reusable common system prompt** and are distinct from the old user's manual pinned conversation snapshots. Leave `warm_start` off initially; measure repeated prompt-prefix use before enabling it.
- The new UI may still keep **new** chat transcripts and a “pin to top” ordering control; neither is a KV persistence contract. Chat messages must be resent to the engine when in-memory cache is lost.

## One-time setup in a new worktree

```powershell
cd E:\LLM\deploy\mikuchin-native
git -c core.longpaths=true submodule update --init --depth 1
.\scripts\native-polystrata.ps1 verify
python -m unittest discover -s backend/gateway -v
```

On Windows enable `core.longpaths=true` for checkout. Official PolyStrata's tracked benchmark paths can exceed Windows' traditional short-path limit. Its source, license and tests remain **unmodified**.

To actually serve a model, set up a *separate* official Python environment and engine through its upstream instructions in `backend/polystrata/README.md`. Prepare an official model config outside user data directories, bind official HTTP only to `127.0.0.1:15240`, and assign it an API key. This is **not yet automated** and no official model was started during this branch bootstrap.

For an isolated Gateway smoke test after official engine setup:

```powershell
$env:MIKUCHIN_GATEWAY_API_KEY = '<private-new-key>'
$env:MIKUCHIN_UPSTREAM_API_KEY = '<official-private-key>'
.\scripts\start-native-gateway.ps1 -Port 15249 -OfficialPort 15240
```

Never hard-code real keys in scripts, commit them, or copy existing Mikuchin secrets into this branch. `15249` is a development Gateway port; later production will retain external `15239`. The official upstream should **never** bind to the public interface.

## Current Gateway contract (first milestone)

Supported: authorized `GET /health`, `GET /v1/models`, standard inference `POST /v1/chat/completions`, `POST /v1/messages`, `POST /v1/responses`, `POST /v1/images/generations`, and generated-image reads. It forwards directly to official localhost PolyStrata with an **independent upstream key** and streams response bytes without buffering the full response.

Explicitly blocked (HTTP 501): `strata_session_id`, `mikuchin_stateless`, `strata_image_tool`, `answer_budget_tokens`. Until an adapter has faithfully ported these semantics it would be unsafe to silently ignore them. No `/slots`, `/config`, direct model control or private application endpoints are exposed to remote clients.

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
2. Complete Gateway state management, character/worldbook/workflow and new isolated SQLite stores (old chat/KV history need not migrate; no manual KV lock feature).
3. Chat tool orchestration, answer token budget, `strata_mcp` events, image-worker scheduling and GPU mutual exclusion.
4. Desktop launcher to supervise *both* Gateway and official PolyStrata, mobile/gallery parity, authentication and upgrade rollbacks.
5. Replace the original single-repo release packager: its current `.gitmodules` restriction belongs to v0.3.0, and cannot be used unmodified for this development branch. Packaging must include a separately versioned official engine with verifiable commit and license.

The detailed migration design is in `docs/PLAN_OFFICIAL_POLYSTRATA_GATEWAY_v0.3.0.md`.
