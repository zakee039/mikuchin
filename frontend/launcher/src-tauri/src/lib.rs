//! Native Gateway launcher. Stable launcher code remains available in Git history;
//! this worktree intentionally runs ONLY the isolated official PolyStrata stack.
mod security;
mod native_prefs;
mod native_network;
mod native;
pub use native::{run, self_test};

pub(crate) fn state_dir() -> std::path::PathBuf {
    native::state_dir()
}
