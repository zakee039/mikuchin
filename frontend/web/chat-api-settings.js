/* Server-owned chat API services, separate from image services. */
"use strict";
(()=>{
  const get=id=>document.getElementById(id), select=get("chat-model-select"), url="v1/mikuchin/chat-api-services";
  let services=[],editing=null,ready=false,changing=false,seq=0,discoverySeq=0,models=[];
  const tr=s=>window.MikuchinI18n?.translate(s)||s;
  const request=async(body=null)=>{const r=await fetch(url,{headers:headers(!!body),cache:"no-store",...(body?{method:"POST",body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(data.error?.message||("HTTP "+r.status));return data;};
  const localName=()=>String(health?.model||"PolyStrata");
  function selected(){return services.find(s=>s.id===chatProfile);}
  function render(){
    const local=localName();get("mk-chat-local-model").textContent=local;
    select.replaceChildren(new Option(tr("本地模型"),"local"));
    for(const s of services)select.add(new Option(s.name,s.id));
    if(chatProfile!=="local"&&!selected())select.add(new Option(tr("已失效的聊天服务"),chatProfile));
    const needsConsent=chatProfile!=="local" && selected()?.revision!==chatRevision;
    if(needsConsent)select.add(new Option(tr("请重新选择并确认聊天模型"),"reconfirm"));
    select.value=needsConsent?"reconfirm":chatProfile;select.disabled=!ready||!sessionV1||changing||!!busy||sessionTransition;
    get("mk-chat-api-add").disabled=!ready;
    const list=get("mk-chat-api-list");list.replaceChildren();
    if(!services.length){const n=document.createElement("div");n.className="muted small";n.textContent=tr(ready?"暂无聊天 API 服务":"聊天 API 服务尚未就绪");list.append(n);}
    for(const s of services){
      const row=document.createElement("div");row.className="mk-api-item";
      const info=document.createElement("div"),name=document.createElement("strong"),sub=document.createElement("div");info.className="mk-api-item-info";name.textContent=s.name;sub.className="muted small";sub.textContent=[s.model,s.stream?tr("流式输出"):null,s.vision?tr("视觉理解"):null,s.tools?"Tool Calling":null].filter(Boolean).join(" · ");info.append(name,sub);row.append(info);
      const actions=document.createElement("div");actions.className="mk-image-service-actions";
      for(const [label,action] of [["编辑",()=>open(s)],["删除",async()=>{if(!confirm(tr("删除此聊天 API 服务？已有聊天记录不会删除。")))return;try{await request({action:"delete",id:s.id});await refresh();}catch(e){toast("error",tr("删除失败"),e.message);}}]]){const b=document.createElement("button");b.type="button";b.className="st-btn st-btn--secondary";b.textContent=tr(label);b.onclick=action;actions.append(b);}
      row.append(actions);list.append(row);
    }
    updateChatModelNotice();
    const p=selected();select.title=p?`${p.name} · ${p.model} · ${tr("在线 API")}${p.vision?"":" · "+tr("仅发送文字；历史图片以文字标记保留")}`:tr("本地模型");
    const sub=get("chat-empty-sub");if(sub&&chatProfile!=="local"){sub.removeAttribute("data-model");sub.textContent=p?`${p.name} · ${p.model} · ${tr("聊天上下文将发送给服务商")}`:tr("已失效的聊天服务");}
  }
  async function refresh(){const n=++seq;try{const d=await request();if(n!==seq)return;services=d.services||[];ready=true;}catch(e){if(n!==seq)return;ready=false;services=[];}render();}
  function resetDiscovery(){discoverySeq++;models=[];const list=get("mk-chat-model-list");list.replaceChildren();list.hidden=true;get("mk-chat-discover").disabled=false;get("mk-chat-discover-status").textContent="";}
  function connection(){return {id:editing?.id,base_url:get("mk-chat-url").value,api_key:get("mk-chat-key").value,proxy:get("mk-chat-proxy").checked,proxy_url:get("mk-chat-proxy-url").value};}
  get("mk-chat-discover").onclick=async()=>{
    resetDiscovery();const n=discoverySeq,b=get("mk-chat-discover"),status=get("mk-chat-discover-status");b.disabled=true;status.textContent=tr("正在获取模型…");
    try{const d=await request({action:"discover",connection:connection()});if(n!==discoverySeq)return;models=Array.isArray(d.models)?d.models:[];const list=get("mk-chat-model-list");list.add(new Option(tr("选择模型"),""));for(const m of models)list.add(new Option(m.id,m.id));list.hidden=!models.length;status.textContent=models.length?`${tr("已获取模型")}：${models.length}`:tr("未返回模型，请手动填写 Model ID");}
    catch(e){if(n===discoverySeq)status.textContent=e.message;}finally{if(n===discoverySeq)b.disabled=false;}
  };
  get("mk-chat-model-list").onchange=()=>{const id=get("mk-chat-model-list").value;if(!id)return;get("mk-chat-model").value=id;const caps=models.find(m=>m.id===id)?.capabilities||{};for(const k of ["stream","vision","tools","reasoning"])if(typeof caps[k]==="boolean")get("mk-chat-"+k).checked=caps[k];if(Object.keys(caps).length<4)get("mk-chat-discover-status").textContent=tr("部分模型能力未提供，请按实际支持情况设置");};
  for(const id of ["mk-chat-url","mk-chat-key","mk-chat-proxy-url"])get(id).addEventListener("input",resetDiscovery);
  function open(s=null){resetDiscovery();editing=s;get("mk-chat-api-title").textContent=tr(s?"编辑 API 服务":"添加 API 服务");
    for(const [key,field,def] of [["name","name",""],["base_url","url",""],["model","model",""],["proxy_url","proxy-url",""],["max_tokens","max-tokens",""],["timeout_seconds","timeout",240]])get("mk-chat-"+field).value=s?.[key]??def;
    get("mk-chat-key").value="";get("mk-chat-key").required=!s?.has_key;for(const key of ["stream","vision","tools","reasoning","proxy"])get("mk-chat-"+key).checked=s?.[key]??(key==="stream");
    get("mk-chat-proxy-wrap").hidden=!get("mk-chat-proxy").checked;get("mk-chat-error").textContent="";get("mk-chat-api-backdrop").hidden=false;
  }
  function close(){resetDiscovery();get("mk-chat-key").value="";get("mk-chat-api-backdrop").hidden=true;editing=null;}
  get("mk-chat-api-add").onclick=()=>open();get("mk-chat-api-close").onclick=close;get("mk-chat-api-cancel").onclick=close;get("mk-chat-proxy").onchange=()=>{get("mk-chat-proxy-wrap").hidden=!get("mk-chat-proxy").checked;resetDiscovery();};
  get("mk-chat-api-form").onsubmit=async e=>{e.preventDefault();const b=get("mk-chat-api-save");if(b.disabled)return;b.disabled=true;try{const s={id:editing?.id,name:get("mk-chat-name").value,base_url:get("mk-chat-url").value,model:get("mk-chat-model").value,api_key:get("mk-chat-key").value,proxy_url:get("mk-chat-proxy-url").value,max_tokens:get("mk-chat-max-tokens").value===""?null:Number(get("mk-chat-max-tokens").value),timeout_seconds:Number(get("mk-chat-timeout").value)};for(const key of ["stream","vision","tools","reasoning","proxy"])s[key]=get("mk-chat-"+key).checked;await request({action:"save",service:s});close();await refresh();}catch(err){get("mk-chat-error").textContent=err.message;}finally{b.disabled=false;}};
  select.onchange=async()=>{const id=select.value,old=chatProfile,fixed=sessionId,p=services.find(x=>x.id===id);if(id==="reconfirm"){render();return;}if(id!=="local"&&(!p||!confirm(`${p.name} (${p.model})\n${p.base_url}\n${tr("选择在线聊天模型时，当前聊天上下文、角色设定与相关附件会发送给对应服务商。生成的图片也可能发送用于视觉回复；调用可能产生费用。继续？")}`))){select.value=old;return;}if(!fixed||!sessionV1||busy||sessionTransition){select.value=old;return;}changing=true;render();try{await sessionSaveChain;const r=await fetch("v1/strata/sessions/"+encodeURIComponent(fixed),{method:"POST",headers:headers(true),body:JSON.stringify({action:"chat_profile",chat_profile:id,chat_revision:p?.revision||""})});if(!r.ok)throw Error("HTTP "+r.status);if(sessionId===fixed){chatProfile=id;chatRevision=p?.revision||"";updateChatModelNotice();}}catch(err){toast("error",tr("切换失败"),err.message);}finally{changing=false;render();}};
  window.MikuchinChatApi={refresh,render,selected,ready:()=>ready,changing:()=>changing};
  refresh();
  document.addEventListener("mikuchin-language-changed",render);
  document.addEventListener("click",e=>{if(e.target.closest('[data-tab="settings"]'))refresh();});
})();
