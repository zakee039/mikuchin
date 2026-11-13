# Third-party code and attribution

Mikuchin is maintained as an independent repository and includes the inference
engine source directly under `backend/polystrata/`. This is a vendored copy,
not a Git submodule and not a dependency on any personal fork.

The engine incorporates work by:

- **Strata** — © 2026 Niko1221 and the Strata contributors.
- **PolyStrata** — © 2026 VecSzn and the PolyStrata contributors.

The inherited engine code is licensed under the **MIT License**. The original
copyright statements, permission terms and disclaimer are preserved verbatim
in [backend/polystrata/LICENSE](backend/polystrata/LICENSE). Contributors retain
their respective copyrights; including source in Mikuchin does not change
authorship or relicensing requirements.

The engine also contains separately licensed dependencies, assets and source
copies. Their original notices remain with their corresponding files and must
be honored when redistributing binaries.

Native runtime libraries, GPU drivers and model weights are **not** bundled with
the Git repository. Obtain them under their own terms when deploying the app.
