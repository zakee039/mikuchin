#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
fn main() {
    if std::env::args()
        .any(|arg| arg == "--self-test" || arg == "--self-test-full" || arg == "--self-test-model")
    {
        std::process::exit(mikuchin_lib::self_test());
    }
    mikuchin_lib::run();
}
