/* Native model-driven image turns: pure rendering decisions and terminal states.
 * A model's textual JSON is never a command. No provider calls from this module.
 */
"use strict";
(function(root){
  const terminal = new Set(["text_done","decision_error","tool_rejected","unavailable",
    "cancelled","image_failed","vision_done","vision_failed"]);
  const active = new Set(["deciding","queued","running","image_done","vision_running","awaiting_approval"]);
  function unfinished(message) {
    return !!message?.native_turn_id && !terminal.has(message.native_tool_state);
  }
  function apply(message,turn){
    if(!message || !turn || message.native_turn_id !== turn.turn_id)
      throw Error("Tool turn does not belong to this assistant message");
    message.native_tool_state=turn.state;
    message.native_tool_finished=terminal.has(turn.state);
    message.native_tool_online=turn.online===true;
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
      else if(turn.state==="deciding") message.text="模型正在判断是否需要调用图片工具…";
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
    if(turn.job_id) t.image_job_id=turn.job_id;
    const job=turn.job || {};
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
      message.text="模型请求调用在线生图服务，等待本次手动确认。";
    } else if(turn.state==="queued" || turn.state==="running"){
      t.state="running";t.result=job.phase || "图像任务正在等待 Worker";
      message.text="正在生成图片；切换设备后仍可查看任务进度。";
    } else if(turn.state==="image_done" || turn.state==="vision_running"){
      t.state="done";t.ok=true;
      t.result="图像已生成，正在识别实际画面…";
      message.text="图片已生成，正在准备简短回复…";
    } else if(turn.state==="vision_done" || turn.state==="vision_failed"){
      t.state="done";t.ok=true;
      t.result="Image generation succeeded; image available in this chat.";
      t.round=1;
      message.text=turn.text || (turn.state==="vision_failed" ?
        "图片已生成；视觉尾部回复未完成。" : "图片已生成。");
    } else {
      t.state="error";t.ok=false;
      t.result=turn.error || "该图像工具请求未执行";
      message.text=turn.text || t.result;
    }
    return message;
  }
  const api=Object.freeze({apply,unfinished,terminal:is => terminal.has(is),active:is => active.has(is)});
  if(typeof module!=="undefined" && module.exports) module.exports=api;
  if(root) root.MikuchinNativeToolClient=api;
})(typeof window!=="undefined" ? window : undefined);
