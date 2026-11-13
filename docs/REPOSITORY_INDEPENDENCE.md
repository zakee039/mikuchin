# Standalone Mikuchin source

Beginning with main-program v0.2.7, Mikuchin's `main` branch
contains the backend code directly as normal Git files.

## What changed

- Removed the `.gitmodules` file and the `backend/polystrata` Gitlink.
- Imported the 4,025 previously tracked engine source files (including
  `backend/polystrata/LICENSE`) into the main repository.
- Relocated 72 deeply nested historical benchmark records into
  `backend/polystrata/bench/results/_portable_runs/` to support default
  Windows Git clones. `PATH_MAP.json` records the former file paths and all
  original file contents were retained.
- Retained the existing `backend/polystrata/` on-disk layout, so launcher,
  server, model setup, CMake, and image generation paths remain compatible.
- Updated release packaging to read **one** Git working tree.
- Added independent-clone regression tests and third-party attribution.

## Clean clone

```sh
git clone https://github.com/zakee039/mikuchin.git
cd mikuchin
```

No `git submodule update`, `--recurse-submodules`, PolyStrata fork or
additional Git remote is necessary to retrieve the app's source code.
This does **not** include prebuilt GPU inference engines or model weights;
follow the model preparation instructions in the README.

## Existing installations

The on-disk backend location is unchanged. Local builds, virtual environments,
models, credentials and conversations must remain outside Git and should be
backed up before replacing a deployed checkout. A clean clone starts without
those private runtime files.

## Historical tags

Earlier commits, including the v0.2.6 Git tag, **still reference the former
PolyStrata fork through a Git submodule**. We deliberately did not rewrite
old commit or tag history. Their GitHub-generated source archives alone cannot
fully reconstruct the backend after that fork disappears. The specifically
attached `Mikuchin-Main-v0.2.6-source.zip` Release asset includes a complete
snapshot of both trees and is independent of the fork.

Use a current commit on `main` (or any newer standalone release) for future
clones and builds.
