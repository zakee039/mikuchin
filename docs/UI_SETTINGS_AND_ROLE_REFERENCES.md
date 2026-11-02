# Settings page, history role badges and character references

## Navigation

- Main tab order: Chat, Images, Characters, Monitor, **Settings**, About.
- Settings contains the former Characters → Global identity/default-character form, the former About → API connection information and API key/theme settings, and the model configuration form.
- About now contains only product/engine information and local hardware.
- The shared Settings view preserves existing field IDs so current credential storage and model configuration controls remain compatible.

## History role watermarks

- Each saved session displays its assigned character as a subtle italic watermark inside its history row.
- The built-in `stateless` role is a small neutral-grey label; built-in `ordinary` has **no role watermark**.
- Other names are rendered in a deterministic color derived from their text. The name stays separate from the session title, and never blocks the row or its action menu.
- History action labels (Rename / Pin / Unpin / Export Markdown / Lock and Release KV / Delete) use the shared Chinese, English and Japanese dictionaries. Saved conversations and user messages are never translated.

## Character reference artwork

- A character card has a reference image picker at its bottom. PNG, JPEG and WebP up to **5 MiB** are accepted.
- Drafts preview locally immediately. Saving a new card first creates the card ID, then automatically uploads the selected image. After reopening a card, its saved image is loaded again.
- The server normalizes the file to a maximum 1600 × 1600 PNG, with an input cap of 16 megapixels, and stores it in `chat/character_images/<32-hex-card-id>.png` beside the existing SQLite database.
- Reference images are **not** embedded into role-card JSON or sent to the model automatically. They are UI reference materials. They do not enter the prompt or KV context.
- `GET /v1/strata/characters/reference/<id>` requires the normal API authentication and same-origin rules. The UI fetches a Blob with authorization and displays it through a temporary object URL.
- `reference_upload` and `reference_remove` are authenticated same-origin character actions. Removing the card also removes its image. Other existing user files and KV snapshots are unaffected.

## Checks

- Mock server integration: reference upload → authenticated download → card rename → remove; unauthenticated image requests return HTTP 401.
- Browser integration: reference image selected before first save and displayed; reopening a saved card recovers the persisted image; history role labels and Japanese action translations render correctly.
- All existing character and inference regression tests must pass before deployment.
