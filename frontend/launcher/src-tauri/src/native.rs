//! Tauri -> Python supervisor private lifecycle bridge.
//! The official PolyStrata submodule is never imported or modified here.
use std::{
    collections::VecDeque,
    fs::{self, OpenOptions},
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    os::windows::process::CommandExt,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Mutex, OnceLock},
    thread,
    time::{Duration, Instant},
};
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, State, WindowEvent,
};
use crate::{security, native_prefs::{self, NativePrefs}, native_network};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
const GATEWAY_PORT: u16 = 15239;
const OFFICIAL_PORT: u16 = 15240;
const STABLE_PORT: u16 = 25239;

// On Windows, hiding the first WebView frame during Tauri setup can leave
// subsequent Tauri show() calls ineffective until Win32 explicitly restores
// the native window. Keep the fallback scoped to the launcher's own HWND.
#[link(name = "user32")]
extern "system" {
    fn ShowWindow(hwnd: *mut std::ffi::c_void, command: i32) -> i32;
    fn SetForegroundWindow(hwnd: *mut std::ffi::c_void) -> i32;
}

pub(crate) fn state_dir() -> PathBuf {
    PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_else(|| ".".into()))
        .join("MikuchinNativeLauncher")
}

fn project_root() -> Result<PathBuf, String> {
    fn has_native_backend(root: &Path) -> bool {
        root.join("backend/gateway/supervisor.py").is_file()
            && root.join("backend/polystrata/serve/server.py").is_file()
    }
    if let Some(explicit) = std::env::var_os("MIKUCHIN_NATIVE_HOME") {
        let root = PathBuf::from(explicit);
        if has_native_backend(&root) {
            return root.canonicalize().map_err(|e| e.to_string());
        }
        return Err("MIKUCHIN_NATIVE_HOME must contain the Native Gateway and official engine".into());
    }
    // A packaged/portable launcher must use files adjacent to itself; it
    // must never silently jump back to a build-time developer source tree.
    if let Ok(executable) = std::env::current_exe() {
        for ancestor in executable.ancestors().skip(1) {
            if has_native_backend(ancestor) {
                return ancestor.canonicalize().map_err(|e| e.to_string());
            }
        }
    }
    // Only an unbundled DEBUG preview may find sources via Cargo's build
    // directory. Release installers cannot accidentally adopt dev files.
    if cfg!(debug_assertions) {
        for ancestor in Path::new(env!("CARGO_MANIFEST_DIR")).ancestors() {
            if has_native_backend(ancestor) {
                return ancestor.canonicalize().map_err(|e| e.to_string());
            }
        }
    }
    Err("Native backend not found beside launcher; configure MIKUCHIN_NATIVE_HOME".into())
}

fn runtime_root(root: &Path) -> Result<PathBuf, String> {
    if let Some(explicit) = std::env::var_os("MIKUCHIN_NATIVE_RUNTIME_HOME") {
        let runtime = PathBuf::from(explicit);
        let stable = root.parent().ok_or("Invalid Native tree")?.join("mikuchin");
        // An explicit override must never recycle the stable main runtime.
        if runtime.starts_with(stable) {
            return Err("The stable Mikuchin runtime cannot be used by Native".into());
        }
        if runtime != root && runtime.join(".venv/Scripts/python.exe").is_file() {
            return runtime.canonicalize().map_err(|e| e.to_string());
        }
        return Err("MIKUCHIN_NATIVE_RUNTIME_HOME must contain .venv/Scripts/python.exe".into());
    }
    let parent = root.parent().ok_or("Invalid native worktree path")?;
    for runtime in [parent.join("mikuchin-native-runtime"), root.join("runtime")] {
        if runtime != root && runtime.join(".venv/Scripts/python.exe").is_file() {
            return runtime.canonicalize().map_err(|e| e.to_string());
        }
    }
    Err("Native Python runtime missing; provide MIKUCHIN_NATIVE_RUNTIME_HOME".into())
}

pub(crate) fn project_root_for_network() -> Result<PathBuf, String> { project_root() }
pub(crate) fn project_runtime_root() -> Result<PathBuf, String> {
    runtime_root(&project_root()?)
}

#[derive(Clone)]
struct LaunchSpec {
    root: PathBuf,
    python: PathBuf,
    data_dir: PathBuf,
    config: Option<PathBuf>,
    idle_override: Option<u32>,
    engine: &'static str,
    gateway_port: u16,
    official_port: u16,
    key: String,
}

fn validate_spec(spec: &LaunchSpec) -> Result<(), String> {
    if spec.gateway_port == STABLE_PORT || spec.official_port == STABLE_PORT
        || spec.gateway_port == spec.official_port
        || spec.gateway_port < 1024 || spec.official_port < 1024 {
        return Err("Invalid native ports (old-mixed port 25239 is reserved)".into());
    }
    if !spec.root.join("backend/gateway/supervisor.py").is_file() {
        return Err("Native supervisor is missing".into());
    }
    if !spec.python.is_file() {
        return Err("Native Python runtime is missing".into());
    }
    if spec.engine == "strata" && !spec.config.as_ref().is_some_and(|p| p.is_file()) {
        return Err("Official model JSON is missing; no fallback to mock".into());
    }
    if spec.key.len() < 12 {
        return Err("Gateway key is too short".into());
    }
    if spec.data_dir.starts_with(spec.root.parent().unwrap_or(&spec.root).join("mikuchin"))
       && !spec.data_dir.starts_with(spec.root.parent().unwrap_or(&spec.root).join("mikuchin-native")) {
        return Err("Stable data directory cannot be used by Native".into());
    }
    Ok(())
}

fn normal_spec() -> Result<LaunchSpec, String> {
    let root = project_root()?;
    let runtime = runtime_root(&root)?;
    let prefs = native_prefs::read()?;
    if !native_prefs::valid_config_name(&prefs.model_config) {
        return Err("非法 Native 模型配置文件名".into());
    }
    let spec = LaunchSpec {
        python: runtime.join(".venv/Scripts/python.exe"),
        data_dir: runtime.join("launcher-user-data"),
        config: Some(runtime.join("config").join(&prefs.model_config)),
        idle_override: Some(prefs.idle_unload_s),
        root,
        engine: "strata",
        gateway_port: GATEWAY_PORT,
        official_port: OFFICIAL_PORT,
        key: security::ensure_api_key()?,
    };
    validate_spec(&spec)?;
    Ok(spec)
}

// Never edit an imported official JSON in place. Only the isolated generated
// copy receives the user-selected idle unload policy on the next model load.
fn effective_config(spec: &LaunchSpec) -> Result<Option<PathBuf>, String> {
    let Some(source) = &spec.config else { return Ok(None); };
    let Some(timeout) = spec.idle_override else { return Ok(Some(source.clone())); };
    if timeout > 86400 { return Err("自动卸载时间超出允许范围".into()); }
    let bytes = fs::read(source).map_err(|e| format!("无法读取 Native 模型配置: {e}"))?;
    if bytes.len() > 256 * 1024 { return Err("模型配置文件过大".into()); }
    let json_bytes = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(&bytes);
    let mut value: Value = serde_json::from_slice(json_bytes)
        .map_err(|e| format!("模型配置不是有效 JSON: {e}"))?;
    if !value.is_object() || !value["args"].is_array() || !value["exe"].is_string() {
        return Err("模型配置缺少官方引擎的 exe/args 字段".into());
    }
    value["idle_unload_s"] = json!(timeout);
    let dest = spec.data_dir.join("active-model-config.json");
    fs::create_dir_all(&spec.data_dir).map_err(|e| e.to_string())?;
    let temp = dest.with_extension("json.tmp");
    fs::write(&temp, serde_json::to_vec_pretty(&value).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    native_prefs::replace_file(&temp, &dest)?;
    Ok(Some(dest))
}

fn port_open(port: u16) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(150)).is_ok()
}

fn spawn_supervisor(spec: &LaunchSpec, log_path: &Path, lan_access: bool) -> Result<Child, String> {
    validate_spec(spec)?;
    if port_open(spec.gateway_port) || port_open(spec.official_port) {
        return Err(format!(
            "Native port {} or {} is in use. Refusing to adopt another process.",
            spec.gateway_port, spec.official_port
        ));
    }
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    fs::create_dir_all(&spec.data_dir).map_err(|e| e.to_string())?;
    let stdout = OpenOptions::new().create(true).append(true).open(log_path)
        .map_err(|e| e.to_string())?;
    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;
    let mut command = Command::new(&spec.python);
    command.args(["-u", "-B", "-m", "backend.gateway.supervisor"])
        .args(["--engine", spec.engine, "--data-dir"])
        .arg(&spec.data_dir)
        .args(["--gateway-port", &spec.gateway_port.to_string()])
        .args(["--upstream-port", &spec.official_port.to_string()])
        .arg("--control-stdin");
    let effective = effective_config(spec)?;
    if let Some(config) = &effective {
        command.arg("--config").arg(config);
    }
    if lan_access {
        command.arg("--lan-access");
    }
    command.current_dir(&spec.root)
        .env("MIKUCHIN_GATEWAY_API_KEY", &spec.key)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
        .spawn()
        .map_err(|e| format!("Native supervisor spawn failed: {e}"))
}

fn request_stop(child: &mut Child) -> Result<(), String> {
    if child.try_wait().map_err(|e| e.to_string())?.is_some() {
        return Ok(());
    }
    let pipe = child.stdin.as_mut().ok_or("Supervisor control pipe missing")?;
    pipe.write_all(b"STOP\n").map_err(|e| e.to_string())?;
    pipe.flush().map_err(|e| e.to_string())
}

// Native raw TCP HTTP avoids forwarding the private key through proxy variables.
fn local_http(port: u16, path: &str, key: Option<&str>) -> Result<(u16, Vec<u8>), String> {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(750))
        .map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_millis(1500))).map_err(|e| e.to_string())?;
    stream.set_write_timeout(Some(Duration::from_millis(1000))).map_err(|e| e.to_string())?;
    let auth = key.map(|s| format!("Authorization: Bearer {s}\r\n")).unwrap_or_default();
    stream.write_all(format!(
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{auth}Connection: close\r\n\r\n"
    ).as_bytes()).map_err(|e| e.to_string())?;
    let mut raw = Vec::new();
    stream.take(128 * 1024).read_to_end(&mut raw).map_err(|e| e.to_string())?;
    let split = raw.windows(4).position(|x| x == b"\r\n\r\n")
        .ok_or("Incomplete HTTP headers")?;
    let first = String::from_utf8_lossy(&raw[..split]);
    let code = first.split_whitespace().nth(1).ok_or("Missing HTTP status")?
        .parse::<u16>().map_err(|e| e.to_string())?;
    Ok((code, raw[split + 4..].to_vec()))
}

fn local_json_post(port: u16, path: &str, key: &str, value: &Value)
    -> Result<(u16, Vec<u8>), String> {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(850))
        .map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_millis(2000))).map_err(|e| e.to_string())?;
    let data = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    let head = format!(
        "POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {key}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        data.len());
    stream.write_all(head.as_bytes()).map_err(|e| e.to_string())?;
    stream.write_all(&data).map_err(|e| e.to_string())?;
    let mut raw = Vec::new();
    stream.take(64 * 1024).read_to_end(&mut raw).map_err(|e| e.to_string())?;
    let split = raw.windows(4).position(|p| p == b"\r\n\r\n")
        .ok_or("Incomplete local API headers")?;
    let code = String::from_utf8_lossy(&raw[..split]).split_whitespace()
        .nth(1).ok_or("Missing HTTP status")?.parse::<u16>()
        .map_err(|e| e.to_string())?;
    Ok((code, raw[split+4..].to_vec()))
}

#[derive(Serialize, serde::Deserialize)]
struct NativeLanguagePref {
    language: String,
    pending: bool,
}
fn language_file() -> PathBuf { state_dir().join("ui-language.json") }
fn is_language(lang: &str) -> bool { matches!(lang, "zh-CN" | "en-US" | "ja-JP") }
fn stored_language() -> Option<NativeLanguagePref> {
    serde_json::from_slice(&fs::read(language_file()).ok()?).ok()
}
fn persist_language(language: &str, pending: bool) -> Result<(), String> {
    fs::create_dir_all(state_dir()).map_err(|e| e.to_string())?;
    let data = serde_json::to_vec(&NativeLanguagePref {
        language: language.to_owned(), pending,
    }).map_err(|e| e.to_string())?;
    let path = language_file();
    let temp = path.with_extension("json.tmp");
    fs::write(&temp, data).map_err(|e| e.to_string())?;
    native_prefs::replace_file(&temp, &path)
}
fn push_language(language: &str) -> Result<(), String> {
    let spec = normal_spec()?;
    let (status, _) = local_json_post(spec.gateway_port,
        "/v1/mikuchin/ui-language", &spec.key, &json!({"language":language}))?;
    if status != 200 { return Err(format!("Native language rejected: HTTP {status}")); }
    Ok(())
}
fn sync_pending_language() {
    if let Some(pref) = stored_language() {
        if pref.pending && is_language(&pref.language) && push_language(&pref.language).is_ok() {
            let _ = persist_language(&pref.language, false);
        }
    }
}
#[tauri::command]
fn get_native_language() -> Result<String, String> {
    if let Some(pref) = stored_language() {
        if pref.pending && is_language(&pref.language) { return Ok(pref.language); }
    }
    if let Ok(spec) = normal_spec() {
        if let Ok((200, body)) = local_http(spec.gateway_port,
            "/v1/mikuchin/ui-language", Some(&spec.key)) {
            if let Ok(value) = serde_json::from_slice::<Value>(&body) {
                if let Some(language) = value["language"].as_str() {
                    if is_language(language) {
                        let _ = persist_language(language, false);
                        return Ok(language.to_string());
                    }
                }
            }
        }
    }
    Ok(stored_language().filter(|v| is_language(&v.language))
        .map(|v| v.language).unwrap_or_else(|| "zh-CN".into()))
}
#[tauri::command]
fn set_native_language(language: String) -> Result<String, String> {
    if !is_language(&language) { return Err("不支持的全局语言".into()); }
    persist_language(&language, true)?;
    if push_language(&language).is_ok() { persist_language(&language, false)?; }
    Ok(language)
}

fn health(spec: &LaunchSpec) -> Option<Value> {
    let (status, body) = local_http(spec.gateway_port, "/health", Some(&spec.key)).ok()?;
    if status == 200 {serde_json::from_slice(&body).ok()} else {None}
}

fn gateway_metrics(spec: &LaunchSpec) -> Option<Value> {
    let (status, body) = local_http(spec.gateway_port, "/metrics", Some(&spec.key)).ok()?;
    if status == 200 { serde_json::from_slice(&body).ok() } else { None }
}

fn gateway_request_monitor(spec: &LaunchSpec) -> Option<Value> {
    let (status, body) = local_http(spec.gateway_port,
        "/v1/mikuchin/request-monitor", Some(&spec.key)).ok()?;
    if status == 200 { serde_json::from_slice(&body).ok() } else { None }
}

fn gpu_snapshot() -> Option<Value> {
    // Cache NVidia queries: the panel polls frequently, but system utilities
    // should not be spawned for every individual status request.
    static CACHE: OnceLock<Mutex<Option<(Instant, Value)>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(None));
    let mut guard = cache.lock().ok()?;
    if let Some((time, data)) = guard.as_ref() {
        if time.elapsed() < Duration::from_secs(5) { return Some(data.clone()); }
    }
    let output = Command::new("nvidia-smi.exe")
        .args(["--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"])
        .creation_flags(CREATE_NO_WINDOW).output().ok()?;
    if !output.status.success() { return None; }
    let line = String::from_utf8_lossy(&output.stdout);
    let mut cells = line.lines().next()?.split(',').map(str::trim);
    let used = cells.next()?.parse::<u64>().ok()?;
    let total = cells.next()?.parse::<u64>().ok()?;
    let data = json!({"gpu_mem_used":used * 1_048_576_u64, "gpu_mem_total":total * 1_048_576_u64});
    *guard = Some((Instant::now(), data.clone()));
    Some(data)
}

fn supervisor_status(spec: &LaunchSpec) -> Option<Value> {
    let path = spec.data_dir.join("supervisor-status.json");
    let bytes = fs::read(path).ok()?;
    if bytes.len() > 16 * 1024 { return None; }
    serde_json::from_slice(&bytes).ok()
}

struct Inner {
    child: Option<Child>,
    tunnel_child: Option<Child>,
    prefs: NativePrefs,
    cf_error: String,
    cf_last_retry: Option<Instant>,
    desired: bool,
    stopping: bool,
    last_error: String,
    restarts: u32,
    failures: VecDeque<Instant>,
    last_restart: Option<Instant>,
}
struct AppState { inner: Mutex<Inner> }
impl Default for AppState {
    fn default() -> Self {
        Self { inner: Mutex::new(Inner {
            child: None, tunnel_child: None,
            prefs: native_prefs::read().unwrap_or_default(),
            cf_error: String::new(), cf_last_retry: None,
            desired: false, stopping: false, last_error: String::new(),
            restarts: 0, failures: VecDeque::new(), last_restart: None,
        }) }
    }
}
fn alive(inner: &mut Inner) -> bool {
    inner.child.as_mut().is_some_and(|c| matches!(c.try_wait(), Ok(None)))
}

fn start_managed(state: &AppState) -> Result<(), String> {
    let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
    if guard.stopping { return Err("Supervisor is stopping; do not restart yet".into()); }
    if alive(&mut guard) { guard.desired = true; return Ok(()); }
    guard.desired = true;
    let result = normal_spec().and_then(|spec|
        spawn_supervisor(&spec, &state_dir().join("supervisor.log"), guard.prefs.lan_access));
    match result {
        Ok(child) => {
            guard.child = Some(child);
            guard.last_error.clear();
            if guard.prefs.cf_enabled {
                native_network::stop(&mut guard.tunnel_child);
                match native_network::spawn(&guard.prefs) {
                    Ok(tunnel) => { guard.tunnel_child = Some(tunnel); guard.cf_error.clear(); },
                    Err(err) => { guard.cf_error = err; },
                }
                guard.cf_last_retry = Some(Instant::now());
            }
            Ok(())
        }
        Err(err) => {
            guard.last_error = err.clone();
            Err(err)
        }
    }
}

fn stop_managed(state: &AppState, manual_unload: bool) -> Result<(), String> {
    let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
    if manual_unload && !guard.prefs.manual_unloaded {
        let mut prefs = guard.prefs.clone();
        prefs.manual_unloaded = true;
        native_prefs::save(&prefs)?;
        guard.prefs = prefs;
    }
    guard.desired = false; // Manual STOP never triggers watchdog restart.
    native_network::stop(&mut guard.tunnel_child);
    if !alive(&mut guard) {
        guard.child = None;
        guard.stopping = false;
        return Ok(());
    }
    guard.stopping = true;
    let result = request_stop(guard.child.as_mut().expect("checked above"));
    if let Err(e) = &result { guard.last_error = format!("STOP pipe failed: {e}"); }
    result
}

fn refresh_child(inner: &mut Inner) {
    let Some(child) = inner.child.as_mut() else { return };
    match child.try_wait() {
        Ok(None) => (),
        Ok(Some(status)) => {
            inner.child = None;
            native_network::stop(&mut inner.tunnel_child);
            if inner.stopping {
                inner.stopping = false;
            } else if inner.desired {
                inner.last_error = format!("Supervisor exited ({status}); watchdog will retry");
            }
        }
        Err(err) => { inner.last_error = format!("Supervisor status failed: {err}"); }
    }
}

#[tauri::command]
fn start_service(state: State<'_, AppState>) -> Result<(), String> {
    {
        let mut inner = state.inner.lock().map_err(|e| e.to_string())?;
        if inner.stopping {
            return Err("模型正在安全卸载，请完成后再重新加载".into());
        }
        if inner.prefs.manual_unloaded {
            let mut prefs = inner.prefs.clone();
            prefs.manual_unloaded = false;
            native_prefs::save(&prefs)?;
            inner.prefs = prefs;
        }
        inner.failures.clear();
        inner.last_restart = None;
        inner.restarts = 0;
    }
    start_managed(&state)
}

#[tauri::command]
fn stop_service(state: State<'_, AppState>) -> Result<(), String> {
    stop_managed(&state, true)
}

#[derive(Serialize)]
struct NativeStatus {
    phase: String,
    desired: bool,
    managed: bool,
    stopping: bool,
    error: String,
    restarts: u32,
    gateway_port: u16,
    official_port: u16,
    gateway_ready: bool,
    model_loaded: Option<bool>,
    api_key_present: bool,
    model: String,
    config_name: String,
    model_context: u64,
    available_configs: Vec<NativeModelConfig>,
    metrics: Option<Value>,
    request_monitor: Option<Value>,
    host_gpu: Option<Value>,
    supervisor_pid: Option<u32>,
    children: Value,
    supervisor_phase: String,
    child_restarts: Value,
    last_recovery: Value,
    gpu_busy: bool,
    gpu_phase: String,
    image_jobs_running: u64,
    image_jobs_phase: String,
    image_worker_ready: bool,
    upscaler_ready: bool,
    log_path: String,
    data_dir: String,
    settings: NativePrefs,
    cf_running: bool,
    cf_connections: Option<u32>,
    cf_error: String,
    cf_token_present: bool,
    cf_binary_ready: bool,
    lan_addresses: Vec<native_network::LanAddress>,
    lan_effective: bool,
}

#[derive(Serialize)]
struct NativeModelConfig {
    file: String,
    name: String,
    model: String,
    context: Option<u64>,
    quantization: String,
    kv_type: String,
    tokenizer: String,
    vision_projector: String,
    draft_model: String,
    vram_reserve_mib: Option<u64>,
    idle_unload_s: Option<u64>,
    conversation_cache_mib: Option<String>,
    engine: String,
    path: String,
}

fn describe_model_config(file: String, path: &Path, value: &Value) -> NativeModelConfig {
    let args = value["args"].as_array();
    let arg_value = |switch: &str| -> Option<String> {
        args?.windows(2).find_map(|pair| {
            (pair[0].as_str() == Some(switch)).then(|| pair[1].as_str())
                .flatten().map(str::to_owned)
        })
    };
    let model = value["model_name"].as_str().or_else(|| value["display_name"].as_str())
        .unwrap_or(&file).to_string();
    let context = arg_value("--max-context").or_else(|| arg_value("--ctx-size"))
        .and_then(|raw| raw.parse::<u64>().ok());
    let model_hint = format!("{} {}", model, arg_value("--model").unwrap_or_default())
        .to_ascii_uppercase();
    let quantization = ["Q4_K_M","Q5_K_M","Q6_K","Q8_0","IQ3_XXS","Q2_K","Q4_0"]
        .iter().find(|tag| model_hint.contains(*tag))
        .map(|x| (*x).to_string()).unwrap_or_default();
    NativeModelConfig {
        name: value["display_name"].as_str().unwrap_or(&file).to_string(),
        file, model, context, quantization,
        kv_type: arg_value("--kv").unwrap_or_default(),
        tokenizer: value["tokenizer"].as_str().unwrap_or_default().to_owned(),
        vision_projector: arg_value("--mmproj").or_else(|| arg_value("--vision-projector"))
            .unwrap_or_default(),
        draft_model: arg_value("--draft-model").unwrap_or_default(),
        vram_reserve_mib: arg_value("--vram-reserve-mib").and_then(|v| v.parse().ok()),
        idle_unload_s: value["idle_unload_s"].as_u64(),
        conversation_cache_mib: arg_value("--conversation-cache-mib"),
        engine: "PolyStrata v0.1.45-poly.10".into(),
        path: path.to_string_lossy().to_string(),
    }
}

fn list_native_model_configs() -> Result<Vec<NativeModelConfig>, String> {
    let folder = project_runtime_root()?.join("config");
    let mut choices = Vec::new();
    for entry in fs::read_dir(folder).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        if !entry.file_type().map_err(|e| e.to_string())?.is_file() { continue; }
        let file = entry.file_name().to_string_lossy().to_string();
        if !native_prefs::valid_config_name(&file) { continue; }
        let bytes = match fs::read(entry.path()) {
            Ok(value) if value.len() <= 256 * 1024 => value,
            _ => continue,
        };
        let json_bytes = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(&bytes);
        let Ok(value) = serde_json::from_slice::<Value>(json_bytes) else { continue; };
        if !value["exe"].is_string() || !value["args"].is_array() { continue; }
        choices.push(describe_model_config(file, &entry.path(), &value));
    }
    choices.sort_by(|a,b| a.file.cmp(&b.file));
    Ok(choices)
}

#[tauri::command]
fn register_native_model_config(path: String) -> Result<NativeModelConfig, String> {
    if path.trim().len() > 1024 { return Err("模型配置文件路径太长".into()); }
    let source = PathBuf::from(path.trim());
    if source.extension().is_none_or(|ext| ext != "json") || !source.is_file() {
        return Err("请选择本机真实存在的模型 JSON 配置文件".into());
    }
    let bytes = fs::read(&source).map_err(|e| e.to_string())?;
    if bytes.len() > 256 * 1024 { return Err("模型 JSON 文件过大".into()); }
    let json_bytes = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(&bytes);
    let value: Value = serde_json::from_slice(json_bytes)
        .map_err(|e| format!("模型配置 JSON 格式错误: {e}"))?;
    if !value["exe"].as_str().is_some_and(|x| !x.is_empty()) || !value["args"].is_array() {
        return Err("文件不是有效的官方 PolyStrata 模型配置 (缺少 exe/args)".into());
    }
    let stem = source.file_stem().unwrap_or_default().to_string_lossy();
    let clean: String = stem.chars().take(55).map(|c|
        if c.is_ascii_alphanumeric() || matches!(c, '-' | '_') { c } else { '_' }
    ).collect();
    let folder = project_runtime_root()?.join("config");
    fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    for n in 1..=100 {
        let file = format!("import-{clean}-{n}.json");
        if !native_prefs::valid_config_name(&file) { continue; }
        let dest = folder.join(&file);
        match OpenOptions::new().write(true).create_new(true).open(&dest) {
            Ok(mut handle) => {
                if let Err(error) = handle.write_all(&bytes) {
                    drop(handle);
                    let _ = fs::remove_file(&dest);
                    return Err(error.to_string());
                }
                return Ok(describe_model_config(file, &dest, &value));
            },
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.to_string()),
        }
    }
    Err("注册数量已达上限，请先整理 Native 模型配置目录".into())
}

// uv's Windows venv python.exe can be a redirector: the launcher owns the
// wrapper PID, while Python's os.getpid() in supervisor-status.json reports
// the wrapper's child PID. After the Gateway authenticates using this
// launcher's private key, its reserved ports and running managed child are
// sufficient to trust the matching supervisor status. Do not trust stale
// status files when health has not authenticated.
fn trusted_supervisor_status(raw: &Value, parent_pid: Option<u32>,
                             managed: bool, authenticated_health: bool) -> bool {
    let pid_matches = raw["supervisor_pid"].as_u64() == parent_pid.map(u64::from);
    let ports_match = raw["gateway_port"].as_u64() == Some(u64::from(GATEWAY_PORT))
        && raw["official_port"].as_u64() == Some(u64::from(OFFICIAL_PORT));
    managed && ports_match && (pid_matches || authenticated_health)
}

fn runtime_phase(stopping: bool, managed: bool, gateway_ready: bool,
                 model_loaded: Option<bool>, live_state: Option<&str>, gpu_busy: bool,
                 desired: bool, has_error: bool) -> &'static str {
    if stopping { "stopping" }
    else if managed && gateway_ready && live_state == Some("reading") { "reading" }
    else if managed && gateway_ready && live_state == Some("generating") { "generating" }
    else if managed && gateway_ready && model_loaded == Some(false) && !gpu_busy {
        // Gateway continues serving API requests; only the LLM weights left
        // VRAM. An active image job may also unload LLM temporarily and must
        // not be labeled as an idle timeout.
        "unloaded"
    } else if managed && gateway_ready { "running" }
    else if managed { "starting" }
    else if desired && has_error { "error" }
    else if desired { "starting" }
    else if has_error { "error" }
    else { "stopped" }
}

#[tauri::command]
fn get_status(state: State<'_, AppState>) -> Result<NativeStatus, String> {
    let (managed, desired, stopping, error, restarts, pid, prefs, cf_running, cf_error) = {
        let mut inner = state.inner.lock().map_err(|e| e.to_string())?;
        refresh_child(&mut inner);
        (alive(&mut inner), inner.desired, inner.stopping,
         inner.last_error.clone(), inner.restarts, inner.child.as_ref().map(Child::id),
         inner.prefs.clone(), inner.tunnel_child.as_mut().is_some_and(|c| c.try_wait().ok().flatten().is_none()),
         inner.cf_error.clone())
    };
    let spec = normal_spec();
    let raw = spec.as_ref().ok().and_then(supervisor_status);
    let health_value = if managed { spec.as_ref().ok().and_then(health) } else {None};
    let gateway_ready = health_value.is_some();
    if gateway_ready { sync_pending_language(); }
    let model_loaded = health_value.as_ref()
        .and_then(|h| h["official_model_loaded"].as_bool());
    let metrics = if gateway_ready { spec.as_ref().ok().and_then(gateway_metrics) } else { None };
    let request_monitor = if gateway_ready {
        spec.as_ref().ok().and_then(gateway_request_monitor)
    } else { None };
    let host_gpu = gpu_snapshot();
    let model = health_value.as_ref().and_then(|h| h["model"].as_str())
        .unwrap_or("—").to_string();
    let supervisor_phase = if raw.as_ref().is_some_and(|v|
        trusted_supervisor_status(v, pid, managed, gateway_ready)) {
        raw.as_ref().and_then(|v| v["phase"].as_str()).unwrap_or("unknown")
    } else { "unknown" }.to_string();
    let children = if supervisor_phase == "unknown" { json!({}) }
        else { raw.as_ref().map(|v| v["children"].clone()).unwrap_or(json!({})) };
    let child_restarts = if supervisor_phase == "unknown" { json!({}) }
        else { raw.as_ref().map(|v| v["child_restarts"].clone()).unwrap_or(json!({})) };
    let last_recovery = if supervisor_phase == "unknown" { json!(null) }
        else { raw.as_ref().map(|v| v["last_recovery"].clone()).unwrap_or(json!(null)) };
    let gpu_busy = health_value.as_ref().and_then(|v| v["native_gpu"]["busy"].as_bool())
        .unwrap_or(false);
    let gpu_phase = health_value.as_ref().and_then(|v| v["native_gpu"]["phase"].as_str())
        .unwrap_or("unknown").to_string();
    let image_jobs_running = health_value.as_ref().and_then(|v| v["native_image_jobs"]["running"].as_u64())
        .unwrap_or(0);
    let image_jobs_phase = health_value.as_ref().and_then(|v| v["native_image_jobs"]["phase"].as_str())
        .unwrap_or("").to_string();
    let image_worker_ready = health_value.as_ref().and_then(|v| v["image_worker_ready"].as_bool())
        .unwrap_or(false);
    let upscaler_ready = health_value.as_ref().and_then(|v| v["native_upscaler_ready"].as_bool())
        .unwrap_or(false);
    let error = if error.is_empty() { spec.as_ref().err().cloned().unwrap_or_default() } else { error };
    let live_state = metrics.as_ref().and_then(|v| v["live"]["state"].as_str());
    let phase = if prefs.manual_unloaded && stopping { "unloading" }
        else if prefs.manual_unloaded && !managed && !desired { "manual_unloaded" }
        else { runtime_phase(stopping, managed, gateway_ready,
                             model_loaded, live_state, gpu_busy, desired, !error.is_empty()) };
    let lan_effective = gateway_ready && supervisor_phase != "unknown" && raw.as_ref()
        .and_then(|r| r["lan_access"].as_bool()).unwrap_or(false);
    Ok(NativeStatus {
        phase: phase.into(), desired, managed, stopping, error, restarts,
        gateway_port: GATEWAY_PORT, official_port: OFFICIAL_PORT,
        gateway_ready, model_loaded, api_key_present: security::read("api-key")?.is_some(),
        model, model_context: health_value.as_ref()
            .and_then(|h| h["max_context"].as_u64()).unwrap_or(0),
        config_name: spec.as_ref().ok().and_then(|s| s.config.as_ref())
            .and_then(|p| p.file_name()).map(|p| p.to_string_lossy().into_owned())
            .unwrap_or_else(|| "未配置".into()),
        available_configs: list_native_model_configs().unwrap_or_default(),
        metrics, request_monitor, host_gpu, supervisor_pid: pid, children, supervisor_phase,
        child_restarts, last_recovery, gpu_busy, gpu_phase,
        image_jobs_running, image_jobs_phase, image_worker_ready, upscaler_ready,
        log_path: state_dir().join("supervisor.log").to_string_lossy().to_string(),
        data_dir: spec.map(|s| s.data_dir.to_string_lossy().to_string()).unwrap_or_default(),
        lan_effective,
        cf_token_present: security::read("native-cf-tunnel-token")?.is_some(),
        cf_binary_ready: native_network::binary_path().is_ok_and(|p| p.is_file()),
        lan_addresses: if prefs.lan_access { native_network::addresses() } else { Vec::new() },
        cf_connections: if cf_running { native_network::connections() } else { None },
        cf_running, cf_error, settings: prefs,
    })
}

#[tauri::command]
fn save_native_preferences(
    state: State<'_, AppState>, incoming: NativePrefs,
) -> Result<NativePrefs, String> {
    if !native_prefs::valid_config_name(&incoming.model_config)
        || !project_runtime_root()?.join("config").join(&incoming.model_config).is_file() {
        return Err("请选择已注册的 Native 模型 JSON 配置".into());
    }
    if incoming.idle_unload_s > 86400 {
        return Err("自动卸载时间必须在 0–86400 秒之间".into());
    }
    if !incoming.cf_hostname.is_empty() && !native_prefs::validate_hostname(&incoming.cf_hostname) {
        return Err("Cloudflare 域名格式无效".into());
    }
    let mut inner = state.inner.lock().map_err(|e| e.to_string())?;
    if inner.stopping {
        return Err("服务正在安全停止，请完成后再修改".into());
    }
    let running = alive(&mut inner);
    // LAN listener changes are saved as desired state and applied on the
    // next graceful service start. NEVER interrupt a GPU/KV/paid image job.
    if incoming.cf_enabled {
        if !native_prefs::validate_hostname(&incoming.cf_hostname) {
            return Err("启用 Tunnel 前需填写独立公网域名".into());
        }
        if security::read("native-cf-tunnel-token")?.is_none() {
            return Err("请先保存 Native 专用 Tunnel Token（不可复用正式版 Token）".into());
        }
        if !native_network::binary_path()?.is_file() {
            return Err("请先安装 Native cloudflared".into());
        }
    }
    native_prefs::save(&incoming)?;
    let changes_tunnel = incoming.cf_enabled != inner.prefs.cf_enabled
        || incoming.cf_hostname != inner.prefs.cf_hostname;
    inner.prefs = incoming.clone();
    if changes_tunnel {
        native_network::stop(&mut inner.tunnel_child);
        inner.cf_error.clear();
        if incoming.cf_enabled && running {
            match native_network::spawn(&incoming) {
                Ok(child) => inner.tunnel_child = Some(child),
                Err(e) => inner.cf_error = e,
            }
            inner.cf_last_retry = Some(Instant::now());
        }
    }
    Ok(incoming)
}

#[tauri::command]
fn save_native_tunnel_token(state: State<'_, AppState>, token: String) -> Result<(), String> {
    let token = token.trim();
    if token.len() < 80 || token.len() > 8000 ||
        !token.bytes().all(|b| b.is_ascii_alphanumeric() || b"_-.".contains(&b)) {
        return Err("Tunnel Token 格式无效，请粘贴 Cloudflare 提供的完整 Token".into());
    }
    security::store("native-cf-tunnel-token", token)?;
    let mut inner = state.inner.lock().map_err(|e| e.to_string())?;
    if inner.prefs.cf_enabled {
        native_network::stop(&mut inner.tunnel_child);
        inner.cf_error.clear();
        if alive(&mut inner) {
            match native_network::spawn(&inner.prefs) {
                Ok(child) => inner.tunnel_child = Some(child),
                Err(e) => inner.cf_error = e,
            }
            inner.cf_last_retry = Some(Instant::now());
        }
    }
    Ok(())
}

#[tauri::command]
fn install_native_tunnel() -> Result<String, String> {
    native_network::provision_binary()
}

#[tauri::command]
fn restart_native_tunnel(state: State<'_, AppState>) -> Result<(), String> {
    let mut inner = state.inner.lock().map_err(|e| e.to_string())?;
    if !inner.prefs.cf_enabled || !alive(&mut inner) {
        return Err("需要先启用 Tunnel 和 Gateway".into());
    }
    native_network::stop(&mut inner.tunnel_child);
    let child = native_network::spawn(&inner.prefs)?;
    inner.tunnel_child = Some(child);
    inner.cf_error.clear();
    inner.cf_last_retry = Some(Instant::now());
    Ok(())
}

#[tauri::command]
fn test_native_tunnel(state: State<'_, AppState>) -> Result<Value, String> {
    let hostname = state.inner.lock().map_err(|e| e.to_string())?.prefs.cf_hostname.clone();
    let (http_status, latency_ms, valid) = native_network::probe(&hostname)?;
    Ok(json!({"http_status":http_status, "latency_ms":latency_ms, "connected":valid}))
}

#[tauri::command]
fn reveal_api_key() -> Result<String, String> {
    security::ensure_api_key()
}

fn can_rotate_key(managed: bool, desired: bool, stopping: bool) -> bool {
    !managed && !desired && !stopping
}

#[tauri::command]
fn rotate_native_api_key(state: State<'_, AppState>) -> Result<(), String> {
    let mut inner = state.inner.lock().map_err(|e| e.to_string())?;
    refresh_child(&mut inner);
    if !can_rotate_key(alive(&mut inner), inner.desired, inner.stopping) {
        return Err("请先点击「卸载模型」，待 Native 服务完全停止后才能轮换 API Key".into());
    }
    // The new DPAPI key is used on the next explicit Native service start.
    // Never alter the running Gateway's key or any production credentials.
    let key = security::random_api_key()?;
    security::store("api-key", &key)
}

#[tauri::command]
fn open_chat() -> Result<(), String> {
    Command::new("rundll32.exe")
        .args(["url.dll,FileProtocolHandler", &format!("http://127.0.0.1:{GATEWAY_PORT}/")])
        .creation_flags(CREATE_NO_WINDOW)
        .spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn get_log() -> String {
    let text = fs::read_to_string(state_dir().join("supervisor.log")).unwrap_or_default();
    text.chars().rev().take(18000).collect::<String>().chars().rev().collect()
}

fn request_show(app: &tauri::AppHandle) {
    let handle = app.clone();
    if let Err(err) = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window("main") {
            let _ = window.unminimize();
            if let Err(err) = window.show() {
                eprintln!("Mikuchin launcher: show failed: {err}");
            }
            // Tauri's show() alone may not restore a startup-hidden WebView
            // on Windows 10. Restore its *own* HWND, never another window.
            if let Ok(hwnd) = window.hwnd() {
                unsafe {
                    ShowWindow(hwnd.0, 9); // SW_RESTORE: show hidden/minimized
                    SetForegroundWindow(hwnd.0);
                }
            }
            if let Err(err) = window.set_focus() {
                eprintln!("Mikuchin launcher: focus failed: {err}");
            }
        }
    }) {
        eprintln!("Mikuchin launcher: dispatch show failed: {err}");
    }
}

fn request_quit(app: tauri::AppHandle) {
    thread::spawn(move || {
        let state = app.state::<AppState>();
        if let Err(err) = stop_managed(&state, false) { let _ = app.emit("manager-error", err); }
        // Wait for the private STOP protocol. Never taskkill a paid Image Worker.
        loop {
            thread::sleep(Duration::from_millis(500));
            let ended = {
                let Ok(mut guard) = state.inner.lock() else { return };
                refresh_child(&mut guard);
                !alive(&mut guard)
            };
            if ended {
                // Python supervisor remains alive while any paid Worker is
                // finishing a task, so process exit means all children closed.
                // Do not rely on potentially stale status files for quit.
                app.exit(0);
                return;
            }
        }
    });
}

fn watchdog(app: tauri::AppHandle) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(2));
        let state = app.state::<AppState>();
        let retry = {
            let Ok(mut inner) = state.inner.lock() else { return };
            refresh_child(&mut inner);
            if inner.prefs.cf_enabled && inner.prefs.watchdog && alive(&mut inner) {
                let cf_alive = inner.tunnel_child.as_mut()
                    .is_some_and(|c| c.try_wait().ok().flatten().is_none());
                if !cf_alive && inner.cf_last_retry.is_none_or(|t| t.elapsed() > Duration::from_secs(15)) {
                    native_network::stop(&mut inner.tunnel_child);
                    let prefs = inner.prefs.clone();
                    match native_network::spawn(&prefs) {
                        Ok(child) => { inner.tunnel_child = Some(child); inner.cf_error.clear(); },
                        Err(err) => inner.cf_error = err,
                    }
                    inner.cf_last_retry = Some(Instant::now());
                }
            }
            if inner.stopping || !inner.desired || !inner.prefs.watchdog || alive(&mut inner) { false }
            else {
                let now = Instant::now();
                while inner.failures.front().is_some_and(|t| now.duration_since(*t) > Duration::from_secs(60)) {
                    inner.failures.pop_front();
                }
                let ready = inner.last_restart.is_none_or(|t| t.elapsed() >= Duration::from_secs(3));
                if ready && inner.failures.len() < 3 {
                    inner.failures.push_back(now);
                    inner.restarts += 1;
                    inner.last_restart = Some(now);
                    true
                } else {
                    if inner.failures.len() >= 3 {
                        inner.desired = false;
                        inner.last_error = "Supervisor restart limit reached (3 in 60s)".into();
                    }
                    false
                }
            }
        };
        if retry {
            if let Err(err) = start_managed(&state) {
                let _ = app.emit("manager-error", err);
            }
        }
    });
}

fn should_auto_start(prefs: &NativePrefs, ui_smoke: bool) -> bool {
    ui_smoke || (prefs.auto_start_service && !prefs.manual_unloaded)
}

fn reserve_test_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    Ok(port)
}

/// Headless smoke: launcher binary -> supervisor -> official mock + worker + Gateway.
/// Does not modify production settings, DPAPI key, models or stable ports.
pub fn self_test() -> i32 {
    let full = std::env::args().any(|arg| arg == "--self-test-full");
    let result = (|| -> Result<Value, String> {
        let root = project_root()?;
        let runtime = runtime_root(&root)?;
        let gateway_port = reserve_test_port()?;
        let mut official_port = reserve_test_port()?;
        while official_port == gateway_port || official_port == STABLE_PORT {
            official_port = reserve_test_port()?;
        }
        let data_dir = std::env::temp_dir().join(format!("mikuchin-native-tauri-smoke-{}", std::process::id()));
        let spec = LaunchSpec {
            root,
            python: runtime.join(".venv/Scripts/python.exe"),
            data_dir: data_dir.clone(),
            config: if full { Some(runtime.join("config/official-sm86-model-test.json")) } else { None },
            idle_override: None,
            engine: if full { "strata" } else { "mock" },
            gateway_port,
            official_port,
            key: security::random_api_key()?,
        };
        let log_path = data_dir.join("launcher-supervisor.log");
        let mut child = spawn_supervisor(&spec, &log_path, false)?;
        let outcome = (|| -> Result<Value, String> {
            let deadline = Instant::now() + Duration::from_secs(if full { 130 } else { 35 });
            while Instant::now() < deadline {
                if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                    return Err(format!("Supervisor quit early: {status}"));
                }
                if health(&spec).is_some() { break; }
                thread::sleep(Duration::from_millis(250));
            }
            if health(&spec).is_none() { return Err("Gateway health timeout".into()); }
            // /health may turn healthy a fraction before the supervisor's
            // atomic status-file transition from starting -> running.
            let status_deadline = Instant::now() + Duration::from_secs(8);
            let status = loop {
                let value = supervisor_status(&spec).ok_or("Supervisor status missing")?;
                if value["phase"] == "running" { break value; }
                if Instant::now() >= status_deadline {
                    return Err(format!("Supervisor status never reached running: {}", value["phase"]));
                }
                thread::sleep(Duration::from_millis(100));
            };
            let (index, _) = local_http(spec.gateway_port, "/", None)?;
            let (unauthorized, _) = local_http(spec.gateway_port, "/health", None)?;
            if index != 200 || unauthorized != 401 {
                return Err(format!("Web/auth mismatch: index={index}, auth={unauthorized}"));
            }
            let model = health(&spec).and_then(|h| h["model"].as_str().map(str::to_string));
            Ok(json!({"gateway_ready":true, "static_home":index,
                "unauthorized_health":unauthorized,"engine":spec.engine,
                "model":model, "children":status["children"]}))
        })();
        let stop_result = request_stop(&mut child);
        let deadline = Instant::now() + Duration::from_secs(if full { 50 } else { 20 });
        let mut stopped = false;
        while Instant::now() < deadline {
            if child.try_wait().map_err(|e| e.to_string())?.is_some() {
                stopped = true; break;
            }
            thread::sleep(Duration::from_millis(250));
        }
        if !stopped {
            return Err("Supervisor did not stop; intentionally NOT terminating children".into());
        }
        stop_result?;
        if port_open(gateway_port) || port_open(official_port) {
            return Err("Native development ports remain in use after STOP".into());
        }
        let final_phase = supervisor_status(&spec)
            .and_then(|s| s["phase"].as_str().map(str::to_string)).unwrap_or_default();
        if final_phase != "stopped" { return Err(format!("Unexpected final phase: {final_phase}")); }
        let _ = fs::remove_dir_all(data_dir);
        outcome
    })();
    let output = match result {
        Ok(mut value) => {
            value["passed"] = json!(true);
            value
        }
        Err(err) => json!({"passed":false, "error":err}),
    };
    println!("{}", serde_json::to_string_pretty(&output).unwrap_or_default());
    if output["passed"] == true { 0 } else { 1 }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| request_show(app)))
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            start_service, stop_service, get_status, reveal_api_key, open_chat, get_log,
            register_native_model_config, rotate_native_api_key,
            save_native_preferences, save_native_tunnel_token, install_native_tunnel,
            restart_native_tunnel, test_native_tunnel,
            get_native_language, set_native_language
        ])
        .setup(|app| {
            let open = MenuItem::with_id(app, "open", "打开启动器", true, None::<&str>)?;
            let chat = MenuItem::with_id(app, "chat", "打开 Chat", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "安全退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &chat, &quit])?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().expect("Missing app icon").clone())
                .tooltip("Mikuchin Native Dev")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| {
                    match event.id().as_ref() {
                        "open" => request_show(app),
                        "chat" => { let _ = open_chat(); },
                        "quit" => request_quit(app.clone()),
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if matches!(event, TrayIconEvent::Click { button: MouseButton::Left, .. }
                        | TrayIconEvent::DoubleClick { button: MouseButton::Left, .. }) {
                        request_show(tray.app_handle());
                    }
                })
                .build(app)?;
            let ui_smoke = std::env::args().any(|arg| arg == "--self-test-ui");
            if ui_smoke || std::env::args().any(|arg| arg == "--background") {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
            let handle = app.handle().clone();
            watchdog(handle.clone());
            if should_auto_start(&native_prefs::read().unwrap_or_default(), ui_smoke) {
                thread::spawn(move || {
                    if let Err(err) = start_managed(&handle.state::<AppState>()) {
                        let _ = handle.emit("manager-error", err);
                    }
                });
            }
            if ui_smoke {
                let probe_app = app.handle().clone();
                thread::spawn(move || {
                    let deadline = Instant::now() + Duration::from_secs(110);
                    let mut success = false;
                    while Instant::now() < deadline {
                        if normal_spec().as_ref().ok().and_then(health).is_some() {
                            success = true;
                            break;
                        }
                        thread::sleep(Duration::from_millis(250));
                    }
                    let _ = fs::create_dir_all(state_dir());
                    let _ = fs::write(state_dir().join("ui-smoke-result.json"),
                        serde_json::to_vec_pretty(&json!({
                            "passed":success, "gateway_port":GATEWAY_PORT,
                            "official_port":OFFICIAL_PORT,
                            "mode":"tauri-event-loop-and-tray"
                        })).unwrap_or_default());
                    request_quit(probe_app);
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("Mikuchin Native startup failed");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manual_unload_survives_app_relaunch_and_overrides_automatic_start() {
        let mut prefs = NativePrefs::default();
        assert!(should_auto_start(&prefs, false));
        prefs.manual_unloaded = true;
        assert!(!should_auto_start(&prefs, false));
        assert!(should_auto_start(&prefs, true)); // isolated UI-smoke override
        prefs.auto_start_service = false;
        assert!(!should_auto_start(&prefs, false));
        prefs.manual_unloaded = false;
        assert!(!should_auto_start(&prefs, false));
        prefs.auto_start_service = true;
        assert!(should_auto_start(&prefs, false));
    }

    #[test]
    fn phase_reflects_idle_unload_not_gateway_shutdown_or_image_handoff() {
        assert_eq!(runtime_phase(false, true, true, Some(false), Some("unloaded"), false, true, false),
                   "unloaded");
        assert_eq!(runtime_phase(false, true, true, Some(true), Some("idle"), false, true, false),
                   "running");
        assert_eq!(runtime_phase(false, true, true, None, None, false, true, false),
                   "running");
        assert_eq!(runtime_phase(false, true, true, Some(false), Some("unloaded"), true, true, false),
                   "running");
        assert_eq!(runtime_phase(false, true, true, Some(false), Some("reading"), false, true, false),
                   "reading");
        assert_eq!(runtime_phase(false, true, true, Some(true), Some("generating"), false, true, false),
                   "generating");
        assert_eq!(runtime_phase(true, true, true, Some(false), Some("unloaded"), false, false, false),
                   "stopping");
        assert_eq!(runtime_phase(false, false, false, Some(false), Some("unloaded"), false, false, false),
                   "stopped");
    }

    #[test]
    fn uv_python_redirector_status_requires_live_authenticated_gateway() {
        let actual_supervisor = json!({
            "supervisor_pid": 3333,
            "gateway_port": GATEWAY_PORT,
            "official_port": OFFICIAL_PORT,
            "phase": "running"
        });
        assert!(trusted_supervisor_status(&actual_supervisor, Some(3333), true, false));
        assert!(trusted_supervisor_status(&actual_supervisor, Some(2222), true, true));
        assert!(!trusted_supervisor_status(&actual_supervisor, Some(2222), true, false));
        assert!(!trusted_supervisor_status(&actual_supervisor, Some(2222), false, true));
        let unrelated = json!({"supervisor_pid": 3333,
            "gateway_port": 25239, "official_port": OFFICIAL_PORT});
        assert!(!trusted_supervisor_status(&unrelated, Some(3333), true, true));
    }

    #[test]
    fn reserved_stable_port_never_allowed() {
        let mut spec = LaunchSpec {
            root: PathBuf::from("does-not-exist"), python: PathBuf::new(),
            data_dir: PathBuf::from("native"), config: None, idle_override: None,
            engine: "mock", gateway_port: STABLE_PORT, official_port: OFFICIAL_PORT,
            key: "a".repeat(32),
        };
        assert!(validate_spec(&spec).unwrap_err().contains("25239"));
        spec.gateway_port = GATEWAY_PORT;
        spec.official_port = STABLE_PORT;
        assert!(validate_spec(&spec).unwrap_err().contains("25239"));
    }

    #[test]
    fn isolated_model_config_override_preserves_registered_source() {
        let root = std::env::temp_dir().join(format!("mikuchin-model-prefs-test-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let source = root.join("registered.json");
        fs::write(&source, b"\xef\xbb\xbf{\"exe\":\"mock.exe\",\"args\":[\"--model\",\"mock.gguf\"],\"idle_unload_s\":900}").unwrap();
        let mut spec = LaunchSpec {
            root: root.clone(), python: PathBuf::new(),
            data_dir: root.join("user-data"), config: Some(source.clone()),
            idle_override: Some(300), engine: "strata",
            gateway_port: GATEWAY_PORT, official_port: OFFICIAL_PORT,
            key: "x".repeat(32),
        };
        let dest = effective_config(&spec).unwrap().unwrap();
        let obj: Value = serde_json::from_slice(&fs::read(&dest).unwrap()).unwrap();
        assert_eq!(obj["idle_unload_s"], 300);
        assert_eq!(obj["args"][1], "mock.gguf");
        let original_bytes = fs::read(&source).unwrap();
        assert!(original_bytes.starts_with(&[0xEF,0xBB,0xBF]));
        let original: Value = serde_json::from_slice(&original_bytes[3..]).unwrap();
        assert_eq!(original["idle_unload_s"], 900);
        spec.idle_override = Some(0);
        let next = effective_config(&spec).unwrap().unwrap();
        let value: Value = serde_json::from_slice(&fs::read(next).unwrap()).unwrap();
        assert_eq!(value["idle_unload_s"], 0);
        spec.idle_override = Some(86401);
        assert!(effective_config(&spec).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn api_key_rotation_requires_a_stopped_unmanaged_native_service() {
        assert!(can_rotate_key(false,false,false));
        assert!(!can_rotate_key(true,false,false));
        assert!(!can_rotate_key(false,true,false));
        assert!(!can_rotate_key(false,false,true));
    }

    #[test]
    fn native_secret_storage_is_not_stable() {
        assert!(state_dir().ends_with("MikuchinNativeLauncher"));
    }

    #[test]
    fn stop_without_owned_child_is_idempotent() {
        let state = AppState::default();
        stop_managed(&state, false).unwrap();
        stop_managed(&state, false).unwrap();
    }
}
