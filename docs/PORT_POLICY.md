# Mikuchin port policy

- Default TCP API port for new installations: **15239**.
- `52039` is valid but lies in the IANA dynamic/private range 49152-65535, so is not chosen as a stable service default.
- This Windows machine's TCP dynamic port range is 1024-15000; 15239 is outside its dynamic and excluded ranges, and was not listening during validation (2026-11-02).
- The legacy deployment remains on 18081 until the remotely managed Cloudflare Tunnel's ingress (`key.zakee.fun` -> `http://localhost:18081`) can be updated to 15239. Do not change its active runtime port first: it would break external access.
- `frontend/launcher/src-tauri/src/lib.rs` and `frontend/launcher/src/main.ts` use default 15239. Existing `settings.json` overrides these defaults by design.
- After updating the Cloudflare ingress to `http://localhost:15239`, change `settings.json` via the Manager API page to 15239, restart/reconfigure as required, then verify `/health`, `/v1/models` with API key, and the public HTTPS endpoint.
