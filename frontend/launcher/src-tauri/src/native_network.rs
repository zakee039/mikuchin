//! Dedicated Cloudflare connector and Native-only LAN discovery.
//! Remote tunnel identity must be NEW: never re-use a stable Mikuchin token.
use std::{
    fs::{self, OpenOptions},
    io::Read,
    net::Ipv4Addr,
    os::windows::process::CommandExt,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};
use serde::{Deserialize, Serialize};
use crate::{native_prefs::NativePrefs, security};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
const METRICS_PORT: u16 = 23189;

pub fn binary_path() -> Result<PathBuf, String> {
    let root = super::native::project_runtime_root()?;
    Ok(root.join("tools/cloudflared.exe"))
}

pub fn provision_binary() -> Result<String, String> {
    let target = binary_path()?;
    if target.is_file() {
        return Ok(target.to_string_lossy().to_string());
    }
    // Only copy the *binary* of the existing installation, never config,
    // tokens, keys, domain or logs. No modification to the stable product.
    let root = super::native::project_root_for_network()?;
    let source = root.parent().ok_or("Invalid Native root")?
        .join("mikuchin/tools/cloudflared/cloudflared.exe");
    if !source.is_file() {
        return Err("未找到 cloudflared，请先在 Native runtime 安装 cloudflared.exe".into());
    }
    fs::create_dir_all(target.parent().ok_or("Invalid tunnel binary path")?)
        .map_err(|e| e.to_string())?;
    fs::copy(source, &target).map_err(|e| e.to_string())?;
    Ok(target.to_string_lossy().to_string())
}

pub fn spawn(prefs: &NativePrefs) -> Result<Child, String> {
    if !prefs.cf_enabled {
        return Err("Tunnel 未启用".into());
    }
    if !crate::native_prefs::validate_hostname(&prefs.cf_hostname) {
        return Err("请填写独立 Tunnel 的合法域名".into());
    }
    let token = security::read("native-cf-tunnel-token")?
        .filter(|v| !v.trim().is_empty())
        .ok_or("请先保存 Native 专用 Cloudflare Tunnel Token")?;
    let exe = binary_path()?;
    if !exe.is_file() {
        return Err("Native cloudflared.exe 不存在，先点击安装".into());
    }
    let directory = super::state_dir();
    fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
    let log = OpenOptions::new().create(true).append(true)
        .open(directory.join("native-cloudflared.log")).map_err(|e| e.to_string())?;
    let stderr = log.try_clone().map_err(|e| e.to_string())?;
    // Token only through environment, NEVER argv / logfile / frontend status.
    Command::new(exe)
        .args(["tunnel","--metrics",&format!("127.0.0.1:{METRICS_PORT}"),
            "--no-autoupdate","run"])
        .env("TUNNEL_TOKEN", token)
        .stdin(Stdio::null())
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(stderr))
        .creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
        .spawn().map_err(|e| format!("cloudflared 启动失败: {e}"))
}

pub fn stop(child: &mut Option<Child>) {
    if let Some(mut proc) = child.take() {
        // cloudflared owns no paid jobs; only this connector is stopped.
        let _ = proc.kill();
        let _ = proc.wait();
    }
}

pub fn connections() -> Option<u32> {
    let resp = ureq::get(&format!("http://127.0.0.1:{METRICS_PORT}/metrics"))
        .timeout(Duration::from_millis(500)).call().ok()?;
    let text = resp.into_string().ok()?;
    for line in text.lines() {
        if line.starts_with("cloudflared_tunnel_ha_connections") {
            return line.split_whitespace().last()?.parse::<f64>().ok()
                .map(|v| v.max(0.0).min(100.0) as u32);
        }
    }
    None
}

pub fn probe(hostname: &str) -> Result<(u16, u64, bool), String> {
    if !crate::native_prefs::validate_hostname(hostname) {
        return Err("请先保存合法 Tunnel 域名".into());
    }
    let start = Instant::now();
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(7)).redirects(0).build();
    let address = format!("https://{hostname}/health");
    let response = agent.get(&address).call();
    let (code, body) = match response {
        Ok(response) => {
            let code = response.status();
            (code, response.into_reader().take(2048).bytes().take(2048)
                .collect::<Result<Vec<_>, _>>().unwrap_or_default())
        }
        Err(ureq::Error::Status(code, response)) => {
            (code, response.into_reader().take(2048).bytes().take(2048)
                .collect::<Result<Vec<_>, _>>().unwrap_or_default())
        }
        Err(err) => return Err(format!("无法通过 HTTPS 访问 Tunnel: {err}")),
    };
    // A bare 401 is insufficient: only the exact Native Gateway error qualifies.
    let valid = code == 401
        && String::from_utf8_lossy(&body).contains("Missing or invalid gateway API key");
    Ok((code, start.elapsed().as_millis().min(120_000) as u64, valid))
}

#[derive(Serialize, Deserialize, Clone)]
pub struct LanAddress {
    pub address: String,
    pub interface: String,
    pub description: String,
}
pub fn addresses() -> Vec<LanAddress> {
    static CACHE: OnceLock<Mutex<Option<(Instant, Vec<LanAddress>)>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(None));
    let Ok(mut guard) = cache.lock() else { return Vec::new(); };
    if let Some((time, entries)) = &*guard {
        if time.elapsed() < Duration::from_secs(15) {
            return entries.clone();
        }
    }
    let script = r#"
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$items=@([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
 Where-Object {$_.OperationalStatus -eq [System.Net.NetworkInformation.OperationalStatus]::Up} |
 ForEach-Object {
  $n=$_
  $n.GetIPProperties().UnicastAddresses |
  Where-Object {$_.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork} |
  ForEach-Object {[PSCustomObject]@{address=$_.Address.ToString();interface=$n.Name;description=$n.Description}}
 })
ConvertTo-Json -InputObject $items -Compress
"#;
    let output = Command::new("powershell.exe")
        .args(["-NoProfile","-NonInteractive","-Command",script])
        .creation_flags(CREATE_NO_WINDOW).output().ok();
    let mut addresses: Vec<LanAddress> = output
        .filter(|output| output.status.success())
        .and_then(|out| serde_json::from_slice(&out.stdout).ok()).unwrap_or_default();
    addresses.retain(|x| x.address.parse::<Ipv4Addr>().is_ok_and(|ip| {
        !ip.is_loopback() && !ip.is_link_local() && !ip.is_unspecified()
            && !ip.is_multicast() && !ip.is_broadcast()
    }));
    addresses.sort_by(|a, b| a.interface.cmp(&b.interface).then(a.address.cmp(&b.address)));
    addresses.dedup_by(|a, b| a.address == b.address);
    *guard = Some((Instant::now(), addresses.clone()));
    addresses
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_tunnel_is_distinct_from_stable_listener() {
        assert_ne!(METRICS_PORT, 23188);
        assert_ne!(METRICS_PORT, 15239);
    }
}
