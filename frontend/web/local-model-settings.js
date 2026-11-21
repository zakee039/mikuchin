// Register an existing on-host Qwen-Image file set. No model uploads, no
// executable paths, no GPU execution, no cross-origin administrator endpoints.
"use strict";
(() => {
  const get=id=>document.getElementById(id);
  const localHost=location.protocol==="http:" &&
    ["localhost","127.0.0.1","::1"].includes(location.hostname.toLowerCase());
  const button=get("mk-local-import-open");
  const backdrop=get("mk-local-import-backdrop");
  const form=get("mk-local-import-form");
  let localModels=[],busy=false;
  function close(){
    if(busy)return;
    backdrop.hidden=true;
    button.focus({preventScroll:true});
  }
  function row(model){
    const entry=document.createElement("div");
    entry.className="mk-api-item mk-api-item--local";
    const detail=document.createElement("div");
    detail.className="mk-api-item-info";
    const name=document.createElement("strong");
    name.textContent=model.name || model.id;
    const meta=document.createElement("span");
    meta.className="muted small";
    meta.textContent=(model.available?"可用":"文件缺失")+
      " · Qwen-Image Turbo · "+
      (model.reference_mode==="single"?"支持单张参考图":"不支持参考图")+
      " · 最大边长 "+model.max_side;
    detail.append(name,meta);
    entry.append(detail);
    return entry;
  }
  async function refresh(){
    const list=get("mk-local-model-list");
    try {
      const r=await fetch("v1/mikuchin/image-models",{headers:headers(),cache:"no-store"});
      if(!r.ok)throw Error("HTTP "+r.status);
      const result=await r.json();
      localModels=(result.models || []).filter(x=>x.type==="local" || (!x.type && x.family==="qwen_turbo"));
      list.replaceChildren();
      if(!localModels.length){
        const empty=document.createElement("p");
        empty.className="muted small";
        empty.textContent="未发现已注册的本地模型；请先通过本机安装 sd-cli 推理环境。";
        list.append(empty);
      }else{
        for(const model of localModels)list.append(row(model));
      }
      const base=get("mk-local-base");
      const previous=base.value;
      base.replaceChildren();
      for(const model of localModels.filter(x=>x.available)){
        base.append(new Option(model.name,model.id));
      }
      if(previous && localModels.some(x=>x.id===previous && x.available))
        base.value=previous;
      button.disabled=!localHost || !localModels.some(x=>x.available);
      button.title=!localHost ?
        "为了安全，只允许在服务端本机使用 http://127.0.0.1:15239 打开后导入" :
        button.disabled?"请先配置可用的 sd-cli 本地运行环境":"注册现有本地模型文件";
    }catch(e){
      list.textContent="读取本地模型失败："+String(e.message||e);
      button.disabled=true;
    }
  }
  button.addEventListener("click",()=>{
    if(!localHost || button.disabled)return;
    form.reset();
    backdrop.hidden=false;
    get("mk-local-name").focus();
  });
  get("mk-local-import-close").addEventListener("click",close);
  get("mk-local-import-cancel").addEventListener("click",close);
  backdrop.addEventListener("click",e=>{if(e.target===backdrop)close();});
  document.addEventListener("keydown",e=>{
    if(e.key==="Escape" && !backdrop.hidden){e.preventDefault();close();}
  });
  form.addEventListener("submit",async e=>{
    e.preventDefault();
    if(busy || !localHost)return;
    busy=true;
    const submit=get("mk-local-import-save");
    submit.disabled=true;
    const model={
      name:get("mk-local-name").value.trim(),
      base_id:get("mk-local-base").value,
      diffusion_model:get("mk-local-diffusion").value.trim(),
      vae:get("mk-local-vae").value.trim(),
      llm:get("mk-local-llm").value.trim(),
      llm_vision:get("mk-local-vision").value.trim()
    };
    try {
      const r=await fetch("v1/mikuchin/local-image-models",{
        method:"POST",headers:headers(true),body:JSON.stringify({action:"import",model})
      });
      let data={};
      try{data=await r.json();}catch(_){}
      if(!r.ok)throw Error(data.error?.message || "HTTP "+r.status);
      backdrop.hidden=true;
      await refresh();
      void window.MikuchinImageStudio?.refresh();
      if(typeof refreshChatImageModels==="function")
        void refreshChatImageModels();
      toast("success","本地模型已注册","没有运行生图或复制权重文件。");
    }catch(error){
      toast("error","导入失败",String(error.message||error),6500);
    }finally {
      busy=false;submit.disabled=false;
    }
  });
  window.MikuchinLocalModels=Object.freeze({refresh});
  if(location.hash==="#settings")void refresh();
})();
