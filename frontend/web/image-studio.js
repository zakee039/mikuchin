// The Images page is a separate creative workspace. No selected image profile,
// natural-language prompt, or reference picture is sent to the Chat tool.
"use strict";
(() => {
  const get = (id) => document.getElementById(id);
  const fields = ["positive", "negative", "size", "upscale", "steps", "seed"];
  const ids = Object.fromEntries(fields.map(k => [k, `img-${k}`]));
  const language = () => document.documentElement.lang || "zh-CN";
  const tr = (zh, en, ja) => language() === "en-US" ? en : language() === "ja-JP" ? ja : zh;
  const draftKey = "image-drafts-v2";
  const drafts = store.get(draftKey, {}) || {};
  let catalog = [];
  let current = store.get("image-profile", "default");
  let sourceModel = null; // non-destructive adaptation suggestion when first switching
  let reference = null; // File kept in this tab only; never uploaded merely by selecting it
  let working = false;

  const model = () => catalog.find(m => m.id === current) || catalog[0];
  const defaultSteps = (m) => Number(m?.steps || (m?.family === "sdxl" ? 28 : 8));
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
      size: inherited.size || "768x768", upscale: inherited.upscale || "auto",
      steps: String(defaultSteps(selected)), seed: inherited.seed || "",
    };
    for (const k of fields) get(ids[k]).value = values[k];
    for (const opt of get("img-size").options) {
      const [w, h] = opt.value.split("x").map(Number);
      opt.disabled = w > Number(selected?.max_side || 2048) || h > Number(selected?.max_side || 2048);
    }
    if (get("img-size").selectedOptions[0]?.disabled) get("img-size").value = "768x768";
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
    get("img-negative-hint").hidden = selected?.family === "sdxl";
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
      if (!working) get("img-hint").textContent = "每次仅生成一张图片；生成图像与聊天请求会相互等待。";
    } catch (e) {
      console.warn("Image model list:", e);
      get("img-hint").textContent = "请填写 API 密钥后查看生图模型";
    }
  }

  function refreshReferenceHint() {
    const hint = get("img-ref-hint"), btn = get("img-ref-convert");
    if (!reference) {
      hint.textContent = "上传参考图后，将按当前生图模型决定使用方式。";
      btn.hidden = true;
      return;
    }
    if (["img2img", "qwen_edit"].includes(model()?.reference_mode)) {
      hint.textContent = model()?.reference_mode === "qwen_edit" ?
        tr("当前 Qwen 模型支持参考图片：文字指令优先，图片仅作视觉参考。",
           "Qwen supports a reference image. Text instructions take priority; the image guides appearance only.",
           "Qwenは参照画像に対応しています。テキスト指示を優先し、画像は外観の補助にのみ使用します。") :
        tr("此模型支持图生图：生成时直接引用当前图片，默认重绘强度 0.65。",
           "This model supports image-to-image (denoise strength: 0.65).",
           "このモデルはimg2imgに対応しています（ノイズ除去強度0.65）。");
      btn.hidden = true;
    } else {
      hint.textContent = health.images ?
        "该模型不支持直接图像参考，可由当前大模型识别图片并转换为 Prompt。" :
        "该模型不支持图像参考；当前大模型没有视觉能力，无法自动转换。";
      btn.hidden = !health.images;
      btn.disabled = working;
    }
  }

  get("img-model").onchange = e => selectModel(e.target.value);
  for (const k of fields) get(ids[k]).addEventListener("input", saveDraft);
  get("img-natural").value = store.get("image-natural", "");
  get("img-natural").addEventListener("input", () => store.set("image-natural", get("img-natural").value));

  get("img-ref-file").onchange = async e => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > 5 * 1024 * 1024 || file.size < 1) {
      toast("warn", "不支持的参考图", "请上传小于 5 MB 的 PNG、JPEG 或 WebP。", 6000);
      return;
    }
    try {
      const url = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("无法读取图片"));
        reader.readAsDataURL(file);
      });
      if (reference?.objectUrl) URL.revokeObjectURL(reference.objectUrl);
      reference = {url, name: file.name, objectUrl: URL.createObjectURL(file)};
      get("img-ref-thumbnail").src = reference.objectUrl;
      get("img-ref-name").textContent = reference.name;
      get("img-ref-preview").hidden = get("img-ref-clear").hidden = false;
      refreshReferenceHint();
    } catch (err) {toast("error", "图片读取失败", String(err.message || err));}
  };
  get("img-ref-clear").onclick = () => {
    if (reference?.objectUrl) URL.revokeObjectURL(reference.objectUrl);
    reference = null;
    get("img-ref-preview").hidden = get("img-ref-clear").hidden = true;
    get("img-ref-thumbnail").removeAttribute("src");
    refreshReferenceHint();
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

  get("img-form").onsubmit = async ev => {
    ev.preventDefault();
    if (working) return;
    const prompt = get("img-positive").value.trim() || get("img-natural").value.trim();
    if (!prompt) {toast("warn", "没有生图描述", "请输入 Positive Prompt，或先使用一键解析。");return;}
    const steps = Number(get("img-steps").value);
    if (!Number.isInteger(steps) || steps < 1 || steps > 100) {toast("warn", "步数错误", "步数应为 1–100 的整数。");return;}
    const selected = model();
    if (reference && !["img2img", "qwen_edit"].includes(selected?.reference_mode)) {
      if (!window.confirm("当前模型不支持直接引用图片。可先点击「立即转换」将图片转为 Prompt；继续只会使用文本 Prompt，确定生成吗？")) return;
    }
    const body = {prompt, negative_prompt: get("img-negative").value.trim(), steps,
      size: get("img-size").value, response_format: "b64_json",
      strata_upscale: get("img-upscale").value, strata_image_profile: current};
    if (get("img-seed").value !== "") body.seed = Number(get("img-seed").value);
    if (reference && ["img2img", "qwen_edit"].includes(selected?.reference_mode)) {
      body.strata_reference_image = reference.url;
      if (selected.reference_mode === "img2img") body.strata_denoise_strength = 0.65;
    }
    saveDraft();
    working = true;
    get("img-go").disabled = true;
    const start = performance.now();
    get("img-hint").textContent = "正在生成…（显存较小时可能需要几分钟）";
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
        caption.textContent = `${j.model || selected?.name}, ${j.size}, ${steps} steps, ${ui("Seed")} ${d.seed}, ${((performance.now() - start)/1000).toFixed(0)} s` +
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
      get("img-hint").textContent = "生成完成，右键图片可以保存。";
    } catch (e) {toast("error", "生成失败", String(e.message || e), 9000);get("img-hint").textContent = "生成失败，请检查模型参数和日志。";}
    finally {working = false;get("img-go").disabled = !catalog.find(m => m.id === current)?.available;refreshReferenceHint();}
  };
  window.MikuchinImageStudio = {refresh, parseJSON};
  if (location.hash === "#images") void refresh();
})();
