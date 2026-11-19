// Mikuchin server-owned external image services. The browser never stores API keys.
"use strict";
(() => {
  const get = id => document.getElementById(id);
  const url = "v1/mikuchin/image-api-services";
  let services = [];
  let editing = null;
  let busy = false;
  let discovering = false;
  let discoverySeq = 0;

  const request = async (body = null) => {
    const opts = {headers: headers(!!body), cache:"no-store"};
    if (body) {opts.method = "POST"; opts.body = JSON.stringify(body);}
    const r = await fetch(url, opts);
    let data;
    try { data = await r.json(); } catch {data = {};}
    if (!r.ok) throw Error(data.error?.message || "HTTP " + r.status);
    return data;
  };

  function refreshModels() {
    void window.MikuchinImageStudio?.refresh();
    if (typeof refreshChatImageModels === "function") void refreshChatImageModels();
  }

  function render() {
    const parent = get("mk-api-list");
    parent.replaceChildren();
    if (!services.length) {
      const empty = document.createElement("p");
      empty.className = "muted small";
      empty.textContent = "暂无 API 服务";
      parent.append(empty);
      return;
    }
    for (const item of services) {
      const row = document.createElement("div");
      row.className = "mk-api-item";
      const detail = document.createElement("div");
      detail.className = "mk-api-item-info";
      const name = document.createElement("strong");
      name.textContent = item.name;
      const meta = document.createElement("span");
      meta.className = "muted small";
      meta.textContent = item.model + (item.proxy ? " · 代理" : " · 直连") +
        " · 并发 " + (item.concurrency || 1) +
        " · 连接 " + (item.connect_timeout_seconds || 15) + "s" +
        " / 读取 " + (item.timeout_seconds || 240) + "s" +
        (item.has_key ? "" : " · 未配置密钥");
      detail.append(name, meta);
      const edit = document.createElement("button");
      edit.type = "button";edit.className="st-btn st-btn--secondary";edit.textContent="编辑";
      edit.addEventListener("click", () => open(item));
      const del = document.createElement("button");
      del.type = "button";del.className="st-btn st-btn--secondary";del.textContent="删除";
      del.addEventListener("click", () => remove(item));
      row.append(detail,edit,del);
      parent.append(row);
    }
  }

  async function refresh() {
    try {
      services = (await request()).services || [];
      render();
    } catch (e) {
      get("mk-api-list").textContent = "无法读取 API 服务：" + (e.message || e);
    }
  }

  function proxyControls() {
    const enabled = get("mk-api-proxy").checked;
    get("mk-api-proxy-wrap").hidden = !enabled;
    get("mk-api-proxy-url").required = enabled;
  }
  get("mk-api-proxy").addEventListener("change", () => {proxyControls(); resetDiscovery();});

  function open(item = null) {
    resetDiscovery();
    editing = item?.id || null;
    get("mk-api-title").textContent = item ? "编辑 API 服务" : "添加 API 服务";
    get("mk-api-name").value = item?.name || "";
    get("mk-api-url").value = item?.base_url || "";
    get("mk-api-model").value = item?.model || "";
    get("mk-api-key").value = "";
    get("mk-api-key").required = !item?.has_key;
    get("mk-api-key").placeholder = item?.has_key ? "留空则保留原密钥" : "输入 API Key";
    get("mk-api-proxy").checked = !!item?.proxy;
    get("mk-api-proxy-url").value = item?.proxy_url || "socks5h://127.0.0.1:7897";
    proxyControls();
    get("mk-api-negative").checked = !!item?.negative;
    get("mk-api-seed").checked = !!item?.seed;
    get("mk-api-steps").checked = !!item?.steps;
    get("mk-api-sizes").value = item?.sizes || "standard";
    get("mk-api-concurrency").value = String(item?.concurrency || 1);
    get("mk-api-connect-timeout").value = String(item?.connect_timeout_seconds || 15);
    get("mk-api-timeout").value = String(item?.timeout_seconds || 240);
    for (const radio of document.querySelectorAll('input[name="mk-api-ref"]'))
      radio.checked = radio.value === (item?.reference_mode || "multi");
    get("mk-api-backdrop").hidden = false;
    get("mk-api-name").focus();
  }
  function close() {
    if (busy) return;
    resetDiscovery();
    get("mk-api-backdrop").hidden = true;
    editing = null;
  }
  async function remove(item) {
    if (!confirm("删除 API 服务「"+item.name+"」？")) return;
    try {
      await request({action:"delete", id:item.id});
      await refresh();
      refreshModels();
      toast("success","服务已删除");
    } catch(e) {toast("error","删除失败",String(e.message||e));}
  }

  function resetDiscovery() {
    discoverySeq++;
    const options = get("mk-api-model-list");
    options.hidden = true;
    options.replaceChildren();
    get("mk-api-discover-status").hidden = true;
    get("mk-api-discover").disabled = false;
    get("mk-api-discover").textContent = "获取模型";
    discovering = false;
  }

  for (const id of ["mk-api-url", "mk-api-key", "mk-api-proxy-url"]) {
    get(id).addEventListener("input", resetDiscovery);
  }
  get("mk-api-model-list").addEventListener("change", e => {
    if (e.target.value) get("mk-api-model").value = e.target.value;
  });
  get("mk-api-discover").addEventListener("click", async () => {
    if (discovering || busy) return;
    const base = get("mk-api-url");
    if (!base.value.trim()) {
      base.focus();
      toast("warn", "请先填写 Base URL");
      return;
    }
    if (get("mk-api-proxy").checked && !get("mk-api-proxy-url").value.trim()) {
      get("mk-api-proxy-url").focus();
      toast("warn", "请先填写代理地址");
      return;
    }
    const seq = ++discoverySeq;
    discovering = true;
    get("mk-api-discover").disabled = true;
    get("mk-api-discover").textContent = "查询中…";
    const status = get("mk-api-discover-status");
    const picker = get("mk-api-model-list");
    picker.hidden = true;
    status.hidden = true;
    try {
      const answer = await request({action:"discover", connection:{
        id: editing, base_url: base.value.trim(),
        api_key: get("mk-api-key").value,
        proxy: get("mk-api-proxy").checked,
        proxy_url: get("mk-api-proxy-url").value.trim()
      }});
      if (seq !== discoverySeq) return;
      const matches = Array.isArray(answer.models) ? answer.models : [];
      picker.replaceChildren();
      if (!matches.length) {
        status.textContent = "未返回可选模型，请手动填写 ID";
        status.hidden = false;
        return;
      }
      picker.add(new Option("选择探测到的模型…", ""));
      for (const [likely, heading] of [[true,"可能支持生图"],[false,"其他模型（未验证生图能力）"]]) {
        const group = document.createElement("optgroup");
        group.label = heading;
        for (const item of matches.filter(m => Boolean(m.image_likely) === likely)) {
          if (typeof item.id !== "string" || !item.id) continue;
          group.append(new Option(item.name && item.name !== item.id ?
            item.name + " (" + item.id + ")" : item.id, item.id));
        }
        if (group.children.length) picker.append(group);
      }
      picker.hidden = false;
      picker.value = "";
      const existing = get("mk-api-model").value;
      if (existing && matches.some(m => m.id === existing)) picker.value = existing;
      status.textContent = "找到 " + answer.total + " 个模型，仅按名称初筛；请确认支持生图" +
        (answer.truncated ? "（列表已截断）" : "");
      status.hidden = false;
    } catch (err) {
      if (seq !== discoverySeq) return;
      status.textContent = "无法获取模型列表，请手动填写模型 ID";
      status.hidden = false;
      toast("warn","模型探测失败",String(err.message || err),5200);
    } finally {
      if (seq === discoverySeq) {
        discovering = false;
        get("mk-api-discover").disabled = false;
        get("mk-api-discover").textContent = "获取模型";
      }
    }
  });

  get("mk-api-add").addEventListener("click",() => open());
  get("mk-api-close").addEventListener("click",close);
  get("mk-api-cancel").addEventListener("click",close);
  get("mk-api-backdrop").addEventListener("click",e => {
    if (e.target === get("mk-api-backdrop")) close();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !get("mk-api-backdrop").hidden) close();
  });
  get("mk-api-form").addEventListener("submit", async e => {
    e.preventDefault();
    if (busy) return;
    busy = true;
    get("mk-api-save").disabled = true;
    const mode = document.querySelector('input[name="mk-api-ref"]:checked')?.value || "none";
    const service = {
      id: editing, name: get("mk-api-name").value.trim(),
      base_url: get("mk-api-url").value.trim(),
      model: get("mk-api-model").value.trim(),
      api_key: get("mk-api-key").value,
      proxy: get("mk-api-proxy").checked,
      proxy_url: get("mk-api-proxy-url").value.trim(),
      reference_mode: mode,
      negative: get("mk-api-negative").checked,
      seed: get("mk-api-seed").checked, steps: get("mk-api-steps").checked,
      sizes: get("mk-api-sizes").value,
      concurrency: Number(get("mk-api-concurrency").value),
      connect_timeout_seconds: Number(get("mk-api-connect-timeout").value),
      timeout_seconds: Number(get("mk-api-timeout").value),
    };
    if (!service.id) delete service.id;
    try {
      await request({action:"save",service});
      get("mk-api-backdrop").hidden = true;
      editing = null;
      await refresh();
      refreshModels();
      toast("success","API 服务已保存");
    } catch(err) {
      toast("error","保存失败",String(err.message||err),6000);
    } finally {
      busy = false;
      get("mk-api-save").disabled = false;
    }
  });
  window.MikuchinImageApi = {refresh};
  if (location.hash === "#settings") void refresh();
})();
