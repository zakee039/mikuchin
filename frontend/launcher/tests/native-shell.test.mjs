import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const mainStyle = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const nativeStyle = readFileSync(new URL("../src/native.css", import.meta.url), "utf8");
const rust = readFileSync(new URL("../src-tauri/src/native.rs", import.meta.url), "utf8");
const windows = readFileSync(new URL("../src-tauri/src/main.rs", import.meta.url), "utf8");
const tauri = JSON.parse(readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));

test("Native preview matches main launcher's compact window, brand and navigation", () => {
  const view = tauri.app.windows[0];
  assert.equal(view.width, 440);
  assert.equal(view.height, 650);
  assert.equal(view.minWidth, 420);
  assert.equal(view.minHeight, 650);
  assert.match(mainStyle, /\.head\{height:76px/);
  assert.match(mainStyle, /\.tabs\{/);
  assert.match(mainStyle, /\.model-card\{/);
  for (const tab of ['overview: "总览"', 'api: "API"', 'settings: "设置"', 'native: "原生状态"']) {
    assert.ok(source.includes(tab), tab);
  }
  assert.doesNotMatch(source, /workflows:|workflowPage\(/);
});

test("150% DPI uses WebView's native scaling, never shrinking the whole document", () => {
  assert.doesNotMatch(source, /document\.documentElement\.style\.zoom/);
  assert.doesNotMatch(source, /fitWindowsScale/);
  assert.doesNotMatch(nativeStyle, /zoom\s*:/);
  assert.equal(tauri.app.windows[0].width, 440);
  assert.equal(tauri.app.windows[0].height, 650);
});

test("status polling never remounts the root or erases tab and scroll state", () => {
  assert.match(source, /const savedScroll = el\.scrollTop/);
  assert.match(source, /if \(!editing && el\.innerHTML !== page\) el\.innerHTML = page/);
  assert.match(source, /el\.scrollTop = savedScroll/);
  assert.match(source, /if \(polling\) return/);
  assert.match(source, /if \(tab !== element\.dataset\.tab\)/);
  const poll = source.split("async function poll()")[1].split("mount();")[0];
  assert.doesNotMatch(poll, /root\.innerHTML/);
  assert.match(poll, /renderBody\(\)/);
});

test("standalone debug app is GUI subsystem with no console; child logs remain accessible", () => {
  assert.match(windows, /cfg_attr\(target_os = "windows", windows_subsystem = "windows"\)/);
  assert.match(rust, /CREATE_NO_WINDOW \| CREATE_NEW_PROCESS_GROUP/);
  assert.match(source, /get_log/);
  assert.match(source, /data-action="show-log"/);
});

test("Native LAN, Tunnel and startup actions map to real commands", () => {
  assert.match(source, /gateway_port/);
  assert.match(source, /host_gpu/);
  assert.match(source, /conversation_cache/);
  assert.match(source, /image_jobs_running/);
  assert.match(source, /upscaler_ready/);
  assert.match(source, /data-action="copy-key"/);
  assert.match(source, /data-action="open-chat"/);
  assert.match(source, /data-setting="lan_access"/);
  assert.match(source, /data-setting="cf_enabled"/);
  assert.match(source, /toggle\("autostart"/);
  assert.match(source, /toggle\("auto_start_service"/);
  assert.match(source, /toggle\("watchdog"/);
  assert.match(source, /Cloudflare Tunnel/);
  assert.match(source, /save_native_preferences/);
  assert.match(source, /save_native_tunnel_token/);
  assert.match(source, /install_native_tunnel/);
  assert.match(source, /test_native_tunnel/);
  assert.match(source, /restart_native_tunnel/);
  assert.doesNotMatch(source, /待接入/);
  assert.doesNotMatch(source, /<h3>服务控制<\/h3>/);
  assert.doesNotMatch(source, /安全停止会等待正在执行的图像任务/);
  assert.match(nativeStyle, /overscroll-behavior:contain/);
  assert.match(rust, /fn gpu_snapshot\(/);
  assert.match(rust, /fn gateway_metrics\(/);
  assert.match(rust, /fn save_native_preferences\(/);
});

test("LAN shows each IPv4 adapter before restart without claiming unreachable links work", () => {
  assert.match(source, /const lanEntries = settings\?\.lan_access/);
  assert.match(source, /lan-address-list/);
  assert.match(source, /lan-address-name/);
  assert.match(source, /lan-chat-inactive/);
  assert.match(source, /lanReady\s*\?/);
  assert.match(source, /监听尚未生效/);
  assert.match(source, /Tailscale/);
  assert.match(source, /Wi-Fi/);
  assert.match(source, /其他网络/);
});

test("header distinguishes official model idle unload from online Gateway", () => {
  assert.match(source, /unloaded:\s*\["空闲卸载",\s*"warn"\]/);
  assert.match(source, /model_loaded: boolean \| null/);
  assert.match(rust, /official_model_loaded/);
  assert.match(rust, /fn runtime_phase\(/);
  assert.match(rust, /model_loaded == Some\(false\)/);
});

test("overview manually unloads and loads models without calling service stop labels", () => {
  assert.match(source, /s\?\.managed \? "卸载模型" : "加载模型"/);
  assert.match(source, /manual_unloaded:\s*\["手动卸载",\s*"warn"\]/);
  assert.match(source, /unloaded:\s*\["空闲卸载",\s*"warn"\]/);
  assert.match(source, /status\?\.managed \? "stop_service" : "start_service"/);
  assert.match(source, /手动卸载会安全暂停 Native 服务栈/);
  assert.doesNotMatch(source, /安全停止服务/);
  assert.match(rust, /stop_managed\(&state, true\)/);
  assert.match(rust, /stop_managed\(&state, false\)/);
  assert.match(rust, /prefs\.manual_unloaded = true/);
  assert.match(rust, /prefs\.manual_unloaded = false/);
  assert.match(rust, /should_auto_start\(/);
});

test("Native model registration and idle timeout are wired to isolated real commands", () => {
  assert.match(source,/id="native-model-select"/);
  assert.match(source,/id="native-idle-seconds"/);
  assert.match(source,/id="native-import-path"/);
  assert.match(source,/register_native_model_config/);
  assert.match(source,/idle_unload_s:Number\(input.value\)/);
  assert.match(source,/model_config:input.value/);
  assert.match(source,/下次手动/);
  assert.match(rust,/fn effective_config\(/);
  assert.match(rust,/value\["idle_unload_s"\] = json!\(timeout\)/);
  assert.match(rust,/fn list_native_model_configs\(/);
  assert.match(rust,/fn register_native_model_config\(/);
});

test("API key rotation is only available when native service is fully unloaded", () => {
  assert.match(source,/data-action="rotate-key"/);
  assert.match(source,/rotate_native_api_key/);
  assert.match(source,/status\?\.managed \|\| status\?\.desired/);
  assert.match(rust,/fn can_rotate_key\(/);
  assert.match(rust,/if !can_rotate_key\(/);
  assert.match(rust,/security::store\("api-key", &key\)/);
  assert.match(source,/旧密钥将立即失效/);
});

test("Native request monitor is authenticated and renders bounded privacy-safe metrics", () => {
  assert.match(rust,/fn gateway_request_monitor\(/);
  assert.match(rust,/request_monitor: Option<Value>/);
  assert.match(rust,/request_monitor = if gateway_ready/);
  assert.match(source,/request_monitor: RequestMetrics \| null/);
  assert.match(source,/请求监控/);
  assert.match(source,/requests\?\.recent \|\| \[\]/);
  assert.match(source,/单次精确 Token 用量暂无来源/);
  assert.doesNotMatch(source,/request\.prompt|req\.messages/);
});

test("Native release installation never silently adopts the compiled developer worktree", () => {
  assert.match(rust, /std::env::current_exe\(\)/);
  assert.match(rust, /if cfg!\(debug_assertions\)/);
  assert.match(rust, /MIKUCHIN_NATIVE_HOME/);
  assert.match(rust, /MIKUCHIN_NATIVE_RUNTIME_HOME/);
  assert.match(rust, /backend\/polystrata\/serve\/server\.py/);
  assert.match(rust, /Native backend not found beside launcher/);
});
