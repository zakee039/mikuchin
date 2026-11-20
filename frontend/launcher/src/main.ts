import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import "./style.css";
import "./native.css";

type Metrics = {
  hardware?: Record<string, unknown>;
  live?: Record<string, unknown>;
  totals?: Record<string, number>;
  requests?: Array<Record<string, number>>;
  conversation_cache?: {requests?: number; requests_reused?: number};
};
type Status = {
  phase: string; desired: boolean; managed: boolean; stopping: boolean;
  error: string; restarts: number; gateway_port: number; official_port: number;
  gateway_ready: boolean; api_key_present: boolean; model: string; config_name: string;
  metrics: Metrics | null; host_gpu: Record<string, number> | null;
  supervisor_pid: number | null; children: Record<string, number>;
  supervisor_phase: string; child_restarts: Record<string, number>;
  last_recovery: {role: string; at: number} | null;
  gpu_busy: boolean; gpu_phase: string; image_jobs_running: number;
  image_jobs_phase: string; image_worker_ready: boolean; upscaler_ready: boolean;
  log_path: string; data_dir: string;
};
type Tab = "overview" | "api" | "settings" | "native";
const root = document.getElementById("app")!;
const names: Record<Tab, string> = {
  overview: "总览", api: "API", settings: "设置", native: "原生状态",
};
const phases: Record<string, [string, string]> = {
  stopped: ["已停止", "dim"], starting: ["启动中", "warn"],
  running: ["运行正常", "good"], stopping: ["安全停止中", "warn"],
  degraded: ["服务异常", "bad"], error: ["启动失败", "bad"],
};
const handoff: Record<string, string> = {
  unloading: "释放 LLM 显存", generating: "Qwen-Image 推理",
  upscaling: "Real-ESRGAN 4×", restoring: "恢复 LLM",
  idle: "空闲", unknown: "状态更新中",
};
let status: Status | null = null;
let tab: Tab = "overview";
let busy = false;
let polling = false;
let notice = "Native 开发版 · 独立端口 15249";
let avatarCount = 0;
let lastAvatar = 0;

const esc = (v: unknown) => String(v ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c));
const num = (v: unknown): number | null => typeof v === "number" && Number.isFinite(v) ? v : null;
const fmt = (v: unknown, digits = 0) => num(v) === null ? "—" :
  (v as number).toLocaleString("zh-CN", {maximumFractionDigits: digits});
const smallNum = (v: unknown) => num(v) === null ? "—" :
  (v as number) >= 1e6 ? ((v as number) / 1e6).toFixed(2) + "M" :
  (v as number) >= 1e3 ? ((v as number) / 1e3).toFixed(1) + "K" : fmt(v);
const gb = (v: unknown) => num(v) === null ? "—" : ((v as number) / (1024 ** 3)).toFixed(1);
const badge = () => {
  const [label, color] = phases[status?.phase || "starting"] || phases.error;
  return `<span class="badge ${color}"><i></i>${label}</span>`;
};
function mark(message: string) {
  notice = message;
  const el = document.getElementById("notice");
  if (el) el.textContent = message;
}
function metric(title: string, value: string, unit = "") {
  return `<div class="metric"><div class="hint-label">${title}</div><div class="figure">${value}<small>${unit}</small></div></div>`;
}
function overview(): string {
  const s = status;
  const m = s?.metrics;
  const live = m?.live || {};
  const last = m?.requests?.[0];
  const tokens = m?.totals;
  const cache = m?.conversation_cache;
  const gpu = s?.host_gpu || m?.hardware || {};
  const used = gb(gpu.gpu_mem_used);
  const total = gb(gpu.gpu_mem_total);
  const promptRate = num(live.prefill_tok_s_mean) ?? (
    last?.prompt_ms && last.prompt_ms > 0 ?
      ((last.prompt_tokens || 0) - (last.reused || 0)) * 1000 / last.prompt_ms : null);
  const decodeRate = num(live.tok_s) ?? num(last?.decode_tok_s);
  const seen = cache?.requests || 0;
  const reused = cache?.requests_reused || 0;
  const hit = seen > 0 ? Math.min(100, Math.max(0, reused * 100 / seen)) : 0;
  return `<section class="overview-page native-overview">
    <div class="model-card">
      <div class="model-head"><span>当前配置文件</span><span class="chip">官方 PolyStrata</span></div>
      <h2 title="${esc(s?.model)}">${esc(s?.model && s.model !== "—" ? s.model : "等待引擎上线")}</h2>
      <div class="current-config-meta"><span title="${esc(s?.config_name)}">${esc(s?.config_name || "未配置")}</span>
        <span>${s?.gateway_ready ? "本机服务已就绪" : "正在连接"}</span></div>
    </div>
    <div class="metrics">
      ${metric("GPU 显存", used + ` <em>/ ${total}</em>`, "GB")}
      <div class="metric token-metric"><div class="hint-label">Token 统计</div>
        <div class="token-split">
          <div class="token-half"><strong>${smallNum(tokens?.prompt_tokens)}</strong><span>输入</span></div>
          <span class="token-divider" aria-hidden="true"></span>
          <div class="token-half"><strong>${smallNum(tokens?.output_tokens)}</strong><span>输出</span></div>
        </div></div>
      ${metric("Prefill", fmt(promptRate, 1), "tok/s")}
      ${metric("Decode", fmt(decodeRate, 1), "tok/s")}
    </div>
    <div class="monitor-bottom">
      <div class="cache half-card">
        <div class="cache-title"><b>缓存命中率</b><strong>${seen ? hit.toFixed(1) + "%" : "—"}</strong></div>
        <div class="track"><div class="fill" style="width:${hit}%"></div></div>
        <div class="mini-sub">${seen ? `${reused} / ${seen} 次命中` : "暂无请求记录"}</div>
      </div>
      <div class="tunnel-monitor half-card">
        <div class="tunnel-monitor-head"><b>CF Tunnel</b><span class="cf-indicator off"><i></i>未接入</span></div>
        <div class="tunnel-monitor-latency"><span>—</span><small>ms / 待迁移</small></div>
        <div class="mini-sub native-mini">当前 Native 仅监听本机</div>
      </div>
    </div>
    <div class="overview-actions">
      <button class="primary" data-action="toggle" ${busy || s?.stopping ? "disabled" : ""}>${s?.managed ? "安全停止服务" : "启动服务"}</button>
      <button class="secondary" data-action="open-chat" ${!s?.gateway_ready || busy ? "disabled" : ""}>打开 Chat →</button>
    </div>
  </section>`;
}
function apiPage(): string {
  const s = status;
  return `<section class="api-compact">
    <div class="setting-card api-panel">
      <h3>本地 API</h3>
      <div class="native-line"><label>Gateway</label><input class="field native-readonly" readonly value="127.0.0.1:${s?.gateway_port || 15249}"></div>
      <div class="native-line"><label>API Key</label><div class="native-buttons">
        <input class="field native-readonly" value="••••••••••••••••" type="text" readonly aria-label="已隐藏 API Key">
        <button class="outline-small" data-action="copy-key">复制</button></div></div>
      <div class="native-line"><label>引擎内部端口</label><input class="field native-readonly" readonly value="127.0.0.1:${s?.official_port || 15240}"></div>
    </div>
    <div class="setting-card">
      <h3>从其它设备访问 <span class="native-coming-soon">待接入</span></h3>
      <div class="toggle-row native-disabled"><b>局域网 HTTP</b><input type="checkbox" disabled><span class="switch"></span></div>
      <div class="toggle-row native-disabled"><b>Cloudflare Tunnel</b><input type="checkbox" disabled><span class="switch"></span></div>
    </div>
  </section>`;
}
function settingsPage(): string {
  return `<section class="setting-page compact-settings native-settings">
    <div class="setting-card"><h3>启动与守护</h3>
      <label class="toggle-row native-disabled"><b>启动器启动后自动拉起服务</b><input type="checkbox" checked disabled><span class="switch"></span></label>
      <label class="toggle-row native-disabled"><b>服务异常自动恢复</b><input type="checkbox" checked disabled><span class="switch"></span></label>
    </div>
    <div class="setting-card"><h3>独立数据目录</h3>
      <div class="native-hint" style="overflow-wrap:anywhere">${esc(status?.data_dir || "正在读取")}</div>
    </div>
  </section>`;
}
const processRow = (label: string, id: string) => {
  const pid = status?.children?.[id];
  return `<div class="native-process"><i class="process-dot ${pid ? "on" : ""}"></i>
    <span>${label}</span><span class="pid">${pid ? "PID " + pid : "未启动"}</span></div>`;
};
function nativePage(): string {
  const s = status;
  const restarts = Object.values(s?.child_restarts || {}).reduce((sum, v) => sum + (Number(v) || 0), 0);
  return `<section class="native-status-page">
    <div class="setting-card native-card">
      <div class="native-title"><h3>进程守护</h3><small>Supervisor ${s?.supervisor_pid ? "PID " + s.supervisor_pid : "未启动"}</small></div>
      ${processRow("Official Engine", "official")}
      ${processRow("Image Worker", "image-worker")}
      ${processRow("Gateway", "gateway")}
      <div class="metric-row"><span>子进程恢复 / Tauri 重启</span><strong>${restarts} / ${s?.restarts || 0}</strong></div>
      <p class="native-hint">守护器状态：${esc(s?.supervisor_phase || "未知")}
        ${s?.last_recovery?.role ? " · 最近恢复：" + esc(s.last_recovery.role) : ""}</p>
    </div>
    <div class="setting-card native-card">
      <div class="native-title"><h3>GPU 与图像任务</h3><small>${s?.gateway_ready ? "实时状态" : "等待 Gateway"}</small></div>
      <div class="metric-row"><span>GPU 占用阶段</span><strong class="${s?.gpu_busy ? "active" : ""}">${s?.gpu_busy ? esc(handoff[s.gpu_phase] || s.gpu_phase) : "空闲"}</strong></div>
      <div class="metric-row"><span>运行中的图像任务</span><strong>${s?.image_jobs_running || 0} 项</strong></div>
      ${s?.image_jobs_running ? `<p class="native-hint">${esc(s.image_jobs_phase)}</p>` : ""}
      <div class="metric-row"><span>Image Worker</span><strong>${s?.image_worker_ready ? "已就绪" : "未就绪"}</strong></div>
      <div class="metric-row"><span>Real-ESRGAN 4×</span><strong>${s?.upscaler_ready ? "已配置" : "尚未配置"}</strong></div>
    </div>
    <div class="setting-card native-card">
      <div class="native-title"><h3>服务端口</h3></div>
      <div class="metric-row"><span>Gateway / Official</span><strong>${s?.gateway_port || 15249} / ${s?.official_port || 15240}</strong></div>
      <div class="actions"><button class="secondary" data-action="show-log">查看运行日志</button>
        <button class="secondary" data-action="open-chat" ${s?.gateway_ready ? "" : "disabled"}>打开 Chat</button></div>
    </div>
  </section>`;
}
function renderBody() {
  const el = document.getElementById("content");
  if (!el) return;
  const savedScroll = el.scrollTop;
  const page = {overview, api: apiPage, settings: settingsPage, native: nativePage}[tab]();
  // Keep the scroll container itself. Polling once discarded the entire
  // document every two seconds, forcing the viewport back to the top.
  if (el.innerHTML !== page) el.innerHTML = page;
  el.scrollTop = savedScroll;
  const phase = document.getElementById("phase");
  if (phase) phase.innerHTML = badge();
  document.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach(btn => {
    btn.classList.toggle("selected", btn.dataset.tab === tab);
    btn.setAttribute("aria-selected", String(btn.dataset.tab === tab));
  });
}
function mount() {
  root.innerHTML = `<header class="head"><div class="brand">
    <button type="button" class="brand-symbol avatar-trigger" id="avatar-trigger" aria-label="Mikuchin">
      <img src="/mikuchin-icon.png" width="43" height="43" alt="Mikuchin"></button>
    <div><h1>Mikuchin</h1><small>LOCAL MODEL MANAGER</small></div>
    </div><div class="header-status"><span id="phase">${badge()}</span>
      <button id="header-log" class="header-log">查看运行日志</button></div></header>
    <nav class="tabs" role="tablist">${(Object.keys(names) as Tab[]).map(key =>
      `<button role="tab" class="tab ${tab === key ? "selected" : ""}" data-tab="${key}">${names[key]}</button>`).join("")}</nav>
    <main id="content"></main>
    <footer><span id="notice">${esc(notice)}</span><span>v0.3.0</span></footer>`;
  renderBody();
}
async function task(name: string, done: string) {
  if (busy) return;
  busy = true;
  mark("操作执行中…");
  renderBody();
  try {
    await invoke(name);
    mark(done);
  } catch (error) {
    mark("操作失败：" + String(error));
  } finally {
    busy = false;
    await poll();
  }
}
async function copyKey() {
  try {
    const key = await invoke<string>("reveal_api_key");
    try {
      await navigator.clipboard.writeText(key);
    } catch {
      const input = document.createElement("textarea");
      input.value = key;
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.append(input);
      input.select();
      const copied = document.execCommand("copy");
      input.remove();
      if (!copied) throw new Error("无法复制到剪贴板");
    }
    mark("API Key 已复制，仅保存在本机");
  } catch (error) {
    mark("复制失败：" + String(error));
  }
}
function modal(title: string, initial: string) {
  document.getElementById("native-modal")?.remove();
  const overlay = document.createElement("div");
  overlay.className = "native-overlay";
  overlay.id = "native-modal";
  overlay.innerHTML = `<div class="modal" role="dialog" aria-modal="true">
    <div class="modal-top"><h3>${esc(title)}</h3><button aria-label="关闭" id="modal-close">×</button></div>
    <pre></pre></div>`;
  overlay.querySelector("pre")!.textContent = initial;
  const close = () => { overlay.remove(); document.removeEventListener("keydown", escape); };
  const escape = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
  overlay.querySelector("#modal-close")?.addEventListener("click", close);
  overlay.addEventListener("click", event => { if (event.target === overlay) close(); });
  document.addEventListener("keydown", escape);
  document.body.append(overlay);
  return overlay.querySelector("pre")!;
}
async function showLogs() {
  const pre = modal("Native 运行日志", "正在读取…");
  try {
    pre.textContent = (await invoke<string>("get_log")) || "暂无运行日志";
    pre.scrollTop = pre.scrollHeight;
  } catch (error) {
    pre.textContent = String(error);
  }
}
function showPortrait() {
  const pre = modal("Mikuchin", "");
  const image = document.createElement("img");
  image.src = "/mikuchin-half.png";
  image.alt = "Mikuchin";
  image.style.cssText = "max-width:100%;max-height:65vh;object-fit:contain;display:block;margin:auto";
  pre.replaceWith(image);
}
root.addEventListener("click", event => {
  const element = (event.target as HTMLElement).closest<HTMLElement>("[data-tab], [data-action], #header-log, #avatar-trigger");
  if (!element) return;
  if (element.dataset.tab && element.dataset.tab in names) {
    if (tab !== element.dataset.tab) {
      tab = element.dataset.tab as Tab;
      const content = document.getElementById("content");
      if (content) content.scrollTop = 0;
      renderBody();
    }
    return;
  }
  if (element.id === "header-log") { void showLogs(); return; }
  if (element.id === "avatar-trigger") {
    const now = performance.now();
    if (now - lastAvatar > 2500) avatarCount = 0;
    lastAvatar = now;
    if (++avatarCount >= 5) { avatarCount = 0; showPortrait(); }
    return;
  }
  const action = element.dataset.action;
  if (action === "copy-key") void copyKey();
  else if (action === "open-chat") void task("open_chat", "已打开 Chat 页面");
  else if (action === "show-log") void showLogs();
  else if (action === "toggle") void task(status?.managed ? "stop_service" : "start_service",
    status?.managed ? "已发送安全停止指令" : "已请求启动 Native 服务");
  else if (action === "start") void task("start_service", "已请求启动 Native 服务");
  else if (action === "stop") void task("stop_service", "已发送安全停止指令");
});
async function poll() {
  if (polling) return;
  polling = true;
  try {
    status = await invoke<Status>("get_status");
  } catch (error) {
    mark("读取 Native 状态失败：" + String(error));
  } finally {
    polling = false;
    renderBody();
  }
}
mount();
void listen<string>("manager-error", event => { mark("守护器：" + event.payload); void poll(); });
void poll();
setInterval(() => void poll(), 2000);
