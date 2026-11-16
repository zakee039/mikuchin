// The Images page is a separate creative workspace. No selected image profile,
// natural-language prompt, or reference picture is sent to the Chat tool.
"use strict";
(() => {
  const get = (id) => document.getElementById(id);
  const fields = ["positive", "negative", "height", "width", "upscale", "steps", "seed"];
  const ids = Object.fromEntries(fields.map(k => [k, `img-${k}`]));
  const language = () => document.documentElement.lang || "zh-CN";
  const tr = (zh, en, ja) => language() === "en-US" ? en : language() === "ja-JP" ? ja : zh;
  const draftKey = "image-drafts-v2";
  const drafts = store.get(draftKey, {}) || {};
  let catalog = [];
  let loraCatalog = [];
  let chosenLora = store.get("image-lora", "none") || "none";
  let current = store.get("image-profile", "default");
  let sourceModel = null; // non-destructive adaptation suggestion when first switching
  let references = []; // Ordered, tab-local uploads. Never transmitted before Generate.
  let reference = null; // First item for optional vision-to-prompt conversion.
  let working = false;

  const model = () => catalog.find(m => m.id === current) || catalog[0];
  const defaultSteps = (m) => Number(m?.steps || (m?.family === "sdxl" ? 28 : 8));
  function refreshLoras() {
    const select = get("img-lora");
    const supported = model()?.family === "qwen_turbo";
    get("img-lora").closest(".img-lora-field").hidden = !supported;
    select.replaceChildren(new Option(tr("无", "None", "なし"), "none"));
    for (const item of loraCatalog) {
      if (item.family !== "qwen_turbo") continue;
      const opt = new Option(item.name + (item.available ? "" : " · 文件缺失"), item.id);
      opt.disabled = !item.available || !supported;
      select.add(opt);
    }
    if (!supported || !loraCatalog.some(l => l.id === chosenLora && l.available)) chosenLora = "none";
    select.value = chosenLora;
    select.disabled = !supported;
    get("img-lora-hint").textContent = !supported ?
      tr("当前模型不支持 Qwen LoRA。", "Qwen LoRAs are not supported by this model.", "このモデルはQwen LoRAに対応していません。") :
      tr("仅影响本页生图；LoRA 强度固定 1.0，Qwen Turbo 8 步效果可能因 LoRA 而异。",
         "Images page only · LoRA strength 1.0 · Results may vary at Turbo's 8 steps.",
         "画像ページ専用 · LoRA強度 1.0 · Turbo 8ステップでは効果が異なる場合があります。");
    store.set("image-lora", chosenLora);
  }
  const pickFields = () => Object.fromEntries(fields.map(k => [k, get(ids[k]).value]));
  const cleanDraft = d => Object.fromEntries(fields.map(k => [k, typeof d?.[k] === "string" ? d[k] : ""]));
  function saveDraft() {
    if (!current) return;
    drafts[current] = pickFields();
    store.set(draftKey, drafts);
    store.set("image-profile", current);
  }
  function loadDraft(id, origin = null, originName = null) {
    const selected = catalog.find(x => x.id === id);
    const existing = drafts[id];
    const inherited = origin ? cleanDraft(origin) : {};
    const values = existing ? cleanDraft(existing) : {
      positive: inherited.positive || "", negative: inherited.negative || "",
      height: inherited.height || "768", width: inherited.width || "768",
      upscale: selected?.family === "api" ? "off" : inherited.upscale || "auto",
      steps: String(defaultSteps(selected)), seed: inherited.seed || "",
    };
    const dims = selected?.family === "api" ?
      selected.sizes === "square" ? ["1024"] : selected.sizes === "standard" ? ["1024","1536"] : ["384","512","768","1024","1536"] : ["384","512","768","1024"];
    // Older drafts without independent dimensions (or an invalid selection)
    // should not leave either dimension blank and submit an invalid size.
    for (const dim of ["height","width"]) {
      if (!dims.includes(values[dim])) values[dim] = selected?.family === "api" ? "1024" : "768";
    }
    if (!["auto","off","4x"].includes(values.upscale)) values.upscale = "auto";
    if (selected?.family === "api" && (values.upscale !== "4x" || selected.upscale_available === false)) values.upscale = "off";
    if (!values.steps) values.steps = String(defaultSteps(selected));
    for (const k of fields) get(ids[k]).value = values[k];
    for (const dim of ["height","width"]) {
      const select = get(ids[dim]);
      for (const opt of select.options) opt.disabled = !dims.includes(opt.value) || Number(opt.value) > Number(selected?.max_side || 2048);
      if (select.selectedOptions[0]?.disabled) select.value = dims.includes("768") ? "768" : dims[0];
      select.dispatchEvent(new Event("change", {bubbles:true}));
    }
    get("img-upscale").dispatchEvent(new Event("change", {bubbles:true}));
    // If a new model had no draft, keep the current positive/negative verbatim
    // until the user explicitly requests re-adaptation.
    sourceModel = (!existing && origin && (origin.positive || origin.negative)) ?
      originName || "前一个模型" : null;
    const note = get("img-adapt-note");
    const adapt = get("img-adapt");
    note.hidden = adapt.hidden = !sourceModel;
    if (sourceModel) note.textContent = tr(
      `已保留来自 ${sourceModel} 的 Prompt；可以直接生成，也可以点击「适配当前模型」。旧模型草稿不受影响。`,
      `Prompts retained from ${sourceModel}. You can generate as-is or adapt them to this model. The original draft is intact.`,
      `${sourceModel} のプロンプトを保持しています。そのまま生成するか、このモデル用に最適化できます。元の下書きは変更しません。`);
    if (!existing) saveDraft();
    get("img-negative-hint").hidden = selected?.family === "sdxl" || selected?.family === "api";
    get("img-negative").disabled = selected?.family === "api" && !selected.negative;
    const isApi = selected?.family === "api";
    get("img-upscale").disabled = isApi;
    get("img-upscale").closest(".img-upscale-local-field").hidden = isApi;
    get("img-api-upscale").closest(".img-upscale-api-field").hidden = !isApi;
    get("img-api-upscale").disabled = isApi && selected.upscale_available === false;
    get("img-api-upscale").checked = isApi && values.upscale === "4x";
    get("img-lora-hint").hidden = selected?.family === "api";
    get("img-steps").closest(".img-steps-field").hidden = selected?.family === "api" && !selected.supports_steps;
    get("img-seed").closest(".img-seed-field").hidden = selected?.family === "api" && !selected.seed;
    refreshLoras();
    refreshReferenceHint();
  }
  function selectModel(id) {
    if (id === current) return;
    const old = pickFields();
    const oldName = model()?.name || "前一个模型";
    saveDraft();
    current = id;
    store.set("image-profile", id);
    loadDraft(id, old, oldName);
  }
  async function refresh() {
    const select = get("img-model");
    try {
      const r = await fetch("v1/mikuchin/image-models", {headers: headers(), cache: "no-store"});
      if (!r.ok) throw Error(`HTTP ${r.status}`);
      const data = await r.json();
      if (!Array.isArray(data.models) || !data.models.length) throw Error("No image models configured");
      if (catalog.length) saveDraft();
      catalog = data.models;
      loraCatalog = Array.isArray(data.loras) ? data.loras : [];
      select.replaceChildren();
      for (const item of catalog) {
        const opt = new Option(item.name + (item.available ? "" : " · 文件缺失"), item.id);
        opt.disabled = !item.available;
        select.add(opt);
      }
      const next = catalog.find(m => m.id === current && m.available) || catalog.find(m => m.available);
      select.disabled = !next;
      get("img-go").disabled = !next;
      if (!next) {get("img-hint").textContent = "未发现可用生图模型";return;}
      current = next.id;
      select.value = current;
      loadDraft(current);
      if (!working) get("img-hint").textContent = model()?.family === "api" ? "API 服务已就绪" : "每次仅生成一张图片；生成图像与聊天请求会相互等待。";
    } catch (e) {
      console.warn("Image model list:", e);
      get("img-hint").textContent = "请填写 API 密钥后查看生图模型";
    }
  }

  const referenceMode = () => model()?.reference_mode || "none";
  const activeReferences = () => referenceMode() === "multi" ? references :
    ["single", "img2img", "qwen_edit"].includes(referenceMode()) ? references.slice(0, 1) : [];
  function renderReferences() {
    const container = get("img-ref-preview");
    container.replaceChildren();
    container.hidden = references.length === 0;
    get("img-ref-clear").hidden = references.length === 0;
    const allowed = activeReferences().length;
    references.forEach((item, index) => {
      const tile = document.createElement("div");
      tile.className = "img-ref-tile" + (index >= allowed ? " inactive" : "");
      const image = document.createElement("img");
      image.src = item.objectUrl; image.alt = item.name;
      const badge = document.createElement("span");
      badge.className = "img-ref-count"; badge.textContent = String(index + 1);
      const name = document.createElement("span");
      name.className = "img-ref-name"; name.textContent = item.name;
      const buttons = document.createElement("div");
      buttons.className = "img-ref-buttons";
      const move = document.createElement("button");
      move.type = "button"; move.textContent = index ? "置首" : "首图";
      move.disabled = index === 0;
      move.onclick = () => {
        references.splice(index, 1); references.unshift(item);
        reference = references[0]; refreshReferenceHint();
      };
      const remove = document.createElement("button");
      remove.type = "button"; remove.textContent = "移除";
      remove.onclick = () => {
        URL.revokeObjectURL(item.objectUrl);
        references.splice(index, 1);
        reference = references[0] || null;
        refreshReferenceHint();
      };
      buttons.append(move, remove); tile.append(image, badge, name, buttons); container.append(tile);
    });
  }
  function refreshReferenceHint() {
    const hint = get("img-ref-hint"), btn = get("img-ref-convert");
    const allowed = activeReferences().length;
    hint.textContent = references.length ?
      `已上传 ${references.length} 张 · 当前使用 ${allowed} 张` : "";
    btn.hidden = !reference || allowed > 0 || !health.images;
    btn.disabled = working;
    renderReferences();
  }

  get("img-model").onchange = e => selectModel(e.target.value);
  get("img-api-upscale").onchange = e => {
    get("img-upscale").value = e.target.checked ? "4x" : "off";
    saveDraft();
  };
  get("img-lora").onchange = e => {
    chosenLora = e.target.value;
    store.set("image-lora", chosenLora);
  };
  for (const k of fields) {
    get(ids[k]).addEventListener("input", saveDraft);
    get(ids[k]).addEventListener("change", saveDraft);
  }
  function adjustApiAspect(changed) {
    const chosen = model();
    if (chosen?.family === "api" && chosen.sizes === "standard" &&
        get("img-width").value === "1536" && get("img-height").value === "1536") {
      get(changed === "width" ? "img-height" : "img-width").value = "1024";
      saveDraft();
    }
  }
  get("img-width").addEventListener("change", () => adjustApiAspect("width"));
  get("img-height").addEventListener("change", () => adjustApiAspect("height"));
  get("img-natural").value = store.get("image-natural", "");
  get("img-natural").addEventListener("input", () => store.set("image-natural", get("img-natural").value));

  get("img-ref-file").onchange = async e => {
    const picked = Array.from(e.target.files || []);
    e.target.value = "";
    for (const file of picked.slice(0, Math.max(0, 8 - references.length))) {
      if (!/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > 5 * 1024 * 1024 || file.size < 1) {
        toast("warn", "不支持的参考图", "仅支持小于 5 MB 的 PNG、JPEG 或 WebP。", 4800);
        continue;
      }
      try {
        const url = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(Error("无法读取图片"));
          reader.readAsDataURL(file);
        });
        references.push({url, name: file.name, objectUrl: URL.createObjectURL(file)});
      } catch(err) { toast("error", "图片读取失败", String(err.message || err)); }
    }
    reference = references[0] || null;
    refreshReferenceHint();
  };
  get("img-ref-clear").onclick = () => {
    for (const item of references) URL.revokeObjectURL(item.objectUrl);
    references = []; reference = null; refreshReferenceHint();
  };

  get("img-clear").onclick = () => {
    if (working) return;
    // Reset every editable input/selection, the reference image, and persisted
    // per-model drafts. Already generated results are not deleted.
    for (const key of Object.keys(drafts)) delete drafts[key];
    store.set(draftKey, {});
    get("img-natural").value = "";
    store.set("image-natural", "");
    get("img-ref-clear").click();
    chosenLora = "none";
    store.set("image-lora", "none");
    const first = catalog.find(item => item.available);
    if (first) {
      current = first.id;
      get("img-model").value = current;
      get("img-model").dispatchEvent(new Event("change", {bubbles:true}));
    }
    sourceModel = null;
    loadDraft(current);
    get("img-adapt-note").hidden = get("img-adapt").hidden = true;
    get("img-hint").textContent = "输入描述后可以生成新图片。";
    get("img-natural").focus();
  };

  function parseJSON(text) {
    const raw = String(text || "").replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
    const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
    const candidate = fenced ? fenced[1] : raw.slice(raw.indexOf("{"), raw.lastIndexOf("}") + 1);
    let obj;
    try { obj = JSON.parse(candidate); } catch (e) {throw Error("模型没有返回有效的 Prompt JSON，请重试。");}
    if (!obj || typeof obj.positive !== "string" || typeof obj.negative !== "string" || !obj.positive.trim()) {
      throw Error("模型返回的 Positive/Negative Prompt 不完整，请重试。");
    }
    return {positive: obj.positive.trim().slice(0, 12000), negative: obj.negative.trim().slice(0, 3000)};
  }
  async function askCurrentLLM(content, {tokens = 1000} = {}) {
    const r = await fetch("v1/chat/completions", {
      method: "POST", headers: headers(true),
      body: JSON.stringify({model: health.model || "current", stream: false,
        mikuchin_stateless: true, strata_image_tool: false, strata_mcp: false,
        max_tokens: tokens, reasoning_effort: "none", temperature: 0.25,
        messages: [{role: "user", content}], tool_choice: "none"}),
    });
    const response = await r.json();
    if (!r.ok) throw Error(response.error?.message || `HTTP ${r.status}`);
    const result = response.choices?.[0]?.message?.content;
    const text = typeof result === "string" ? result :
      Array.isArray(result) ? result.filter(p => p.type === "text").map(p => p.text).join("\n") : "";
    if (!text) throw Error("当前大模型没有返回文本；请确认模型已启动且可回答。");
    return text;
  }
  const currentDescription = () => model()?.family === "sdxl" ?
    (current === "animagine-xl-4-opt" ? "Animagine XL anime booru-style English tags" :
      "SDXL Base English descriptive phrases") : "Qwen Image Turbo natural English description";
  async function rewrite({adapt = false} = {}) {
    const natural = get("img-natural").value.trim();
    const previous = pickFields();
    if (!natural && !previous.positive) {toast("warn", "需要描述", "请填写自然语言或 Positive Prompt。");return;}
    if ((previous.positive.trim() || previous.negative.trim()) &&
        !window.confirm("解析会覆盖当前模型的 Positive / Negative Prompt。继续吗？")) return;
    const target = current;
    get("img-parse").disabled = get("img-adapt").disabled = true;
    get("img-hint").textContent = "正在调用当前大模型解析 Prompt…";
    try {
      const instructions = `You are a text-to-image prompt editor. Convert the user's creative intent into excellent ENGLISH prompts for ${currentDescription()}. Preserve explicit subjects, identities, scene, composition, style and constraints; do not add unrelated details. Output ONLY valid JSON of the form {"positive":"...", "negative":"..."}. Both values must be strings; negative should be concise. Do not explain.\nNatural request:\n${natural || '(no extra natural-language request)'}\nExisting positive:\n${previous.positive}\nExisting negative:\n${previous.negative}`;
      const pair = parseJSON(await askCurrentLLM(instructions));
      if (current !== target) {toast("info", "解析已完成", "已切换模型；旧模型草稿未被更改。");return;}
      get("img-positive").value = pair.positive;
      get("img-negative").value = pair.negative;
      sourceModel = null;
      get("img-adapt-note").hidden = get("img-adapt").hidden = true;
      saveDraft();
      toast("success", "Prompt 已解析", "已填入英文 Positive 和 Negative Prompt。", 3800);
      get("img-hint").textContent = "解析完成，可编辑 Prompt 后生成。";
    } catch (e) {toast("error", "解析失败", String(e.message || e), 6500);}
    finally {get("img-parse").disabled = get("img-adapt").disabled = false;}
  }
  get("img-parse").onclick = () => rewrite();
  get("img-adapt").onclick = () => rewrite({adapt: true});

  get("img-ref-convert").onclick = async () => {
    if (!reference || !health.images) return;
    const target = current;
    const img = reference.url;
    get("img-ref-convert").disabled = true;
    get("img-hint").textContent = "正在用当前大模型识别参考图…";
    try {
      const content = [{type: "text", text: `Describe the attached reference image as an ENGLISH positive image-generation prompt for ${currentDescription()}. Mention its visible subjects, colors, composition and style accurately. Do not invent identities or unrelated elements. Output one concise English prompt only, not Markdown or JSON.`},
        {type: "image_url", image_url: {url: img}}];
      const result = (await askCurrentLLM(content, {tokens: 420})).trim();
      if (target !== current || reference?.url !== img) {toast("info", "参考图解析完成", "当前模型或图片已经改变，未自动写入草稿。");return;}
      if (!result || result.length > 2500) throw Error("视觉模型返回了无效的图片描述。");
      const old = get("img-positive").value.trim();
      get("img-positive").value = [old, result].filter(Boolean).join(", ");
      saveDraft();
      toast("success", "已转换参考图", "已追加到 Positive Prompt，原图仍保留。", 4200);
      get("img-hint").textContent = "参考图描述已追加至 Positive Prompt。";
    } catch (e) {toast("error", "参考图转换失败", String(e.message || e), 7500);}
    finally {get("img-ref-convert").disabled = false;}
  };

  function newTaskId() {
    const bytes = new Uint8Array(12);
    if (window.crypto?.getRandomValues) window.crypto.getRandomValues(bytes);
    else for (let i=0; i<bytes.length; i++) bytes[i] = Math.floor(Math.random()*256);
    return "img-" + Array.from(bytes, x => x.toString(16).padStart(2, "0")).join("");
  }
  function formatDuration(ms) {
    const seconds = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(seconds / 60), s = seconds % 60;
    return (m >= 60 ? String(Math.floor(m / 60)).padStart(2, "0") + ":" : "") +
      String(m % 60).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }
  function watchTask(id, start) {
    let stopped = false, querying = false;
    const clock = get("img-elapsed");
    clock.hidden = false;
    function tick() {clock.textContent = formatDuration(performance.now() - start);}
    tick();
    const ticker = setInterval(tick, 500);
    const probe = async () => {
      if (stopped || querying) return;
      querying = true;
      try {
        const res = await fetch("v1/mikuchin/image-task-status?id=" + encodeURIComponent(id),
          {headers: headers(), cache:"no-store"});
        if (!res.ok) return;
        const state = await res.json();
        if (stopped || state.state === "unknown") return;
        let label = state.phase || "正在生成";
        if (state.state === "working" && Number.isInteger(state.step) && state.steps)
          label += " · " + state.step + "/" + state.steps + " 步";
        get("img-hint").textContent = label;
      } catch (err) {
        // Progress is best-effort. The generating request remains authoritative.
      } finally {querying = false;}
    };
    const updater = setInterval(probe, 1000);
    void probe();
    return () => {
      stopped = true;
      clearInterval(ticker);
      clearInterval(updater);
      tick();
    };
  }

  get("img-form").onsubmit = async ev => {
    ev.preventDefault();
    if (working) return;
    const prompt = get("img-positive").value.trim() || get("img-natural").value.trim();
    if (!prompt) {toast("warn", "没有生图描述", "请输入 Positive Prompt，或先使用一键解析。");return;}
    const steps = Number(get("img-steps").value);
    if (!Number.isInteger(steps) || steps < 1 || steps > 100) {toast("warn", "步数错误", "步数应为 1–100 的整数。");return;}
    const selected = model();
    const taskId = newTaskId();
    const body = {prompt, negative_prompt: get("img-negative").value.trim(), steps,
      size: `${get("img-width").value}x${get("img-height").value}`, response_format: "b64_json",
      strata_upscale: get("img-upscale").value, strata_image_profile: current,
      strata_image_task_id: taskId};
    if (chosenLora !== "none" && selected?.family === "qwen_turbo")
      body.strata_lora_id = chosenLora;
    if (get("img-seed").value !== "") body.seed = Number(get("img-seed").value);
    const usableReferences = activeReferences();
    if (usableReferences.length && selected?.family === "api")
      body.strata_reference_images = usableReferences.map(item => item.url);
    else if (usableReferences.length) {
      body.strata_reference_image = usableReferences[0].url;
      if (selected.reference_mode === "img2img") body.strata_denoise_strength = 0.65;
    }
    saveDraft();
    working = true;
    get("img-go").disabled = true;
    const start = performance.now();
    get("img-task-error").textContent = "";
    get("img-task-error").hidden = true;
    get("img-hint").textContent = selected?.family === "api" ? "正在请求 API" : "等待本地生成任务";
    const stopWatching = watchTask(taskId, start);
    try {
      const res = await fetch("v1/images/generations", {method:"POST",headers:headers(true),body:JSON.stringify(body)});
      const j = await res.json();
      if (!res.ok) throw Error(j.error?.message || `HTTP ${res.status}`);
      for (const d of j.data || []) {
        const fig = document.createElement("figure");
        const pic = document.createElement("img");
        pic.src = "data:image/png;base64," + d.b64_json;
        pic.alt = prompt;
        const caption = document.createElement("figcaption");
        const loraName = loraCatalog.find(l => l.id === j.strata?.lora_id)?.name;
        caption.textContent = `${j.model || selected?.name}, ${j.size}` +
          (selected?.family === "api" && !selected.supports_steps ? "" : `, ${steps} steps`) +
          (d.seed == null ? "" : `, ${ui("Seed")} ${d.seed}`) +
          `, ${((performance.now() - start)/1000).toFixed(0)} s` +
          (loraName ? ` · LoRA: ${loraName}` : "") +
          (j.strata?.upscale_applied ? " · Anime 4×" : "") + `: ${prompt}`;
        const originalFile = (j.strata?.upscale_original_files || [])[0];
        if (originalFile && /^[a-f0-9]{32}\.png$/.test(originalFile)) {
          const link = document.createElement("a");
          link.href = "v1/images/files/" + originalFile;
          link.textContent = ` · ${ui("Original image")}`;
          link.target = "_blank"; link.rel = "noopener noreferrer";
          caption.append(link);
        }
        fig.append(pic, caption);
        get("img-results").prepend(fig);
      }
      const upscaleError = j.strata?.upscale_error;
      get("img-hint").textContent = upscaleError ? "生成成功 · 超分未完成（已保留原图）" : "生成完成";
      if (upscaleError) {
        get("img-task-error").textContent = String(upscaleError);
        get("img-task-error").hidden = false;
      }
    } catch (e) {
      const detail = String(e.message || e);
      get("img-hint").textContent = "生成失败";
      get("img-task-error").textContent = detail;
      get("img-task-error").hidden = false;
      toast("error", "生成失败", detail, 9000);
    }
    finally {
      stopWatching();
      working = false;
      get("img-go").disabled = !catalog.find(m => m.id === current)?.available;
      refreshReferenceHint();
    }
  };
  window.MikuchinImageStudio = {refresh, parseJSON};
  if (location.hash === "#images") void refresh();
})();
