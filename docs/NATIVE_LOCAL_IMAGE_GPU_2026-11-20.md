# Native Image Worker, LoRA, Real-ESRGAN and GPU arbitration

2026-11-20, development branch `refactor/official-polystrata-gateway`.
This is an experimental implementation, **not a production release**.

## Architecture

```
Tauri Native launcher
    -> NativeSupervisor
         |-- official PolyStrata: 127.0.0.1:15240 (unchanged submodule)
         |-- Image Worker: one process, SQLite-backed queue
         '-- Gateway: 127.0.0.1:15249 (only public local HTTP entry)
                   |
                   |-- inference -> OS shared GPU turn -> official LLM
                   '-- image jobs -> SQLite -> Worker
                                          |-- online OpenAI Images API
                                          |-- local sd-cli/Qwen-Image
                                          '-- optional Real-ESRGAN 4x
```

### Isolation

- Production port **15239** and the original stable source/data are never used.
- Upstream engine credentials are private, never accepted or exposed by the browser.
- `backend/polystrata` remains the unmodified official Git submodule.
- The Native data directory owns the model registry, drafts/jobs, gallery and GPU lock.
- `gpu_gate.gpu_turn` uses a cross-process OS lock. On Windows, shared readers take distinct single-byte slots while the image writer locks the whole 256-byte region; Linux uses flock shared/exclusive. It is released automatically after process death.
- Each Gateway inference request holds the read lock until the upstream HTTP stream finishes; local image work holds an exclusive lock from official model unload through attempted reload. This prevents *Gateway*-originated inference from competing on an 8 GB GPU. Privileged direct access to the internal upstream API bypasses this policy and must remain private.

### Local image registry

The Native-only configuration is located at:

`<MIKUCHIN_NATIVE_DATA_DIR>/images/config/native-local-images.json`

Use `scripts/configure-native-local-images.ps1` with an isolated data directory to provision the default local machine. Existing config is protected against overwrite unless `-Force` is explicitly given. The provisioned profiles are:

- `local-qwen-official`
- `local-qwen-uncensored`
- LoRAs: `female-anatomy-v3`, `anatomy-fix`, `nsfw-qwen`
- Real-ESRGAN `realesrgan-x4plus-anime`

Model weights remain in `E:\LLM\models`, while installed executable/DLL and upscaler model copies live only under the separate `E:\LLM\deploy\mikuchin-native-runtime\image-engines` directory.

The config is **server-owned**. The browser chooses only a model ID and LoRA ID, never a binary path, model file path or shell argument. Required files are checked before activation; absent files appear unavailable in the model catalog. The Qwen Turbo default is 8 steps, Euler, CFG 1 and its designated sigmas, with configurable trusted local `sd-cli` arguments. Local Qwen requests accept only dimensions divisible by 32; advertised recommended sizes are 384/512/768/1024 subject to configured max side. Multi-image references are rejected if the model profile does not support them. The current default profiles do not enable the Qwen vision reference model.

## 4x semantics

- Explicit `4x` is validated **before activating** a task, including model asset availability and the maximum 4x output side (default 3072). A bad 4x request never triggers an online provider charge.
- `auto` applies only when the prompt suggests anime and does not explicitly suggest photography/realism, and the output would fit. `off` always skips 4x.
- The worker runs Real-ESRGAN as a separate GPU turn. On success, the gallery indexes a 4x cover and retains the original in one artwork pair. On failure, it records `upscale_warning` but keeps the original generation marked **success**. This is especially important for paid online providers: never retry an already generated billable image just because upscaling failed.
- A Qwen generation followed by a 4x stage currently releases and reacquires the GPU, unloading/reloading the official LLM between stages. Correctness and isolation are preferred to performance here; eliminating this redundant handoff is a follow-up optimization.

## Test commands

```powershell
$py = 'E:\LLM\deploy\mikuchin-native-runtime\.venv\Scripts\python.exe'
& $py -B -m unittest discover -s backend/gateway -q
node --test (Get-ChildItem frontend/web/tests/*.test.mjs | ForEach-Object FullName)
node --check frontend/web/image-studio.js
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/native-polystrata.ps1 verify

# Full GPU smoke: real CUDA LLM -> local Vulkan Qwen -> official LLM reload,
# separate test root, private random keys, no paid external API.
& $py -u -B scripts/smoke-native-local-real.py
```

Tests added in `backend/gateway/test_local_images.py` include concurrent shared/exclusive turns, **cross-process** lock denial/release, catalog validation, LoRA selection, Qwen subprocess adapter, original/4x gallery pairing and 4x failure preservation.

## Constraints / follow-ups

- This milestone does not build a new installer, Android APK, Tag or Release. Versions remain main 0.3.1 / launcher 0.3.0 / Android 0.3.0.
- No automatic recovery/replay of uncertain paid provider tasks after a worker crash.
- The experimental real-GPU smoke must complete separately. A fake-`_run` test proves integration logic, not actual image quality or GPU memory fit.
- The Native image binaries are local runtime dependencies, not Git-tracked distribution assets. Packaging must provide/provision these before advertising bundled local image generation.

## Real-device verification (2026-11-20, RTX 3070 Ti 8 GB)

Both runs used the actual Tauri-compatible NativeSupervisor → official CUDA
PolyStrata → independent Image Worker → authenticated Gateway, with private
random keys and disposable test roots on ports 15240/15249. No external
paid provider request was made.

| Run | Actual result | Worker duration | Gallery |
|---|---|---:|---|
| `native-real-image-smoke-20261120-v2` | Qwen-Image Official 384×384, success | 115.42 s | one indexed original |
| `native-real-image-smoke-20261120-lora4x` | Qwen-Image Official + `female-anatomy-v3` LoRA + Real-ESRGAN 4× to 1536×1536, success | 144.92 s | 4× cover plus original, two variants |

An additional direct real-Vulkan Real-ESRGAN invocation on the first
384×384 output produced a validated 1536×1536 PNG in **1.62 seconds**.
Both supervised runs showed actual private LLM unload/reload, Gateway
`/health = ok`, and parent supervisor clean exit code zero. The first
smoke attempt was interrupted by the remote command session timeout while
model weights were loading; it was marked failed without automatic retry
and its child processes exited. The two later runs are confirmed successes
with separate data roots, not a reinterpretation of that first attempt.

After validation, ports 15240/15249 had no listeners and NVIDIA reported
approximately 158 MiB / 8192 MiB idle VRAM. Port 15239 remained unused by
the tests. `scripts/smoke-native-transport.ps1` also passed the official
mock transport/Worker/character/SSE checks after real-GPU testing.
