// Automatic chat-image routing. Pure decision helpers are also Node-testable.
// Never treat arbitrary model JSON as an executable tool invocation.
"use strict";
(function (root) {
  const IMAGE = /(?:图片|图像|插画|照片|头像|壁纸|海报|画面|画作|配图|立绘|image|picture|photo|portrait|illustration|poster|wallpaper)/i;
  const GENERATE = /(?:生成|生图|绘制|创作|画(?:一|张|个|幅|出|给|下|点)|做(?:一张|张|一幅|个)|制作|给我(?:来|做)|帮我(?:画|生成|做)|来(?:一张|张|一幅)|generate|draw|create|make me)/i;
  const EDIT = /(?:改(?:成|一下|为|掉|动)|修改|调整|调(?:大|小|亮|暗|成)|去掉|换(?:成|掉|为)|添加|加上|移除|去除|修(?:一|改)|放大|缩小|重画|重绘|edit|change|remove|replace)/i;
  const DISCUSS = /(?:怎么|如何|为什么|是否|能否|教程|原理|步骤|能不能解释|介绍一下|什么是|不用|不要|别|无需|不需要|how to|why|explain|tutorial|do not|don't)/i;
  function intent(text, hasEarlierImage = false) {
    const s = String(text || "").trim().slice(0, 4000);
    if (!s || DISCUSS.test(s)) return "text";
    if (hasEarlierImage && EDIT.test(s) && (IMAGE.test(s) ||
      /(?:这张|上一张|刚才|刚生成|眼睛|头发|衣服|服装|背景|颜色|表情|手指|人物|姿势)/i.test(s))) return "edit";
    if ((GENERATE.test(s) && IMAGE.test(s)) ||
        /(?:^|[，。！？,.!\s])(?:帮我|请|给我|来)?画(?:一张|一幅|一个|张|幅|个)/u.test(s)) return "generate";
    return "text";
  }
  function looksLikeTool(text) {
    const s = String(text || "").trim();
    const body = s.startsWith("```") ?
      s.replace(/^```(?:json)?\s*/i, "") : s;
    // A legitimate JSON answer can have an action field. Only recognize
    // legacy image-tool envelopes; never hide an unrelated JSON answer.
    return /^\{\s*"action"\s*:\s*"(?:dalle\.text2im|image_gen\.text2im|generate_image)"/i.test(body);
  }
  function tool(text) {
    let raw = String(text || "").trim();
    if (raw.startsWith("\`\`\`")) raw = raw.replace(/^\`\`\`(?:json)?\s*/i, "").replace(/\s*\`\`\`$/, "");
    if (!raw.startsWith("{") || raw.length > 12000) return null;
    let envelope;
    try { envelope = JSON.parse(raw); } catch (_) { return null; }
    if (!envelope || typeof envelope !== "object" || Array.isArray(envelope) ||
        !["dalle.text2im", "image_gen.text2im", "generate_image"].includes(envelope.action)) return null;
    let input = envelope.action_input;
    if (typeof input === "string") {
      try { input = JSON.parse(input); } catch (_) { return null; }
    }
    if (!input || typeof input !== "object" || Array.isArray(input) ||
        typeof input.prompt !== "string") return null;
    const prompt = input.prompt.trim();
    return prompt.length >= 3 && prompt.length <= 4000 ? {action: "generate", prompt} : null;
  }
  const api = Object.freeze({intent, tool, looksLikeTool});
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MikuchinChatImageRouter = api;
})(typeof window !== "undefined" ? window : undefined);
