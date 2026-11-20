"use strict";
// Explicit capability negotiation between the shared web UI, legacy Mikuchin,
// and the official-PolyStrata Native Gateway. No unsupported options are
// silently changed to different semantics (especially max_tokens).
(function (root) {
  function apply(body, health, settings, context = {}) {
    if (!body || !health || !settings) throw Error("Missing chat request state");
    const max = settings.max;
    if (max !== "" && max !== null && max !== undefined) {
      if (health.answer_budget_tokens === false)
        throw Error("当前 Native Gateway 尚不支持独立正文 Token 上限。请在采样设置中清空 Answer Token budget 后重试；思考 Token 预算仍可正常使用。");
      const parsed = Number(max);
      if (!Number.isInteger(parsed) || parsed < 1 || parsed > 262144)
        throw Error("Answer Token budget must be an integer from 1 to 262144");
      body.answer_budget_tokens = parsed;
    }
    if (!context.stateless && settings.mcp !== false && context.mcpTools > 0 &&
        health.chat_mcp !== false)
      body.strata_mcp = true;
    // A working Image Studio is NOT a working in-chat image tool. For legacy
    // services without this flag, preserve their existing capability signal.
    if (health.image_generation && health.chat_image_tool !== false)
      body.strata_image_tool = true;
    return body;
  }
  const api = Object.freeze({apply});
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MikuchinChatCapabilities = api;
})(typeof window !== "undefined" ? window : undefined);
