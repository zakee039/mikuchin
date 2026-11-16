// Mikuchin unified image gallery — index-backed, no direct filesystem access.
"use strict";
(() => {
  const $g = id => document.getElementById(id);
  const api = "v1/mikuchin/gallery";
  const limit = 60;
  let items = [], total = 0, loading = false, multi = false;
  let selected = new Set(), lightbox = -1, revealed = false;
  let visibleNsfw = false, fetchVersion = 0;

  const sourceLabel = value => ({
    studio:"生图",chat:"聊天",local:"本地",api:"API"
  })[value] || value || "—";
  const dateLabel = seconds => {
    const n = Number(seconds);
    if (!Number.isFinite(n) || !n) return "—";
    try {return new Date(n * 1000).toLocaleString(document.documentElement.lang || "zh-CN", {
      year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"
    });} catch {return "—";}
  };
  async function request(body) {
    const options = {headers:headers(Boolean(body)),cache:"no-store"};
    if (body) {options.method="POST";options.body=JSON.stringify(body);}
    const response = await fetch(api,options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(result.error?.message || "HTTP " + response.status);
    return result;
  }
  const masked = item => Boolean(item?.nsfw && !visibleNsfw);
  function make(tag, cls, value) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value != null) node.textContent = value;
    return node;
  }
  function setSelectionUI() {
    $g("gallery-selection-bar").hidden = !multi;
    $g("gallery-select-mode").textContent = multi ? "完成" : "选择";
    $g("gallery-selected-count").textContent = "已选择 " + selected.size + " 张";
    $g("gallery-delete-selected").disabled = !selected.size;
    $g("gallery-batch-nsfw").disabled = !selected.size;
    $g("gallery-delete-selected").textContent = selected.size ? "删除所选 (" + selected.size + ")" : "删除所选";
  }
  function render() {
    const grid = $g("gallery-grid");
    grid.replaceChildren();
    $g("gallery-count").textContent = total + " 张";
    $g("gallery-empty").hidden = Boolean(items.length || loading);
    $g("gallery-more").hidden = items.length >= total || !items.length;
    for (const [index, item] of items.entries()) {
      const active = selected.has(item.id);
      const card = make("button","gallery-card" + (active?" gallery-selected":"") + (multi?" is-selecting":""));
      card.type="button";
      card.dataset.galleryId=item.id;
      card.setAttribute("aria-label", "查看生成图片 " + (item.model || item.id));
      card.setAttribute("aria-pressed", String(multi && active));
      const frame = make("div","gallery-card-media");
      const img = make("img",masked(item)?"gallery-blurred":"");
      img.src = api + "/thumb/" + item.id;
      img.loading = index < 12 ? "eager" : "lazy";
      img.decoding = "async";
      img.alt = item.model || "生成图片";
      frame.append(img);
      if (item.nsfw && masked(item)) {
        const shade = make("div","gallery-spoiler");
        shade.append(make("span","", "NSFW · 已隐藏"));
        frame.append(shade);
      }
      if (multi) frame.append(make("span","gallery-select-mark",active ? "✓" : ""));
      if ((item.variant_count || 1) > 1) {
        const badge=make("span","gallery-pair-badge",String(item.variant_count));
        badge.title="原图和 4× 超分图，共 " + item.variant_count + " 张";
        frame.append(badge);
      }
      frame.append(make("span","gallery-source-label",sourceLabel(item.source)));
      const desc = make("div","gallery-card-meta");
      desc.append(make("strong","", item.model || "历史生成图片"));
      desc.append(make("span","", dateLabel(item.created) + " · " + item.width + "×" + item.height));
      card.append(frame, desc);
      card.addEventListener("click", () => multi ? toggle(item.id) : open(index));
      grid.append(card);
    }
    setSelectionUI();
  }
  function toggle(id) {
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    render();
  }
  async function load(reset = true) {
    if (loading) return;
    loading=true;
    const version=++fetchVersion;
    if (reset) {
      items=[];total=0;selected.clear();
      if (lightbox !== -1) close();
    }
    $g("gallery-empty").hidden=true;
    $g("gallery-more").disabled=true;
    try {
      const query = new URLSearchParams({
        source:$g("gallery-source").value,
        order:$g("gallery-order").value,
        limit:String(limit),offset:String(items.length)
      });
      const response = await fetch(api+"?"+query.toString(),
        {headers:headers(),cache:"no-store"});
      const answer = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(answer.error?.message || "HTTP "+response.status);
      if (fetchVersion !== version) return;
      total=answer.total || 0;
      items.push(...(Array.isArray(answer.items)?answer.items:[]));
      render();
    } catch(e) {
      toast("error","画廊加载失败",String(e.message||e),6000);
      if (!items.length) $g("gallery-empty").textContent = "画廊加载失败，请检查服务连接";
      $g("gallery-empty").hidden=Boolean(items.length);
    } finally {
      loading=false;
      $g("gallery-more").disabled=false;
      $g("gallery-more").hidden = items.length >= total;
    }
  }
  function open(index) {
    if (!items[index]) return;
    lightbox=index;revealed=false;
    $g("gallery-viewer").hidden=false;
    showViewer();
    $g("gallery-close").focus();
  }
  function close() {
    if (lightbox === -1) return;
    const id=items[lightbox]?.id;
    lightbox=-1;revealed=false;
    $g("gallery-viewer").hidden=true;
    $g("gallery-full").removeAttribute("src");
    const from=$g("gallery-grid").querySelector('[data-gallery-id="'+id+'"]');
    from?.focus({preventScroll:true});
  }
  function showViewer() {
    if (lightbox === -1) return;
    const item=items[lightbox];
    if (!item) {close();return;}
    $g("gallery-position").textContent=(lightbox+1)+" / "+total;
    $g("gallery-full").src="v1/images/files/"+item.id+".png";
    const hide=masked(item) && !revealed;
    $g("gallery-full").classList.toggle("gallery-blurred",hide);
    $g("gallery-viewer-spoiler").hidden=!hide;
    $g("gallery-mark-nsfw").textContent=item.nsfw?"取消 NSFW 标记":"标记为 NSFW";
    const pair=Boolean(item.variants?.original && item.variants?.upscaled);
    $g("gallery-delete-original").hidden=!pair;
    $g("gallery-delete-upscaled").hidden=!pair;
    $g("gallery-details").textContent=[
      dateLabel(item.created),sourceLabel(item.source),
      item.provider?sourceLabel(item.provider):"",
      item.model,item.width+"×"+item.height,
      (item.variant_count || 1)>1?"原图 + 4× 超分":""
    ].filter(Boolean).join(" · ");
    $g("gallery-prompt").textContent=item.prompt || "";
  }
  async function shift(delta) {
    if (lightbox === -1 || !items.length) return;
    if (delta>0 && lightbox === items.length-1 && items.length<total) {
      await load(false);
      if (lightbox === -1) return;
    }
    lightbox=(lightbox+delta+items.length)%items.length;
    revealed=false;
    showViewer();
  }
  async function mutateNsfw() {
    const item=items[lightbox];
    if (!item) return;
    try {
      const result=await request({action:"nsfw",id:item.id,nsfw:!item.nsfw});
      item.nsfw=result.nsfw;
      revealed=false;
      render();
      showViewer();
    } catch(e) {toast("error","NSFW 标记失败",String(e.message||e));}
  }
  async function markSelectedNsfw() {
    const ids=[...selected];
    if (!ids.length) return;
    if (!confirm("将选中的 "+ids.length+" 组作品标记为 NSFW？原图和 4× 图片将同时生效。")) return;
    try {
      let updated=0;
      for(let i=0;i<ids.length;i+=150){
        const answer=await request({action:"nsfw_many",ids:ids.slice(i,i+150),nsfw:true});
        const changed=new Set(answer.updated || []);
        for (const item of items) if(changed.has(item.id)) item.nsfw=true;
        updated+=changed.size;
      }
      render();
      toast("success","已标记 NSFW","共 "+updated+" 组作品");
    } catch(e) {
      await load(true);
      toast("error","批量标记失败",String(e.message||e),6000);
    }
  }

  async function deleteSingleVariant(variant) {
    const item=items[lightbox];
    if(!item?.variants?.original || !item?.variants?.upscaled) return;
    const original=variant==="original";
    const name=original?"原图":"4× 超分图";
    if(!confirm("只删除这组作品的"+name+"？\n另一份图片将保留。"
      +(original?"":"\n聊天记录如果引用了 4× 图片，删除后该引用将失效。")
      +"\n此操作不可撤销。"))return;
    try {
      const result=await request({action:"delete_variant",id:item.id,variant});
      const remaining=result.remaining;
      await load(true);
      const found=items.findIndex(entry=>entry.id===remaining);
      if(found!==-1) open(found);
      toast("success","已删除"+name,"保留了另一份图片");
    }catch(e){
      toast("error","删除"+name+"失败",String(e.message||e),6000);
    }
  }

  async function deleteImages(ids) {
    const n=ids.length;
    if (!n) return;
    if (!confirm("永久删除选中的 "+n+" 组作品？\n每组的原图与 4× 超分图将一起删除，聊天记录中引用的图片也可能失效。此操作不可撤销。")) return;
    try {
      let removed=0,groups=0,failed=0;
      for(let i=0;i<ids.length;i+=150){
        const result=await request({action:"delete",ids:ids.slice(i,i+150)});
        removed+=(result.deleted?.length||0);
        groups+=(result.deleted_groups||0);
        failed+=(result.failed?.length||0);
      }
      if (failed) toast("warn","部分图片未删除","已删除 "+removed+" 个文件，失败 "+failed+" 个",5000);
      else toast("success","删除完成","已删除 "+groups+" 组作品，共 "+removed+" 个文件");
      if (lightbox!==-1) close();
      selected.clear();
      await load(true);
    } catch(e) {toast("error","删除失败",String(e.message||e),6000);}
  }
  $g("gallery-select-mode").addEventListener("click",() => {
    multi=!multi;selected.clear();
    if (lightbox!==-1) close();
    render();
  });
  $g("gallery-select-all").addEventListener("click",()=> {
    for (const item of items) selected.add(item.id);
    render();
  });
  $g("gallery-select-none").addEventListener("click",()=> {selected.clear();render();});
  $g("gallery-delete-selected").addEventListener("click",()=>deleteImages([...selected]));
  $g("gallery-batch-nsfw").addEventListener("click",markSelectedNsfw);
  $g("gallery-source").addEventListener("change",()=>load(true));
  $g("gallery-order").addEventListener("change",()=>load(true));
  $g("gallery-show-nsfw").addEventListener("change",e=> {
    visibleNsfw=e.target.checked;render();if(lightbox!==-1)showViewer();
  });
  $g("gallery-refresh").addEventListener("click",async()=>{
    try {
      const scan=await request({action:"repair"});
      await load(true);
      if(scan.added||scan.removed)toast("success","索引已同步","补入 "+scan.added+" 张，清理 "+scan.removed+" 条");
    } catch(e){toast("error","刷新失败",String(e.message||e));}
  });
  $g("gallery-more").addEventListener("click",()=>load(false));
  $g("gallery-close").addEventListener("click",close);
  $g("gallery-prev").addEventListener("click",()=>shift(-1));
  $g("gallery-next").addEventListener("click",()=>shift(1));
  $g("gallery-mark-nsfw").addEventListener("click",mutateNsfw);
  $g("gallery-reveal").addEventListener("click",()=>{revealed=true;showViewer();});
  $g("gallery-delete-original").addEventListener("click",()=>deleteSingleVariant("original"));
  $g("gallery-delete-upscaled").addEventListener("click",()=>deleteSingleVariant("upscaled"));
  $g("gallery-viewer-delete").addEventListener("click",()=> {
    const item=items[lightbox];
    if(item) void deleteImages([item.id]);
  });
  $g("gallery-viewer").addEventListener("click",e=>{
    if(e.target===$g("gallery-viewer")||e.target===$g("gallery-viewer-stage"))close();
  });
  document.addEventListener("keydown",e=>{
    if (lightbox===-1) return;
    if(e.key==="Escape"){e.preventDefault();close();}
    else if(e.key==="ArrowLeft"){e.preventDefault();void shift(-1);}
    else if(e.key==="ArrowRight"){e.preventDefault();void shift(1);}
  });
  let touchX=null;
  $g("gallery-viewer-stage").addEventListener("touchstart",e=>{
    touchX=e.touches.length===1?e.touches[0].clientX:null;
  },{passive:true});
  $g("gallery-viewer-stage").addEventListener("touchend",e=>{
    if(touchX==null||!e.changedTouches.length)return;
    const dist=e.changedTouches[0].clientX-touchX;touchX=null;
    if(Math.abs(dist)>75)void shift(dist>0?-1:1);
  },{passive:true});
  window.MikuchinGallery={refresh:()=>load(true)};
  if(location.hash==="#gallery")void load(true);
})();
