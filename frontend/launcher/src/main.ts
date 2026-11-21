import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import {getLocale, setLocale, translateDom, observeLocale, tr} from "./i18n";
import "./style.css";
import "./native.css";

type Metrics = {
  hardware?: Record<string, unknown>;
  live?: Record<string, unknown>;
  totals?: Record<string, number>;
  requests?: Array<Record<string, number>>;
  conversation_cache?: {requests?: number; requests_reused?: number};
};
type RequestMetrics = {
  uptime_s: number; total: number; failed: number; active: number;
  by_kind: Record<string, number>;
  recent: Array<{kind: string; status: number; outcome: string;
    duration_ms: number; response_bytes: number; completed_at: number}>;
};
type NativePrefs = {
  autostart: boolean; auto_start_service: boolean; watchdog: boolean;
  manual_unloaded: boolean;
  model_config: string; idle_unload_s: number;
  lan_access: boolean; cf_enabled: boolean; cf_hostname: string;
};
type LanAddress = {address: string; interface: string; description: string};
type Status = {
  phase: string; desired: boolean; managed: boolean; stopping: boolean;
  error: string; restarts: number; gateway_port: number; official_port: number;
  gateway_ready: boolean; model_loaded: boolean | null; api_key_present: boolean; model: string; config_name: string;
  model_context: number;
  available_configs: ModelConfig[];
  metrics: Metrics | null; request_monitor: RequestMetrics | null;
  host_gpu: Record<string, number> | null;
  supervisor_pid: number | null; children: Record<string, number>;
  supervisor_phase: string; child_restarts: Record<string, number>;
  last_recovery: {role: string; at: number} | null;
  gpu_busy: boolean; gpu_phase: string; image_jobs_running: number;
  image_jobs_phase: string; image_worker_ready: boolean; upscaler_ready: boolean;
  log_path: string; data_dir: string;
  settings: NativePrefs; cf_running: boolean; cf_connections: number | null;
  cf_error: string; cf_token_present: boolean; cf_binary_ready: boolean;
  lan_addresses: LanAddress[]; lan_effective: boolean;
};
type ModelConfig = {file:string; name:string; model:string; context:number|null;
  quantization:string; kv_type:string; tokenizer:string; vision_projector:string;
  draft_model:string; vram_reserve_mib:number|null; idle_unload_s:number|null;
  conversation_cache_mib:string|null; engine:string; path:string};
type Tab = "overview" | "api" | "settings" | "native";
const root = document.getElementById("app")!;
const names: Record<Tab, string> = {
  overview: "总览", api: "API", settings: "设置", native: "原生状态",
};
const phases: Record<string, [string, string]> = {
  stopped: ["已停止", "dim"], starting: ["启动中", "warn"],
  running: ["运行正常", "good"], stopping: ["安全停止中", "warn"],
  unloaded: ["空闲卸载", "warn"],
  manual_unloaded: ["手动卸载", "warn"], unloading: ["正在卸载", "warn"],
  reading: ["Prefill", "good"], generating: ["生成中", "good"],
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
let notice = "本机服务管理 · Windows";
let keyCache = "";
let cfLatencyMs: number | null = null;
let avatarCount = 0;
let lastAvatar = 0;
let cfHostnameDraft: string | null = null;
let cfTokenDraft = "";


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
  const selected = s?.available_configs?.find(c => c.file === s?.settings?.model_config);
  const tunnelOn = Boolean(s?.settings?.cf_enabled);
  const tunnelConnected = tunnelOn && Boolean(s?.cf_running && (s.cf_connections || 0) > 0);
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
      <div class="model-head"><span>当前配置文件</span>
        <div class="config-head-actions"><button class="chip chip-action" data-action="choose-config">选择配置文件 ▾</button>
          <button class="chip chip-action" data-action="view-config" ${selected ? "" : "disabled"}>查看</button></div></div>
      <h2 title="${esc(selected?.name || s?.model)}">${esc(selected?.name || s?.model || "等待引擎上线")}</h2>
      <div class="current-config-meta"><span title="${esc(selected?.path || s?.config_name)}">${esc(s?.settings?.model_config || "未配置")}</span>
        <span>${s?.model_context || selected?.context ? (s?.model_context || selected?.context)?.toLocaleString("zh-CN") + " Token" : "上下文未指定"}</span></div>
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
        <div class="tunnel-monitor-head"><b>CF Tunnel</b>
          <span class="cf-indicator ${tunnelConnected ? "on" : tunnelOn ? "pending" : "off"}"><i></i>${tunnelConnected ? "已连接" : tunnelOn ? "连接中" : "未启用"}</span></div>
        <div class="tunnel-monitor-latency"><span>${cfLatencyMs ?? "—"}</span><small>ms · HTTPS 延迟</small></div>
        <div class="monitor-buttons"><button data-action="test-tunnel" ${!tunnelOn || busy ? "disabled" : ""}>测试</button>
          <button data-action="restart-tunnel" ${!tunnelOn || busy ? "disabled" : ""}>重启</button></div>
      </div>
    </div>
    <div class="overview-actions">
      <button class="primary" data-action="toggle"
        title="手动卸载会安全暂停 Native 服务栈（包括 API 与图像任务入口），下次需点击加载模型才能恢复"
        ${busy || s?.stopping ? "disabled" : ""}>${s?.stopping ? "正在卸载" : s?.managed ? "卸载模型" : "加载模型"}</button>
      <button class="secondary" data-action="open-chat" ${!s?.gateway_ready || busy ? "disabled" : ""}>打开 Chat →</button>
    </div>
  </section>`;
}
function apiPage(): string {
  const s = status;
  const settings = s?.settings;
  const cfOn = Boolean(settings?.cf_enabled);
  const cfActive = cfOn && s?.cf_running && (s.cf_connections || 0) > 0;
  const cfState = !cfOn ? "未启用" : cfActive ? "已连接" : s?.cf_running ? "连接中" : "未连接";
  const lanReady = Boolean(s?.gateway_ready && s?.lan_effective);
  const lanEntries = settings?.lan_access ? `<div class="lan-address-list" aria-label="局域网访问地址">
      ${!lanReady ? '<span class="lan-address-note">以下为本机网卡地址，监听尚未生效</span>' : ""}
      ${(s?.lan_addresses || []).map(item => {
        const adapter = (item.interface + " " + item.description).toLowerCase();
        const kind = /tailscale/.test(adapter) ? "Tailscale" :
          /wi-fi|wireless|wlan|802\.11/.test(adapter) ? "Wi-Fi" :
          /ethernet|以太网/.test(adapter) ? "以太网" : "其他网络";
        const url = `http://${item.address}:${s?.gateway_port || 15239}/`;
        return `<div class="lan-address-entry">
          <span class="lan-address-name" title="${esc(item.interface + " · " + item.description)}">
            <strong>${esc(kind)}</strong><small>${esc(item.interface)}</small>
          </span>
          ${lanReady
            ? `<a class="lan-chat-link" href="${esc(url)}" title="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>`
            : `<span class="lan-chat-inactive" title="监听尚未生效">${esc(url)}</span>`}
        </div>`;
      }).join("")}
      ${!(s?.lan_addresses || []).length ? '<span class="lan-chat-pending">未检测到可用的 IPv4 网卡地址</span>' : ""}
    </div>` : "";
  return `<section class="api-compact">
    <div class="setting-card api-panel">
      <div class="api-line"><strong>端口</strong><input class="field port-field native-readonly" readonly value="${s?.gateway_port || 15239}"><span class="native-inline-note">Native Gateway</span></div>
      <div class="api-line"><strong>API Key</strong><input id="api-key-display" class="field key-display native-readonly" type="text" readonly autocomplete="off" value="${esc(keyCache)}"><button class="outline-small" data-action="copy-key">复制</button><button class="outline-small" data-action="rotate-key" ${busy ? "disabled" : ""}>更换</button></div>
      <div class="api-line toggle-compact lan-toggle-row"><strong>局域网 HTTP 直连</strong>
        <label class="lan-toggle" title="更改监听范围后须安全重启服务，现有任务不会被中断">
          <input type="checkbox" data-setting="lan_access" ${settings?.lan_access ? "checked" : ""} ${busy ? "disabled" : ""}><span class="switch"></span></label></div>
      <div class="lan-chat-slot">${lanEntries}
        ${s?.managed && Boolean(settings?.lan_access) !== Boolean(s?.lan_effective)
          ? '<span class="lan-chat-pending">监听变更已保存，安全重启服务后生效</span>' : ""}</div>
    </div>
    <div class="setting-card tunnel-panel">
      <div class="tunnel-heading"><strong>Cloudflare Tunnel</strong>
        <span class="cf-indicator ${cfActive ? "on" : cfOn ? "pending" : "off"}"><i></i>${cfState}</span>
      </div>
      <div class="api-line"><label for="cf-hostname">域名</label><input id="cf-hostname" class="field" spellcheck="false" placeholder="native.example.com" value="${esc(cfHostnameDraft ?? settings?.cf_hostname ?? "")}"></div>
      <div class="api-line"><label for="cf-token">Token</label><input id="cf-token" class="field" type="password" autocomplete="off" placeholder="${s?.cf_token_present ? "已安全保存 · 留空不修改" : "粘贴独立 Tunnel Token"}" value="${esc(cfTokenDraft)}"></div>
      <div class="tunnel-actions">
        <span class="tunnel-meta"><span data-cf-latency>${s?.cf_connections ?? "—"} 条连接</span>
          <span data-cf-message>${esc(s?.cf_error || "")}</span></span>
        <button class="primary-small" data-action="install-tunnel" ${busy ? "disabled" : ""}>安装</button>
        <button class="outline-small" data-action="test-tunnel" ${busy ? "disabled" : ""}>测试</button>
        <button class="outline-small" data-action="restart-tunnel" ${busy || !cfOn ? "disabled" : ""}>重启</button>
      </div>
    </div>
  </section>`;
}
function settingsPage(): string {
  const prefs = status?.settings;
  const toggle = (key: keyof Pick<NativePrefs,"autostart"|"auto_start_service"|"watchdog">, name: string) =>
    `<label class="toggle-row"><b>${name}</b><input type="checkbox" data-setting="${key}" ${prefs?.[key] ? "checked" : ""} ${busy ? "disabled" : ""}><span class="switch"></span></label>`;
  return `<section class="setting-page compact-settings native-settings">
    <div class="setting-card"><h3>启动与守护</h3>
      ${toggle("autostart","开机自启")}
      ${toggle("auto_start_service","启动后自动加载模型")}
      ${toggle("watchdog","服务守护")}
    </div>
    <div class="setting-card"><h3>全局语言</h3>
      <div class="setting-inline"><label for="global-language">语言</label>
        <select id="global-language" class="field setting-select" ${busy ? "disabled" : ""}>
          <option value="zh-CN" ${getLocale()==="zh-CN" ? "selected" : ""}>简体中文</option>
          <option value="ja-JP" ${getLocale()==="ja-JP" ? "selected" : ""}>日本語</option>
          <option value="en-US" ${getLocale()==="en-US" ? "selected" : ""}>English</option>
        </select></div>
    </div>
    <div class="setting-card"><h3>空闲卸载时间</h3>
      <div class="setting-inline idle-control"><label for="idle-minutes">分钟</label>
        <input id="idle-minutes" type="number" class="field idle-input" min="0" max="1440" step="1"
          value="${Math.round((prefs?.idle_unload_s ?? 900) / 60)}" ${busy ? "disabled" : ""}>
        <button class="outline-small" data-action="save-idle-timeout" ${busy ? "disabled" : ""}>保存并重启服务</button></div>
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
  const requests=s?.request_monitor;
  const requestNames:Record<string,string> = {
    chat:"Chat", messages:"Messages", responses:"Responses", images:"Images",
  };
  const recent=(requests?.recent || []).slice(0,5).map(req =>
    `<div class="metric-row"><span>${esc(requestNames[req.kind] || req.kind)}
      · HTTP ${Number(req.status)}</span><strong>${Math.max(0,Number(req.duration_ms)||0)} ms</strong></div>`
  ).join("");
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
      <div class="native-title"><h3>请求监控</h3><small>本次 Gateway 运行期间</small></div>
      <div class="metric-row"><span>总请求 / 失败</span>
        <strong>${requests ? requests.total+" / "+requests.failed : "—"}</strong></div>
      <div class="metric-row"><span>执行中的请求</span>
        <strong>${requests?.active ?? "—"} 项</strong></div>
      <div class="metric-row"><span>Chat / Messages / Responses</span>
        <strong>${requests ? [requests.by_kind.chat,requests.by_kind.messages,
          requests.by_kind.responses].map(v=>v||0).join(" / ") : "—"}</strong></div>
      ${recent}
      <p class="native-hint">只记录请求类别、状态、耗时和响应字节数；
        不记录聊天正文、凭据或设备地址。重启后清零，单次精确 Token 用量暂无来源。</p>
    </div>
    <div class="setting-card native-card">
      <div class="native-title"><h3>服务端口</h3></div>
      <div class="metric-row"><span>Gateway / Official</span><strong>${s?.gateway_port || 15239} / ${s?.official_port || 15240}</strong></div>
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
  // Polling must never destroy focused form inputs while someone enters a
  // Tunnel domain/secret. The latest status is displayed after focus leaves.
  const active = document.activeElement;
  const editing = (active instanceof HTMLInputElement && !active.readOnly && active.type !== "checkbox"
    || active instanceof HTMLSelectElement) && el.contains(active);
  if (!editing && el.innerHTML !== page) el.innerHTML = page;
  translateDom(el);
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
    <footer><span id="notice">${esc(notice)}</span><span>v0.5.0</span></footer>`;
  renderBody();
  translateDom(root);
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
    mark("API Key 已复制");
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

const ctxText = (value: number|null|undefined) => typeof value === "number" && value > 0
  ? value.toLocaleString("zh-CN") + " Token" : "未指定";
function showConfig(config: ModelConfig) {
  const valueOrUnset = (value: string | null | undefined) => value || "未指定";
  const idle = typeof config.idle_unload_s === "number"
    ? config.idle_unload_s === 0 ? "已关闭" : config.idle_unload_s + " 秒（" +
      Math.round(config.idle_unload_s / 60) + " 分钟）" : "未在配置中指定";
  const rows: Array<[string,string]> = [
    ["模型名称",config.name], ["模型权重",config.model],
    ["上下文窗口",ctxText(config.context || status?.model_context)],
    ["量化格式",valueOrUnset(config.quantization)],
    ["KV 精度",valueOrUnset(config.kv_type)],
    ["推理引擎",config.engine],
    ["Tokenizer",valueOrUnset(config.tokenizer)],
    ["视觉投影文件",valueOrUnset(config.vision_projector)],
    ["草稿模型",valueOrUnset(config.draft_model)],
    ["显存预留",typeof config.vram_reserve_mib === "number" ? config.vram_reserve_mib + " MiB" : "未设置"],
    ["RAM 对话缓存",config.conversation_cache_mib
      ? config.conversation_cache_mib === "auto" ? "自动预算" : config.conversation_cache_mib + " MiB"
      : "未设置"],
    ["空闲自动卸载",idle], ["配置文件完整路径",config.path],
  ];
  const bg = document.createElement("div");
  bg.className = "modal-backdrop";
  bg.innerHTML = `<div class="modal config-modal" role="dialog" aria-modal="true" aria-label="配置文件详情">
    <div class="modal-top"><div><strong>配置文件详情</strong><small>${esc(config.file)}</small></div>
    <button type="button" data-close-config aria-label="关闭">×</button></div>
    <div class="detail-list">${rows.map(([name,val]) => `<div class="detail-row"><span>${esc(name)}</span>
      <strong title="${esc(val)}">${esc(val)}</strong></div>`).join("")}</div></div>`;
  const close = () => bg.remove();
  bg.querySelector("[data-close-config]")?.addEventListener("click",close);
  bg.addEventListener("click",e => {if(e.target===bg)close();});
  document.body.appendChild(bg);
  translateDom(bg);
}
async function openConfigPicker() {
  const items = status?.available_configs || [];
  const selected = status?.settings?.model_config || "";
  const bg = document.createElement("div"); bg.className = "modal-backdrop";
  bg.innerHTML = `<div class="modal config-picker-modal" role="dialog" aria-modal="true" aria-label="选择配置文件">
    <div class="modal-top"><div><strong>选择配置文件</strong><small>已注册 ${items.length} 个部署配置</small></div>
      <button type="button" data-close-picker aria-label="关闭">×</button></div>
    <div class="config-picker-scroll"><div class="model-list">${items.map(item => {
      const current = selected===item.file;
      return `<div class="model-item ${current?"is-selected":""}">
        <div class="model-text"><b title="${esc(item.path)}">${esc(item.file)}</b>
          <small>${esc(item.name)}</small>
          <span class="config-context">${esc(ctxText(item.context))}${item.quantization?" · "+esc(item.quantization):""}</span></div>
        <div class="config-actions"><button type="button" data-view-config="${esc(item.file)}">查看</button>
          <button class="choice ${current?"active":""}" data-select-config="${esc(item.file)}"
            ${current||busy?"disabled":""}>${current?"使用中":"使用"}</button></div></div>`;
    }).join("") || `<div class="empty">没有已注册的模型配置</div>`}</div>
      <div class="config-picker-bottom"><button type="button" class="mini-primary" data-import-config>＋ 注册配置文件</button></div>
    </div></div>`;
  const close = () => bg.remove();
  bg.querySelector("[data-close-picker]")?.addEventListener("click",close);
  bg.addEventListener("click",e => {if(e.target===bg)close();});
  bg.querySelectorAll<HTMLButtonElement>("[data-view-config]").forEach(button => button.addEventListener("click",()=>{
    const item = items.find(c => c.file === button.dataset.viewConfig);
    if(item)showConfig(item);
  }));
  bg.querySelectorAll<HTMLButtonElement>("[data-select-config]").forEach(button => button.addEventListener("click",async()=>{
    const file=button.dataset.selectConfig;
    if(!file||busy)return;
    close();
    await updatePrefs({model_config:file},"模型配置已选择，下次加载模型时生效");
  }));
  bg.querySelector("[data-import-config]")?.addEventListener("click",async()=>{
    if(busy)return;
    try {
      const path=await open({multiple:false,directory:false,filters:[{name:"模型 JSON 配置",extensions:["json"]}]});
      if(typeof path!=="string")return;
      await invoke<ModelConfig>("register_native_model_config",{path});
      close();await poll();await openConfigPicker();mark("配置文件已注册");
    } catch(error){ mark("注册配置失败："+String(error)); }
  });
  document.body.appendChild(bg);
  translateDom(bg);
}
async function updatePrefs(updates: Partial<NativePrefs>, success: string) {
  if (busy || !status?.settings) return;
  busy = true;
  try {
    const incoming = {...status.settings, ...updates};
    const saved = await invoke<NativePrefs>("save_native_preferences", {incoming});
    status.settings = saved;
    mark(success);
  } catch (error) {
    mark("设置失败：" + String(error));
  } finally {
    busy = false;
    await poll();
  }
}
async function rotateNativeKey() {
  if (busy || status?.managed || status?.desired || status?.stopping) {
    mark("请先卸载模型，等 Native 服务完全停止后再轮换密钥"); return;
  }
  if (!window.confirm("确定轮换 Native API Key？当前所有设备、浏览器保存的旧密钥将立即失效。此操作不会影响正式版。")) return;
  busy = true;
  try {
    await invoke("rotate_native_api_key");
    await refreshKey();
    mark("API Key 已更换，请同步更新其他客户端");
  } catch (error) { mark("密钥轮换失败：" + String(error)); }
  finally { busy = false; await poll(); }
}
async function refreshKey() {
  try {
    keyCache=await invoke<string>("reveal_api_key");
    const field=document.getElementById("api-key-display") as HTMLInputElement|null;
    if(field)field.value=keyCache;
  } catch(error) {mark("读取 API Key 失败："+String(error));}
}
async function saveIdleTimeout() {
  const input=document.getElementById("idle-minutes") as HTMLInputElement|null;
  const raw=input?.value.trim()||"";
  const minutes=Number(raw);
  if(!raw||!Number.isInteger(minutes)||minutes<0||minutes>1440){mark("请输入 0–1440 分钟");return;}
  if(busy||!status?.settings)return;
  const safe = !status.image_jobs_running && !status.gpu_busy
    && !(status.request_monitor?.active||0) && !["reading","generating","starting","stopping"].includes(status.phase);
  const wasRunning=status.managed;
  busy=true;
  try {
    status.settings=await invoke<NativePrefs>("save_native_preferences",
      {incoming:{...status.settings,idle_unload_s:minutes*60}});
    if(wasRunning&&safe){
      await invoke("stop_service");
      await invoke("start_service");
      mark("空闲卸载时间已保存，Native 服务已安全重启");
    }else if(wasRunning){
      mark("设置已保存；当前有任务或请求，空闲后请手动重启服务");
    }else{mark("空闲卸载时间已保存，下次启动生效");}
  }catch(error){mark("更新空闲卸载失败："+String(error));}
  finally{busy=false;await poll();}
}
async function saveTunnelForm() {
  if (busy || !status?.settings) return;
  busy = true;
  try {
    const hostname = (cfHostnameDraft ?? status.settings.cf_hostname).trim();
    if (!/^[a-z0-9.-]+$/i.test(hostname) || hostname.length > 253) {
      throw new Error("请填写正确的 Tunnel 域名");
    }
    if (cfTokenDraft.trim()) {
      await invoke("save_native_tunnel_token", {token: cfTokenDraft.trim()});
    }
    await invoke("install_native_tunnel");
    const saved = await invoke<NativePrefs>("save_native_preferences",
      {incoming: {...status.settings, cf_hostname: hostname, cf_enabled:true}});
    status.settings = saved;
    cfHostnameDraft = null;
    cfTokenDraft = "";
    mark("Cloudflare Tunnel 已配置；等待本地连接数确认公网状态");
  } catch (error) {
    mark("保存 Tunnel 失败：" + String(error));
  } finally {
    busy = false;
    await poll();
  }
}
async function tunnelAction(action: "install_native_tunnel"|"test_native_tunnel"|"restart_native_tunnel") {
  if (busy) return;
  busy = true;
  try {
    const result = await invoke<unknown>(action);
    if (action === "test_native_tunnel") {
      const test = result as {http_status: number; latency_ms: number; connected: boolean};
      cfLatencyMs = test.connected ? test.latency_ms : null;
      mark(test.connected ? `Tunnel 已连接：${test.latency_ms} ms` :
        `Tunnel 尚未接入 Native Gateway（HTTP ${test.http_status}）`);
    } else {
      mark(action === "install_native_tunnel" ? "Native cloudflared 已安装" : "Tunnel 重启指令已发送");
    }
  } catch (error) {
    mark("Tunnel 操作失败：" + String(error));
  } finally {
    busy = false;
    await poll();
  }
}

root.addEventListener("input", event => {
  const input = event.target as HTMLInputElement;
  if (input.id === "cf-hostname") cfHostnameDraft = input.value;
  if (input.id === "cf-token") cfTokenDraft = input.value;

});
root.addEventListener("change", event => {
  const input = event.target as HTMLInputElement;
  if (input.id === "global-language") {
    const language=input.value;
    void invoke<string>("set_native_language",{language}).then(v=>{
      setLocale(v);renderBody();mark("全局语言已保存");
    }).catch(err=>mark("语言设置失败："+String(err)));
    return;
  }
  const key = input.dataset.setting;
  if (!key || input.type !== "checkbox") return;
  if (key === "lan_access" || key === "cf_enabled" ||
      key === "autostart" || key === "auto_start_service" || key === "watchdog") {
    void updatePrefs({[key]: input.checked}, "设置已保存");
  }
});
root.addEventListener("click", event => {
  const element = (event.target as HTMLElement).closest<HTMLElement>("[data-tab], [data-action], #header-log, #avatar-trigger");
  if (!element) return;
  if (element.dataset.tab && element.dataset.tab in names) {
    if (tab !== element.dataset.tab) {
      tab = element.dataset.tab as Tab;
      const content = document.getElementById("content");
      if (content) content.scrollTop = 0;
      renderBody();
      if(tab==="api")void refreshKey();
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
  else if (action === "rotate-key") void rotateNativeKey();
  else if (action === "choose-config") void openConfigPicker();
  else if (action === "view-config") {
    const item=status?.available_configs?.find(c=>c.file===status?.settings?.model_config);
    if(item)showConfig(item);
  }
  else if (action === "save-idle-timeout") void saveIdleTimeout();
  else if (action === "open-chat") void task("open_chat", "已打开 Chat 页面");
  else if (action === "show-log") void showLogs();

  else if (action === "install-tunnel") void saveTunnelForm();
  else if (action === "test-tunnel") void tunnelAction("test_native_tunnel");
  else if (action === "restart-tunnel") void tunnelAction("restart_native_tunnel");
  else if (action === "toggle") void task(status?.managed ? "stop_service" : "start_service",
    status?.managed ? "正在安全卸载模型；服务将暂停，之后不会自动恢复" : "已请求加载模型并恢复 Native 服务");
  else if (action === "start") void task("start_service", "已请求加载模型并恢复 Native 服务");
  else if (action === "stop") void task("stop_service", "正在安全卸载模型；服务将暂停，之后不会自动恢复");
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
void invoke<string>("get_native_language").then(language=>{setLocale(language);renderBody();}).catch(()=>{});
observeLocale();
void poll();
setInterval(() => void poll(), 2000);
