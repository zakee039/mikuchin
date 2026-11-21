// The Images page is a separate creative workspace. No selected image profile,
// natural-language prompt, or reference picture is sent to the Chat tool.
"use strict";
(() => {
  const get = (id) => document.getElementById(id);
  const imageSizes = window.MikuchinImageSizes;
  const fields = ["positive", "negative", "width", "height", "standard_size", "custom_width", "custom_height", "upscale", "steps", "seed"];
  const ids = Object.fromEntries(fields.map(k => [k, `img-${k.replaceAll("_", "-")}`]));
  const standardPicker = get("img-standard-size");
  for (const item of imageSizes.standard)
    standardPicker.add(new Option(`${item.size.replace("x", "×")} · ${item.ratio} · ${item.note}`, item.size));
  function currentSize() {
    return imageSizes.dimensions(model(), {
      width:get("img-width").value, height:get("img-height").value,
      standard:get("img-standard-size").value,
      customWidth:get("img-custom-width").value, customHeight:get("img-custom-height").value,
    });
  }
  const language = () => document.documentElement.lang || "zh-CN";
  const tr = (zh, en, ja) => language() === "en-US" ? en : language() === "ja-JP" ? ja : zh;
  const draftKey = "image-drafts-v2";
  const drafts = store.get(draftKey, {}) || {};
  let catalog = [];
  let loraCatalog = [];
  let chosenLora = store.get("image-lora", "none") || "none";
  let current = store.get("image-profile", "default");
  let sourceModel = null; // non-destructive adaptation suggestion when first switching
  let references = []; // Ordered uploads and server-backed reference assets.
  let reference = null; // First item for optional vision-to-prompt conversion.
  let working = false;
  const taskRecords = new Map();
  const taskRows = new Map();
  const taskNsfw = new Map();
  const taskNsfwPending = new Set();
  let jobListLoading = false;
  let openedTaskImage = "";
  let openedTaskRevealed = false;
  let restoredImageJobs = false;
  let draftReady = false, suspendDraft = false, initialDraftRestored = false;
  let currentDraftId = null, draftTimer = null;
  let provisionalDraftId = null, formRevision = 0;
  let draftWrites = Promise.resolve();
  const activeDraftKey = "mikuchin-image-active-draft-v1";

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
    if (draftReady && !suspendDraft) {
      initialDraftRestored = true;
      formRevision++;
      scheduleDraftSave();
    }
  }
  function loadDraft(id, origin = null, originName = null) {
    const selected = catalog.find(x => x.id === id);
    const existing = drafts[id];
    const inherited = origin ? cleanDraft(origin) : {};
    const values = existing ? cleanDraft(existing) : {
      positive: inherited.positive || "", negative: inherited.negative || "",
      height: inherited.height || "768", width: inherited.width || "768",
      standard_size: inherited.standard_size || "", custom_width: inherited.custom_width || "",
      custom_height: inherited.custom_height || "",
      upscale: selected?.family === "api" ? "off" : inherited.upscale || "auto",
      steps: String(defaultSteps(selected)), seed: inherited.seed || "",
    };
    const pack = imageSizes.pack(selected);
    const dims = pack === "square" ? ["1024"] : imageSizes.local.map(String);
    // Preserve the original persisted WIDTHxHEIGHT before narrowing the
    // now-hidden local dropdowns. Older API drafts used those two fields.
    const legacySize = `${values.width}x${values.height}`;
    const previousWidth = values.width, previousHeight = values.height;
    // Older drafts without independent dimensions (or an invalid selection)
    // should not leave either dimension blank and submit an invalid size.
    for (const dim of ["height","width"]) {
      if (!dims.includes(values[dim])) values[dim] = pack === "square" || pack === "standard" || pack === "custom" ? "1024" : "768";
    }
    if (!imageSizes.isStandard(values.standard_size))
      values.standard_size = imageSizes.isStandard(legacySize) ? legacySize : "1024x1024";
    values.custom_width = String(imageSizes.nearest16(values.custom_width || previousWidth || inherited.width || 1024));
    values.custom_height = String(imageSizes.nearest16(values.custom_height || previousHeight || inherited.height || 1024));
    if (!["auto","off","4x"].includes(values.upscale)) values.upscale = "auto";
    if (selected?.family === "api" && (values.upscale !== "4x" || selected.upscale_available === false)) values.upscale = "off";
    if (!values.steps) values.steps = String(defaultSteps(selected));
    for (const k of fields) get(ids[k]).value = values[k];
    for (const dim of ["width","height"])
      get(`img-${dim}`).closest(`.img-${dim}-field`).hidden = pack === "standard" || pack === "custom";
    get("img-standard-size").closest(".img-standard-field").hidden = pack !== "standard";
    for (const dim of ["width","height"])
      get(`img-custom-${dim}`).closest(".img-custom-field").hidden = pack !== "custom";
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
    suspendDraft = true;
    saveDraft();
    current = id;
    store.set("image-profile", id);
    loadDraft(id, old, oldName);
    suspendDraft = false;
    saveDraft();
  }
  async function refresh() {
    const select = get("img-model");
    if (!restoredImageJobs) {
      restoredImageJobs = true;
      void refreshImageJobs();
    }
    try {
      const r = await fetch("v1/mikuchin/image-models", {headers: headers(), cache: "no-store"});
      if (!r.ok) throw Error(`HTTP ${r.status}`);
      const data = await r.json();
      if (!Array.isArray(data.models) || !data.models.length) throw Error("No image models configured");
      if (catalog.length) { suspendDraft = true;saveDraft();suspendDraft = false; }
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
      suspendDraft = true;
      loadDraft(current);
      suspendDraft = false;
      draftReady = true;
      void tryRestoreDraft();
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
        reference = references[0]; refreshReferenceHint(); saveDraft();
      };
      const remove = document.createElement("button");
      remove.type = "button"; remove.textContent = "移除";
      remove.onclick = () => {
        URL.revokeObjectURL(item.objectUrl);
        references.splice(index, 1);
        reference = references[0] || null;
        refreshReferenceHint(); saveDraft();
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
    saveDraft();
  };
  for (const k of fields) {
    get(ids[k]).addEventListener("input", saveDraft);
    get(ids[k]).addEventListener("change", saveDraft);
  }
  for (const dim of ["width","height"]) {
    const input = get(`img-custom-${dim}`);
    const snap = () => {
      const corrected = String(imageSizes.nearest16(input.value));
      if (input.value !== corrected) {input.value = corrected; saveDraft();}
    };
    input.addEventListener("change", snap);
    input.addEventListener("blur", snap);
  }
  get("img-natural").value = store.get("image-natural", "");
  get("img-natural").addEventListener("input", () => {
    store.set("image-natural", get("img-natural").value); saveDraft();
  });

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
    refreshReferenceHint(); saveDraft();
  };
  get("img-ref-clear").onclick = () => {
    for (const item of references) URL.revokeObjectURL(item.objectUrl);
    references = []; reference = null; refreshReferenceHint(); saveDraft();
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

  function formatDuration(ms) {
    const seconds = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(seconds / 60), s = seconds % 60;
    return (m >= 60 ? String(Math.floor(m / 60)).padStart(2, "0") + ":" : "") +
      String(m % 60).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }
  function taskElapsed(job, now = Date.now()) {
    if (!Number.isFinite(job.started_at) || job.state === "draft") return "";
    // started_at is assigned by the Worker when generation actually starts;
    // time spent queued or preparing a draft must not be counted.
    const end = activeJob(job) ? now :
      Number.isFinite(job.finished_at) ? job.finished_at * 1000 : now;
    const duration = formatDuration(end - job.started_at * 1000);
    return duration.split(":").length === 2 ? "00:" + duration : duration;
  }
  function tickTaskTimers(now = Date.now()) {
    // This clock runs independently of polling/network response latency.
    // Update ONLY timer text; leave thumbnails, inputs and focus untouched.
    for (const [id, row] of taskRows) {
      if (!row.isConnected) continue;
      const job = taskRecords.get(id);
      if (!job || !activeJob(job)) continue;
      const clock = row.querySelector(".img-job-timer");
      if (clock && Number.isFinite(job.started_at) && job.phase !== "排队等待执行")
        clock.textContent = "已运行 " + taskElapsed(job, now);
    }
  }
  // One server-side task equals one compact row; images appear only at right.
  // Task records remain in SQLite even after this tab or device disconnects.
  const activeJob = job => ["running", "submitting"].includes(job.state);
  const validImageId = id => /^[a-f0-9]{32}$/.test(id || "");

  function formRequest() {
    const positive = get("img-positive").value;
    const natural = get("img-natural").value;
    const selected = model();
    const request = {
      prompt: positive.trim() || natural.trim(),
      positive_prompt: positive,
      natural_prompt: natural,
      negative_prompt: get("img-negative").value,
      size: currentSize().size,
      steps: Number(get("img-steps").value) || defaultSteps(selected),
      strata_upscale: get("img-upscale").value,
      strata_image_profile: current,
      strata_reference_mode: referenceMode(),
      response_format:"url",
      strata_reference_assets: activeReferences().map(item => item.assetId ?
        {id:item.assetId,name:item.name} : {data_url:item.url,name:item.name}),
    };
    if (chosenLora !== "none" && selected?.family === "qwen_turbo")
      request.strata_lora_id = chosenLora;
    if (get("img-seed").value !== "") request.seed = Number(get("img-seed").value);
    if (referenceMode() === "img2img") request.strata_denoise_strength = 0.65;
    return request;
  }

  async function jobCommand(body) {
    const response = await fetch("v1/mikuchin/image-jobs", {
      method:"POST", headers:headers(true), body:JSON.stringify(body), cache:"no-store"});
    const data = await response.json();
    if (!response.ok) throw Error(data.error?.message || `HTTP ${response.status}`);
    return data;
  }

  function scheduleDraftSave() {
    // Show a new draft immediately, before its debounced disk write finishes.
    if (!currentDraftId && !provisionalDraftId) {
      provisionalDraftId = "pending-draft-" + Date.now();
      const now = Date.now()/1000;
      taskRecords.set(provisionalDraftId, {id:provisionalDraftId,kind:"generate",
        state:"draft",phase:"正在保存草稿…",created:now,updated:now,
        prompt_summary:(get("img-positive").value || get("img-natural").value).slice(0,180),
        profile_id:current,requested_size:currentSize().size});
      renderTaskRows();
    }
    if (draftTimer !== null) clearTimeout(draftTimer);
    draftTimer = setTimeout(() => {
      draftTimer = null;
      void flushDraftSave().catch(() => {});
    }, 280);
  }

  async function flushDraftSave() {
    if (draftTimer !== null) {clearTimeout(draftTimer);draftTimer=null;}
    if (!draftReady || suspendDraft) return draftWrites;
    const snapshot = formRequest();
    const capturedRefs = references.slice();
    draftWrites = draftWrites.catch(() => {}).then(async () => {
      const ident = currentDraftId;
      const saved = await jobCommand(ident ?
        {action:"save_draft",id:ident,request:snapshot} : {action:"draft",request:snapshot});
      if (currentDraftId === ident) {
        currentDraftId = saved.id;
        store.set(activeDraftKey, saved.id);
      }
      if (provisionalDraftId) {
        taskRecords.delete(provisionalDraftId);
        taskRows.delete(provisionalDraftId);
        provisionalDraftId=null;
      }
      const ids = saved.request?.strata_reference_assets || [];
      for (let i=0;i<capturedRefs.length;i++) {
        if (references.includes(capturedRefs[i]) && ids[i]?.id)
          capturedRefs[i].assetId = ids[i].id;
      }
      taskRecords.set(saved.id,saved);
      renderTaskRows();
      return saved;
    });
    try {return await draftWrites;}
    catch (err) {
      get("img-hint").textContent = "草稿保存失败：" + String(err.message || err);
      toast("error","草稿未保存到桌面",String(err.message || err));
      throw err;
    }
  }

  function resetReferenceObjects() {
    for (const item of references) if (item.objectUrl) URL.revokeObjectURL(item.objectUrl);
    references = [];
    reference = null;
  }

  async function referenceFromAsset(asset) {
    const response = await fetch("v1/mikuchin/image-job-reference/" +
      encodeURIComponent(asset.id), {headers:headers(),cache:"no-store"});
    if (!response.ok) throw Error("参考图不可用：" + asset.name);
    const blob = await response.blob();
    const url = await new Promise((resolve,reject) => {
      const reader = new FileReader();
      reader.onload=()=>resolve(String(reader.result));
      reader.onerror=()=>reject(Error("参考图读取失败"));
      reader.readAsDataURL(blob);
    });
    return {assetId:asset.id,name:asset.name,url,objectUrl:URL.createObjectURL(blob)};
  }

  async function loadTaskForm(job, restoreFromServer=true) {
    const req = job.request || {};
    const revisionAtStart = formRevision;
    // Fetch every reference before replacing the current form. A failed asset
    // must not silently produce a partial draft that can be submitted.
    const fetched = await Promise.allSettled((req.strata_reference_assets || []).map(referenceFromAsset));
    const loaded = fetched.filter(item => item.status === "fulfilled").map(item => item.value);
    const failure = fetched.find(item => item.status === "rejected");
    if (failure) {
      for (const item of loaded) URL.revokeObjectURL(item.objectUrl);
      throw failure.reason;
    }
    if (formRevision !== revisionAtStart) {
      for (const item of loaded) URL.revokeObjectURL(item.objectUrl);
      if (restoreFromServer) throw Error("恢复任务期间表单内容发生变化，请重新点击编辑");
      return;
    }
    suspendDraft=true;
    try {
      const target = catalog.find(x => x.id === req.strata_image_profile);
      if (!target) throw Error("原生图服务已不在当前配置中，无法完整恢复该任务");
      current=target.id;
      get("img-model").value=current;
      const match = /^(\d+)x(\d+)$/.exec(req.size || "");
      drafts[current] = {
        positive:req.positive_prompt ?? req.prompt ?? "", negative:req.negative_prompt || "",
        width:match?.[1] || "768", height:match?.[2] || "768",
        standard_size:imageSizes.isStandard(req.size) ? req.size : "1024x1024",
        custom_width:match?.[1] || "1024", custom_height:match?.[2] || "1024",
        upscale:req.strata_upscale || "off",steps:String(req.steps ?? defaultSteps(model())),
        seed:req.seed == null ? "" : String(req.seed),
      };
      chosenLora=req.strata_lora_id || "none";
      loadDraft(current);
      get("img-natural").value=req.natural_prompt || "";
      store.set("image-natural",get("img-natural").value);
      resetReferenceObjects();
      references=loaded;
      reference=references[0] || null;
      refreshReferenceHint();
      store.set(draftKey,drafts);
      store.set("image-profile",current);
      store.set("image-lora",chosenLora);
      currentDraftId=job.id;
      provisionalDraftId=null;
      store.set(activeDraftKey,job.id);
      initialDraftRestored=true;
    } catch (error) {
      for (const item of loaded) URL.revokeObjectURL(item.objectUrl);
      throw error;
    } finally {suspendDraft=false;}
    if (restoreFromServer) {
      get("img-form").scrollIntoView({behavior:"smooth",block:"start"});
      get("img-positive").focus();
    }
  }

  async function tryRestoreDraft() {
    if (initialDraftRestored || !draftReady || !restoredImageJobs || !taskRecords.size) return;
    initialDraftRestored=true;
    const savedId=store.get(activeDraftKey, "");
    const draftsOnly=[...taskRecords.values()].filter(t => t.kind==="generate" && t.state==="draft");
    draftsOnly.sort((a,b)=>(b.updated||0)-(a.updated||0));
    const latest=draftsOnly.find(t=>t.id===savedId) || draftsOnly[0];
    if (!latest) return;
    try {await loadTaskForm(latest,false);}
    catch (error) {get("img-hint").textContent = "恢复草稿失败："+String(error.message||error);}
  }

  function part(tag, cls, value = "") {
    const node = document.createElement(tag);
    node.className = cls;
    node.textContent = value;
    return node;
  }
  function rowFor(job) {
    if (taskRows.has(job.id)) return taskRows.get(job.id);
    const row = part("article", "img-job-item");
    row.dataset.jobId = job.id;
    const info = part("div", "img-job-info");
    const top = part("div", "img-job-top");
    top.append(part("span", "img-job-state"), part("span", "img-job-meta"),
      part("span", "img-job-timer"));
    info.append(top, part("div", "img-job-prompt"), part("div", "img-job-phase"),
      part("div", "img-job-ops"));
    row.append(info, part("div", "img-job-output", "尚无图片"));
    taskRows.set(job.id, row);
    return row;
  }
  function inspectNsfw(imageId) {
    if (taskNsfw.has(imageId) || taskNsfwPending.has(imageId)) return;
    taskNsfwPending.add(imageId);
    fetch("v1/mikuchin/gallery/item?id=" + encodeURIComponent(imageId),
      {headers: headers(), cache:"no-store"}).then(async response => {
      if (!response.ok) throw Error("gallery metadata unavailable");
      const item = await response.json();
      taskNsfw.set(imageId, Boolean(item.nsfw));
      if (!get("img-job-viewer").hidden && openedTaskImage === imageId) {
        const hide = Boolean(item.nsfw) && !get("gallery-show-nsfw").checked && !openedTaskRevealed;
        get("img-job-viewer-image").classList.toggle("img-job-nsfw", hide);
        get("img-job-viewer-spoiler").hidden = !hide;
      }
      renderTaskRows();
    }).catch(() => { /* Unknown NSFW status: cover until metadata is available. */ })
      .finally(() => taskNsfwPending.delete(imageId));
  }
  function showTaskImage(imageId) {
    if (!validImageId(imageId)) return;
    openedTaskImage = imageId;
    openedTaskRevealed = false;
    const img = get("img-job-viewer-image");
    void window.MikuchinSecureImages.load(img,"v1/images/files/" + imageId + ".png")
      .catch(() => toast("error","图片加载失败","请检查客户端鉴权和服务状态",5000));
    const unmasked = taskNsfw.has(imageId) &&
      (!taskNsfw.get(imageId) || get("gallery-show-nsfw").checked);
    img.classList.toggle("img-job-nsfw", !unmasked);
    get("img-job-viewer-spoiler").hidden = unmasked;
    get("img-job-viewer").hidden = false;
    get("img-job-viewer-close").focus();
    inspectNsfw(imageId);
  }
  function closeTaskImage() {
    get("img-job-viewer").hidden = true;
    window.MikuchinSecureImages.release(get("img-job-viewer-image"));
    openedTaskImage = "";
    openedTaskRevealed = false;
  }
  get("img-job-viewer-close").addEventListener("click", closeTaskImage);
  get("img-job-viewer").addEventListener("click", event => {
    if (event.target.id === "img-job-viewer") closeTaskImage();
  });
  get("img-job-viewer-reveal").addEventListener("click", () => {
    openedTaskRevealed = true;
    get("img-job-viewer-spoiler").hidden = true;
    get("img-job-viewer-image").classList.remove("img-job-nsfw");
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !get("img-job-viewer").hidden) {
      event.preventDefault(); closeTaskImage();
    }
  });

  function taskAction(label, handler) {
    const button = part("button", "img-job-action", label);
    button.type = "button";
    button.addEventListener("click", handler);
    return button;
  }

  async function editTask(job) {
    // Draft keeps its ID and moves to top; all other statuses create a new draft.
    try {
      if (draftTimer !== null) await flushDraftSave();
      else await draftWrites;
      const copy = await jobCommand(job.state === "draft" ?
        {action:"draft",id:job.id} : {action:"draft",copy_id:job.id});
      await loadTaskForm(copy);
      taskRecords.set(copy.id,copy);
      renderTaskRows();
      if (copy.legacy_incomplete)
        toast("warn","历史任务参数不完整","此旧任务没有完整参数与参考图，仅复制了可恢复的信息。",7500);
    } catch (error) {toast("error","编辑任务失败",String(error.message||error),7500);}
  }

  async function retryTask(job) {
    // A new running task; only a failed source is removed after server success.
    try {
      const created = await jobCommand({action:"retry",id:job.id});
      if (created.deleted_original_id) {
        taskRecords.delete(created.deleted_original_id);
        taskRows.delete(created.deleted_original_id);
      }
      taskRecords.set(created.id,created);
      renderTaskRows();
      toast("success","新任务已提交",created.deleted_original_id ?
        "原失败任务记录已删除。" : "原成功任务保持不变。",4200);
      void refreshImageJobs();
    } catch (error) {toast("error","重试未提交",String(error.message||error),8500);}
  }

  async function copyTaskError(message) {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(message);
      else {
        const input = document.createElement("textarea");
        input.value = message;
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.append(input);
        input.select();
        const copied = document.execCommand("copy");
        input.remove();
        if (!copied) throw Error("copy unavailable");
      }
      toast("success", "已复制错误信息");
    } catch { toast("warn", "复制失败", "请长按任务错误文字手动复制。"); }
  }

  async function changeTaskRecords(action, id = null) {
    const payload = action === "delete" ? {action,id} : {action};
    const res = await fetch("v1/mikuchin/image-jobs", {
      method:"POST",headers:headers(true),body:JSON.stringify(payload)});
    const data = await res.json();
    if (!res.ok) throw Error(data.error?.message || `HTTP ${res.status}`);
    if (action === "delete" && id) {
      taskRecords.delete(id);
      taskRows.delete(id);
    } else if (action === "clear_completed") {
      for (const [jobId, job] of taskRecords) {
        if (job.kind === "generate" && ["success","failed"].includes(job.state)) {
          taskRecords.delete(jobId);
          taskRows.delete(jobId);
        }
      }
    }
    renderTaskRows();
    await refreshImageJobs();
    return data.deleted || 0;
  }

  function updateTaskActions(row, job) {
    const actions = row.querySelector(".img-job-ops");
    if (actions.dataset.state === job.state) return;
    actions.dataset.state = job.state;
    actions.replaceChildren();
    // Edit is always shown. Draft edits touch the same task; other edits copy.
    actions.append(taskAction("编辑", () => void editTask(job)));
    if (["success", "failed"].includes(job.state))
      actions.append(taskAction("重试", () => void retryTask(job)));
    if (job.state === "failed" && job.error)
      actions.append(taskAction("复制错误", () => void copyTaskError(job.error)));
    if (activeJob(job)) return;
    actions.append(taskAction("删除记录", async () => {
      if (!confirm("仅删除这条任务记录，生成图片仍保留在画廊。继续吗？")) return;
      try {
        await changeTaskRecords("delete", job.id);
        if (currentDraftId === job.id) { currentDraftId=null;store.set(activeDraftKey,""); }
        toast("success", "任务记录已删除");
      } catch (error) {toast("error", "删除任务失败", String(error.message || error));}
    }));
  }

  function renderTaskRows() {
    const container = get("img-job-list");
    const allEntries = [...taskRecords.values()]
      .filter(job => job.kind === "generate")
      .sort((a,b) => (b.updated || 0) - (a.updated || 0));
    // No queued/working job may vanish merely because newer requests completed.
    const entries = allEntries.slice(0,100);
    const activeCount = entries.filter(activeJob).length;
    get("img-job-count").textContent = `${entries.length}/100 条 · ${activeCount} 项进行中`;
    const visible = get("img-job-active-only").checked ? entries.filter(activeJob) : entries;
    if (!visible.length) {
      container.replaceChildren(part("p", "muted small",
        entries.length ? "没有进行中的图像任务" : "暂无任务，点击上方「生成」开始"));
      return;
    }
    const rows = [];
    const stateLabel = {draft:"草稿",running:"进行中",success:"成功",
      failed:"失败",submitting:"进行中"};
    for (const job of visible) {
      const row = rowFor(job);
      row.dataset.state = job.state;
      const [state, meta, timer] = row.querySelector(".img-job-top").children;
      state.textContent = stateLabel[job.state] || job.state;
      const created = job.created ? new Date(job.created*1000).toLocaleString(language(),
        {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}) : "";
      meta.textContent = [created, job.result?.model ||
        catalog.find(m => m.id === job.profile_id)?.name || job.profile_id || "生图任务",
      job.result?.size || job.requested_size].filter(Boolean).join(" · ");
      timer.hidden = job.state === "draft" || job.state === "submitting";
      const executing = Number.isFinite(job.started_at) && job.phase !== "排队等待执行";
      timer.classList.toggle("img-job-timer-legacy", !executing);
      timer.textContent = executing ?
        (activeJob(job) ? "已运行 " : "耗时 ") + taskElapsed(job) :
        activeJob(job) ? "排队中" : "未记录执行耗时";
      const prompt = row.querySelector(".img-job-prompt");
      prompt.textContent = job.prompt_summary || "历史图像任务";
      const phase = row.querySelector(".img-job-phase");
      const step = Number.isInteger(job.step) && job.steps ?
        ` · ${job.step}/${job.steps} 步` : "";
      const message = [job.error || job.phase || "等待桌面端处理", step,
        job.result?.upscale_error ? " · 超分提示：" + job.result.upscale_error : ""].join("");
      phase.textContent = message;
      phase.title = message;
      updateTaskActions(row, job);
      const output = row.querySelector(".img-job-output");
      const ids = (job.result?.image_ids || []).filter(validImageId);
      const imageId = ids[0];
      if (imageId && output.dataset.imageId !== imageId) {
        output.dataset.imageId = imageId;
        const button = part("button", "", "");
        button.type = "button";
        button.setAttribute("aria-label", "查看当前任务生成图片");
        const thumbnail = document.createElement("img");
        void window.MikuchinSecureImages.load(thumbnail,"v1/mikuchin/gallery/thumb/" + imageId)
          .catch(() => {thumbnail.alt="缩略图加载失败";});
        thumbnail.className = "img-job-nsfw";
        thumbnail.alt = "生成图片缩略图";
        thumbnail.loading = "lazy";
        button.append(thumbnail);
        button.onclick = () => showTaskImage(imageId);
        window.MikuchinSecureImages.clearWithin(output);
        output.replaceChildren(button);
        if (ids.length > 1) output.append(part("span", "img-job-output-count", "+"+(ids.length-1)));
        inspectNsfw(imageId);
      } else if (!imageId && output.dataset.imageId) {
        delete output.dataset.imageId;
        window.MikuchinSecureImages.clearWithin(output);
        output.textContent = "尚无图片";
      } else if (!imageId) {
        output.textContent = job.state === "draft" ? "草稿" : activeJob(job) ? "生成中…" : "无产图";
      }
      if (imageId) {
        // Fail closed until metadata arrives; never expose an NSFW thumbnail
        // because a job completed before the gallery metadata was fetched.
        const isSafe = taskNsfw.has(imageId) &&
          (!taskNsfw.get(imageId) || get("gallery-show-nsfw").checked);
        output.querySelector("img")?.classList.toggle("img-job-nsfw", !isSafe);
      }
      rows.push(row);
    }
    // Preserve the exact row nodes during polling: reattaching image nodes
    // on every tick can restart downloads or interrupt a thumbnail tap.
    if (container.children.length !== rows.length ||
        rows.some((row,index) => container.children[index] !== row)) {
      container.replaceChildren(...rows);
    }
  }

  async function refreshImageJobs() {
    if (jobListLoading) return;
    jobListLoading = true;
    try {
      const res = await fetch("v1/mikuchin/image-jobs?kind=generate", {headers:headers(),cache:"no-store"});
      if (!res.ok) throw Error("HTTP " + res.status);
      const data = await res.json();
      const serverIds = new Set();
      for (const job of data.jobs || []) {
        if (job.kind !== "generate") continue;
        serverIds.add(job.id);
        taskRecords.set(job.id, job);
      }
      for (const id of taskRecords.keys()) {
        if (!id.startsWith("pending-") && !serverIds.has(id)) {
          taskRecords.delete(id);
          taskRows.delete(id);
        }
      }
      renderTaskRows();
      void tryRestoreDraft();
    } catch (_error) {
      if (!taskRecords.size) get("img-job-list").textContent =
        "无法读取任务列表；服务恢复后会自动重试";
    } finally {jobListLoading = false;}
  }
  get("img-job-refresh").addEventListener("click", () => void refreshImageJobs());
  get("img-job-active-only").addEventListener("change", renderTaskRows);
  get("img-job-clear").addEventListener("click", async () => {
    const ended = [...taskRecords.values()].filter(j => j.kind === "generate" &&
      ["success","failed"].includes(j.state));
    if (!ended.length) {toast("info", "没有已结束的任务记录");return;}
    if (!confirm("清空所有已完成、失败和中断的生图任务记录？画廊和原始图片不会删除。")) return;
    const button = get("img-job-clear");
    button.disabled = true;
    try {
      const count = await changeTaskRecords("clear_completed");
      toast("success", "记录已清理", `清理了 ${count} 条记录，图片仍在画廊中。`);
    } catch (error) {toast("error", "清理任务失败", String(error.message || error));}
    finally {button.disabled = false;}
  });
  setInterval(() => {
    if (location.hash === "#images") void refreshImageJobs();
  }, 1800);
  // Foreground display clock: never couple elapsed time to API status polling.
  setInterval(tickTaskTimers, 1000);

  get("img-form").onsubmit = async ev => {
    ev.preventDefault();
    if (working) return;
    const prompt = get("img-positive").value.trim() || get("img-natural").value.trim();
    if (!prompt) {
      toast("warn", "没有生图描述", "请先填写 Positive Prompt 或自然语言描述。");
      return;
    }
    const steps = Number(get("img-steps").value);
    if (!Number.isInteger(steps) || steps < 1 || steps > 100) {
      toast("warn", "步数错误", "步数必须在 1～100 之间。");
      return;
    }
    working = true;
    get("img-go").disabled = true;
    get("img-task-error").hidden = true;
    get("img-hint").textContent = "正在保存完整参数与参考图…";
    try {
      // Convert the current form into its server-owned draft snapshot first.
      // Activation preserves the very same ID, preventing an extra record.
      await flushDraftSave();
      if (!currentDraftId) throw Error("草稿尚未保存到桌面");
      const created = await jobCommand({action:"activate",id:currentDraftId});
      taskRecords.set(created.id,created);
      currentDraftId=null;
      store.set(activeDraftKey,"");
      renderTaskRows();
      get("img-hint").textContent = "任务已提交到桌面后台；关闭浏览器不影响执行";
      void refreshImageJobs();
    } catch(error) {
      const message=String(error.message || error);
      get("img-hint").textContent = "任务提交失败，草稿仍保留";
      get("img-task-error").textContent = message;
      get("img-task-error").hidden = false;
      toast("error", "提交失败", message, 8500);
    } finally {
      working = false;
      get("img-go").disabled = !catalog.find(item=>item.id===current)?.available;
      refreshReferenceHint();
    }
  };
  window.MikuchinImageStudio = {refresh, parseJSON};
  if (location.hash === "#images") void refresh();
})();
