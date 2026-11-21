// Read-only chat image viewer. Private images must be fetched using Bearer
// headers through MikuchinSecureImages (never authenticated image URLs).
"use strict";
(() => {
  const get=id=>document.getElementById(id);
  const overlay=get("chat-image-viewer"),img=get("chat-image-viewer-image"),
        loading=get("chat-image-viewer-loading"),secure=window.MikuchinSecureImages;
  const valid=/^v1\/images\/files\/[a-f0-9]{32}\.png$/;
  let selected="",version=0,returnFocus=null,oldOverflow="";
  function close(){
    if(overlay.hidden)return;
    version++;
    overlay.hidden=true;
    selected="";
    loading.hidden=true;
    secure?.release(img);
    img.alt="聊天生成图片";
    document.body.style.overflow=oldOverflow;
    returnFocus?.focus?.({preventScroll:true});
    returnFocus=null;
  }
  async function open(path,alt="聊天生成图片"){
    if(!valid.test(path))throw Error("无效的聊天图片路径");
    if(!secure)throw Error("安全图片加载器不可用");
    if(!overlay.hidden)close();
    const mine=++version;
    selected=path;
    returnFocus=document.activeElement;
    oldOverflow=document.body.style.overflow;
    document.body.style.overflow="hidden";
    img.alt=String(alt||"聊天生成图片").slice(0,160);
    loading.hidden=false;loading.textContent="正在加载图片…";
    overlay.hidden=false;
    get("chat-image-viewer-close").focus({preventScroll:true});
    try {
      await secure.load(img,path);
      if(mine===version)loading.hidden=true;
    }catch(err){
      if(mine===version)loading.textContent="图片加载失败，请关闭后重试";
    }
  }
  get("chat-image-viewer-close").addEventListener("click",close);
  get("chat-image-viewer-download").addEventListener("click",async ()=>{
    const path=selected;
    if(!path)return;
    try{
      const blob=await secure.prefetch(path);
      if(selected!==path)return;
      const url=URL.createObjectURL(blob);
      const a=document.createElement("a");
      a.href=url;a.download=path.split("/").at(-1);
      document.body.appendChild(a);
      a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),5000);
    }catch(e){window.toast?.("error","图片下载失败",String(e));}
  });
  overlay.addEventListener("click",event=>{
    if(event.target===overlay || event.target===get("chat-image-viewer-stage"))close();
  });
  document.addEventListener("keydown",event=>{
    if(!overlay.hidden && event.key==="Escape"){event.preventDefault();event.stopPropagation();close();}
  },true);
  window.MikuchinChatImageViewer=Object.freeze({open,close,
    isOpen:()=>!overlay.hidden});
})();
