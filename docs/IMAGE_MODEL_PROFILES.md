# Mikuchin — four image profiles (Qwen Turbo official/uncensored, Animagine, SDXL)

## Model truth and provenance

`qwen_image_2.1-Q4_K.gguf` newly downloaded from `leejet/Qwen-Image-2.1-GGUF` is **Qwen Image 2.1 Base** (NOT Turbo). It is retained under `E:/LLM/models/Qwen-Image-2.1-Official-Components/` but deliberately not exposed as the Turbo profile. Base requires different recommended denoising parameters (about 40 steps) and should not use the Turbo 8-step sigma schedule.

The Turbo DiT file `Qwen-Image-2.1-Turbo-AD-Q4_K.gguf` is the pre-existing **community-quantized** Turbo main model (AtomicChat lineage). `E:/LLM/models/Qwen-Image-2.1-Official-Components/` contains a hard link to it; this avoids duplicating ~4.2 GB. **It is not a vendor-published original-precision Turbo checkpoint.** The two Turbo profiles share the same DiT main tensors but use different Qwen3-VL text encoders, so this is a genuine unmodified-encoder vs modified-encoder comparison, not two independent DiT checkpoints.

- `qwen-image-2.1-turbo-official` (default for Chat image tool unless overridden in Global Settings): community Turbo DiT, new Qwen official `Qwen3VL-8B-Instruct-Q4_K_M.gguf` + `mmproj-Qwen3VL-8B-Instruct-F16.gguf`, shared BF16 Qwen Image 2.1 VAE. Text-to-image and native reference-image edit via sd-cli `--llm_vision` and `--ref-image`. 8 steps, CFG 1, Turbo sigma schedule.
- `qwen-image-2.1-turbo-uncensored`: same Turbo DiT, legacy modified/unrestricted Qwen3-VL 8B encoder, shared BF16 VAE. Text-to-image; no visual projector connected to this profile.
- `animagine-xl-4-opt`: unchanged standalone SDXL checkpoint, 28 steps, CFG 7.
- `sdxl-base-1`: unchanged standalone SDXL checkpoint, 30 steps, CFG 7.

The active Windows Manager registered configuration is `E:/LLM/deploy/benchmark/configs/reserve1024-128-v1.json`; project-local `config/active.json` is only a reference. Both files are locally backed up before mutation and are not committed to Git. `images.profile_id` exposes the default profile as `qwen-image-2.1-turbo-official` in the browser while the API still accepts the legacy `default` alias. This is per-deployment configuration, not a public API model change.

## Role-linked Chat images: weak reference policy

Only the authenticated first-party Chat tool can use private character reference images. For a named, assigned character with a stored reference picture, the model can mark a tool request `character_related: true` **only when the image subject is the assigned role**. The server independently verifies the session-to-character assignment and reads a bounded picture directly from the trusted SessionV1 store; the client cannot supply a filesystem path or impersonate a role. Stateless and ordinary assistants never get character references; generic landscape/art requests do not get a reference.

The role image is a **weak identity/style reference**, not a prompt or scene instruction. The generated tool prompt explicitly prioritizes the user's current turn and established conversation context: special events/holidays, clothing, pose, environment, subject and composition override any conflicting visual elements in the role art. The native Qwen runner uses `--ref-image` and an experimentally conservative `--img-cfg-scale 0.7`; this mitigates but cannot strictly guarantee reference strength. Never use the role picture as a global fixed image init or blindly copy its background/clothing.

Image-page manual reference and SDXL img2img behavior are independent; ordinary third-party OpenAI-compatible API calls without a role/session remain unaffected.

## Validation

Both the official text encoder path and the native Qwen reference picture path were executed with the actual local `sd-cli`: 256×256, 1-step smoke tests returned PNG images. These tests prove loading and API wiring, not final 8-step visual quality or identity fidelity. Automated tests cover profile ID routing, no unrelated reference, no stateless/ordinary reference, text prompt priority, and CLI arguments.

## Configurable Chat image model (Global Settings)

The **Settings → Global settings → Chat image model** selector is independent from the Images tab selector. Its selected ID is validated on the server against the available model profiles, saved in the SessionV1 character-card `options` SQLite table under `chat_image_profile`, and used by the Chat image tool for **each subsequent request** (including existing conversations). Old clients that omit the field preserve the previously selected model. The default `default` alias resolves to the currently configured Official model. The API key and local-first origin protections apply to changing the global setting.

When Chat selects an SDXL profile, it uses that profile's steps/CFG and English prompt guidance. A character reference is **not** silently sent as SDXL img2img: that would be strong scene reference, contrary to the user-requested weak visual reference. Role images are automatically added only for the official Qwen model with native weak image reference and an explicitly character-related tool call. Other models generate based on the chat prompt alone, including the specified holiday, outfit, pose and scene. The direct Images page retains its own explicit SDXL img2img upload option.

## Persistent generated image URLs (2026-11-03 fix)

The first-party Chat image tool and the Images page use the **same durable**
`<session_v1_dir>/generated-images/` directory when SessionV1 is enabled.
The image retrieval route `/v1/images/files/<32-hex>.png` must resolve that
server-owned directory **first**, independent of the selected image profile and
across Manager/server restarts. Every `ImageGen` starts with a different temporary
directory, which previously led to false 404s for existing PNGs after restart or
when a non-default profile had generated the image. The URL itself contains only
an opaque 128-bit image id, never an input filesystem path; strict file-name
validation remains in place. Deployments without SessionV1 still use the older
in-process output directories. Images stored under SessionV1 remain available
until explicitly deleted or the underlying storage disappears.
