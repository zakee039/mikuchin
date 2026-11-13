# Mikuchin v0.2.7 — standalone repository

## Independent source repository

Mikuchin no longer relies on the personal PolyStrata fork for its source code:

- Removed the Git submodule, `.gitmodules`, and the external fork URL.
- Imported the 4,025 existing backend source files into `backend/polystrata/`
  as regular, first-party-repository-tracked files.
- Preserved the original MIT license and attribution in
  `backend/polystrata/LICENSE` and `THIRD_PARTY_NOTICES.md`.
- Kept backend paths and application interfaces intact so existing deployments
  can continue to use their local runtime, models and sessions.
- Updated three-language README clone instructions, standalone-repository
  regression tests, source packaging and the official website version.
- Shortened the paths of 72 legacy benchmark records (without dropping their
  contents) and added a mapping manifest, so default Git for Windows clones
  work without enabling `core.longpaths`.

## Component versions

- **Mikuchin main program:** 0.2.7 (new independent source tree).
- **Windows launcher:** 0.2.4 (unchanged binaries, same SHA-256 as v0.2.6).
- **Android:** 0.2.4 / versionCode 204 (unchanged signed APK).

## Get the source

```sh
git clone https://github.com/zakee039/mikuchin.git
```

No `--recurse-submodules` or `git submodule update` is required.
Both GitHub's automatically generated source archives for **this tag** and the
attached main-program ZIP include the bundled backend code.

As before, a source checkout is not a portable prebuilt GPU runtime: model
weights, native engines, GPU drivers and local configuration are not bundled.

## Assets

- `Mikuchin-Main-v0.2.7-source.zip` — self-contained tracked source tree.
- `Mikuchin-Main-v0.2.7-source.zip.sha256` — SHA-256 digest.
- `Mikuchin-Launcher-v0.2.4.exe` — unchanged Windows portable client.
- `Mikuchin-Launcher-v0.2.4-Setup.exe` — unchanged Windows installer.
- `Mikuchin-Android-v0.2.4.apk` — unchanged Android release APK.

Earlier tags such as v0.2.6 still have historical submodule entries. Their
GitHub automatic source archives should not be used after the fork is removed;
use this tag or the independently packaged v0.2.6 release attachment instead.

## Validation

Standalone source-tracking checks, Python regression tests, frontend build,
source archive audit and clean-clone checks validate this release. GPU inference
and remote-device behavior still require testing on the target hardware.
