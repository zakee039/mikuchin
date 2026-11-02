# Image Studio: model-specific drafts and optional reference images

Mikuchin's **Images** tab (not Chat) supports three editable inputs:

- **Natural language**: one shared text across image models; always preserved on switching.
- **Positive Prompt / Negative Prompt**: editable model-specific drafts. The image endpoint receives the positive text directly; if it is empty, generation uses the natural-language text unmodified. Native SDXL and Qwen prompt translation is not automatic.
- **Parse with AI**: an explicit one-shot `/v1/chat/completions` call to the **currently active LLM**. It uses `mikuchin_stateless: true`, a single user message with instructions, `stream: false`, no MCP/tools/image generation, and expects JSON with English `positive` and `negative` strings. Existing prompts are overwritten only after confirmation and a successful valid response. It does not save a Chat conversation or use SessionV1 KV.

Switching the image model never invokes the LLM automatically. The first switch to a new profile copies the current positive and negative text into that profile's draft, without deleting the source. Existing target drafts are restored instead of overwritten. A button allows an explicit model-specific rewrite. Each profile stores its own positive/negative text, size, upscale, steps and seed under a browser-local `image-drafts-v2` record. Natural language is shared across models. This is client-side browser storage, not a sync of draft data across devices.

## Reference picture

The selected image remains in the current browser tab while switching models, and is **not** uploaded until the user explicitly generates or converts it. Reference pictures are limited to PNG, JPEG or WebP, 5 MB.

- **SDXL Base 1.0 and Animagine XL 4.0**: supports real **img2img** through `sd-cli --init-img` and `--strength 0.65`. The backend validates the file, normalizes its colors/orientation, resizes it to the request's output canvas and stores it in the short-lived image-job directory. It is deleted with the job. This is img2img, not IP-Adapter identity reference or ControlNet. It may alter the source subject strongly at higher strengths.
- **Qwen-Image Turbo Official**: the new Qwen3-VL encoder and mmproj enable native image reference using stable-diffusion.cpp `--ref-image`; explicit text instructions remain primary. **Qwen Turbo Uncensored** has no matching mmproj configured; it uses Convert now as a fallback. A reference is never silently handed to the Qwen generator. When the current text LLM has vision capabilities, **Convert now** makes an explicit single-turn multimodal LLM request and **appends** its English description to Positive Prompt, preserving the picture and previous Prompt. If no vision support, conversion is disabled and explained. The user can still generate using only text after explicit confirmation.

The backend image-model catalog advertises `steps`, `max_side`, and `reference_mode`, without revealing private weight paths; the API key is required. The image generation endpoint optionally accepts `steps`, `negative_prompt`, `strata_image_profile`, `strata_reference_image` (strict image data URL only for SDXL), `strata_denoise_strength` (0.05–1) and existing OpenAI-compatible fields.

The original Chat image-generation tool remains wired to the original default Qwen image model: neither the image-page selector nor its drafts or reference uploads are passed to Chat. Stable-diffusion.cpp with 8GB VRAM still uses the existing GPU FIFO/unload/reload design.

## Testing and limitations

- SDXL image reference uses img2img, **not** a guaranteed faithful identity or style reference. Stronger semantics need dedicated future model adapters.
- There is no image analysis for text-only LLMs: the UI explains why conversion is not available.
- An in-browser reference file is intentionally **not written to localStorage**, to avoid a hidden persistent copy of private images; reselect after a browser refresh. Other text draft fields persist locally.
- Prompt rewriting is only as reliable as the current LLM's English and JSON output. Parse failures do not overwrite existing drafts.
