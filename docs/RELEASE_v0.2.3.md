# Mikuchin v0.2.3

## Images

- Image Studio settings are arranged in even columns: model, LoRA, length and width; then seed, upscaling and steps.
- Length and width can each be chosen independently from 384, 512, 768 and 1024 pixels.
- One-click clear resets prompt inputs, selections, LoRA and the selected reference picture without deleting generated artwork.
- Qwen LoRA remains limited to the Images page, with no impact on Chat image generation.

## Characters and settings

- Removed the character and global settings Save buttons; changes persist automatically with status/error feedback.
- New roles are assigned the next available name, such as `角色1`, and can be renamed.
- Worldbook, Markdown sources, workflow bindings and reference-image uploads participate in autosave.
- Switching roles waits for pending writes to avoid losing edits.
- API key field no longer displays the misleading placeholder or helper wording.

## Release boundaries

- Version: `0.2.3`; existing model configuration is unchanged.
- No legacy deployment compatibility, old data roots or compatibility ports have been reintroduced.
- Cloudflare Tunnel route changes are independent from the source release.
