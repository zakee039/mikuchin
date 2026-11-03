# Mikuchin independent versions

Mikuchin has **three separately versioned components**, effective from the
**main-program v0.2.5** release:

| Component | Authority | v0.2.5 release |
| --- | --- | --- |
| Main program (server + web workspace) | `frontend/web/versions.js` → `main` | **0.2.5** |
| Windows desktop launcher (Tauri) | `frontend/launcher/src-tauri/tauri.conf.json`, `Cargo.toml`, `package.json`/lock | **0.2.4** |
| Android client (WebView + embedded tsnet) | `frontend/android/app/build.gradle.kts` | **0.2.4**, `versionCode=204` |

`frontend/web/versions.js` also displays the **current** launcher and Android
component versions on the About page. When changing either client, update
its corresponding source manifest and this display metadata together. Check
alignment with `python -m unittest discover -s tests -p test_release_versions.py`.

The GitHub release tag `vX.Y.Z` **always denotes the main-program version**.
It is not an assertion that the Tauri or Android binaries have the same version.
Use component-aware filenames and state unchanged components plainly in the
release notes.

For main-only releases, attach the existing, **byte-identical** signed APK and
launcher/installer binaries with their **original** versioned names. Do not
recompile, re-sign, increase Android `versionCode`, or bump Tauri just to match
the main-program number. Windows and Android clients connect to the new main
program over the same API.

`scripts/package-main-release.py` packages committed tracked files, including
the pinned PolyStrata submodule. This is **source code**: Python deps, native
engine binaries, model weights, secrets and user data are deliberately excluded.
The GitHub-generated automatic source archive does **not** include submodule
content; use the explicit main-program ZIP when the complete source is needed.
