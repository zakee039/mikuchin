import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import "./style.css";

type Status = {
  phase: string;
  desired: boolean;
  managed: boolean;
  stopping: boolean;
  error: string;
  restarts: number;
  gateway_port: number;
  official_port: number;
  gateway_ready: boolean;
  api_key_present: boolean;
  model: string;
  supervisor_pid: number | null;
  children: Record<string, number>;
  supervisor_phase: string;
  child_restarts: Record<string, number>;
  last_recovery: { role: string; at: number } | null;
  gpu_busy: boolean;
  gpu_phase: string;
  image_jobs_running: number;
  image_jobs_phase: string;
  image_worker_ready: boolean;
  upscaler_ready: boolean;
  log_path: string;
  data_dir: string;
};

const root = document.querySelector<HTMLDivElement>("#app")!;
let status: Status | null = null;
let actionBusy = false;
let notice = "原生独立开发实例 · 只监听本机环回地址";
const escapeHtml = (text: unknown) => String(text ?? "").replace(/[&<>"']/g, ch =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] || ch));
const phaseNames: Record<string, string> = {
  stopped: "已停止", starting: "启动中", running: "运行正常",
  degraded: "服务异常", stopping: "安全停止中", error: "启动失败",
};
function badge(phase: string) {
  const color = phase === "running" ? "good" : phase === "error" || phase === "degraded" ? "bad" : phase === "stopped" ? "dim" : "busy";
  return `<span class="status-badge ${color}"><span class="dot"></span>${phaseNames[phase] || phase}</span>`;
}
function child(label: string, key: string) {
  const pid = status?.children?.[key];
  return `<div class="process-row"><span class="process-dot ${pid ? "on" : ""}"></span><span>${label}</span><span class="pid">${pid ? "PID " + pid : "未启动"}</span></div>`;
}
function render() {
  const s = status;
  const phase = s?.phase || "starting";
  const handoffNames: Record<string, string> = {
    unloading: "释放 LLM 显存", generating: "Qwen-Image 推理",
    upscaling: "Real-ESRGAN 4×", restoring: "恢复 LLM", idle: "空闲",
    unknown: "状态更新中",
  };
  const imageBusy = (s?.image_jobs_running ?? 0) > 0;
  const childRecoveryCount = Object.values(s?.child_restarts || {})
    .reduce((sum, n) => sum + (Number(n) || 0), 0);
  const recentRecovery = s?.last_recovery?.role
    ? `最近恢复：${escapeHtml(s.last_recovery.role)}`
    : "未发生子进程恢复";
  root.innerHTML = `
    <header class="topbar">
      <div class="brand"><img src="/mikuchin-icon.png" width="48" height="48" alt="Mikuchin" />
      <div><h1>Mikuchin</h1><p>NATIVE STACK <span class="dot-sep">/</span> DEVELOPMENT</p></div></div>
      ${badge(phase)}
    </header>
    <main>
      <section class="overview">
        <div class="section-kicker">官方 PolyStrata · 统一 Gateway</div>
        <h2>${s?.gateway_ready ? "原生服务已就绪" : phase === "stopping" ? "正在安全释放资源" : phase === "error" ? "服务启动失败" : "正在检查服务状态"}</h2>
        <p class="subtitle">${s?.gateway_ready ? "推理引擎、独立图片 Worker 与网页 Gateway 正常连接。" :
          phase === "stopping" ? "已经发送私有 STOP 指令。活跃付费生图完成前不会强制终止进程。" :
          phase === "error" ? escapeHtml(s?.error || "请查看运行日志。") :
          "模型和服务进程通过专用启动管道管理，正式 15239 不受影响。"}</p>
        <div class="port-pair">
          <div><small>Gateway</small><strong>127.0.0.1:${s?.gateway_port || 15249}</strong></div>
          <div><small>Official Engine</small><strong>127.0.0.1:${s?.official_port || 15240}</strong></div>
        </div>
      </section>
      <section class="panel">
        <div class="section-head"><h3>进程守护</h3><span>PID ${s?.supervisor_pid ?? "—"}</span></div>
        ${child("Official Engine", "official")}
        ${child("Image Worker", "image-worker")}
        ${child("Gateway", "gateway")}
        <p class="panel-note">守护器：${escapeHtml(s?.supervisor_phase || "未知")} · 子进程恢复 ${childRecoveryCount} 次 · ${recentRecovery} · Tauri 重启 ${s?.restarts ?? 0} 次</p>
      </section>
      <section class="model-panel">
        <div><div class="section-kicker">当前模型</div><strong>${escapeHtml(s?.model && s.model !== "—" ? s.model : "等待引擎上线")}</strong></div>
        <span class="small-tag">官方引擎</span>
      </section>
      <section class="panel resource-panel">
        <div class="section-head"><h3>GPU 与图像任务</h3><span>${s?.gateway_ready ? "独立 Native 资源协调" : "等待 Gateway"}</span></div>
        <div class="resource-row"><span>GPU 独占任务</span>
          <strong class="${s?.gpu_busy ? "resource-active" : ""}">${s?.gpu_busy ? escapeHtml(handoffNames[s.gpu_phase] || s.gpu_phase) : "空闲 / 可进行推理"}</strong></div>
        <div class="resource-row"><span>图像队列</span>
          <strong>${imageBusy ? `${s?.image_jobs_running} 项运行中` : "无运行任务"}</strong></div>
        ${imageBusy ? `<p class="resource-phase">${escapeHtml(s?.image_jobs_phase || "等待 Worker 更新状态")}</p>` : ""}
        <div class="resource-row"><span>Image Worker / Real-ESRGAN</span>
          <strong>${s?.image_worker_ready ? "已就绪" : "未就绪"} / ${s?.upscaler_ready ? "可用" : "未配置"}</strong></div>
      </section>
      <div class="actions">
        <button id="open-chat" class="primary" ${!s?.gateway_ready || actionBusy ? "disabled" : ""}>打开聊天网页</button>
        <button id="start" ${actionBusy || s?.stopping || s?.managed ? "disabled" : ""}>启动服务</button>
        <button id="stop" class="danger" ${actionBusy || !s?.managed || s.stopping ? "disabled" : ""}>安全停止</button>
      </div>
      <div class="links">
        <button id="copy-key" ${actionBusy ? "disabled" : ""}>复制 Gateway API Key</button>
        <button id="show-log">查看运行日志</button>
      </div>
    </main>
    <footer><span id="notice">${escapeHtml(notice)}</span><span>v0.3.0</span></footer>`;
  root.querySelector<HTMLButtonElement>("#start")?.addEventListener("click", () => void action("start_service", "已发出启动指令"));
  root.querySelector<HTMLButtonElement>("#stop")?.addEventListener("click", () => void action("stop_service", "已发送安全停止指令"));
  root.querySelector<HTMLButtonElement>("#open-chat")?.addEventListener("click", () => void action("open_chat", "已打开聊天页面"));
  root.querySelector<HTMLButtonElement>("#copy-key")?.addEventListener("click", () => void copyKey());
  root.querySelector<HTMLButtonElement>("#show-log")?.addEventListener("click", () => void showLogs());
}
async function action(name: string, done: string) {
  if (actionBusy) return;
  actionBusy = true;
  notice = "操作执行中…";
  render();
  try {
    await invoke(name);
    notice = done;
  } catch (error) {
    notice = "操作失败：" + String(error);
  } finally {
    actionBusy = false;
    await poll();
  }
}
async function copyKey() {
  try {
    const key = await invoke<string>("reveal_api_key");
    try {
      await navigator.clipboard.writeText(key);
    } catch {
      const el = document.createElement("textarea");
      el.value = key;
      el.style.position = "fixed";
      el.style.opacity = "0";
      document.body.append(el);
      el.select();
      if (!document.execCommand("copy")) throw Error("系统剪贴板不可用");
      el.remove();
    }
    notice = "API Key 已复制，未写入网页地址或日志";
  } catch (error) {
    notice = "复制失败：" + String(error);
  }
  render();
}
async function showLogs() {
  const overlay = document.createElement("div");
  overlay.className = "log-overlay";
  overlay.innerHTML = '<section class="log-dialog" role="dialog" aria-modal="true" aria-label="Native 运行日志"><div class="log-head"><h3>运行日志</h3><button id="close-log">关闭</button></div><pre>读取中…</pre></section>';
  document.body.append(overlay);
  const close = () => overlay.remove();
  overlay.querySelector("#close-log")?.addEventListener("click", close);
  overlay.addEventListener("click", ev => { if (ev.target === overlay) close(); });
  try {
    const log = await invoke<string>("get_log");
    const pre = overlay.querySelector("pre")!;
    pre.textContent = log || "暂时没有日志";
    pre.scrollTop = pre.scrollHeight;
  } catch (e) { overlay.querySelector("pre")!.textContent = String(e); }
}
async function poll() {
  try {
    status = await invoke<Status>("get_status");
  } catch (error) {
    notice = "状态读取失败：" + String(error);
  }
  render();
}
render();
void listen<string>("manager-error", ev => { notice = "守护器：" + ev.payload; void poll(); });
void poll();
setInterval(() => void poll(), 2000);
