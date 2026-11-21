/* Single source of truth for the header indicator.
 * The upstream Metrics state describes inference, Native Health describes
 * whether model weights are actually loaded and whether image jobs are running.
 * No network requests or DOM mutations here: one renderer owns the pill. */
"use strict";
(function(root){
  function metricState(metrics) {
    const live=metrics?.live || {};
    if(live.state==="reading"){
      const pct=Number(live.prompt_total)>0 ?
        Math.round(100*Number(live.prompt_read||0)/Number(live.prompt_total)) : null;
      return {state:"reading",text:pct===null?"读取上下文":`读取上下文 · ${pct}%`};
    }
    if(live.state==="generating"){
      const speed=Number(live.tok_s || 0);
      return {state:"generating",text:`生成中 · ${speed.toFixed(1)} tok/s`};
    }
    if(Number(live.queued)>0)return {state:"queued",text:`排队中 · ${live.queued}`};
    return {state:"idle",text:"空闲"};
  }
  function resolve({metrics=null,health=null,networkFailed=false,unauthorized=false}={}){
    if(unauthorized)return {state:"queued",text:"需要 API Key",imageCount:0};
    const active=Number(health?.native_image_jobs?.running)||0;
    const concurrent=active>0;
    const phase=health?.native_gpu?.busy ? health.native_gpu.phase : null;
    let status;
    if(phase==="unloading")status={state:"reading",text:"正在卸载语言模型"};
    else if(phase==="restoring")status={state:"reading",text:"正在恢复语言模型 / KV 缓存"};
    else if(phase==="upscaling")status={state:"generating",text:"正在进行 4× 超分"};
    else if(metrics && ["reading","generating"].includes(metrics.live?.state))
      status=metricState(metrics);
    else if(phase==="generating")status={state:"generating",text:"正在生成图片"};
    else if(health?.official_polystrata_reachable===false)
      status={state:"queued",text:"推理引擎暂不可用"};
    else if(health?.official_model_loaded===false)
      status={state:"idle",text:"模型已空闲卸载"};
    else if(metrics)status=metricState(metrics);
    else if(health?.official_model_loaded===true)
      status={state:"idle",text:"空闲"};
    else status={state:networkFailed?"queued":"idle",
      text:networkFailed?"服务无法连接":"连接中…"};
    // Don't duplicate the only image job when the pill already displays it.
    const imageIsPrimary=phase==="generating" || phase==="upscaling" ||
      (!metrics?.live?.state && status.text.includes("生成图片"));
    return {...status,imageCount:concurrent && !imageIsPrimary ? active : 0};
  }
  const api=Object.freeze({resolve,metricState});
  if(typeof module!=="undefined" && module.exports)module.exports=api;
  if(root)root.MikuchinHeaderStatus=api;
})(typeof window!=="undefined" ? window : undefined);
