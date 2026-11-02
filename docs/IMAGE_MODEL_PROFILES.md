# Mikuchin — Independent model profiles in the Images page

The **Images** tab has its own image model selector; the chat image tool intentionally keeps the old default `images` model and ignores this selection.

## Installed models

| ID | Model | Weights | Default steps | CFG |
| --- | --- | --- | --- | --- |
| `default` | Existing Qwen Turbo | `E:/LLM/models/Qwen-Image-2.1-Turbo-Uncensored-AD-Q4_K/` | 8 | 1.0 |
| `qwen-turbo-standard` | Standard Qwen Turbo AD-Q4_K | `E:/LLM/models/Qwen-Image-2.1-Turbo-Standard-AD-Q4_K/Qwen-Image-2.1-Turbo-AD-Q4_K.gguf` | 8 | 1.0 |
| `animagine-xl-4-opt` | Animagine XL 4.0 Opt | `E:/LLM/models/Animagine-XL-4.0-Opt/animagine-xl-4.0-opt.safetensors` | 28 | 7.0 |
| `sdxl-base-1` | SDXL Base 1.0 | `E:/LLM/models/SDXL-Base-1.0/sd_xl_base_1.0.safetensors` | 30 | 7.0 |

SHA256 verification showed the newly downloaded standard Qwen Turbo GGUF is **byte-for-byte identical** to the currently deployed default Qwen Turbo main GGUF. These two selections therefore produce the same results when paired with the same encoder, VAE and parameters. The standard Qwen Turbo profile reuses the existing Qwen3-VL Q4 text encoder and official BF16 VAE. It is **not** an entirely original official BF16 end-to-end pipeline. Both SDXL checkpoints are self-contained and run through `sd-cli --model` with Euler sampling and no Qwen Turbo sigmas.

`config/active.json` has a locally configured `images.profiles` mapping with these IDs; the previous active config is backed up at `config/active.json.pre-image-profiles.bak`. Both files are ignored by Git. Default `images` paths and chat behavior are unchanged.

## API / safety

- Authenticated `GET /v1/mikuchin/image-models` reveals configured profile names, families, and existence checks (no arbitrary file paths).
- `POST /v1/images/generations` accepts optional `strata_image_profile`; absent means the existing default. Only configured IDs are accepted; arbitrary paths and options cannot be submitted.
- The profile is selected per request; no GPU weights are permanently held by the image process. The shared FIFO and `gpu_turn` logic are retained.
- Actual model quality is not established by API tests; SDXL Base / Animagine output should be checked visually with representative prompts.

No chat model picker integration is included in this change.
