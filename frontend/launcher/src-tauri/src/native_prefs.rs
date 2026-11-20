//! Isolated Native preferences. Only non-secret switches and public hostname
//! are persisted as JSON; API and Tunnel tokens remain under Native DPAPI.
use serde::{Deserialize, Serialize};
use std::{fs, path::Path};

const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
const RUN_NAME: &str = "MikuchinNativeDev";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default, deny_unknown_fields)]
pub struct NativePrefs {
    pub autostart: bool,
    pub auto_start_service: bool,
    pub watchdog: bool,
    // A deliberate unload is persistent: restart/startup/watchdog must not
    // silently bring the model (or its Native service stack) back.
    pub manual_unloaded: bool,
    pub lan_access: bool,
    pub cf_enabled: bool,
    pub cf_hostname: String,
}
impl Default for NativePrefs {
    fn default() -> Self {
        Self {
            autostart: false,
            auto_start_service: true,
            watchdog: true,
            manual_unloaded: false,
            lan_access: false,
            cf_enabled: false,
            cf_hostname: String::new(),
        }
    }
}

pub fn validate_hostname(value: &str) -> bool {
    if value.len() > 253 || value.len() < 4 || value.contains('/') || value.contains(':') {
        return false;
    }
    let host = value.to_ascii_lowercase();
    if [".local", ".localhost", ".internal", ".invalid", ".test"]
        .iter().any(|suffix| host.ends_with(suffix)) {
        return false;
    }
    let parts: Vec<_> = value.split('.').collect();
    parts.len() >= 2 && parts.iter().all(|part| {
        !part.is_empty() && part.len() <= 63 && !part.starts_with('-')
            && !part.ends_with('-')
            && part.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
    }) && value.bytes().any(|b| b.is_ascii_alphabetic())
}

pub fn read() -> Result<NativePrefs, String> {
    let path = super::state_dir().join("preferences.json");
    let mut prefs = match fs::read(&path) {
        Ok(bytes) => serde_json::from_slice::<NativePrefs>(&bytes)
            .map_err(|e| format!("Invalid Native preferences JSON: {e}"))?,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => NativePrefs::default(),
        Err(e) => return Err(format!("Cannot read Native preferences: {e}")),
    };
    prefs.autostart = has_autostart()?;
    Ok(prefs)
}

pub fn save(prefs: &NativePrefs) -> Result<(), String> {
    if !prefs.cf_hostname.is_empty() && !validate_hostname(&prefs.cf_hostname) {
        return Err("Cloudflare Tunnel 域名格式不正确".into());
    }
    let path = super::state_dir().join("preferences.json");
    fs::create_dir_all(path.parent().ok_or("Invalid Native settings path")?)
        .map_err(|e| e.to_string())?;
    // HKCU Run is specific to the Native EXE. Never touch stable Mikuchin.
    set_autostart(prefs.autostart)?;
    let tmp = path.with_extension("json.tmp");
    let value = serde_json::to_vec_pretty(prefs).map_err(|e| e.to_string())?;
    fs::write(&tmp, value).map_err(|e| e.to_string())?;
    replace_file(&tmp, &path)
}

fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    let from: Vec<_> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let to: Vec<_> = destination.as_os_str().encode_wide().chain(Some(0)).collect();
    #[link(name="Kernel32")]
    unsafe extern "system" {
        fn MoveFileExW(from: *const u16, to: *const u16, flags: u32) -> i32;
    }
    if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), 0x1 | 0x8) } == 0 {
        return Err(std::io::Error::last_os_error().to_string());
    }
    Ok(())
}

fn has_autostart() -> Result<bool, String> {
    use winreg::{enums::*, RegKey};
    let root = RegKey::predef(HKEY_CURRENT_USER);
    let key = match root.open_subkey(RUN_KEY) {
        Ok(value) => value,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(e) => return Err(e.to_string()),
    };
    match key.get_value::<String, _>(RUN_NAME) {
        Ok(_) => Ok(true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(e.to_string()),
    }
}

fn set_autostart(enabled: bool) -> Result<(), String> {
    use winreg::{enums::*, RegKey};
    let root = RegKey::predef(HKEY_CURRENT_USER);
    let (key, _) = root.create_subkey(RUN_KEY).map_err(|e| e.to_string())?;
    if enabled {
        let path = std::env::current_exe().map_err(|e| e.to_string())?;
        key.set_value(RUN_NAME, &format!(r#""{}" --background"#, path.display()))
            .map_err(|e| e.to_string())
    } else {
        match key.delete_value(RUN_NAME) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(e.to_string()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn isolated_settings_defaults_are_conservative() {
        let prefs = NativePrefs::default();
        assert!(!prefs.autostart && !prefs.lan_access && !prefs.cf_enabled);
        assert!(prefs.auto_start_service && prefs.watchdog);
        assert!(!prefs.manual_unloaded);
    }
    #[test]
    fn manual_unload_flag_serializes_and_defaults_for_existing_preferences() {
        let old = r#"{"autostart":false,"auto_start_service":true,"watchdog":true}"#;
        let mut prefs: NativePrefs = serde_json::from_str(old).unwrap();
        assert!(!prefs.manual_unloaded);
        prefs.manual_unloaded = true;
        let encoded = serde_json::to_string(&prefs).unwrap();
        let decoded: NativePrefs = serde_json::from_str(&encoded).unwrap();
        assert!(decoded.manual_unloaded);
        assert!(decoded.auto_start_service);
    }
    #[test]
    fn tunnel_hostname_validation_rejects_url_and_localhost() {
        for host in ["http://foo.com","bad/path","localhost","a..b","a-.example.com",
                     "127.0.0.1:15249","host.local","host.localhost","dev.test",""] {
            assert!(!validate_hostname(host), "{host}");
        }
        assert!(validate_hostname("native.example.com"));
    }
}
