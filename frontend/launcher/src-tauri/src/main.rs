// Hide a console for standalone debug previews as well as Release builds.
#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]
fn main() {
    if std::env::args().any(|arg| arg == "--self-test-native" || arg == "--self-test"
        || arg == "--self-test-full") {
        std::process::exit(mikuchin_lib::self_test());
    }
    mikuchin_lib::run();
}
