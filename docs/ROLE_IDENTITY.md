# Mikuchin — Global identity, characters and stateless chats

## Identity model

- **Global** settings are `user_name`, `user_description`, and `default_role`. Both user fields move together as one identity.
- **Ordinary assistant (built-in)** uses the global identity and normal multi-turn history / KV.
- **Custom characters** choose one of `none` (no user name or description), `global` (both fields inherited), or `independent` (both fields stored on the character card). The independent values are retained if the user switches modes temporarily.
- **Stateless (built-in)** provides no user identity, character card, world info, workflow or history to inference. Each request contains only the latest user message. Its visible conversation and complete replies are still persisted to the standard session database (`web_messages`) and can be reopened and exported. The inference API is deliberately not populated with historical `api_messages`, and the request's `strata_session_id` is stripped before KV restoration/snapshot sampling. It does **not** unload or reload the model per request.

## Per-conversation role lock

- A new, empty conversation starts with the global `default_role` and may be changed freely before its first message.
- Once the first user message or built-in character greeting is added, the role button is disabled and grayed out. The current role name remains visible.
- Loading saved conversations restores their own role assignments, without rewriting the global default.
- The server independently refuses `assign` when the session already has `web_messages` or `api_messages`, preventing UI bypasses. Changing the default does not alter existing conversations.

## Storage

- A single SQLite database (`character_cards.sqlite3`) stores character cards, session assignments and global identity/options next to the existing SessionV1 chat database.
- The source version has no old-card migration, as the user did not have any custom cards.
- The two built-in roles use reserved IDs `stateless` and `ordinary` and cannot be edited as cards.

## Safety and verification

- This mode is *stateless in model context*, not stateless in recordkeeping. It does not imply secret or ephemeral chats.
- HTTP mock tests validate assignment before/after a persisted message, one-message-only stateless requests, and durable web history without session API history.
- CharacterStore regression tests validate global settings, independent identity, built-ins, deletion and default-role checks.
- Browser tests validate global and independent fields, new-chat role selection, and the disabled role control after a saved message.
