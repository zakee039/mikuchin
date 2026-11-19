// Shared width × height contract for Image Studio and chat-image preferences.
"use strict";
(() => {
  const standard = Object.freeze([
    {size:"1024x1024",ratio:"1:1",note:"标准方形"},
    {size:"2048x2048",ratio:"1:1",note:"2K 方形"},
    {size:"1536x1024",ratio:"3:2",note:"官方推荐横图"},
    {size:"1024x1536",ratio:"2:3",note:"官方推荐竖图"},
    {size:"1536x864",ratio:"16:9",note:"自定义横图"},
    {size:"2560x1440",ratio:"16:9",note:"2K 横图"},
    {size:"3840x2160",ratio:"16:9",note:"4K 横图，实验性"},
    {size:"2160x3840",ratio:"9:16",note:"4K 竖图，实验性"},
  ]);
  const local = Object.freeze([384, 512, 768, 1024]);
  const standardSizes = new Set(standard.map(p => p.size));
  function nearest16(value, fallback = 1024) {
    const number = Number(value);
    const chosen = Number.isFinite(number) && value !== "" && value != null ? number : fallback;
    return Math.max(256, Math.min(4096, Math.round(chosen / 16) * 16));
  }
  function pack(model) {
    return model?.family !== "api" ? "local" : model.sizes || "standard";
  }
  function isStandard(value) {return standardSizes.has(value);}
  function dimensions(model, fields) {
    const mode = pack(model);
    if (mode === "standard") {
      const match = isStandard(fields.standard) ? fields.standard : "1024x1024";
      const [width,height] = match.split("x").map(Number);
      return {width,height,size:match};
    }
    if (mode === "custom") {
      const width = nearest16(fields.customWidth), height = nearest16(fields.customHeight);
      return {width,height,size:`${width}x${height}`};
    }
    if (mode === "square") return {width:1024,height:1024,size:"1024x1024"};
    const width = Number(fields.width) || 768, height = Number(fields.height) || 768;
    return {width,height,size:`${width}x${height}`};
  }
  const api = Object.freeze({standard,local,nearest16,pack,isStandard,dimensions});
  if (typeof window !== "undefined") window.MikuchinImageSizes = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
