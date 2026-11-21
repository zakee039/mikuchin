/* Native model-driven image turns: pure rendering decisions and terminal states.
 * A model's textual JSON is never a command. No provider calls from this module.
 */
"use strict";
(function(root){
  const terminal = new Set(["text_done","decision_error","tool_rejected","unavailable",
    "cancelled","image_failed","vision_done","vision_failed"]);
  const active = new Set(["deciding","queued","running","image_done","vision_running","awaiting_approval"]);
  function stage(phase){
    const s=String(phase || "");
    if(/Waiting for official model unload|正在卸载/i.test(s))return "正在卸载语言模型";
    if(/Restoring active KV snapshot|恢复.*KV/i.test(s))return "正在恢复 KV 缓存";
    if(/Restoring official text model|正在恢复语言模型/i.test(s))return "正在加载语言模型";
    if(/Real-ESRGAN|upscal|超分/i.test(s))return "正在进行 4× 超分";
    if(/Local Qwen-Image inference/i.test(s))return "正在使用 Qwen-Image 生成图片";
    if(/Local SDXL inference/i.test(s))return "正在使用 SDXL 生成图片";
    if(/排队|waiting|queued/i.test(s))return "排队等待图像 Worker";
    if(/调用图像 API|request_start|response_headers/i.test(s))return "正在调用在线图像模型";
    return s.slice(0,100) || "等待图像 Worker";
  }
  function healthStage(h){
    if(!h || h.component!=="mikuchin-gateway")return null;
    const gpu=h.native_gpu || {}, jobs=h.native_image_jobs || {};
    if(gpu.busy){
      const phase=gpu.phase;
      const known=stage(jobs.phase);
      if(phase==="unloading")return {state:"reading",text:"正在卸载语言模型"};
      if(phase==="restoring")return {state:"reading",
        text:/KV/.test(known)?known:"正在加载语言模型 / 恢复缓存"};
      if(phase==="upscaling")return {state:"generating",text:"正在进行 4× 超分"};
      return {state:"generating",text:known!=="等待图像 Worker"?known:"正在生成图片"};
    }
    if(jobs.running>0)return {state:"queued",text:stage(jobs.phase)};
    if(h.official_model_loaded===false && h.official_polystrata_reachable)
      return {state:"idle",text:"模型已空闲卸载"};
    if(!h.official_polystrata_reachable)
      return {state:"queued",text:"推理引擎暂不可用"};
    return null;
  }
  function recordStage(tool,label){
    if(!label)return;
    const stages=Array.isArray(tool.phase_history)?tool.phase_history:[];
    if(stages[stages.length-1]!==label){
      stages.push(label);
      if(stages.length>16)stages.shift();
    }
    tool.phase_history=stages;
  }
  function unfinished(message) {
    return !!message?.native_turn_id && !terminal.has(message.native_tool_state);
  }
  function apply(message,turn){
    if(!message || !turn || message.native_turn_id !== turn.turn_id)
      throw Error("Tool turn does not belong to this assistant message");
    message.native_tool_state=turn.state;
    message.native_tool_finished=terminal.has(turn.state);
    message.native_tool_online=turn.online===true;
    if(turn.background===true)message.native_background=true;
    if(typeof turn.reasoning==="string" &&
       turn.reasoning.length>(message.reasoning || "").length)
      message.reasoning=turn.reasoning;
    const tool=turn.tool;
    if(!tool){
      message.tools=null;
      if(turn.state==="text_done"){
        const raw=String(turn.text || "");
        let legacy=false;
        if(raw.length<20000 && raw.trim().startsWith("{")){
          try {
            const parsed=JSON.parse(raw);
            legacy=parsed && parsed.action==="dalle.text2im";
          }catch(_){ /* text can resemble JSON without being executable */ }
        }
        message.text=legacy ?
          "模型输出了旧版生图命令文本，但未实际调用 Tool Calling；未提交图像任务。请重试。" : raw;
      }
      else if(turn.state==="deciding") message.text=message.text || "";
      else message.text=turn.error || "模型未能完成此次工具决策，未生成图片。";
      return message;
    }
    let t=(message.tools || []).find(t=>t.native_turn_id===turn.turn_id);
    if(!t){
      t={id:tool.tool_call_id,native_turn_id:turn.turn_id,
        image_request_id:turn.turn_id,at:0,rat:0,created_at:Date.now()};
      message.tools=[t];
    }
    t.id=tool.tool_call_id;
    t.name=tool.name;
    t.tool=tool.name==="edit_image" ? "编辑图片" : "生成图片";
    t.arguments=tool.arguments;
    t.image_prompt=String(tool.arguments?.prompt || tool.arguments?.instruction || "");
    t.edited_previous=tool.name==="edit_image";
    if(message.native_background){
      t.native_hide_image=true; // shown only by the independent completion message
      t.round=null; // not a completed tool exchange in intervening chats
    }
    if(turn.job_id) t.image_job_id=turn.job_id;
    const job=turn.job || {};
    if(Number.isFinite(job.started_at) && job.started_at>0)
      t.image_job_started_at=job.started_at;
    if(Number.isFinite(job.finished_at) && job.finished_at>0)
      t.image_job_finished_at=job.finished_at;
    if(Number.isFinite(job.elapsed_s))
      t.image_job_elapsed_s=job.elapsed_s;
    const picture=job.result || {};
    if(picture.image_file && /^[a-f0-9]{32}\.png$/.test(picture.image_file))
      t.image_file=picture.image_file;
    if(picture.image_original_file && /^[a-f0-9]{32}\.png$/.test(picture.image_original_file))
      t.image_original_file=picture.image_original_file;
    else if(/^[a-f0-9]{32}$/.test(picture.upscale_original_id || ""))
      t.image_original_file=picture.upscale_original_id+".png";
    t.upscale_applied=picture.upscale_applied===true;
    t.upscale_fallback=picture.upscale_fallback===true;
    if(turn.state==="awaiting_approval"){
      t.state="writing";t.result="等待在线生图授权（尚未计费）";
      t.status_label="待确认";
      message.text="";
    } else if(turn.state==="queued" || turn.state==="running"){
      t.state="running";t.result=stage(job.phase);
      t.status_label=turn.state==="queued"?"排队中":t.result;
      message.text=message.native_background ?
        "已经开始为你生成图片了，完成后我会告诉你。你可以继续聊天。" : "";
    } else if(turn.state==="image_done" || turn.state==="vision_running"){
      t.state="running";t.ok=true;t.status_label="正在理解图片";
      t.result="图像已生成，正在识别实际画面…";
      message.text=message.native_background ?
        "已经开始为你生成图片了，完成后我会告诉你。你可以继续聊天。" : "";
    } else if(turn.state==="vision_done" || turn.state==="vision_failed"){
      t.state="done";t.ok=true;
      t.status_label="已完成";
      t.result="图片生成成功，可以在聊天中查看。";
      if(message.native_background){
        // Keep the acknowledgement. Append the completed image as a NEW
        // message after any active user conversation has finished.
        t.round=null;
        t.native_hide_image=true;
        message.native_completion_text=turn.text || (turn.state==="vision_failed" ?
          "图片画好了，但这次视觉理解未完成。":"图片画好了，你看看！");
        message.native_completion_ready=true;
        message.text="已经开始为你生成图片了，完成后我会告诉你。你可以继续聊天。";
      }else{
        t.round=1;
        message.text=turn.text || (turn.state==="vision_failed" ?
          "图片已生成；视觉尾部回复未完成。" : "图片已生成。");
      }
    } else {
      t.state="error";t.ok=false;
      t.status_label="失败";
      t.result=turn.error || "该图像工具请求未执行";
      message.text=turn.text || t.result;
    }
    recordStage(t,t.status_label);
    return message;
  }
  const api=Object.freeze({apply,stage,healthStage,
    unfinished,terminal:is => terminal.has(is),active:is => active.has(is)});
  if(typeof module!=="undefined" && module.exports) module.exports=api;
  if(root) root.MikuchinNativeToolClient=api;
})(typeof window!=="undefined" ? window : undefined);
