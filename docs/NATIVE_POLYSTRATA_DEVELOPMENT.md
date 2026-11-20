# Native PolyStrata integration branch

> **2026-11-20 status note:** Sections further down this page are a chronological
> migration journal and may describe earlier missing features. Native
> three-process Tauri supervision and Gateway static serving have since been
> implemented and tested. The isolated local Qwen-Image Official/Uncensored,
> three LoRAs, Real-ESRGAN 4× and cross-process GPU arbitration are implemented
> and verified with real RTX 3070 Ti/CUDA/Vulkan runs; see
> `docs/NATIVE_LOCAL_IMAGE_GPU_2026-11-20.md` for current behavior, tests and
> limitations. No installer/Tag/Release has been created for this architecture.

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
- Global chat-image preferences currently permit only the placeholder `default` profile with valid local sizes and **no LoRA**; locally running Qwen-Image and LoRA providers are not yet implemented. The separate online Image Worker is described below.
- `characters.js` already composes character identity, worldbook snippets and workflow instructions into the **full system prompt sent to official PolyStrata**. This does not turn external `/v1/chat/completions` calls into a server-side role injector; separate non-browser callers must still construct their own context.
- Character module unit tests were carried forward and adapted as native Gateway tests; HTTP tests now cover locked-after-first-message role assignment, Markdown lookup, workflow first-turn initialization/version freeze and protected reference images. The one-command official-process smoke test also verifies a character + Markdown + workflow through the Gateway.

## Online image API + task history + indexed gallery (first implementation)

Mikuchin owns `backend/gateway/image_providers.py`, `image_jobs.py`,
`worker.py`, and `gallery.py`. These modules are **outside** the official
engine's Git submodule. **The Gateway is now enqueue-only**: billable online
image calls execute in a distinct `python -m backend.gateway.worker` process.
The model/GPU resource arbiter and local Qwen-Image/LoRA/4× worker remain
unimplemented. The worker can currently be launched manually, but the native
desktop launcher **does not supervise/restart it yet**.

Start separate processes in distinct terminals (do not run the stable desktop
launcher during experimental model tests):

```powershell
# The official PolyStrata service binds 127.0.0.1:15240 separately.
.\scripts\start-native-image-worker.ps1
$env:MIKUCHIN_GATEWAY_API_KEY = '<private-gateway-key>'
$env:MIKUCHIN_UPSTREAM_API_KEY = '<private-official-key>'
.\scripts\start-native-gateway.ps1 -Port 15249 -OfficialPort 15240
```

Both Gateway and Worker use the same *new* `MIKUCHIN_NATIVE_DATA_DIR` when
overridden. Only the Worker executes requests: an absent/unhealthy heartbeat
causes an explicit rejection of paid submissions. `native-worker.lock` is held
by the operating system so a second worker cannot reset live jobs; SQLite
`worker_status` publishes a heartbeat while provider requests block. The worker
recovers uncertain previous tasks as failed, **never replays** them, and uses
transactional single-job claims. In unit tests only, an explicit
`embedded_worker=True` flag supplies an in-process fake provider; production
Gateway never enables that flag. Keep a worker *running* before accepting any
billable image submissions; the independent Worker lifecycle should eventually
be owned by the native launcher.

- `GET/POST /v1/mikuchin/image-api-services` saves/list/deletes online OpenAI Images-compatible services and probes model catalogs on explicit request. Service credentials live in the isolated Native data root under `images/config/image-api-services.json`; returned public service metadata contains `has_key`, never the API key. SOCKS proxy selection needs PySocks from `backend/gateway/requirements.txt`.
- `GET /v1/mikuchin/image-models` lists configured **online API** image models only. It deliberately does not advertise missing local engines/LoRA models. Nine fixed standards (including 1536×1536), local preset sizes and custom 16-aligned sizes are enforced according to provider configuration.
- `GET/POST /v1/mikuchin/image-jobs` supports detached, SQLite-backed drafts, edit, copy, activate, retry, list, delete and clear completed records. **Draft saving never causes a paid API call. Only explicit activation or retry enters the queue.** Task capacity is bounded to 80; this first worker serializes generation even if a provider advertises greater concurrency. Browser disconnect does not automatically cancel accepted tasks. Service restart converts uncertain `running` tasks to `failed` **without replay**, warning the user to check upstream billing before manually retrying.
- A failed task retry inserts the replacement `running` record and deletes its predecessor in **one SQLite transaction**, only after preparing/validating the new job. Successful-task retries keep the old success record. A failed validation/queue rejection cannot delete the old failed record.
- Up to 8 reference PNG/JPEG/WebP images are stored using SHA-256 content-addressed files outside SQLite. Credentials and raw image bytes are never added to job rows. Existing reference IDs work across draft edits and retries. Generated PNGs are independent files under `images/generated-images` and do not disappear when users delete history records.
- `GET/POST /v1/mikuchin/gallery`, `GET /v1/mikuchin/gallery/item`, and authenticated image/thumbnail GETs use a private SQLite gallery index; NSFW flags, multiple selection/delete and existing variant operations are separate from task records. Neither old gallery databases nor old session folders are imported.
- **Not ported**: Qwen-Image local/uncensored paths, LoRA, image-to-image local workers, GPU sharing, 4× upscaling, chat-triggered image tool, generating-image-to-LLM vision feedback, and client runtime packaging. `strata_upscale=4x` is rejected instead of silently claiming success. Full browser UI still requires all its non-image settings endpoints.
- **UI image authentication now implemented**: `frontend/web/auth-images.js` fetches gallery thumbnails and full images with Bearer headers, creates only ephemeral Blob URLs, cleans up on page/re-render/image switch, caps the binary cache, and flushes it on authorization identity changes. Gallery and Image Studio now use it instead of raw `<img src>` for protected endpoints. Authorization remains mandatory on the server. A full end-to-end interactive browser run is still required before declaring the native UI complete.
- An image provider request that succeeds but fails at **gallery indexing** is recorded as a successful generation with a recoverable `gallery_warning`, not as an unsuccessful paid request requiring another chargeable retry.
- Local tests use a **localhost fake OpenAI Images server** to exercise actual HTTP, base64 response decoding, PNG writing, gallery registration and task/gallery deletion separately. The smoke script only creates a disposable service and an **offline draft**; it never activates a paid request. Real third-party image APIs have not been contacted.

## Three-process Native supervisor (development CLI implemented)

`backend/gateway/supervisor.py` and `managed_child.py` now own the lifecycle
of three independent services: **unmodified official PolyStrata**, detached
Image Worker, and authenticated Mikuchin Gateway. No upstream source edits are
needed. This is currently a **developer CLI**, not the finished Tauri Launcher.

```powershell
cd E:\LLM\deploy\mikuchin-native
$env:MIKUCHIN_GATEWAY_API_KEY = '<new-private-key-of-at-least-12-characters>'

# No GPU or billable requests:
.\scripts\start-native-stack.ps1 -Engine mock

# Verified local RTX 3070 Ti / official Gemma 4 GGUF:
.\scripts\start-native-stack.ps1 -Engine strata `
  -ConfigPath 'E:\LLM\deploy\mikuchin-native-runtime\config\official-sm86-model-test.json'
```

Gateway serves the browser shell at `http://127.0.0.1:15249/`, and the
official engine remains restricted to `127.0.0.1:15240`. Press Ctrl+C to
stop the stack gracefully. A future desktop Launcher may start the Python
supervisor with `--control-stdin` and send a private `STOP` line. The public
Gateway key is supplied by the user; a **different** internal-only upstream
key is generated on every startup, never logged or persisted. Default storage
is `mikuchin-native-runtime/native-user-data` rather than the old chat folder.

- Startup waits for official `/health`, Worker SQLite heartbeat, then Gateway
  `/health`. A stale Worker heartbeat cannot satisfy this readiness test.
- Startup refuses occupied ports, **15239**, and any data folder beneath
  the stable Mikuchin repository. The stable Launcher is never stopped.
- Unexpected child exits are restarted at most three times per role in a
  sliding 60-second window; crash loops stop the stack. Worker restart marks
  uncertain paid jobs as failed **without automatically retrying them**.
- Shutdown stops Gateway intake first, lets the Worker finish active provider
  requests, and asks the official service to execute its normal cleanup via
  a private stdin control pipe. `supervisor-status.json` exposes only phase,
  PIDs and ports; logs are contained within the Native runtime data folder.
- On Windows some virtual-environment `python.exe` executables are redirector
  processes, so Worker readiness uses a new heartbeat since startup rather
  than assuming `subprocess.Popen.pid == os.getpid()` inside the worker.
- Public static routes are allowlisted (`/`, `/index.html`, `/monitor.html`,
  `/web/*.js|css|svg`). **All private APIs and images still require Bearer
  authorization.** Safe authenticated `GET /api/models` and `/metrics` are
  forwarded. `/config` and arbitrary raw upstream control remain blocked.

**Real unified-stack validation (2026-11-20):** Three processes all became
healthy; the browser HTML loaded without API credentials while `/v1/models`
returned HTTP 401 unauthenticated. A real Gemma 4 26B-A4B chat request via
Gateway returned `2` for `1+1` (1.34s). Repeating a 1,221-token prompt with
12-token answer limits reported 0 then **1,220** cached tokens (1.95s then
0.16s). Sending `STOP` ended the manager and freed both development ports.
These are individual local timings, not a general throughput benchmark.

**Still unfinished:** Tauri tray/installer supervision, interactive browser
settings and model lifecycle controls, Android integration, local Qwen-Image,
LoRA, 4× upscaling and GPU arbitration. A usable HTML entrypoint is not yet
equivalent to a complete stable-client replacement.

## One-time setup in a new worktree

```powershell
cd E:\LLM\deploy\mikuchin-native
git -c core.longpaths=true submodule update --init --depth 1
.\scripts\native-polystrata.ps1 verify
python -m unittest discover -s backend/gateway -v
```

On Windows enable `core.longpaths=true` for checkout. Official PolyStrata's tracked benchmark paths can exceed Windows' traditional short-path limit. Its source, license and tests remain **unmodified**.

To serve a real GPU model, prepare a separate official model configuration outside both Git worktrees and bind upstream HTTP only to loopback. The Native supervisor above has now **successfully launched the actual official CUDA Gemma 4 engine**, not just the Mock Engine.

An isolated Python **3.12** environment with official pinned Python requirements is installed at `E:\LLM\deploy\mikuchin-native-runtime\.venv`. The original Mock smoke script finds the sibling runtime directory or accepts `-RuntimeRoot` and `-Python`; private data remains outside both Git worktrees. The **official CUDA executable has been compiled and loaded with the existing GGUF** from `mikuchin-native-runtime\build-cuda86`, without changing the official submodule. Never substitute the old stable application's patched `strata-poly.exe` for this official binary.

### Verified official-process transport smoke test (Mock Engine, no real GPU)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-native-transport.ps1
```

This starts the **unmodified official** `python -m serve.server --engine mock` on `127.0.0.1:15240`, the standalone Gateway on `127.0.0.1:15249`, and the **separate Native Image Worker subprocess**, using freshly generated API keys and a disposable data directory. It verifies `/health`, worker heartbeat, `/v1/models`, Chat Completions, SSE streaming, fresh sessions, roles/Markdown/workflow, online image service registry, **offline draft** and empty gallery, and HTTP 501 for unported answer-budget semantics. All three children are stopped and disposable data deleted when the script exits. Pass alternate ports like `-UpstreamPort 15440 -GatewayPort 15449` if a real model is already running on 15240/15249. A successful Mock test does not demonstrate GPU/KV throughput.

### Real official CUDA model and automatic KV reuse: verified

On the Windows 10 RTX 3070 Ti / CUDA 13.2 machine, we compiled the **unmodified
official tag v0.1.45-poly.10** for `CMAKE_CUDA_ARCHITECTURES=86` and used the
resulting 74.8 MB `strata-poly.exe` from the sibling runtime directory. It
successfully loaded the existing **Gemma 4 26B-A4B Q4_K_M GGUF (16.1 GiB)**
with `--conversation-cache-mib auto --conversation-cache-slots 4 --kv int8`
and an 8192-token context. The model and old tokenizer were read only; the
expert profile was copied into the new runtime directory, so no old service
data was mutated. Real Chat Completions were exercised both directly and
through the standalone Gateway. A 6755-token synthetic prompt received 0
cached tokens on the first request and **6754 cached tokens** on immediate
repeat; after several other requests, resubmitting it through Gateway still
reported 6754 cached tokens. See
[`docs/NATIVE_OFFICIAL_CUDA_VALIDATION_2026-11-20.md`](NATIVE_OFFICIAL_CUDA_VALIDATION_2026-11-20.md).

For an isolated Gateway smoke test after official engine setup:

```powershell
$env:MIKUCHIN_GATEWAY_API_KEY = '<private-new-key>'
$env:MIKUCHIN_UPSTREAM_API_KEY = '<official-private-key>'
.\scripts\start-native-gateway.ps1 -Port 15249 -OfficialPort 15240
```

Never hard-code real keys in scripts, commit them, or copy existing Mikuchin secrets into this branch. `15249` is a development Gateway port; later production will retain external `15239`. The official upstream should **never** bind to the public interface.

## Current Gateway contract (first milestone)

Supported: authorized `GET /health`, `GET /v1/models`, `GET /api/models`, `GET /metrics`, standard inference `POST /v1/chat/completions`, `POST /v1/messages`, `POST /v1/responses`, `POST /v1/images/generations`, and generated-image reads. It forwards directly to official localhost PolyStrata with an **independent upstream key** and streams response bytes without buffering the full response. New-session, character, Markdown/workflow, role reference, online image services/jobs/gallery, and global sampling APIs are handled by Mikuchin's own stores and **never** forwarded upstream. Generated image URLs under `/v1/images/files/{id}.png` are served from the Native gallery when indexed there, with the official server as fallback.

Explicitly blocked (HTTP 501): `strata_image_tool`, `answer_budget_tokens`. The UI-only `strata_session_id` and `mikuchin_stateless` are validated and stripped from otherwise full-context inference requests. The old `lock_kv` API returns HTTP 410 (retired). No `/slots`, `/config`, direct model control or other private application endpoints are exposed to remote clients. The browser's other settings/model management endpoints remain incomplete; serving HTML does **not** imply every UI control is functional.

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

1. **Text-only CUDA smoke complete** for Gemma 4, including actual automatic KV reuse; continue with mixed prompts, short/long context, multi-session cache eviction, restart and vision. Official Warm Start/PIN remain optional and are not needed for the initial native architecture.
2. Extend the **newly implemented** session/character/worldbook/workflow APIs to all remaining UI state, then serve the full new Web UI only when all required endpoints, image hooks and access-control checks exist. Old chat/KV history need not migrate and no manual KV lock feature returns.
3. Chat tool orchestration, answer token budget, `strata_mcp` events, image-worker scheduling and GPU mutual exclusion.
4. **Tauri Native Launcher integrated (2026-11-20)**: Rust manages the three-process supervisor through a private STOP pipe, separate DPAPI key/app identity/data directory, bounded watchdog, and new status UI. Rust unit tests, Mock/CUDA headless smoke, and actual Tauri window/tray event-loop smoke passed. Next: settings/mobile parity, GPU coordination, native packaging, and rollback tests. See `docs/NATIVE_TAURI_LAUNCHER.md`.
5. Replace the original single-repo release packager: its current `.gitmodules` restriction belongs to v0.3.0, and cannot be used unmodified for this development branch. Packaging must include a separately versioned official engine with verifiable commit and license.

The detailed migration design is in `docs/PLAN_OFFICIAL_POLYSTRATA_GATEWAY_v0.3.0.md`.
